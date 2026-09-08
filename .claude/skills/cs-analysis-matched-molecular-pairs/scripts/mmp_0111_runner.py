from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import html
import json
import math
import shutil
from itertools import permutations
from pathlib import Path
from typing import Any

import pandas as pd
from rdkit import Chem
from rdkit import RDLogger
from rdkit.Chem import Draw, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

from batch_skill_common import (
    finish as finish_request,
    frame_html,
    html_page,
    parse_request,
    dataset as request_dataset,
)
from mmp_engine import build_native_database, extract_pairs, load_input, sha256_file, utc_now
from mmp_0111_evidence import (
    build_target_evidence,
    build_virtual_candidates,
    normalize_target_registry,
)
from mmp_0111_audit import audit_database_output, audit_output
from mmp_0111_model import (
    CALCULATION_VERSION,
    DEFAULT_TWO_CUT_THRESHOLDS,
    ENGINE_VERSION,
    NEUTRAL_TOLERANCE,
    MODEL_REVISION,
    SCHEMA_VERSION,
    canonicalize_pair_transformations,
    effect_signature,
    load_canonical_database,
    read_fragmentations,
    structure_signature,
    write_canonical_database,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(part) for key, part in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(part) for part in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def write_json(path: Path, value: Any) -> None:
    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): clean(part) for key, part in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(part) for part in item]
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if hasattr(item, "item"):
            return clean(item.item())
        return item
    path.write_text(
        json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def render_template(name: str, values: dict[str, Any]) -> str:
    path = SKILL_DIR / "templates" / name
    # JavaScript template literals also use ${...}; replace only the explicit
    # repository-template tokens owned by Python instead of interpreting JS.
    rendered = path.read_text(encoding="utf-8")
    for key, value in values.items():
        rendered = rendered.replace(f"${key}", str(value))
    unresolved = [key for key in values if f"${key}" in rendered]
    if unresolved:
        raise ValueError(f"Unresolved A008 report placeholders: {unresolved}")
    return rendered


def adapt_legacy_parameters(parameters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Convert the old three-role vocabulary to the two-mode contract.

    Type-I requires the caller to add its selected targets; it is not allowed
    to silently select them inside the scientific engine.
    """
    if "mode" in parameters:
        mode = str(parameters["mode"]).lower()
        if mode not in {"target", "database"}:
            raise ValueError("MMP parameters.mode must be target or database")
        return dict(parameters), None
    role = str(parameters.get("role", "")).lower()
    if role not in {"type-i", "type-ii", "type-iii"}:
        raise ValueError("MMP parameters.mode is required")
    converted = dict(parameters)
    converted.pop("role", None)
    converted["mode"] = "database" if role == "type-iii" else "target"
    if role == "type-i" and not converted.get("targets"):
        raise ValueError(
            "Legacy Type-I must be adapted by the Orchestrator to explicit targets; "
            "the 0.1.11 MMP engine does not select analysis-unit Top1 implicitly"
        )
    if role == "type-ii" and converted.get("target_compound_ids") and not converted.get("targets"):
        converted["targets"] = [
            {
                "compound_id": str(target_id),
                "selection_sources": [{"source_type": "human_explicit", "source_id": "legacy_type_ii"}],
            }
            for target_id in converted["target_compound_ids"]
        ]
    return converted, {"legacy_role": role, "converted_mode": converted["mode"]}


def validate_parameters(parameters: dict[str, Any]) -> None:
    allowed = {
        "mode", "targets", "cuts", "radius_min", "radius_max",
        "neutral_tolerance", "near_core_tanimoto", "near_core_mcs_coverage",
        "max_compounds", "max_embedded_evidence", "cut_smarts",
        "min_core_heavy_atoms", "min_core_fraction",
        "max_variable_heavy_atoms", "two_cut_thresholds",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"Unknown CONDUCTOR 0.1.11 MMP parameters: {unknown}")
    mode = str(parameters.get("mode", ""))
    if mode not in {"target", "database"}:
        raise ValueError("MMP parameters.mode must be target or database")
    if mode == "database" and parameters.get("targets"):
        raise ValueError("MMP mode=database is Target-independent and cannot receive targets")
    if str(parameters.get("cut_smarts", "default")) not in {
        "default", "cut_AlkylChains", "exocyclic"
    }:
        raise ValueError("cut_smarts must be default, cut_AlkylChains, or exocyclic")
    for name in ("near_core_tanimoto", "near_core_mcs_coverage", "min_core_fraction"):
        value = float(parameters.get(name, .7 if name != "min_core_fraction" else .5))
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
    embedded = int(parameters.get("max_embedded_evidence", 500))
    if not 1 <= embedded <= 5000:
        raise ValueError("max_embedded_evidence must be between 1 and 5000")
    thresholds = parameters.get("two_cut_thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ValueError("two_cut_thresholds must be an object")
    unknown_thresholds = sorted(set(thresholds) - set(DEFAULT_TWO_CUT_THRESHOLDS))
    if unknown_thresholds:
        raise ValueError(f"Unknown two_cut_thresholds: {unknown_thresholds}")


def _refresh_effects(
    details: pd.DataFrame,
    compounds: pd.DataFrame,
    higher_is_better: bool,
    neutral_tolerance: float,
) -> pd.DataFrame:
    frame = details.copy()
    lookup = dict(zip(compounds["compound_id"].astype(str), compounds["endpoint"]))
    frame["endpoint_from"] = frame["compound_id_from"].astype(str).map(lookup)
    frame["endpoint_to"] = frame["compound_id_to"].astype(str).map(lookup)
    frame["endpoint_delta"] = pd.to_numeric(frame["endpoint_to"], errors="coerce") - pd.to_numeric(frame["endpoint_from"], errors="coerce")
    frame["normalized_signed_delta"] = frame["endpoint_delta"] * (1.0 if higher_is_better else -1.0)
    frame["fixed_direction_effect"] = frame["normalized_signed_delta"]
    frame["favorable_delta"] = frame["fixed_direction_effect"]
    effect = pd.to_numeric(frame["fixed_direction_effect"], errors="coerce")
    frame["effect_status"] = "missing"
    frame.loc[effect.notna() & effect.abs().lt(neutral_tolerance), "effect_status"] = "neutral"
    frame.loc[effect.ge(neutral_tolerance), "effect_status"] = "supports_fixed_direction"
    frame.loc[effect.le(-neutral_tolerance), "effect_status"] = "opposes_fixed_direction"
    frame["neutral_tolerance"] = neutral_tolerance
    return frame


def _metric_grid(items: list[tuple[str, Any]]) -> str:
    return "<div class='metric-grid'>" + "".join(
        f"<div class='metric'><span class='muted'>{html.escape(str(label))}</span><b>{html.escape(str(value))}</b></div>"
        for label, value in items
    ) + "</div>"


def _molecule_svg_data(
    value: Any,
    width: int = 260,
    height: int = 170,
    *,
    reference: Any = None,
    core: Any = None,
) -> str:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmiles("*")
    try:
        if reference is not None:
            reference_molecule = Chem.MolFromSmiles(str(reference))
            core_molecule = Chem.MolFromSmiles(str(core)) if core else None
            if reference_molecule is not None:
                rdDepictor.Compute2DCoords(reference_molecule)
                parameters = rdDepictor.ConstrainedDepictionParams()
                parameters.acceptFailure = True
                rdDepictor.GenerateDepictionMatching2DStructure(
                    molecule, reference_molecule, refPatt=core_molecule, params=parameters
                )
        elif molecule.GetNumConformers() == 0:
            rdDepictor.Compute2DCoords(molecule)
    except (RuntimeError, ValueError):
        rdDepictor.Compute2DCoords(molecule)
    svg = str(Draw.MolsToGridImage(
        [molecule], molsPerRow=1, subImgSize=(width, height), legends=[""], useSVG=True
    ))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _mol_svg_data(molecule: Chem.Mol, width: int, height: int) -> str:
    """Draw a molecule without recomputing an existing constrained depiction."""
    svg = str(Draw.MolsToGridImage(
        [molecule], molsPerRow=1, subImgSize=(width, height), legends=[""], useSVG=True
    ))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _svg_data_to_text(value: str) -> str:
    """Convert an SVG Data URI to actual XML before writing an external file."""
    prefix = "data:image/svg+xml;base64,"
    if value.startswith(prefix):
        try:
            return base64.b64decode(value[len(prefix):], validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError) as error:
            raise ValueError("Invalid base64 SVG Data URI") from error
    if value.lstrip().startswith(("<?xml", "<svg")):
        return value
    raise ValueError("External SVG asset is neither SVG XML nor a base64 SVG Data URI")


def _alignment_query(value: Any) -> Chem.Mol | None:
    """Return an attachment-tolerant query for a shared MMP Core."""
    query = Chem.MolFromSmarts(str(value)) if value is not None else None
    if query is None and value is not None:
        molecule = Chem.MolFromSmiles(str(value))
        if molecule is not None:
            query = Chem.Mol(molecule)
    return query


def _aligned_pair_svg_data(
    left_smiles: Any,
    right_smiles: Any,
    core: Any,
    width: int = 270,
    height: int = 170,
) -> tuple[str, str, str]:
    """Align two observed compounds on their shared MMP Core.

    The right compound is the depiction reference.  If constrained alignment
    fails, both standalone depictions are still returned and the caller marks
    the comparison as ``Align ×``.  This preserves the complete compound
    context without implying that the orientations correspond.
    """
    left = Chem.MolFromSmiles(str(left_smiles)) if left_smiles is not None else None
    right = Chem.MolFromSmiles(str(right_smiles)) if right_smiles is not None else None
    query = _alignment_query(core)
    if left is None or right is None or query is None:
        return (
            _molecule_svg_data(left_smiles, width, height),
            _molecule_svg_data(right_smiles, width, height),
            "alignment_unavailable",
        )
    try:
        if not left.HasSubstructMatch(query) or not right.HasSubstructMatch(query):
            return (
                _mol_svg_data(left, width, height),
                _mol_svg_data(right, width, height),
                "core_mapping_failed",
            )
        rdDepictor.Compute2DCoords(right)
        parameters = rdDepictor.ConstrainedDepictionParams()
        parameters.acceptFailure = False
        rdDepictor.GenerateDepictionMatching2DStructure(
            left, right, refPatt=query, params=parameters
        )
        return (
            _mol_svg_data(left, width, height),
            _mol_svg_data(right, width, height),
            "core_aligned",
        )
    except (RuntimeError, ValueError):
        if left.GetNumConformers() == 0:
            rdDepictor.Compute2DCoords(left)
        if right.GetNumConformers() == 0:
            rdDepictor.Compute2DCoords(right)
        return (
            _mol_svg_data(left, width, height),
            _mol_svg_data(right, width, height),
            "core_mapping_failed",
        )


def _format_number(value: Any) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(number) else f"{float(number):.2f}"


def _highlighted_core_svg_data(
    value: Any, mcs_smarts: Any, environment_radius: Any,
    width: int = 220, height: int = 130,
) -> str:
    """Render attachment/MCS/environment/unmapped regions without Vision."""
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return _molecule_svg_data(value, width, height)
    rdDepictor.Compute2DCoords(molecule)
    atom_colors = {atom.GetIdx(): (0.70, 0.70, 0.70) for atom in molecule.GetAtoms()}
    query = Chem.MolFromSmarts(str(mcs_smarts)) if mcs_smarts else None
    if query is None and mcs_smarts:
        query = Chem.MolFromSmiles(str(mcs_smarts))
    match = molecule.GetSubstructMatch(query) if query is not None else ()
    for atom_index in match:
        atom_colors[atom_index] = (0.20, 0.62, 0.36)
    radius = 0
    if str(environment_radius) in {"exact", "2"}:
        radius = 2
    elif str(environment_radius) == "1":
        radius = 1
    dummy_indices = [
        atom.GetIdx() for atom in molecule.GetAtoms() if atom.GetAtomicNum() == 0
    ]
    distance = Chem.GetDistanceMatrix(molecule)
    for dummy_index in dummy_indices:
        for atom in molecule.GetAtoms():
            atom_index = atom.GetIdx()
            graph_distance = int(distance[dummy_index, atom_index])
            if 1 <= graph_distance <= radius:
                atom_colors[atom_index] = (
                    (0.96, 0.62, 0.24) if graph_distance == 1
                    else (0.36, 0.66, 0.78)
                )
        atom_colors[dummy_index] = (0.84, 0.16, 0.20)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.DrawMolecule(
        molecule,
        highlightAtoms=list(atom_colors),
        highlightAtomColors=atom_colors,
        highlightBonds=[],
    )
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    return "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")
    ).decode("ascii")


def _comparison_core(value: Any) -> Any:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return None
    molecule = Chem.Mol(molecule)
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
            atom.SetIsotope(0)
    return molecule


def _attachment_stripped_components(value: Any) -> tuple[Any, ...]:
    """Return retained Core components without attachment dummy atoms.

    The dummy marks where a fragmentation boundary was drawn.  Keeping it in
    a substructure query incorrectly makes a smaller Core fail to match a
    larger Core whenever the latter moves that boundary farther outward.
    Components remain separate so a 2-cut comparison cannot satisfy both
    retained anchors with the same connected component.
    """
    molecule = _comparison_core(value)
    if molecule is None:
        return ()
    cleaned: list[Any] = []
    for fragment in Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=False):
        editable = Chem.RWMol(fragment)
        for atom_index in sorted(
            (atom.GetIdx() for atom in editable.GetAtoms() if atom.GetAtomicNum() == 0),
            reverse=True,
        ):
            editable.RemoveAtom(atom_index)
        component = editable.GetMol()
        if component.GetNumAtoms() == 0:
            continue
        try:
            Chem.SanitizeMol(component)
        except Exception:
            component.UpdatePropertyCache(strict=False)
        cleaned.append(component)
    return tuple(cleaned)


def _component_rank(components: tuple[Any, ...]) -> tuple[int, int, int]:
    return (
        sum(atom.GetAtomicNum() > 1 for mol in components for atom in mol.GetAtoms()),
        sum(mol.GetNumAtoms() for mol in components),
        sum(mol.GetNumBonds() for mol in components),
    )


def _strict_core_contains(
    larger_components: tuple[Any, ...],
    smaller_components: tuple[Any, ...],
    *,
    cut_count: int,
) -> bool:
    """Whether a Core is a strict superset while preserving anchor components."""
    if not larger_components or len(larger_components) != len(smaller_components):
        return False
    expected_components = 1 if cut_count == 1 else 2
    if len(larger_components) != expected_components:
        return False
    if _component_rank(larger_components) <= _component_rank(smaller_components):
        return False
    for ordered_larger in permutations(larger_components):
        if all(
            larger.HasSubstructMatch(smaller, useChirality=True)
            for larger, smaller in zip(ordered_larger, smaller_components)
        ):
            return True
    return False


def _minimal_direct_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Report-only maximal Core selection; canonical CSV remains complete."""
    if frame.empty:
        return frame.copy()
    selected: list[Any] = []
    group_columns = ["target_compound_id", "neighbor_compound_id", "cut_count"]
    for _, group in frame.groupby(group_columns, sort=True, dropna=False):
        cut_count = int(pd.to_numeric(group["cut_count"], errors="coerce").iloc[0])
        unique_cores = group.sort_values("evidence_id", kind="mergesort").drop_duplicates(
            "exact_core_smiles", keep="first"
        )
        candidates: list[tuple[Any, tuple[Any, ...], tuple[int, int, int, str]]] = []
        for index, row in unique_cores.iterrows():
            components = _attachment_stripped_components(row.get("exact_core_smiles"))
            rank = (*_component_rank(components), str(row.get("exact_core_smiles", "")))
            candidates.append((index, components, rank))
        maximal: list[tuple[Any, tuple[Any, ...], tuple[int, int, int, str]]] = []
        for candidate in candidates:
            dominated = False
            if candidate[1]:
                for other in candidates:
                    if other[0] == candidate[0] or not other[1]:
                        continue
                    if _strict_core_contains(
                        other[1], candidate[1], cut_count=cut_count
                    ):
                        dominated = True
                        break
            if not dominated:
                maximal.append(candidate)
        selected.extend(item[0] for item in (maximal or candidates))
    return frame.loc[selected].sort_values(
        ["cut_count", "neighbor_compound_id", "pair_favorable_gain", "evidence_id"],
        ascending=[True, True, False, True], kind="mergesort",
    ).reset_index(drop=True)


def _report_visible_evidence(evidence: pd.DataFrame) -> pd.DataFrame:
    eligible = evidence.loc[
        ~(
            evidence["cut_count"].eq(2)
            & evidence["two_cut_quality_class"].eq("2C-X")
        )
    ]
    direct = _minimal_direct_rows(
        eligible.loc[eligible["connection_scope"].eq("direct")]
    )
    transferred = eligible.loc[eligible["connection_scope"].eq("transferred")]
    return pd.concat([direct, transferred], ignore_index=True, sort=False)


def _portal_core_id(target_id: str, cut_count: Any, structure: Any) -> str:
    key = f"{target_id}|{int(cut_count)}|{str(structure)}"
    return "PCORE-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _add_portal_core_ids(evidence: pd.DataFrame, target_id: str) -> pd.DataFrame:
    """Link Direct Core nodes to Transferred evidence mapped onto that Target Core."""
    frame = evidence.copy()
    if frame.empty:
        frame["portal_core_id"] = pd.Series(dtype=str)
        return frame
    structures = frame.apply(
        lambda row: (
            row.get("exact_core_smiles", "")
            if row.get("connection_scope") == "direct"
            else row.get("target_core_smiles", "") or row.get("exact_core_smiles", "")
        ),
        axis=1,
    )
    frame["portal_core_id"] = [
        _portal_core_id(target_id, cut, structure)
        for cut, structure in zip(frame["cut_count"], structures)
    ]
    return frame


def _relationship_map(
    target_id: str,
    target_smiles: str,
    target_endpoint: Any,
    evidence: pd.DataFrame,
    *,
    cut_count: int | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Create a compact portal map; chemical detail belongs to the side panel."""
    eligible = evidence.loc[
        ~(
            evidence["cut_count"].eq(2)
            & evidence["two_cut_quality_class"].eq("2C-X")
        )
    ]
    eligible = _add_portal_core_ids(eligible, target_id)
    direct = _minimal_direct_rows(eligible.loc[eligible["connection_scope"].eq("direct")])
    transferred = eligible.loc[eligible["connection_scope"].eq("transferred")]
    if cut_count is not None:
        direct = direct.loc[direct["cut_count"].eq(cut_count)]
        transferred = transferred.loc[transferred["cut_count"].eq(cut_count)]
    if direct.empty:
        cut_label = f"{cut_count}-cut " if cut_count is not None else ""
        empty = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 700" role="img" aria-label="MMP relationship map">'
            '<rect width="1200" height="700" fill="#fff"/><text x="600" y="340" text-anchor="middle" '
            f'font-family="sans-serif" font-size="22" fill="#66737b">{cut_label}Direct MMPは検出されませんでした</text></svg>'
        )
        return empty, empty, {}
    primary_cut = cut_count if cut_count is not None else (1 if direct["cut_count"].eq(1).any() else 2)
    direct = direct.loc[direct["cut_count"].eq(primary_cut)]
    transferred = transferred.loc[transferred["cut_count"].eq(primary_cut)]
    if "target_oriented_delta" not in direct:
        gain = pd.to_numeric(direct.get("pair_favorable_gain"), errors="coerce")
        direct["target_oriented_delta"] = gain.where(
            direct.get("interpretation_role").eq("target_explanation"), -gain
        )
    direct["_abs_target_delta"] = pd.to_numeric(
        direct["target_oriented_delta"], errors="coerce"
    ).abs()
    core_stats = direct.groupby("portal_core_id", dropna=False).agg(
        direct_pair_count=("pair_id", "nunique"),
        max_effect=("_abs_target_delta", "max"),
    ).reset_index().sort_values(
        ["direct_pair_count", "max_effect", "portal_core_id"],
        ascending=[False, False, True], kind="mergesort",
    ).head(5)
    core_ids = core_stats["portal_core_id"].astype(str).tolist()
    center = (600.0, 360.0)
    # Each Core receives five collision-free portal slots.  Slots occupy the
    # outer perimeter and extend mainly left/right from off-axis Cores instead
    # of making the Map taller.  At six or more Neighbors they become one count
    # portal; nothing is dropped from the Core detail data.
    layouts_by_count = {
        1: [((600.0, 190.0), [(312.0, 35.0), (456.0, 35.0), (600.0, 35.0), (744.0, 35.0), (888.0, 35.0)])],
        2: [
            ((365.0, 360.0), [(90.0, 220.0), (90.0, 290.0), (90.0, 360.0), (90.0, 430.0), (90.0, 500.0)]),
            ((835.0, 360.0), [(1110.0, 220.0), (1110.0, 290.0), (1110.0, 360.0), (1110.0, 430.0), (1110.0, 500.0)]),
        ],
        3: [
            ((600.0, 175.0), [(312.0, 35.0), (456.0, 35.0), (600.0, 35.0), (744.0, 35.0), (888.0, 35.0)]),
            ((365.0, 500.0), [(90.0, 385.0), (90.0, 455.0), (90.0, 525.0), (90.0, 595.0), (90.0, 665.0)]),
            ((835.0, 500.0), [(1110.0, 385.0), (1110.0, 455.0), (1110.0, 525.0), (1110.0, 595.0), (1110.0, 665.0)]),
        ],
        4: [
            ((365.0, 190.0), [(90.0, 35.0), (90.0, 105.0), (90.0, 175.0), (90.0, 245.0), (90.0, 315.0)]),
            ((835.0, 190.0), [(1110.0, 35.0), (1110.0, 105.0), (1110.0, 175.0), (1110.0, 245.0), (1110.0, 315.0)]),
            ((365.0, 530.0), [(90.0, 385.0), (90.0, 455.0), (90.0, 525.0), (90.0, 595.0), (90.0, 665.0)]),
            ((835.0, 530.0), [(1110.0, 385.0), (1110.0, 455.0), (1110.0, 525.0), (1110.0, 595.0), (1110.0, 665.0)]),
        ],
        5: [
            ((600.0, 175.0), [(312.0, 35.0), (456.0, 35.0), (600.0, 35.0), (744.0, 35.0), (888.0, 35.0)]),
            ((835.0, 235.0), [(1110.0, 35.0), (1110.0, 105.0), (1110.0, 175.0), (1110.0, 245.0), (1110.0, 315.0)]),
            ((835.0, 500.0), [(1110.0, 385.0), (1110.0, 455.0), (1110.0, 525.0), (1110.0, 595.0), (1110.0, 665.0)]),
            ((600.0, 525.0), [(312.0, 665.0), (456.0, 665.0), (600.0, 665.0), (744.0, 665.0), (888.0, 665.0)]),
            ((365.0, 380.0), [(90.0, 220.0), (90.0, 290.0), (90.0, 360.0), (90.0, 430.0), (90.0, 500.0)]),
        ],
    }
    layouts = layouts_by_count[len(core_ids)]
    nodes: list[str] = []
    static_nodes: list[str] = []
    edges: list[str] = []
    image_lookup: dict[str, str] = {}
    target_image = _molecule_svg_data(target_smiles, 220, 135)
    target_node = (
        f'<g class="node" data-kind="target"><rect class="node-box target-box" x="485" y="282" rx="18" width="230" height="156"/>'
        f'<text class="node-role" x="500" y="304" fill="#173f67">TARGET</text><image href="{target_image}" x="507" y="308" width="186" height="90"/>'
        f'<text class="node-id" x="600" y="414" text-anchor="middle">{html.escape(target_id)}</text>'
        f'<text class="node-metric" x="600" y="430" text-anchor="middle">Endpoint {_format_number(target_endpoint)}</text></g>'
    )
    nodes.append(target_node); static_nodes.append(
        target_node.replace('class="node"', 'class="static-node"', 1)
    )
    for index, (core_id, layout) in enumerate(zip(core_ids, layouts), 1):
        (cx, cy), neighbor_slots = layout
        part = direct.loc[direct["portal_core_id"].astype(str).eq(core_id)].sort_values(
            ["_abs_target_delta", "neighbor_compound_id", "evidence_id"],
            ascending=[False, True, True], na_position="last", kind="mergesort",
        ).drop_duplicates("neighbor_compound_id")
        visible = part if len(part) <= 5 else part.iloc[0:0]
        core_structure = str(part.iloc[0]["exact_core_smiles"])
        core_image = _molecule_svg_data(core_structure, 138, 78)
        image_lookup[core_id] = core_image
        core_label = "RETAINED ANCHORS" if primary_cut == 2 else "EXACT CORE"
        related_count = int(
            transferred.loc[
                transferred["portal_core_id"].astype(str).eq(core_id), "evidence_id"
            ].nunique()
        )
        core_node = (
            f'<g class="node" data-kind="core" role="button" tabindex="0" data-core-id="{html.escape(core_id, quote=True)}" data-direct-count="{len(part)}" data-related-count="{related_count}">'
            f'<rect class="node-box core-box" x="{cx-76:.1f}" y="{cy-54:.1f}" rx="13" width="152" height="108"/>'
            f'<text class="node-role" x="{cx:.1f}" y="{cy-36:.1f}" text-anchor="middle" fill="#21834a">{core_label} {index}</text>'
            f'<image href="{core_image}" x="{cx-58:.1f}" y="{cy-30:.1f}" width="116" height="60"/>'
            f'<text class="node-metric" x="{cx:.1f}" y="{cy+40:.1f}" text-anchor="middle">Direct {len(part)} · Similar {related_count}</text></g>'
        )
        nodes.append(core_node); static_nodes.append(
            core_node.replace('class="node"', 'class="static-node"', 1)
        )
        if len(visible) == 1:
            slots = [neighbor_slots[2]]
        elif len(visible) == 2:
            slots = [neighbor_slots[1], neighbor_slots[3]]
        elif len(visible) == 3:
            slots = [neighbor_slots[0], neighbor_slots[2], neighbor_slots[4]]
        elif len(visible) == 4:
            slots = [neighbor_slots[0], neighbor_slots[1], neighbor_slots[3], neighbor_slots[4]]
        else:
            slots = neighbor_slots
        if len(part) > 5:
            nx, ny = neighbor_slots[2]
            edges.append(f'<path class="edge neutral" d="M {nx:.1f} {ny:.1f} L {cx:.1f} {cy:.1f} L 600 360"/>')
            group_node = (
                f'<g class="node" data-kind="neighbor-group" role="button" tabindex="0" data-core-id="{html.escape(core_id, quote=True)}" data-neighbor-count="{len(part)}">'
                f'<rect class="node-box neighbor-box" x="{nx-70:.1f}" y="{ny-31:.1f}" rx="10" width="140" height="62"/>'
                f'<text class="node-id" x="{nx:.1f}" y="{ny-2:.1f}" text-anchor="middle">{len(part)} Neighbor</text>'
                f'<text class="node-metric" x="{nx:.1f}" y="{ny+15:.1f}" text-anchor="middle">クリックして全件表示</text></g>'
            )
            nodes.append(group_node)
            static_nodes.append(group_node.replace('class="node"', 'class="static-node"', 1))
        for (nx, ny), row in zip(slots, visible.to_dict(orient="records")):
            target_delta = pd.to_numeric(
                pd.Series([row.get("target_oriented_delta")]), errors="coerce"
            ).iloc[0]
            if pd.isna(target_delta) or abs(float(target_delta)) < .10:
                edge_class = "neutral"
            elif float(target_delta) > 0:
                edge_class = "explanation"
            else:
                edge_class = "improvement"
            # Target is always the product/end of the displayed arrow.
            path = f"M {nx:.1f} {ny:.1f} L {cx:.1f} {cy:.1f} L 600 360"
            edges.append(f'<path class="edge {edge_class}" d="{path}"/>')
            evidence_id = str(row["evidence_id"])
            neighbor_id = str(row["neighbor_compound_id"])
            neighbor_node = (
                f'<g class="node" data-kind="neighbor" role="button" tabindex="0" data-evidence-id="{html.escape(evidence_id, quote=True)}" data-neighbor-count="1">'
                f'<rect class="node-box neighbor-box" x="{nx-70:.1f}" y="{ny-31:.1f}" rx="10" width="140" height="62"/>'
                f'<text class="node-id" x="{nx:.1f}" y="{ny-10:.1f}" text-anchor="middle">{html.escape(neighbor_id[:15])}</text>'
                f'<text class="node-metric" x="{nx:.1f}" y="{ny+7:.1f}" text-anchor="middle">Endpoint {_format_number(row["neighbor_endpoint"])}</text>'
                f'<text class="node-metric" x="{nx:.1f}" y="{ny+22:.1f}" text-anchor="middle">ΔN2T {_format_number(target_delta)}</text></g>'
            )
            nodes.append(neighbor_node)
            static_nodes.append(
                neighbor_node.replace('class="node"', 'class="static-node"', 1)
            )
    svg_style = (
        '<style>.edge{fill:none;stroke:#b7bec2;stroke-width:1.7px;stroke-dasharray:5 4}'
        '.edge.explanation{stroke:#173f67;marker-end:url(#arrowNavy)}'
        '.edge.improvement{stroke:#e07a24;marker-end:url(#arrowOrange)}'
        '.edge.neutral{stroke:#9aa3a8}'
        '.node-box{fill:#fff;stroke-width:3px}.target-box{stroke:#173f67}'
        '.core-box{stroke:#21834a}.neighbor-box{stroke:#e07a24}'
        '.node-role{font:800 11px sans-serif;letter-spacing:.05em}'
        '.node-id{font:750 12px sans-serif}.node-metric{font:12px sans-serif;fill:#4e5960}'
        '</style>'
    )
    defs = (
        '<defs>' + svg_style
        + '<marker id="arrowNavy" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#173f67"/></marker>'
        '<marker id="arrowOrange" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#e07a24"/></marker></defs>'
    )
    legend = '<g font-family="sans-serif" font-size="13"><circle cx="34" cy="755" r="6" fill="#173f67"/><text x="47" y="760">Target</text><circle cx="125" cy="755" r="6" fill="#21834a"/><text x="138" y="760">Core / anchors</text><circle cx="286" cy="755" r="6" fill="#e07a24"/><text x="299" y="760">Neighbor</text><line x1="425" y1="755" x2="468" y2="755" stroke="#173f67" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrowNavy)"/><text x="480" y="760">Positive N2T: ΔN2T ≥ +0.10</text><line x1="765" y1="755" x2="808" y2="755" stroke="#e07a24" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrowOrange)"/><text x="820" y="760">Negative N2T: ΔN2T ≤ -0.10</text></g>'
    opening = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 710" role="img" aria-label="MMP relationship map">'
    static_opening = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 785" role="img" aria-label="MMP relationship map">'
    interactive = opening + defs + "".join(edges + nodes) + "</svg>"
    static = static_opening + defs + "".join(edges + static_nodes) + legend + "</svg>"
    return interactive, static, image_lookup


def _evidence_payload(
    evidence: pd.DataFrame, max_rows: int, external_asset_dir: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, str], bool, list[Path]]:
    ordered = evidence.assign(
        _quality_order=evidence["target_evidence_quality"].map(
            {"high": 0, "limited": 1, "not_applicable": 2, "ambiguous": 3}
        ).fillna(4),
        _scope_order=evidence["connection_scope"].map({"direct": 0, "transferred": 1}).fillna(2),
    ).sort_values(
        ["_quality_order", "_scope_order", "pair_favorable_gain", "evidence_id"],
        ascending=[True, True, False, True], na_position="last", kind="mergesort",
    ).drop(columns=["_quality_order", "_scope_order"])
    limited = len(ordered) > max_rows
    records: list[dict[str, Any]] = []
    assets: dict[str, str] = {}
    asset_keys: dict[tuple[Any, ...], str] = {}
    external_files: set[Path] = set()

    def image_asset(
        value: Any, width: int, height: int, *, reference: Any = None, core: Any = None,
        mcs_smarts: Any = None, environment_radius: Any = None,
    ) -> str:
        key = (
            str(value), width, height, str(reference or ""), str(core or ""),
            str(mcs_smarts or ""), str(environment_radius or ""),
        )
        asset_id = asset_keys.get(key)
        if asset_id is None:
            asset_id = "IMG-" + hashlib.sha256(
                json.dumps(key, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            asset_keys[key] = asset_id
            assets[asset_id] = (
                _highlighted_core_svg_data(
                    value, mcs_smarts, environment_radius, width, height
                ) if mcs_smarts else _molecule_svg_data(
                    value, width, height, reference=reference, core=core
                )
            )
        return "@" + asset_id

    def raw_image_asset(
        value: str, key: tuple[Any, ...], *, external: bool = False
    ) -> str:
        if not value:
            return ""
        if external and external_asset_dir is not None:
            external_asset_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(
                json.dumps(key, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:20]
            path = external_asset_dir / f"aligned_{digest}.svg"
            path.write_text(_svg_data_to_text(value), encoding="utf-8")
            external_files.add(path)
            return f"assets/{path.name}"
        asset_id = asset_keys.get(key)
        if asset_id is None:
            asset_id = "IMG-" + hashlib.sha256(
                json.dumps(key, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            asset_keys[key] = asset_id
            assets[asset_id] = value
        return "@" + asset_id

    for row in ordered.head(max_rows).to_dict(orient="records"):
        target_smiles = row.get("target_smiles", "")
        is_direct = row.get("connection_scope") == "direct"
        fixed_side = str(row.get("target_variable_side_fixed", ""))
        if is_direct:
            neighbor_smiles = row.get("neighbor_smiles", "")
            neighbor_image, target_image, alignment_status = _aligned_pair_svg_data(
                neighbor_smiles, target_smiles, row.get("exact_core_smiles"), 270, 170
            )
            row["neighbor_image"] = raw_image_asset(neighbor_image, (
                "aligned-neighbor", neighbor_smiles, target_smiles,
                row.get("exact_core_smiles"), 270, 170,
            ))
            row["target_image"] = raw_image_asset(target_image, (
                "target-reference", target_smiles, 270, 170,
            ))
            row["alignment_status"] = alignment_status
            target_fragment = (
                row.get("variable_from") if fixed_side == "A" else row.get("variable_to")
            )
            counterpart_fragment = (
                row.get("variable_to") if fixed_side == "A" else row.get("variable_from")
            )
        else:
            # Transferred observations do not contain the exact Target.  When
            # its current fragment maps uniquely to one observed side, display
            # that Target-like analog on the right and the counterpart on the
            # left.  This gives the Target report one stable visual direction
            # without mutating the canonical Database direction.
            target_like_is_from = fixed_side == "A"
            mapping_directional = fixed_side in {"A", "B"}
            left_smiles = (
                row.get("smiles_to") if target_like_is_from else row.get("smiles_from")
            )
            right_smiles = (
                row.get("smiles_from") if target_like_is_from else row.get("smiles_to")
            )
            left_image, right_image, alignment_status = _aligned_pair_svg_data(
                left_smiles, right_smiles,
                row.get("exact_core_smiles"), 250, 155
            )
            alignment_key = (
                left_smiles, right_smiles,
                row.get("exact_core_smiles"), 250, 155,
            )
            row["observed_counterpart_image"] = raw_image_asset(
                left_image, ("aligned-observed-counterpart",) + alignment_key,
                external=True,
            )
            row["observed_target_like_image"] = raw_image_asset(
                right_image, ("aligned-observed-target-like",) + alignment_key,
                external=True,
            )
            row["observed_counterpart_id"] = (
                row.get("compound_id_to") if target_like_is_from else row.get("compound_id_from")
            )
            row["observed_target_like_id"] = (
                row.get("compound_id_from") if target_like_is_from else row.get("compound_id_to")
            )
            row["observed_counterpart_endpoint"] = (
                row.get("endpoint_to") if target_like_is_from else row.get("endpoint_from")
            )
            row["observed_target_like_endpoint"] = (
                row.get("endpoint_from") if target_like_is_from else row.get("endpoint_to")
            )
            row["observed_counterpart_fragment_image"] = image_asset(
                row.get("variable_to") if target_like_is_from else row.get("variable_from"),
                180, 105,
            )
            row["observed_target_like_fragment_image"] = image_asset(
                row.get("variable_from") if target_like_is_from else row.get("variable_to"),
                180, 105,
            )
            row["target_like_mapping_directional"] = mapping_directional
            row["alignment_status"] = alignment_status
            row["target_image"] = image_asset(target_smiles, 270, 170)
            row["neighbor_image"] = ""
            target_fragment = row.get("target_current_variable")
            counterpart_fragment = (
                row.get("variable_to") if fixed_side == "A"
                else row.get("variable_from") if fixed_side == "B"
                else ""
            )
        row["core_image"] = image_asset(row.get("exact_core_smiles"), 220, 130)
        # Every Transferred row must remain visually inspectable, including
        # not-applicable and ambiguous references.  Evidence quality controls
        # interpretation, not whether its Core structures are rendered.
        if row.get("connection_scope") == "transferred":
            row["target_core_image"] = image_asset(
                row.get("target_core_smiles") or row.get("exact_core_smiles"), 220, 130,
                mcs_smarts=row.get("mapped_mcs_smarts"),
                environment_radius=row.get("environment_match_radius"),
            )
            row["evidence_core_image"] = image_asset(
                row.get("exact_core_smiles"), 220, 130,
                mcs_smarts=row.get("mapped_mcs_smarts"),
                environment_radius=row.get("environment_match_radius"),
            )
        else:
            row["target_core_image"] = ""
            row["evidence_core_image"] = ""
        row["counterpart_fragment_image"] = (
            image_asset(counterpart_fragment, 190, 110) if counterpart_fragment else ""
        )
        row["target_fragment_image"] = (
            image_asset(target_fragment, 190, 110) if target_fragment else ""
        )
        row["observed_from_fragment_image"] = image_asset(
            row.get("variable_from"), 180, 105
        )
        row["observed_to_fragment_image"] = image_asset(
            row.get("variable_to"), 180, 105
        )
        # Compatibility aliases for external consumers; the Interactive report
        # uses the explicitly Target-oriented names above.
        row["before_image"] = row["counterpart_fragment_image"]
        row["after_image"] = row["target_fragment_image"]
        for key, value in list(row.items()):
            if isinstance(value, float) and not math.isfinite(value):
                row[key] = None
            elif hasattr(value, "item"):
                row[key] = value.item()
        records.append(row)
    return records, assets, limited, sorted(external_files)


def _report_indexes(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build deterministic portal and interpretation summaries for the HTML."""
    by_core: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_core.setdefault(str(record.get("portal_core_id", "")), []).append(record)
    core_index: list[dict[str, Any]] = []
    for portal_id, rows in sorted(by_core.items()):
        if not portal_id:
            continue
        direct = [row for row in rows if row.get("connection_scope") == "direct"]
        transferred = [row for row in rows if row.get("connection_scope") == "transferred"]
        first = (direct or transferred)[0]
        related: dict[str, list[dict[str, Any]]] = {}
        for row in transferred:
            related.setdefault(str(row.get("core_id", "")), []).append(row)
        related_groups = []
        for evidence_core_id, group in sorted(related.items()):
            representative = group[0]
            related_groups.append({
                "evidence_core_id": evidence_core_id,
                "evidence_ids": [str(item.get("evidence_id")) for item in group],
                "core_image": representative.get("evidence_core_image") or representative.get("core_image"),
                "evidence_class": representative.get("evidence_class"),
                "mapping_status": representative.get("mapping_status"),
                "core_tanimoto": representative.get("core_tanimoto"),
                "mcs_coverage": representative.get("mcs_coverage"),
                "unique_pair_count": max(int(item.get("unique_pair_count") or 0) for item in group),
                "direction_consistency": max(
                    [float(item.get("direction_consistency")) for item in group if item.get("direction_consistency") is not None]
                    or [math.nan]
                ),
            })
        core_index.append({
            "portal_core_id": portal_id,
            "cut_count": int(first.get("cut_count") or 0),
            "label": (
                "2-cuts Target-side anchors"
                if int(first.get("cut_count") or 0) == 2
                else "1-cut Target-side Core"
            ),
            "core_image": (
                (direct[0].get("core_image") if direct else first.get("target_core_image"))
                or first.get("core_image")
            ),
            "target_image": (
                (direct[0].get("target_image") if direct else first.get("target_image"))
                or first.get("target_image")
            ),
            "direct_evidence_ids": [str(row.get("evidence_id")) for row in direct],
            "neighbor_count": len({str(row.get("neighbor_compound_id")) for row in direct}),
            "transferred_evidence_count": len({str(row.get("evidence_id")) for row in transferred}),
            "related_core_groups": related_groups,
        })

    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("portal_core_id", "")),
            str(record.get("transformation_family_id", "")),
            int(record.get("cut_count") or 0),
        )
        grouped.setdefault(key, []).append(record)
    insights: list[dict[str, Any]] = []
    for (portal_id, family_id, cut), rows in sorted(grouped.items()):
        deltas = [
            float(row["target_oriented_delta"])
            for row in rows
            if row.get("target_oriented_delta") is not None
            and math.isfinite(float(row["target_oriented_delta"]))
        ]
        positive = sum(value >= 0 for value in deltas)
        negative = sum(value < 0 for value in deltas)
        neutral = sum(abs(value) < .10 for value in deltas)
        # A transformation family may contain both signs in different
        # contexts.  Emit one insight card per Target reading so an
        # improvement card can never open a positive representative (or vice
        # versa).  The opposing count remains visible as conflict context.
        for reading, predicate in (
            ("support", lambda value: value >= 0),
            ("improvement", lambda value: value < 0),
        ):
            reading_rows = [
                row for row in rows
                if row.get("target_oriented_delta") is not None
                and math.isfinite(float(row["target_oriented_delta"]))
                and predicate(float(row["target_oriented_delta"]))
            ]
            if not reading_rows:
                continue
            representative = sorted(
                reading_rows,
                key=lambda row: (
                    -abs(float(row["target_oriented_delta"])),
                    str(row.get("evidence_id", "")),
                ),
            )[0]
            reading_deltas = [float(row["target_oriented_delta"]) for row in reading_rows]
            insights.append({
                "group_id": "IG-" + hashlib.sha256(
                    f"{portal_id}|{family_id}|{cut}|{reading}".encode("utf-8")
                ).hexdigest()[:16],
                "reading": reading,
                "portal_core_id": portal_id,
                "transformation_family_id": family_id,
                "cut_count": cut,
                "evidence_ids": [str(row.get("evidence_id")) for row in reading_rows],
                "representative_evidence_id": str(representative.get("evidence_id")),
                "direct_count": sum(
                    row.get("connection_scope") == "direct" for row in reading_rows
                ),
                "transferred_count": sum(
                    row.get("connection_scope") == "transferred" for row in reading_rows
                ),
                "positive_count": positive,
                "negative_count": negative,
                "neutral_count": neutral,
                "reading_count": len(reading_rows),
                "median_target_delta": float(pd.Series(reading_deltas).median()),
                "counterpart_fragment_image": representative.get("counterpart_fragment_image"),
                "target_fragment_image": representative.get("target_fragment_image"),
                "counterpart_fragment": (
                    representative.get("variable_to")
                    if representative.get("target_variable_side_fixed") == "A"
                    else representative.get("variable_from")
                ),
                "target_fragment": representative.get("target_current_variable"),
                "evidence_class": representative.get("evidence_class"),
            })
    insights.sort(key=lambda row: (
        -abs(float(row["median_target_delta"])) if math.isfinite(float(row["median_target_delta"])) else math.inf,
        row["group_id"],
    ))
    return core_index, insights


def _database_summaries(
    details: pd.DataFrame, contexts: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create deterministic, cut-separated human and machine summaries."""
    transformation_columns = [
        "cut_count", "transformation_family_id", "transformation_id",
        "variable_from", "variable_to", "unique_pair_count",
        "unique_compound_count", "unique_context_count", "supporting_pair_count",
        "conflicting_pair_count", "neutral_pair_count", "missing_pair_count",
        "direction_consistency", "signed_delta_median", "signed_delta_iqr",
        "signed_delta_min", "signed_delta_max",
    ]
    transformation_rows: list[dict[str, Any]] = []
    if len(details):
        for keys, group in details.groupby(
            ["cut_count", "transformation_family_id", "transformation_id",
             "variable_from", "variable_to"],
            dropna=False, sort=True,
        ):
            pairs = group.drop_duplicates("pair_id")
            effect = pd.to_numeric(pairs["fixed_direction_effect"], errors="coerce")
            nonneutral = effect[effect.abs().ge(NEUTRAL_TOLERANCE)].dropna()
            supporting = int(nonneutral.gt(0).sum())
            conflicting = int(nonneutral.lt(0).sum())
            compounds = set(pairs["compound_id_from"].astype(str)) | set(
                pairs["compound_id_to"].astype(str)
            )
            transformation_rows.append({
                "cut_count": int(keys[0]),
                "transformation_family_id": keys[1],
                "transformation_id": keys[2],
                "variable_from": keys[3],
                "variable_to": keys[4],
                "unique_pair_count": int(len(pairs)),
                "unique_compound_count": int(len(compounds)),
                "unique_context_count": int(group["core_id"].nunique()),
                "supporting_pair_count": supporting,
                "conflicting_pair_count": conflicting,
                "neutral_pair_count": int(effect.abs().lt(NEUTRAL_TOLERANCE).sum()),
                "missing_pair_count": int(effect.isna().sum()),
                "direction_consistency": (
                    supporting / (supporting + conflicting)
                    if supporting + conflicting else math.nan
                ),
                "signed_delta_median": float(nonneutral.median()) if len(nonneutral) else math.nan,
                "signed_delta_iqr": (
                    float(nonneutral.quantile(.75) - nonneutral.quantile(.25))
                    if len(nonneutral) else math.nan
                ),
                "signed_delta_min": float(nonneutral.min()) if len(nonneutral) else math.nan,
                "signed_delta_max": float(nonneutral.max()) if len(nonneutral) else math.nan,
            })
    transformation = pd.DataFrame(transformation_rows, columns=transformation_columns)

    context_columns = [
        "cut_count", "core_id", "core_or_anchor_smiles", "unique_pair_count",
        "unique_transformation_count", "core_heavy_atoms",
        "environment_radius_coverage",
    ]
    context_rows: list[dict[str, Any]] = []
    radius_lookup: dict[str, str] = {}
    if len(contexts) and {"mmp_id", "radius"}.issubset(contexts.columns):
        radius_lookup = {
            str(mmp_id): "|".join(str(int(value)) for value in sorted(
                set(pd.to_numeric(group["radius"], errors="coerce").dropna())
            ))
            for mmp_id, group in contexts.groupby("mmp_id", dropna=False)
        }
    if len(details):
        for (cut_count, core_id), group in details.groupby(
            ["cut_count", "core_id"], dropna=False, sort=True
        ):
            radii: set[str] = set()
            for mmp_id in group["mmp_id"].astype(str).unique():
                radii.update(item for item in radius_lookup.get(mmp_id, "").split("|") if item)
            context_rows.append({
                "cut_count": int(cut_count),
                "core_id": core_id,
                "core_or_anchor_smiles": group.iloc[0]["exact_core_smiles"],
                "unique_pair_count": int(group["pair_id"].nunique()),
                "unique_transformation_count": int(group["transformation_id"].nunique()),
                "core_heavy_atoms": int(group["core_heavy_atoms"].max()),
                "environment_radius_coverage": "|".join(sorted(radii, key=int)),
            })
    context_summary = pd.DataFrame(context_rows, columns=context_columns)

    quality_columns = [
        "two_cut_quality_class", "two_cut_quality_reasons",
        "pair_transformation_rows", "unique_pair_count", "unique_context_count",
    ]
    quality_rows: list[dict[str, Any]] = []
    two_cut = details.loc[details["cut_count"].eq(2)] if len(details) else details
    if len(two_cut):
        for (quality, reasons), group in two_cut.groupby(
            ["two_cut_quality_class", "two_cut_quality_reasons"],
            dropna=False, sort=True,
        ):
            quality_rows.append({
                "two_cut_quality_class": quality,
                "two_cut_quality_reasons": reasons,
                "pair_transformation_rows": int(len(group)),
                "unique_pair_count": int(group["pair_id"].nunique()),
                "unique_context_count": int(group["core_id"].nunique()),
            })
    quality_summary = pd.DataFrame(quality_rows, columns=quality_columns)

    environment_columns = ["radius", "native_context_rows", "unique_mmp_count"]
    environment_rows: list[dict[str, Any]] = []
    if len(contexts) and "radius" in contexts:
        for radius, group in contexts.groupby("radius", dropna=False, sort=True):
            environment_rows.append({
                "radius": radius,
                "native_context_rows": int(len(group)),
                "unique_mmp_count": int(group["mmp_id"].nunique()),
            })
    environment_summary = pd.DataFrame(environment_rows, columns=environment_columns)
    return transformation, context_summary, quality_summary, environment_summary


def _build_database(
    args: argparse.Namespace,
    outdir: Path,
    valid: pd.DataFrame,
    coverage: pd.DataFrame,
    neutral_tolerance: float,
    two_cut_thresholds: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], list[str]]:
    fragment_db, native_db = build_native_database(
        valid, outdir / "_work", jobs=args.fragment_jobs, num_cuts=args.num_cuts,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        extended_core_fraction=args.min_core_fraction,
        min_radius=args.min_radius, max_radius=args.max_radius,
        cut_smarts=args.cut_smarts,
        max_variable_heavy_atoms=args.max_variable_heavy_atoms,
    )
    endpoint_map = dict(zip(valid["compound_id"], valid["endpoint"]))
    native_details, contexts, filter_stats = extract_pairs(
        native_db, endpoint_map, higher_is_better=args.higher_is_better,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        min_core_fraction=args.min_core_fraction,
    )
    details = canonicalize_pair_transformations(
        native_details, higher_is_better=args.higher_is_better,
        neutral_tolerance=neutral_tolerance, two_cut_thresholds=two_cut_thresholds,
    )
    fragmentations = read_fragmentations(fragment_db)
    structural_parameters = {
        "min_core_heavy_atoms": args.min_core_heavy_atoms,
        "min_core_fraction": args.min_core_fraction,
        "max_variable_heavy_atoms": args.max_variable_heavy_atoms,
        "radius": [args.min_radius, args.max_radius],
        "two_cut_thresholds": two_cut_thresholds,
    }
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "model_revision": MODEL_REVISION,
        "engine_version": ENGINE_VERSION,
        "input_sha256": sha256_file(Path(args.input)),
        "structure_signature": structure_signature(
            coverage, cut_smarts=args.cut_smarts, num_cuts=args.num_cuts,
            parameters=structural_parameters,
        ),
        "effect_signature": effect_signature(
            coverage, endpoint_column=args.endpoint_column,
            higher_is_better=args.higher_is_better,
            neutral_tolerance=neutral_tolerance,
        ),
        "endpoint_column": args.endpoint_column,
        "higher_is_better": args.higher_is_better,
        "neutral_tolerance": neutral_tolerance,
        "cut_smarts": args.cut_smarts,
        "num_cuts": args.num_cuts,
        "structural_parameters": structural_parameters,
        "filter_stats": filter_stats,
        "created_at": utc_now(),
        "target_independent": True,
        "immutable": True,
        "benchmark_status": "provisional_pending_human_checkpoints_A_B_D",
        "template_hashes": {
            name: sha256_file(SKILL_DIR / "templates" / name)
            for name in (
                "mmp_database_report_0111.html",
                "mmp_target_index_0111.html",
                "mmp_target_workspace_template.html",
            )
        },
    }
    return details, fragmentations, contexts, metadata, []


def execute() -> int:
    # mmpdb/RDKit can emit one warning per rejected fragmentation.  The
    # structured coverage and exclusion tables retain the actionable result;
    # suppressing console warnings keeps background execution observable.
    RDLogger.DisableLog("rdApp.warning")
    request, outdir, capability = parse_request()
    parameters, legacy = adapt_legacy_parameters(request.get("parameters", {}))
    validate_parameters(parameters)
    mode = parameters["mode"]
    data, compound_id, smiles, endpoint = request_dataset(request)
    dataset_input = next((item for item in request.get("inputs", []) if item.get("role") == "dataset"), None)
    if dataset_input is None:
        raise ValueError("MMP Execution Request requires one dataset input")
    input_path = Path(dataset_input["path"]).resolve()
    higher_is_better = bool(request.get("endpoint", {}).get("higher_is_better"))
    neutral_tolerance = float(parameters.get("neutral_tolerance", NEUTRAL_TOLERANCE))
    if neutral_tolerance != NEUTRAL_TOLERANCE:
        raise ValueError("CONDUCTOR 0.1.11 fixes neutral_tolerance at 0.10")
    num_cuts = int(parameters.get("cuts", 2))
    if num_cuts != 2:
        raise ValueError("CONDUCTOR 0.1.11 canonical database uses maximum cuts=2 and separates 1/2-cut rows")
    radius_min, radius_max = int(parameters.get("radius_min", 0)), int(parameters.get("radius_max", 2))
    if not (0 <= radius_min <= radius_max <= 2):
        raise ValueError("MMP radius must satisfy 0 <= radius_min <= radius_max <= 2")
    max_compounds = int(parameters.get("max_compounds", 5000))
    if max_compounds != 5000:
        raise ValueError("CONDUCTOR 0.1.11 formal MMP maximum is fixed at 5000 compounds")
    valid, coverage, warnings = load_input(
        input_path, compound_id, smiles, endpoint, max_compounds
    )
    cut_smarts = str(parameters.get("cut_smarts", "default"))
    thresholds = {**DEFAULT_TWO_CUT_THRESHOLDS, **parameters.get("two_cut_thresholds", {})}
    args = argparse.Namespace(
        input=str(input_path), endpoint_column=endpoint,
        higher_is_better=higher_is_better,
        fragment_jobs=max(1, min(8, int(request.get("resources", {}).get("node_cpu_cores", 1)))),
        num_cuts=2, min_core_heavy_atoms=int(parameters.get("min_core_heavy_atoms", 8)),
        min_core_fraction=float(parameters.get("min_core_fraction", .5)),
        max_variable_heavy_atoms=int(parameters.get("max_variable_heavy_atoms", 20)),
        min_radius=radius_min, max_radius=radius_max, cut_smarts=cut_smarts,
    )
    structural_parameters = {
        "min_core_heavy_atoms": args.min_core_heavy_atoms,
        "min_core_fraction": args.min_core_fraction,
        "max_variable_heavy_atoms": args.max_variable_heavy_atoms,
        "radius": [radius_min, radius_max],
        "two_cut_thresholds": thresholds,
    }
    expected_structure_signature = structure_signature(
        coverage, cut_smarts=cut_smarts, num_cuts=2,
        parameters=structural_parameters,
    )
    expected_effect_signature = effect_signature(
        coverage, endpoint_column=endpoint, higher_is_better=higher_is_better,
        neutral_tolerance=neutral_tolerance,
    )
    database_input = next((item for item in request.get("inputs", []) if item.get("role") == "mmp_database"), None)
    if mode == "database" and database_input is not None:
        raise ValueError("MMP mode=database constructs a new canonical database and does not accept mmp_database input")
    reused_database = False
    effect_refreshed = False
    if database_input is not None:
        database_path = Path(str(database_input.get("path", ""))).resolve()
        details, fragmentations, contexts, metadata = load_canonical_database(database_path)
        if metadata.get("structure_signature") != expected_structure_signature:
            raise ValueError("Canonical MMP database structure signature is incompatible with this Run")
        reused_database = True
        if metadata.get("effect_signature") != expected_effect_signature:
            details = _refresh_effects(details, coverage, higher_is_better, neutral_tolerance)
            effect_refreshed = True
    else:
        details, fragmentations, contexts, metadata, build_warnings = _build_database(
            args, outdir, valid, coverage, neutral_tolerance, thresholds
        )
        warnings.extend(build_warnings)
        database_path = outdir / "mmp_database.sqlite"
        storage = write_canonical_database(
            database_path, details=details, fragmentations=fragmentations,
            compounds=coverage, contexts=contexts, metadata=metadata,
        )
        metadata["storage"] = storage
        shutil.rmtree(outdir / "_work", ignore_errors=True)

    details_path = outdir / "mmp_pair_detail.csv"
    fragments_path = outdir / "mmp_fragmentations.csv"
    details.to_csv(details_path, index=False)
    fragmentations.to_csv(fragments_path, index=False)
    transformation_summary, context_summary, quality_summary, environment_summary = (
        _database_summaries(details, contexts)
    )
    transformation_summary_path = outdir / "transformation_summary.csv"
    context_summary_path = outdir / "context_summary.csv"
    quality_summary_path = outdir / "two_cut_quality_summary.csv"
    environment_summary_path = outdir / "environment_summary.csv"
    transformation_summary.to_csv(transformation_summary_path, index=False)
    context_summary.to_csv(context_summary_path, index=False)
    quality_summary.to_csv(quality_summary_path, index=False)
    environment_summary.to_csv(environment_summary_path, index=False)
    manifest_path = outdir / "mmp_database_manifest.json"
    manifest = {
        **metadata,
        "schema_version": SCHEMA_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "template_hashes": {
            name: sha256_file(SKILL_DIR / "templates" / name)
            for name in (
                "mmp_database_report_0111.html",
                "mmp_target_index_0111.html",
                "mmp_target_workspace_template.html",
            )
        },
        "mode": mode,
        "legacy_adapter": legacy,
        "database_path": str(database_path),
        "database_reused": reused_database,
        "effect_columns_refreshed": effect_refreshed,
        "current_effect_signature": expected_effect_signature,
        "row_counts": {
            "all": int(len(details)),
            "one_cut": int(details["cut_count"].eq(1).sum()) if len(details) else 0,
            "two_cut": int(details["cut_count"].eq(2).sum()) if len(details) else 0,
            "transformation_summary": int(len(transformation_summary)),
            "context_summary": int(len(context_summary)),
            "environment_summary": int(len(environment_summary)),
        },
    }
    write_json(manifest_path, manifest)

    if mode == "database":
        cut_table = details.groupby("cut_count").size().rename("pair transformation rows").reset_index()
        quality_table = (
            details.loc[details["cut_count"].eq(2), "two_cut_quality_class"]
            .value_counts(dropna=False).rename_axis("2-cut class").reset_index(name="rows")
        )
        report = outdir / "mmp_database_report.html"
        body = render_template("mmp_database_report_0111.html", {
            "metrics": _metric_grid([
                ("Compounds", coverage["compound_id"].nunique()),
                ("Canonical pairs", details["pair_id"].nunique() if len(details) else 0),
                ("Transformations", details["transformation_family_id"].nunique() if len(details) else 0),
                ("1-cut / 2-cut", f"{int(details['cut_count'].eq(1).sum())} / {int(details['cut_count'].eq(2).sum())}" if len(details) else "0 / 0"),
            ]),
            "cut_table": frame_html(cut_table, 20),
            "quality_table": frame_html(quality_table, 20),
            "environment_table": frame_html(environment_summary, 20),
        })
        report.write_text(html_page("A008 Canonical MMP Database", body), encoding="utf-8")
        audit_path = outdir / "mmp_database_audit.json"
        audit = audit_database_output(outdir, database_path)
        write_json(audit_path, audit)
        if audit["status"] != "passed":
            raise ValueError("A008 database audit failed: " + "; ".join(audit["failures"][:10]))
        extras = [
            details_path, fragments_path, manifest_path, audit_path,
            transformation_summary_path, context_summary_path, quality_summary_path,
            environment_summary_path,
        ]
        finish_request(
            request, outdir, capability, primary=database_path,
            summary={
                "mode": mode, "canonical_pair_count": int(details["pair_id"].nunique()) if len(details) else 0,
                "one_cut_rows": int(details["cut_count"].eq(1).sum()) if len(details) else 0,
                "two_cut_rows": int(details["cut_count"].eq(2).sum()) if len(details) else 0,
                "negative_result": len(details) == 0,
            },
            report=report, extra_artifacts=extras, warnings=warnings,
        )
        return 0

    registry, sources = normalize_target_registry(parameters, data, compound_id)
    target_root = outdir / "targets"
    target_root.mkdir(exist_ok=True)
    registry_path = outdir / "mmp_target_registry.csv"
    sources_path = outdir / "mmp_target_selection_sources.csv"
    registry.to_csv(registry_path, index=False); sources.to_csv(sources_path, index=False)
    summaries: list[dict[str, Any]] = []
    index_records: list[dict[str, Any]] = []
    overview_cards: list[str] = []
    report_artifacts: list[Path] = []
    data_by_id = data.assign(_id=data[compound_id].astype(str)).set_index("_id")
    max_embedded = int(parameters.get("max_embedded_evidence", 500))
    for target_id in registry["target_compound_id"].astype(str):
        evidence = build_target_evidence(
            target_id, details=details, fragmentations=fragmentations, data=data,
            compound_id_column=compound_id, smiles_column=smiles, endpoint_column=endpoint,
            neutral_tolerance=neutral_tolerance,
            core_tanimoto_threshold=float(parameters.get("near_core_tanimoto", .70)),
            mcs_coverage_threshold=float(parameters.get("near_core_mcs_coverage", .70)),
        )
        virtual = build_virtual_candidates(
            target_id, evidence, fragmentations, data, compound_id, smiles, endpoint
        )
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in target_id)[:64]
        suffix = hashlib.sha256(target_id.encode("utf-8")).hexdigest()[:12]
        basename = f"{safe}_{suffix}"
        evidence_path = target_root / f"target_evidence_{basename}.csv"
        virtual_path = target_root / f"virtual_candidates_{basename}.csv"
        evidence.to_csv(evidence_path, index=False); virtual.to_csv(virtual_path, index=False)
        target_row = data_by_id.loc[target_id]
        target_smiles = str(target_row[smiles]); target_endpoint = target_row[endpoint]
        map_one, static_one, _ = _relationship_map(
            target_id, target_smiles, target_endpoint, evidence, cut_count=1
        )
        map_two, static_two, _ = _relationship_map(
            target_id, target_smiles, target_endpoint, evidence, cut_count=2
        )
        direct_cuts = set(pd.to_numeric(
            evidence.loc[evidence["connection_scope"].eq("direct"), "cut_count"],
            errors="coerce",
        ).dropna().astype(int))
        default_map_cut = 1 if 1 in direct_cuts else 2
        interactive_map = (
            f'<div class="map-stack" data-default-cut="{default_map_cut}">'
            f'<div class="map-layer{" active" if default_map_cut == 1 else ""}" data-map-cut="1">{map_one}</div>'
            f'<div class="map-layer{" active" if default_map_cut == 2 else ""}" data-map-cut="2">{map_two}</div>'
            '</div>'
        )
        static_map = static_one if default_map_cut == 1 else static_two
        static_path = target_root / f"mmp_static_map_{basename}.svg"
        static_path.write_text(static_map, encoding="utf-8")
        report_evidence = _add_portal_core_ids(
            _report_visible_evidence(evidence), target_id
        )
        records, image_assets, payload_truncated, external_image_files = _evidence_payload(
            report_evidence, max_embedded, target_root / "assets"
        )
        core_index, insight_groups = _report_indexes(records)
        virtual_records = virtual.to_dict(orient="records")
        for record in virtual_records:
            record["candidate_image"] = _molecule_svg_data(
                record.get("candidate_smiles"), 240, 150,
                reference=target_smiles,
            )
            for key, value in list(record.items()):
                if isinstance(value, float) and not math.isfinite(value):
                    record[key] = None
                elif hasattr(value, "item"):
                    record[key] = value.item()
        payload = {
            "target_id": target_id,
            "target_endpoint": None if pd.isna(target_endpoint) else float(target_endpoint),
            "evidence": records,
            "byId": {row["evidence_id"]: row for row in records},
            "assets": image_assets,
            "virtualCandidates": virtual_records,
            "coreIndex": core_index,
            "insightGroups": insight_groups,
            "reportSemantics": {
                "arrow": "Neighbor or observed counterpart to Target",
                "delta": "Target-oriented signed Endpoint difference",
                "positive": "Target Endpointを支持する観測",
                "negative": "Targetからの改善を考える手掛かり",
            },
        }
        payload_json = json.dumps(
            _json_safe(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).replace("</", "<\\/")
        source_part = sources.loc[sources["target_compound_id"].eq(target_id)]
        source_pills = "".join(
            f"<span class='pill source'>{html.escape(row.source_type)}: {html.escape(row.source_id or '—')}</span>"
            for row in source_part.itertuples(index=False)
        )
        page = target_root / f"mmp_target_{basename}.html"
        page.write_text(render_template("mmp_target_workspace_template.html", {
            "page_title": html.escape(f"MMP target {target_id}"),
            "target_heading": html.escape(f"MMP Target: {target_id}"),
            "target_meta": f"<span class='pill'>Endpoint {_format_number(target_endpoint)}</span>{source_pills}",
            "relationship_map": interactive_map,
            "payload_json": payload_json,
            "evidence_csv": html.escape(evidence_path.name, quote=True),
            "database_csv": html.escape(f"../{details_path.name}", quote=True),
        }), encoding="utf-8")
        direct_visible = report_evidence.loc[
            report_evidence["connection_scope"].eq("direct")
        ]
        transferred_visible = report_evidence.loc[
            report_evidence["connection_scope"].eq("transferred")
        ]
        pair_identity = "compound_pair_id" if "compound_pair_id" in evidence else "pair_id"
        def signed_count(frame: pd.DataFrame, *, positive: bool, identity: str) -> int:
            """Count the report interpretation from Target-oriented signed delta.

            The canonical transformation role remains available for evidence
            aggregation and candidate generation, but the Target report cards
            are defined only by Neighbor/analog -> Target signed direction.
            """
            delta = pd.to_numeric(frame["target_oriented_delta"], errors="coerce")
            mask = delta.ge(NEUTRAL_TOLERANCE) if positive else delta.le(-NEUTRAL_TOLERANCE)
            return int(frame.loc[mask, identity].nunique())
        direct_all = direct_visible
        canonical_direct = evidence.loc[evidence["connection_scope"].eq("direct")]
        summary = {
            "target_compound_id": target_id,
            "target_endpoint": None if pd.isna(target_endpoint) else float(target_endpoint),
            "direct_pair_count": int(direct_all[pair_identity].nunique()) if len(direct_all) else 0,
            "canonical_direct_pair_count": int(
                canonical_direct[pair_identity].nunique()
            ) if len(canonical_direct) else 0,
            "direct_one_cut_pair_count": int(
                direct_all.loc[direct_all["cut_count"].eq(1), "pair_id"].nunique()
            ) if len(direct_all) else 0,
            "direct_two_cut_pair_count": int(
                direct_all.loc[direct_all["cut_count"].eq(2), "pair_id"].nunique()
            ) if len(direct_all) else 0,
            "target_explanation_count": signed_count(
                direct_visible, positive=True, identity=pair_identity
            ),
            "observed_improvement_count": signed_count(
                direct_visible, positive=False, identity=pair_identity
            ),
            "transferred_explanation_count": signed_count(
                transferred_visible, positive=True, identity="evidence_id"
            ),
            "proposed_improvement_count": signed_count(
                transferred_visible, positive=False, identity="evidence_id"
            ),
            "virtual_candidate_count": int(len(virtual)),
            "interactive_report_path": str(page.relative_to(outdir)).replace("\\", "/"),
            "static_map_path": str(static_path.relative_to(outdir)).replace("\\", "/"),
            "evidence_csv_path": str(evidence_path.relative_to(outdir)).replace("\\", "/"),
            "canonical_evidence_row_count": int(len(evidence)),
            "report_evidence_row_count": int(len(report_evidence)),
            "embedded_evidence_row_count": int(len(records)),
            "payload_truncated": payload_truncated,
        }
        summaries.append(summary)
        overview_cards.append(
            "<article class='card'><div style='display:grid;grid-template-columns:180px 1fr;gap:14px;align-items:center'>"
            f"<img src='{_molecule_svg_data(target_smiles, 180, 120)}' alt='Target {html.escape(target_id, quote=True)} structure' style='width:180px;height:120px;object-fit:contain'>"
            "<div><h3>" + html.escape(target_id) + "</h3>"
            + source_pills
            + _metric_grid([
                ("Endpoint", _format_number(target_endpoint)),
                ("Direct 1-cut / 2-cut", f"{summary['direct_one_cut_pair_count']} / {summary['direct_two_cut_pair_count']}"),
                ("Positive N2T (ΔN2T ≥ +0.10)", summary["target_explanation_count"] + summary["transferred_explanation_count"]),
                ("Negative N2T (ΔN2T ≤ -0.10)", summary["observed_improvement_count"] + summary["proposed_improvement_count"]),
            ])
            + f"<p><a href='{html.escape(summary['interactive_report_path'], quote=True)}'>Interactive Target report</a> · <a href='{html.escape(summary['static_map_path'], quote=True)}'>Static map</a></p>"
            "</div></div></article>"
        )
        for source in source_part.to_dict(orient="records"):
            index_records.append({
                **summary,
                **source,
                "analysis_unit_id": (
                    str(source["source_id"])
                    if source["source_type"] in {"analysis_unit_top1", "global_top1"}
                    else ""
                ),
            })
        report_artifacts.extend([
            page, static_path, evidence_path, virtual_path, *external_image_files
        ])

    summary_frame = pd.DataFrame(summaries)
    summary_path = outdir / "mmp_target_summary.csv"
    summary_frame.to_csv(summary_path, index=False)
    index_path = outdir / "mmp_report_index.json"
    write_json(index_path, {
        "schema_version": "2.0.0", "calculation_version": CALCULATION_VERSION,
        "mode": "target", "unit_reports": index_records,
        "overview_path": "mmp_report.html",
    })
    cards = "".join(overview_cards)
    report = outdir / "mmp_report.html"
    body = render_template("mmp_target_index_0111.html", {
        "metrics": _metric_grid([
            ("Targets", len(registry)),
            ("Canonical pairs", details["pair_id"].nunique() if len(details) else 0),
            ("1-cut rows", int(details["cut_count"].eq(1).sum()) if len(details) else 0),
            ("2-cut rows", int(details["cut_count"].eq(2).sum()) if len(details) else 0),
        ]),
        "target_cards": cards,
    })
    report.write_text(html_page("A008 MMP Target解析", body), encoding="utf-8")
    audit_path = outdir / "mmp_report_audit.json"
    audit = audit_output(outdir)
    write_json(audit_path, audit)
    if audit["status"] != "passed":
        raise ValueError("A008 report audit failed: " + "; ".join(audit["failures"][:10]))
    extras = [
        details_path, fragments_path, manifest_path, registry_path, sources_path,
        transformation_summary_path, context_summary_path, quality_summary_path,
        environment_summary_path, index_path, audit_path, *report_artifacts,
    ]
    extras = list(dict.fromkeys(extras))
    if database_path.parent == outdir:
        extras.append(database_path)
    finish_request(
        request, outdir, capability, primary=summary_path,
        summary={
            "mode": mode, "target_count": int(len(registry)),
            "direct_pair_count": int(summary_frame["direct_pair_count"].sum()) if len(summary_frame) else 0,
            "database_reused": reused_database,
            "effect_refreshed": effect_refreshed,
            "negative_result": bool(summary_frame["direct_pair_count"].sum() == 0) if len(summary_frame) else True,
        },
        report=report, extra_artifacts=extras, warnings=warnings,
    )
    return 0
