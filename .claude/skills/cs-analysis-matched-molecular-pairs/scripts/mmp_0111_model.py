from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import networkx as nx
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdFMCS

from mmp_engine import stable_id


SCHEMA_VERSION = "2.0.0"
CALCULATION_VERSION = "0.1.11"
ENGINE_VERSION = "mmpdb-3.1.4"
MODEL_REVISION = "canonical-evidence-v6"
NEUTRAL_TOLERANCE = 0.10

# Provisional values. They are deliberately recorded in every manifest and
# remain subject to Human checkpoint A in the 0.1.11 implementation plan.
DEFAULT_TWO_CUT_THRESHOLDS = {
    # Each disconnected retained anchor must be chemically substantial.
    # Tiny anchors (for example a methyl group) usually duplicate a 1-cut
    # description and obscure the linker/core-replacement purpose of 2-cut.
    "min_anchor_heavy_atoms": 4,
    "min_combined_retained_fraction": 0.60,
    "max_variable_heavy_atoms": 15,
    "max_variable_fraction": 0.40,
}
_CORE_FP_GENERATOR = AllChem.GetMorganGenerator(radius=2, fpSize=2048)


def canonical_structure(value: Any) -> str:
    """Canonicalize a SMILES/SMARTS-like structure while retaining atom maps."""
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    molecule = Chem.MolFromSmiles(text)
    if molecule is None:
        molecule = Chem.MolFromSmarts(text)
    if molecule is None:
        return text
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def attachment_neutral_structure(value: Any) -> str:
    """Canonical graph key which ignores attachment label numbering.

    mmpdb query fragmentations contain unlabeled ``*`` atoms while indexed
    rule SMILES contain ``[*:1]``/``[*:2]``.  They must compare as the same
    fragment without discarding the original ordered mapping columns.
    """
    text = "" if value is None else str(value).strip()
    molecule = Chem.MolFromSmiles(text)
    if molecule is None:
        molecule = Chem.MolFromSmarts(text)
    if molecule is None:
        return text
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
            atom.SetIsotope(0)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def ordered_fragmentation_structures(
    variable: Any, constant: Any, attachment_order: Any
) -> tuple[str, str]:
    """Apply mmpdb's attachment order to an unlabeled fragmentation.

    mmpdb defines ``attachment_order[i]`` as the constant wildcard connected
    to the i-th variable wildcard.  Preserving that order is essential for
    2-cut A/B matching; stripping labels would conflate swapped linker ends.
    """
    variable_molecule = Chem.MolFromSmiles(str(variable))
    order_text = str(attachment_order)
    if variable_molecule is None:
        return canonical_structure(variable), canonical_structure(constant)
    variable_dummies = [
        atom for atom in variable_molecule.GetAtoms() if atom.GetAtomicNum() == 0
    ]
    if len(order_text) != len(variable_dummies) or not all(
        character.isdigit() for character in order_text
    ):
        return canonical_structure(variable), canonical_structure(constant)
    for atom, character in zip(variable_dummies, order_text):
        atom.SetAtomMapNum(int(character) + 1)
        atom.SetIsotope(0)
    variable_labeled = Chem.MolToSmiles(
        variable_molecule, canonical=True, isomericSmiles=True
    )
    constant_parts: list[str] = []
    for position, part in enumerate(str(constant).split("."), 1):
        molecule = Chem.MolFromSmiles(part)
        if molecule is None:
            return variable_labeled, canonical_structure(constant)
        for atom in molecule.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(position)
                atom.SetIsotope(0)
        constant_parts.append(Chem.MolToSmiles(
            molecule, canonical=True, isomericSmiles=True
        ))
    return variable_labeled, ".".join(constant_parts)


def heavy_atom_count(value: Any) -> int:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return 0
    return sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())


def core_fingerprint(value: Any) -> Any:
    molecule = Chem.MolFromSmiles(attachment_neutral_structure(value))
    return _CORE_FP_GENERATOR.GetFingerprint(molecule) if molecule is not None else None


def attachment_topology(value: Any) -> str:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return ""
    sites: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0:
            continue
        label = dummy.GetAtomMapNum() or dummy.GetIsotope()
        neighbors = list(dummy.GetNeighbors())
        if not neighbors:
            sites.append(f"{label}:unbound")
            continue
        neighbor = neighbors[0]
        bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
        sites.append(
            ":".join(
                [
                    str(label),
                    str(neighbor.GetAtomicNum()),
                    "ar" if neighbor.GetIsAromatic() else "al",
                    "ring" if neighbor.IsInRing() else "chain",
                    str(bond.GetBondType()) if bond is not None else "none",
                ]
            )
        )
    return "|".join(sorted(sites))


def attachment_topology_unlabeled(value: Any) -> str:
    """Attachment topology independent of label representation."""
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return ""
    sites: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0:
            continue
        neighbors = list(dummy.GetNeighbors())
        if not neighbors:
            sites.append("unbound")
            continue
        neighbor = neighbors[0]
        bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
        sites.append(":".join([
            str(neighbor.GetAtomicNum()),
            "ar" if neighbor.GetIsAromatic() else "al",
            "ring" if neighbor.IsInRing() else "chain",
            str(bond.GetBondType()) if bond is not None else "none",
        ]))
    return "|".join(sorted(sites))


def environment_signature(value: Any, radius: int) -> str:
    """Return a deterministic attachment-centred graph signature.

    This is used for Target-side comparison. Native mmpdb environment SMARTS
    remain stored unchanged for database auditability.
    """
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return ""
    sites: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0 or not dummy.GetNeighbors():
            continue
        frontier = {dummy.GetNeighbors()[0].GetIdx()}
        visited = {dummy.GetIdx()}
        layers: list[str] = []
        for _ in range(radius + 1):
            atoms: list[str] = []
            next_frontier: set[int] = set()
            for atom_index in sorted(frontier):
                if atom_index in visited:
                    continue
                visited.add(atom_index)
                atom = molecule.GetAtomWithIdx(atom_index)
                atoms.append(
                    ":".join(
                        [
                            str(atom.GetAtomicNum()),
                            str(atom.GetFormalCharge()),
                            "ar" if atom.GetIsAromatic() else "al",
                            "ring" if atom.IsInRing() else "chain",
                            str(atom.GetTotalDegree()),
                        ]
                    )
                )
                next_frontier.update(neighbor.GetIdx() for neighbor in atom.GetNeighbors())
            layers.append(",".join(sorted(atoms)))
            frontier = next_frontier - visited
        sites.append("/".join(layers))
    return "|".join(sorted(sites))


def _swap_record(record: dict[str, Any]) -> dict[str, Any]:
    swapped = dict(record)
    for left, right in (
        ("compound_id_from", "compound_id_to"),
        ("smiles_from", "smiles_to"),
        ("endpoint_from", "endpoint_to"),
        ("variable_from", "variable_to"),
        ("core_fraction_from", "core_fraction_to"),
    ):
        swapped[left], swapped[right] = record.get(right), record.get(left)
    value = pd.to_numeric(pd.Series([record.get("endpoint_delta")]), errors="coerce").iloc[0]
    swapped["endpoint_delta"] = -float(value) if pd.notna(value) else math.nan
    return swapped


def _constant_for_weld(value: Any) -> str:
    """Order constant components by attachment label, then remove labels."""
    components: list[tuple[int, str]] = []
    for position, text in enumerate(str(value).split("."), 1):
        molecule = Chem.MolFromSmiles(text)
        if molecule is None:
            return attachment_neutral_structure(value)
        labels = [
            atom.GetAtomMapNum() or atom.GetIsotope()
            for atom in molecule.GetAtoms() if atom.GetAtomicNum() == 0
        ]
        label = min((item for item in labels if item > 0), default=position)
        for atom in molecule.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(0)
                atom.SetIsotope(0)
        components.append((label, Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)))
    return ".".join(text for _, text in sorted(components))


def weld_labeled_fragments(constant: Any, variable: Any) -> Chem.Mol:
    """Reconnect mapped constant/variable dummies with RDKit graph edits.

    mmpdb's convenience SMILES welder does not support some valid branched
    two-cut fragments.  The canonical rows already carry attachment labels,
    so a graph-level weld is both simpler and more complete.
    """
    constant_molecule = Chem.MolFromSmiles(str(constant))
    variable_molecule = Chem.MolFromSmiles(str(variable))
    if constant_molecule is None or variable_molecule is None:
        raise ValueError("Cannot parse labeled fragments")
    combined = Chem.CombineMols(constant_molecule, variable_molecule)
    editable = Chem.RWMol(combined)
    attachments: dict[int, list[tuple[int, int, Chem.BondType]]] = {}
    for atom in editable.GetAtoms():
        if atom.GetAtomicNum() != 0:
            continue
        label = atom.GetAtomMapNum() or atom.GetIsotope()
        neighbors = list(atom.GetNeighbors())
        if label <= 0 or len(neighbors) != 1:
            raise ValueError("Attachment dummy must have one positive label and one neighbor")
        neighbor = neighbors[0]
        bond = editable.GetBondBetweenAtoms(atom.GetIdx(), neighbor.GetIdx())
        attachments.setdefault(label, []).append((
            atom.GetIdx(), neighbor.GetIdx(),
            bond.GetBondType() if bond is not None else Chem.BondType.SINGLE,
        ))
    if not attachments or any(len(entries) != 2 for entries in attachments.values()):
        raise ValueError("Each attachment label must occur once in constant and variable")
    dummy_indices: list[int] = []
    for label in sorted(attachments):
        left, right = attachments[label]
        bond_type = left[2] if left[2] == right[2] else Chem.BondType.SINGLE
        if editable.GetBondBetweenAtoms(left[1], right[1]) is not None:
            raise ValueError("Attachment weld would create a duplicate bond")
        editable.AddBond(left[1], right[1], bond_type)
        dummy_indices.extend([left[0], right[0]])
    for index in sorted(dummy_indices, reverse=True):
        editable.RemoveAtom(index)
    product = editable.GetMol()
    Chem.SanitizeMol(product)
    return product


def _reconstructs_compound(constant: Any, variable: Any, expected: Any) -> bool:
    """Verify that an mmpdb constant/variable pair reconstructs its parent."""
    try:
        product = weld_labeled_fragments(constant, variable)
        expected_molecule = Chem.MolFromSmiles(str(expected))
        if expected_molecule is None:
            return False
        # Fragment welding can change RDKit's local atom ordering at a chiral
        # attachment and therefore its textual @/@@ spelling.  This gate asks
        # whether the 2-cut connectivity reconstructs the parent; stereo is
        # preserved and checked separately when materializing a candidate.
        expected_key = Chem.MolToSmiles(
            expected_molecule, canonical=True, isomericSmiles=False
        )
        product_key = Chem.MolToSmiles(
            product, canonical=True, isomericSmiles=False
        )
        return bool(expected_key and product_key and expected_key == product_key)
    except Exception:
        return False


def canonicalize_pair_transformations(
    details: pd.DataFrame,
    *,
    higher_is_better: bool,
    neutral_tolerance: float = NEUTRAL_TOLERANCE,
    two_cut_thresholds: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Convert native mmpdb rows into Target-independent fixed directions."""
    thresholds = {**DEFAULT_TWO_CUT_THRESHOLDS, **(two_cut_thresholds or {})}
    if details.empty:
        return details.copy()
    records: list[dict[str, Any]] = []
    for native in details.to_dict(orient="records"):
        record = dict(native)
        record["variable_from"] = canonical_structure(record.get("variable_from"))
        record["variable_to"] = canonical_structure(record.get("variable_to"))
        record["exact_core_smiles"] = canonical_structure(record.get("exact_core_smiles"))
        record["variable_from_key"] = attachment_neutral_structure(record["variable_from"])
        record["variable_to_key"] = attachment_neutral_structure(record["variable_to"])
        record["variable_from_ordered_key"] = record["variable_from"]
        record["variable_to_ordered_key"] = record["variable_to"]
        record["exact_core_key"] = attachment_neutral_structure(record["exact_core_smiles"])
        cut_count = int(record.get("cut_count") or max(1, record["variable_from"].count("[*:")))
        fixed_key = (
            record["variable_from"],
            record["variable_to"],
            str(record.get("compound_id_from", "")),
            str(record.get("compound_id_to", "")),
        )
        reverse_key = (
            record["variable_to"],
            record["variable_from"],
            str(record.get("compound_id_to", "")),
            str(record.get("compound_id_from", "")),
        )
        if reverse_key < fixed_key:
            record = _swap_record(record)
        topology = attachment_topology(record["exact_core_smiles"])
        family_variables = sorted([record["variable_from"], record["variable_to"]])
        record["pair_id"] = stable_id(
            f"PAIR{cut_count}C",
            sorted([str(record["compound_id_from"]), str(record["compound_id_to"])]),
        )
        # A compound pair can have both 1-cut and 2-cut representations.  Keep
        # the cut-scoped pair_id for the separated stores, and a cut-neutral
        # identity for detecting redundant 2-cut representations.
        record["compound_pair_id"] = stable_id(
            "CPAIR",
            sorted([str(record["compound_id_from"]), str(record["compound_id_to"])]),
        )
        record["transformation_family_id"] = stable_id(
            f"TF{cut_count}C", cut_count, topology, family_variables
        )
        record["transformation_id"] = stable_id(
            f"TR{cut_count}C",
            cut_count,
            topology,
            record["variable_from"],
            record["variable_to"],
        )
        record["transform_id"] = record["transformation_id"]
        record["transform_smirks"] = f"{record['variable_from']}>>{record['variable_to']}"
        core_prefix = "CORE1C" if cut_count == 1 else "ANCHOR2C"
        record["core_id"] = stable_id(core_prefix, cut_count, topology, record["exact_core_smiles"])
        record["pair_transformation_id"] = stable_id(
            "PTR", record["pair_id"], record["transformation_id"], record["core_id"]
        )
        record["attachment_topology"] = topology
        record["attachment_topology_unlabeled"] = attachment_topology_unlabeled(
            record["exact_core_smiles"]
        )
        delta = pd.to_numeric(pd.Series([record.get("endpoint_delta")]), errors="coerce").iloc[0]
        record["endpoint_delta"] = float(delta) if pd.notna(delta) else math.nan
        effect = (
            float(delta) * (1.0 if higher_is_better else -1.0)
            if pd.notna(delta) else math.nan
        )
        # Signed effect in the fixed structural direction after applying the
        # Run's Higher/Lower-is-favorable contract.  A positive value means
        # the canonical From -> To transformation improved the Endpoint.
        record["normalized_signed_delta"] = effect
        record["fixed_direction_effect"] = effect
        # Compatibility alias for legacy read-only consumers.  The canonical
        # contract is fixed_direction_effect; this value is never reoriented
        # per Target inside the database.
        record["favorable_delta"] = effect
        if not math.isfinite(effect):
            status = "missing"
        elif abs(effect) < neutral_tolerance:
            status = "neutral"
        elif effect > 0:
            status = "supports_fixed_direction"
        else:
            status = "opposes_fixed_direction"
        record["effect_status"] = status
        record["neutral_tolerance"] = float(neutral_tolerance)
        record["cut_count"] = cut_count
        record["environment_signature_radius_1"] = environment_signature(record["exact_core_smiles"], 1)
        record["environment_signature_radius_2"] = environment_signature(record["exact_core_smiles"], 2)
        records.append(record)

    frame = pd.DataFrame(records)
    frame["variable_heavy_atoms_max"] = [
        max(heavy_atom_count(left), heavy_atom_count(right))
        for left, right in zip(frame["variable_from"], frame["variable_to"])
    ]
    # A 2-cut view is redundant only when the same compound pair has a 1-cut
    # description whose changed fragment is no larger.  Merely having any
    # 1-cut representation is insufficient: a large one-sided replacement can
    # obscure the smaller linker/ring change that 2-cut is intended to expose.
    one_cut_variable_size = (
        frame.loc[frame["cut_count"].eq(1)]
        .groupby("compound_pair_id")["variable_heavy_atoms_max"]
        .min()
        .to_dict()
    )
    quality_classes: list[str] = []
    quality_reasons: list[str] = []
    mapping_statuses: list[str] = []
    for record in frame.to_dict(orient="records"):
        if int(record["cut_count"]) == 1:
            quality_classes.append("not_applicable")
            quality_reasons.append("")
            mapping_statuses.append("unique")
            continue
        constant = Chem.MolFromSmiles(str(record.get("exact_core_smiles", "")))
        variable = Chem.MolFromSmiles(str(record.get("variable_from", "")))
        components = Chem.GetMolFrags(constant, asMols=True) if constant is not None else ()
        component_heavies = [
            sum(atom.GetAtomicNum() > 1 for atom in component.GetAtoms())
            for component in components
        ]
        dummy_count = (
            sum(atom.GetAtomicNum() == 0 for atom in constant.GetAtoms())
            if constant is not None else 0
        )
        variable_dummy_count = (
            sum(atom.GetAtomicNum() == 0 for atom in variable.GetAtoms())
            if variable is not None else 0
        )
        reasons: list[str] = []
        if constant is None or variable is None:
            reasons.append("unparseable_fragment")
        if len(components) != 2:
            reasons.append("constant_component_count")
        if dummy_count != 2 or variable_dummy_count != 2:
            reasons.append("attachment_count")
        one_cut_size = one_cut_variable_size.get(str(record["compound_pair_id"]))
        if one_cut_size is not None and int(one_cut_size) <= int(record["variable_heavy_atoms_max"]):
            reasons.append("reducible_to_1cut")
        if constant is not None and any(
            sum(atom.GetAtomicNum() > 1 for atom in component.GetAtoms())
            < int(thresholds["min_anchor_heavy_atoms"])
            for component in components
        ):
            reasons.append("anchor_below_minimum_heavy_atoms")
        if variable is not None and heavy_atom_count(record.get("variable_from")) < 1:
            reasons.append("variable_below_safety_floor")
        if not _reconstructs_compound(
            record.get("exact_core_smiles"), record.get("variable_from"),
            record.get("smiles_from"),
        ) or not _reconstructs_compound(
            record.get("exact_core_smiles"), record.get("variable_to"),
            record.get("smiles_to"),
        ):
            reasons.append("reconstruction_failed")
        # mmpdb records ordered attachment labels. Duplicate labels indicate an
        # unusable mapping; symmetric labels are retained as equivalent.
        labels = []
        if constant is not None:
            labels = [
                atom.GetAtomMapNum() or atom.GetIsotope()
                for atom in constant.GetAtoms() if atom.GetAtomicNum() == 0
            ]
        mapping_status = "unique" if len(set(labels)) == len(labels) else "symmetry_equivalent"
        mapping_statuses.append(mapping_status)
        if reasons:
            quality_classes.append("2C-X")
            quality_reasons.append("|".join(sorted(set(reasons))))
            continue
        min_anchor = min(component_heavies) if component_heavies else 0
        retained = min(
            float(record.get("core_fraction_from") or 0),
            float(record.get("core_fraction_to") or 0),
        )
        variable_heavies = int(record["variable_heavy_atoms_max"])
        total_from = max(1, heavy_atom_count(record.get("smiles_from")))
        total_to = max(1, heavy_atom_count(record.get("smiles_to")))
        variable_fraction = max(variable_heavies / total_from, variable_heavies / total_to)
        standard_failures: list[str] = []
        if retained < float(thresholds["min_combined_retained_fraction"]):
            standard_failures.append("low_retained_fraction")
        if variable_heavies > int(thresholds["max_variable_heavy_atoms"]):
            standard_failures.append("large_variable")
        if variable_fraction > float(thresholds["max_variable_fraction"]):
            standard_failures.append("large_variable_fraction")
        quality_classes.append("2C-B" if standard_failures else "2C-A")
        quality_reasons.append("|".join(standard_failures))
    frame["two_cut_quality_class"] = quality_classes
    frame["two_cut_quality_reasons"] = quality_reasons
    frame["mapping_status"] = mapping_statuses
    return frame.sort_values(
        ["cut_count", "pair_id", "core_id", "transformation_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def read_fragmentations(fragment_db: Path) -> pd.DataFrame:
    query = """
    SELECT r.title AS compound_id, r.input_smiles, r.normalized_smiles,
           f.num_cuts AS cut_count, f.enumeration_label,
           f.variable_num_heavies, f.variable_symmetry_class,
           f.variable_smiles, f.attachment_order,
           f.constant_num_heavies, f.constant_symmetry_class,
           f.constant_smiles
      FROM fragmentation f
      JOIN record r ON r.id = f.record_id
     WHERE f.num_cuts IN (1, 2)
     ORDER BY r.title, f.num_cuts, f.id
    """
    with closing(sqlite3.connect(fragment_db)) as connection:
        frame = pd.read_sql_query(query, connection)
    if frame.empty:
        return frame
    frame["variable_smiles_raw"] = frame["variable_smiles"].astype(str)
    frame["constant_smiles_raw"] = frame["constant_smiles"].astype(str)
    frame["variable_smiles"] = frame["variable_smiles"].map(canonical_structure)
    frame["constant_smiles"] = frame["constant_smiles"].map(canonical_structure)
    frame["variable_structure_key"] = frame["variable_smiles"].map(attachment_neutral_structure)
    frame["constant_structure_key"] = frame["constant_smiles"].map(attachment_neutral_structure)
    ordered = frame.apply(
        lambda row: ordered_fragmentation_structures(
            row["variable_smiles_raw"], row["constant_smiles_raw"], row["attachment_order"]
        ),
        axis=1,
    )
    frame["variable_ordered_smiles"] = [value[0] for value in ordered]
    frame["constant_ordered_smiles"] = [value[1] for value in ordered]
    frame["variable_ordered_key"] = frame["variable_ordered_smiles"].map(canonical_structure)
    frame["constant_ordered_key"] = frame["constant_ordered_smiles"].map(canonical_structure)
    frame["attachment_topology"] = frame["constant_smiles"].map(attachment_topology)
    frame["attachment_topology_unlabeled"] = frame["constant_smiles"].map(
        attachment_topology_unlabeled
    )
    frame["environment_signature_radius_1"] = frame["constant_smiles"].map(
        lambda value: environment_signature(value, 1)
    )
    frame["environment_signature_radius_2"] = frame["constant_smiles"].map(
        lambda value: environment_signature(value, 2)
    )
    frame["fragmentation_id"] = frame.apply(
        lambda row: stable_id(
            f"FRAG{int(row.cut_count)}C",
            str(row.compound_id), int(row.cut_count), str(row.variable_smiles),
            str(row.constant_smiles), str(row.attachment_order),
        ),
        axis=1,
    )
    return frame.drop_duplicates("fragmentation_id").reset_index(drop=True)


def structure_signature(
    compounds: pd.DataFrame,
    *,
    cut_smarts: str,
    num_cuts: int,
    parameters: dict[str, Any],
) -> str:
    rows = sorted(
        (str(row.compound_id), canonical_structure(row.smiles))
        for row in compounds.itertuples(index=False)
    )
    payload = {
        "calculation_version": CALCULATION_VERSION,
        "model_revision": MODEL_REVISION,
        "engine": ENGINE_VERSION,
        "compounds": rows,
        "cut_smarts": cut_smarts,
        "num_cuts": int(num_cuts),
        "structural_parameters": parameters,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def effect_signature(
    compounds: pd.DataFrame,
    *,
    endpoint_column: str,
    higher_is_better: bool,
    neutral_tolerance: float,
) -> str:
    rows = []
    for row in compounds.itertuples(index=False):
        value = getattr(row, "endpoint", math.nan)
        rows.append((str(row.compound_id), None if pd.isna(value) else float(value)))
    payload = {
        "calculation_version": CALCULATION_VERSION,
        "endpoint_column": endpoint_column,
        "higher_is_better": bool(higher_is_better),
        "neutral_tolerance": float(neutral_tolerance),
        "values": sorted(rows),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return value


def write_canonical_database(
    path: Path,
    *,
    details: pd.DataFrame,
    fragmentations: pd.DataFrame,
    compounds: pd.DataFrame,
    contexts: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Write, audit, and atomically publish an immutable canonical database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(temporary)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
        metadata_rows = [
            (key, json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True))
            for key, value in {**metadata, "build_complete": True}.items()
        ]
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata_rows)

        compound_table = compounds.copy()
        keep = [column for column in [
            "compound_id", "smiles", "endpoint", "valid_smiles", "heavy_atoms",
            "endpoint_available", "exclusion_reason",
        ] if column in compound_table.columns]
        compound_table = compound_table[keep].drop_duplicates("compound_id")
        compound_table.to_sql("compounds", connection, index=False)
        fragmentations.to_sql("fragmentations", connection, index=False)

        family_columns = [
            "transformation_family_id", "cut_count", "attachment_topology",
            "attachment_topology_unlabeled",
        ]
        families = details[family_columns].drop_duplicates("transformation_family_id")
        families.to_sql("transformation_families", connection, index=False)
        transformation_columns = [
            "transformation_id", "transformation_family_id", "cut_count",
            "variable_from", "variable_to", "variable_from_key", "variable_to_key",
            "variable_from_ordered_key", "variable_to_ordered_key", "transform_smirks",
            "attachment_topology", "attachment_topology_unlabeled",
        ]
        details[transformation_columns].drop_duplicates("transformation_id").to_sql(
            "transformations", connection, index=False
        )
        core_columns = [
            "core_id", "cut_count", "exact_core_smiles", "exact_core_key",
            "attachment_topology", "attachment_topology_unlabeled",
            "core_heavy_atoms", "core_molecular_weight",
        ]
        cores = details[core_columns].drop_duplicates("core_id")
        cores.loc[cores["cut_count"].eq(1)].to_sql("exact_cores", connection, index=False)
        cores.loc[cores["cut_count"].eq(2)].to_sql("retained_anchors", connection, index=False)

        pair_columns = [
            "pair_id", "compound_pair_id", "cut_count", "compound_id_from", "compound_id_to", "smiles_from", "smiles_to",
            "endpoint_from", "endpoint_to", "normalized_signed_delta", "effect_status",
        ]
        details[pair_columns].drop_duplicates("pair_id").to_sql("pairs", connection, index=False)
        details.to_sql("pair_transformations", connection, index=False)
        contexts.to_sql("environments", connection, index=False)
        details.loc[details["cut_count"].eq(2), [
            "pair_transformation_id", "pair_id", "transformation_id", "core_id", "two_cut_quality_class",
            "two_cut_quality_reasons", "mapping_status",
        ]].drop_duplicates().to_sql("two_cut_quality", connection, index=False)
        exclusions = details.loc[
            details.get("two_cut_quality_class", pd.Series(index=details.index)).eq("2C-X"),
            ["pair_id", "transformation_id", "two_cut_quality_reasons"],
        ].copy()
        exclusions.to_sql("exclusion_reasons", connection, index=False)
        connection.execute(
            "CREATE VIEW pair_transformations_1cut AS SELECT * FROM pair_transformations WHERE cut_count=1"
        )
        connection.execute(
            "CREATE VIEW pair_transformations_2cut AS SELECT * FROM pair_transformations WHERE cut_count=2"
        )
        for table, column in (
            ("compounds", "compound_id"),
            ("fragmentations", "compound_id"),
            ("pairs", "pair_id"),
            ("pair_transformations", "pair_transformation_id"),
            ("pair_transformations", "transformation_family_id"),
            ("pair_transformations", "core_id"),
            ("environments", "mmp_id"),
        ):
            connection.execute(f"CREATE INDEX idx_{table}_{column} ON {table}({column})")
        connection.execute("ANALYZE")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Canonical MMP database integrity check failed: {integrity}")
        connection.commit()
    temporary.replace(path)
    return {
        "database_path": str(path),
        "database_bytes": path.stat().st_size,
        "table_rows": {
            "compounds": int(compounds["compound_id"].nunique()),
            "fragmentations": int(len(fragmentations)),
            "pair_transformations": int(len(details)),
            "pair_transformations_1cut": int(details["cut_count"].eq(1).sum()),
            "pair_transformations_2cut": int(details["cut_count"].eq(2).sum()),
        },
    }


def load_canonical_database(
    path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        metadata = {
            key: json.loads(value) for key, value in connection.execute(
                "SELECT key, value_json FROM metadata"
            )
        }
        if metadata.get("schema_version") != SCHEMA_VERSION or not metadata.get("build_complete"):
            raise ValueError("Not a completed CONDUCTOR 0.1.11 canonical MMP database")
        details = pd.read_sql_query("SELECT * FROM pair_transformations", connection)
        fragmentations = pd.read_sql_query("SELECT * FROM fragmentations", connection)
        contexts = pd.read_sql_query("SELECT * FROM environments", connection)
    return details, fragmentations, contexts, metadata


def maximum_disjoint_pair_count(pairs: Iterable[tuple[str, str]]) -> int:
    """Return the exact maximum number of compound-disjoint observations."""
    graph = nx.Graph()
    graph.add_edges_from(
        sorted({tuple(sorted((str(left), str(right)))) for left, right in pairs if str(left) != str(right)})
    )
    return len(nx.algorithms.matching.max_weight_matching(graph, maxcardinality=True))


def core_similarity_mapping(
    left: str,
    right: str,
    *,
    minimum_tanimoto: float = 0.0,
    left_fingerprint: Any = None,
    right_fingerprint: Any = None,
) -> dict[str, Any]:
    """Attachment-aware prefilter and MCS mapping diagnostics."""
    left_original = Chem.MolFromSmiles(left)
    right_original = Chem.MolFromSmiles(right)
    if left_original is None or right_original is None:
        return {"core_tanimoto": 0.0, "mcs_coverage": 0.0, "mapping_status": "failed"}
    if attachment_topology_unlabeled(left) != attachment_topology_unlabeled(right):
        return {"core_tanimoto": 0.0, "mcs_coverage": 0.0, "mapping_status": "failed"}
    left_mol, right_mol = Chem.Mol(left_original), Chem.Mol(right_original)
    for molecule in (left_mol, right_mol):
        for atom in molecule.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(0)
                atom.SetIsotope(0)
    left_fp = (
        left_fingerprint
        if left_fingerprint is not None
        else _CORE_FP_GENERATOR.GetFingerprint(left_mol)
    )
    right_fp = (
        right_fingerprint
        if right_fingerprint is not None
        else _CORE_FP_GENERATOR.GetFingerprint(right_mol)
    )
    similarity = float(DataStructs.TanimotoSimilarity(left_fp, right_fp))
    if similarity < minimum_tanimoto:
        return {
            "core_tanimoto": similarity,
            "mcs_coverage": 0.0,
            "mapping_status": "prefilter_rejected",
        }
    # Most related MMP cores differ by a peripheral extension.  An exact
    # attachment-preserving substructure mapping is much faster and more
    # deterministic than invoking FMCS for those common cases.
    for query_mol, target_mol in ((left_mol, right_mol), (right_mol, left_mol)):
        matches = target_mol.GetSubstructMatches(query_mol, uniquify=True, maxMatches=64)
        if not matches:
            continue
        query_dummies = [
            atom.GetIdx() for atom in query_mol.GetAtoms() if atom.GetAtomicNum() == 0
        ]
        attachment_preserving = [
            match for match in matches
            if all(target_mol.GetAtomWithIdx(match[index]).GetAtomicNum() == 0 for index in query_dummies)
        ]
        if not attachment_preserving:
            continue
        coverage = min(
            heavy_atom_count(attachment_neutral_structure(left))
            / max(1, heavy_atom_count(attachment_neutral_structure(right))),
            heavy_atom_count(attachment_neutral_structure(right))
            / max(1, heavy_atom_count(attachment_neutral_structure(left))),
        )
        if len(attachment_preserving) == 1:
            return {
                "core_tanimoto": similarity,
                "mcs_coverage": float(coverage),
                "mapping_status": "unique",
                "mcs_smarts": Chem.MolToSmarts(query_mol),
                "mapping_method": "attachment_substructure",
            }
    result = rdFMCS.FindMCS(
        [left_mol, right_mol], timeout=3, ringMatchesRingOnly=True,
        completeRingsOnly=True, atomCompare=rdFMCS.AtomCompare.CompareElements,
        bondCompare=rdFMCS.BondCompare.CompareOrder,
    )
    if result.canceled or not result.smartsString:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    query = Chem.MolFromSmarts(result.smartsString)
    if query is None:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    query_dummy_count = sum(atom.GetAtomicNum() == 0 for atom in query.GetAtoms())
    expected_dummies = sum(atom.GetAtomicNum() == 0 for atom in left_mol.GetAtoms())
    if query_dummy_count < expected_dummies:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    mcs_heavies = sum(atom.GetAtomicNum() > 1 for atom in query.GetAtoms())
    coverage = min(
        mcs_heavies / max(1, heavy_atom_count(left)),
        mcs_heavies / max(1, heavy_atom_count(right)),
    )
    left_matches = left_mol.GetSubstructMatches(query, uniquify=True, maxMatches=64)
    right_matches = right_mol.GetSubstructMatches(query, uniquify=True, maxMatches=64)
    query_dummies = [atom.GetIdx() for atom in query.GetAtoms() if atom.GetAtomicNum() == 0]
    mappings: set[tuple[tuple[int, int], ...]] = set()
    for left_match in left_matches:
        for right_match in right_matches:
            mapping: list[tuple[int, int]] = []
            valid = True
            for query_index in query_dummies:
                left_index, right_index = left_match[query_index], right_match[query_index]
                if (
                    left_mol.GetAtomWithIdx(left_index).GetAtomicNum() != 0
                    or right_mol.GetAtomWithIdx(right_index).GetAtomicNum() != 0
                ):
                    valid = False
                    break
                mapping.append((left_index, right_index))
            if valid:
                mappings.add(tuple(sorted(mapping)))
    if len(mappings) == 1:
        status = "unique"
    elif mappings:
        # Multiple mappings are acceptable only when every attachment is
        # locally indistinguishable on both structures.  Otherwise a target
        # site cannot be assigned reliably and the evidence stays ambiguous.
        def site_signatures(molecule: Chem.Mol) -> set[tuple[Any, ...]]:
            output: set[tuple[Any, ...]] = set()
            for dummy in molecule.GetAtoms():
                if dummy.GetAtomicNum() != 0 or not dummy.GetNeighbors():
                    continue
                neighbor = dummy.GetNeighbors()[0]
                output.add((
                    neighbor.GetAtomicNum(), neighbor.GetFormalCharge(),
                    neighbor.GetIsAromatic(), neighbor.IsInRing(),
                    str(molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx()).GetBondType()),
                ))
            return output
        symmetric = len(site_signatures(left_mol)) == 1 and len(site_signatures(right_mol)) == 1
        status = "symmetry_equivalent" if symmetric else "ambiguous"
    elif left_matches and right_matches:
        status = "ambiguous"
    else:
        status = "ambiguous"
    return {
        "core_tanimoto": similarity,
        "mcs_coverage": float(coverage),
        "mapping_status": status,
        "mcs_smarts": result.smartsString,
    }
