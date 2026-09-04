from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import shutil
import sys
from pathlib import Path
from string import Template
from typing import Any

import pandas as pd

from batch_skill_common import (
    analysis_units,
    dataset as request_dataset,
    finish as finish_request,
    frame_html,
    html_page,
    image_uri,
    parse_request,
)

from mmp_engine import (
    build_native_database,
    extract_pairs,
    load_input,
    sha256_file,
    summary_tables,
    utc_now,
    write_stable_database,
)
from mmp_outputs import (
    load_database,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))

MMP_REPORT_COLUMNS = {
    "overview": [
        "analysis_unit_id", "target_compound_id", "target_endpoint",
        "mmp_pair_count", "effect_summary", "underexplored",
    ],
    "basic": [
        "mmp_id", "target_compound_id", "target_endpoint",
        "neighbor_compound_id", "neighbor_endpoint", "favorable_delta_report",
    ],
    "detail": [
        "mmp_id", "exact_core_smiles", "variable_neighbor", "variable_target",
    ],
}

MMP_REPORT_LABELS = {
    "analysis_unit_id": "Analysis unit",
    "target_compound_id": "Target compound ID",
    "target_endpoint": "Target Endpoint",
    "neighbor_compound_id": "Neighbor compound ID",
    "neighbor_endpoint": "Neighbor Endpoint",
    "favorable_delta_report": "Favorable Δ (Neighbor → Target)",
    "mmp_pair_count": "MMP count",
    "effect_summary": "Observed effect",
    "underexplored": "Underexplored",
    "mmp_id": "MMP ID",
    "exact_core_smiles": "Core SMILES",
    "variable_neighbor": "Before fragment (Neighbor)",
    "variable_target": "After fragment (Target)",
}

MMP_REPORT_TITLES = {
    "overview": "Target別MMP概要Table",
    "basic": "MMP基本情報Table",
    "detail": "MMP変換詳細Table",
}

MMP_REPORT_COLUMN_HELP = {
    "analysis_unit_id": "Targetを選抜したSeriesまたはfallback Cluster ID。",
    "target_compound_id": "定型解析ではanalysis unit内Endpoint上位1化合物。",
    "target_endpoint": "Target化合物のEndpoint値。",
    "neighbor_compound_id": "Targetとmatched molecular pairを形成する化合物ID。",
    "neighbor_endpoint": "Neighbor化合物のEndpoint値。",
    "favorable_delta_report": "NeighborからTargetへの変換に伴う方向正規化済みEndpoint差。正値ほどFavorable。",
    "mmp_pair_count": "Targetに接続するMMP件数。",
    "effect_summary": "観測された変換効果の要約。",
    "underexplored": "MMPが少なく追加調査余地があることを示す補助flag。",
    "mmp_id": "MMP Database内の一意ID。",
    "exact_core_smiles": "Attachment pointを保持した共通Core。",
    "variable_neighbor": "Neighbor側の置換前fragment。",
    "variable_target": "Target側の置換後fragment。",
}


def render_mmp_template(name: str, values: dict[str, Any]) -> str:
    path = SKILL_DIR / "templates" / name
    if not path.is_file():
        raise FileNotFoundError(f"MMP report template is missing: {path}")
    return Template(path.read_text(encoding="utf-8")).substitute(
        {key: str(value) for key, value in values.items()}
    )


def display_value(value: Any) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != 0 and abs(value) < .001:
            return f"{value:.3e}"
        return f"{value:.4g}"
    return str(value)


def compact_mmp_table(
    frame: pd.DataFrame, table_kind: str, limit: int = 100,
) -> str:
    columns = [
        column for column in MMP_REPORT_COLUMNS[table_kind]
        if column in frame.columns
    ]
    if not columns:
        return frame_html(pd.DataFrame(), limit)
    view = frame.loc[:, columns].copy()
    for column in view.columns:
        view[column] = view[column].map(display_value)
    view = view.rename(columns=MMP_REPORT_LABELS)
    table = frame_html(view, limit)
    help_items = "".join(
        f"<dt>{html.escape(MMP_REPORT_LABELS.get(column, column))}</dt>"
        f"<dd>{html.escape(MMP_REPORT_COLUMN_HELP.get(column, '補助出力列。'))}</dd>"
        for column in columns
    )
    return (
        "<details class='report-table'><summary>"
        f"{html.escape(MMP_REPORT_TITLES[table_kind])}を表示"
        f"（{min(len(view), limit)}件）</summary>{table}"
        "<details class='column-help'><summary>列の説明</summary>"
        f"<dl>{help_items}</dl></details></details>"
    )


def mmp_metric_grid(items: list[tuple[str, Any]]) -> str:
    cards = "".join(
        f"<div class='metric'><span class='muted'>{html.escape(label)}</span>"
        f"<b>{html.escape(display_value(value))}</b></div>"
        for label, value in items
    )
    return f"<div class='metric-grid'>{cards}</div>"


def mmp_metric_stack(items: list[tuple[str, Any]]) -> str:
    cards = "".join(
        f"<div class='metric'><span class='muted'>{html.escape(label)}</span>"
        f"<b>{html.escape(display_value(value))}</b></div>"
        for label, value in items
    )
    return f"<div class='metric-stack'>{cards}</div>"


def select_type_i_targets(
    data: pd.DataFrame, compound_id: str, endpoint: str,
    higher_is_better: bool, units: dict[str, set[str]],
) -> list[dict[str, str]]:
    """Select exactly one top compound for each Series/fallback Cluster."""
    ranked = data.dropna(subset=[endpoint]).sort_values(
        [endpoint, compound_id],
        ascending=[not higher_is_better, True],
        kind="mergesort",
    )
    target_rows: list[dict[str, str]] = []
    for unit_id in sorted(units):
        if unit_id == "GLOBAL":
            continue
        members = units[unit_id]
        candidates = ranked.loc[
            ranked[compound_id].isin(members), compound_id
        ].head(1)
        for value in candidates:
            target_rows.append({
                "analysis_unit_id": unit_id,
                "target_compound_id": str(value),
                "target_rank": "1",
            })
    return target_rows


def depiction_molecule(value: Any) -> Any:
    """Parse either a SMILES-like or SMARTS-like value for report drawing."""
    from rdkit import Chem

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return None
    return Chem.MolFromSmiles(text) or Chem.MolFromSmarts(text)


def comparison_core(value: Any) -> Any:
    """Return a core molecule with attachment labels neutralized."""
    from rdkit import Chem

    molecule = depiction_molecule(value)
    if molecule is None:
        return None
    molecule = Chem.Mol(molecule)
    for atom in molecule.GetAtoms():
        atom.SetAtomMapNum(0)
        if atom.GetAtomicNum() == 0:
            atom.SetIsotope(0)
    return molecule


def core_rank(row: pd.Series) -> tuple[int, int, int, str]:
    molecule = comparison_core(row.get("exact_core_smiles"))
    if molecule is None:
        return (-1, -1, -1, str(row.get("exact_core_smiles", "")))
    heavy = sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())
    return (
        heavy, molecule.GetNumAtoms(), molecule.GetNumBonds(),
        str(row.get("exact_core_smiles", "")),
    )


def select_minimal_transform_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep one smallest-change representation per Target–Neighbor pair.

    A row is dominated when its exact core is a proper substructure of another
    row's core for the same compound pair.  The larger core represents the
    smaller variable transformation.  Incomparable maxima are resolved by
    core size and then stable identifiers.  Incomparable maximal cores are all
    retained because they express distinct attachment-aware transformations.
    The canonical CSV/database is intentionally left untouched.
    """
    if frame.empty:
        return frame.copy()
    required = {"target_compound_id", "neighbor_compound_id"}
    if not required.issubset(frame.columns):
        raise ValueError(
            "MMP report rows require target_compound_id and "
            "neighbor_compound_id"
        )
    chosen_indices: list[Any] = []
    for _, group in frame.groupby(
        ["target_compound_id", "neighbor_compound_id"],
        sort=True, dropna=False,
    ):
        group = group.drop_duplicates("mmp_id") if "mmp_id" in group else group
        records = [
            (index, comparison_core(row.get("exact_core_smiles")), core_rank(row))
            for index, row in group.iterrows()
        ]
        maximal: list[tuple[Any, Any, tuple[int, int, int, str]]] = []
        for candidate in records:
            _, smaller, smaller_rank = candidate
            dominated = False
            if smaller is not None:
                for other in records:
                    if other[0] == candidate[0] or other[1] is None:
                        continue
                    larger = other[1]
                    if (
                        other[2][:3] > smaller_rank[:3]
                        and larger.HasSubstructMatch(smaller)
                    ):
                        dominated = True
                        break
            if not dominated:
                maximal.append(candidate)
        pool = sorted(
            maximal or records,
            key=lambda item: (
                -item[2][0], -item[2][1], -item[2][2], item[2][3],
                str(frame.at[item[0], "mmp_id"])
                if "mmp_id" in frame else str(item[0]),
            ),
        )
        chosen_indices.extend(item[0] for item in pool)
    return frame.loc[chosen_indices].sort_values(
        ["neighbor_compound_id", "mmp_id"]
        if "mmp_id" in frame else ["neighbor_compound_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def orient_report_rows_target_to(frame: pd.DataFrame) -> pd.DataFrame:
    """Orient report-only columns as Neighbor (From) → Target (To)."""
    oriented = frame.copy()
    if oriented.empty:
        return oriented
    oriented["compound_id_from"] = oriented["neighbor_compound_id"]
    oriented["compound_id_to"] = oriented["target_compound_id"]
    oriented["smiles_from"] = oriented["neighbor_smiles"]
    oriented["smiles_to"] = oriented["target_smiles"]
    oriented["endpoint_from"] = oriented["neighbor_endpoint"]
    oriented["endpoint_to"] = oriented["target_endpoint"]
    oriented["variable_from"] = oriented["variable_neighbor"]
    oriented["variable_to"] = oriented["variable_target"]
    oriented["favorable_delta"] = pd.to_numeric(
        oriented["favorable_delta_toward_target"], errors="coerce"
    )
    oriented["favorable_delta_report"] = oriented["favorable_delta"]
    oriented["transform_smirks"] = (
        oriented["variable_from"].astype(str)
        + ">>" + oriented["variable_to"].astype(str)
    )
    oriented["effect_direction"] = "neighbor_to_target"
    return oriented


def canonical_core_key(value: Any) -> str:
    """Canonicalize a core while retaining dummy atoms and attachment labels."""
    from rdkit import Chem

    molecule = depiction_molecule(value)
    if molecule is None:
        return str(value or "")
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def align_depiction_to_reference(
    reference: Any, molecule: Any, core_value: Any = None,
) -> bool:
    """Align one molecule to an existing reference depiction through a core."""
    from rdkit import Chem
    from rdkit.Chem import rdDepictor, rdFMCS

    if reference is None or molecule is None:
        return False
    try:
        if reference.GetNumConformers() == 0:
            rdDepictor.Compute2DCoords(reference)
        core = depiction_molecule(core_value)
        if (
            core is None
            or not reference.HasSubstructMatch(core)
            or not molecule.HasSubstructMatch(core)
        ):
            match = rdFMCS.FindMCS(
                [reference, molecule], timeout=2,
                ringMatchesRingOnly=True, completeRingsOnly=True,
            )
            core = (
                Chem.MolFromSmarts(match.smartsString)
                if match.numAtoms > 0 else None
            )
        if core is None:
            return False
        parameters = rdDepictor.ConstrainedDepictionParams()
        parameters.acceptFailure = False
        mapping = rdDepictor.GenerateDepictionMatching2DStructure(
            molecule, reference, refPatt=core, params=parameters,
        )
        return bool(mapping)
    except (RuntimeError, ValueError):
        return False


def align_target_depiction_to_neighbor(
    neighbor: Any, target: Any, core_value: Any = None,
) -> bool:
    """Align Target 2D coordinates to Neighbor using their common structure."""
    return align_depiction_to_reference(neighbor, target, core_value)


def align_neighbor_depiction_to_target(
    target: Any, neighbor: Any, core_value: Any = None,
) -> bool:
    """Align a Neighbor depiction to the fixed Target orientation."""
    return align_depiction_to_reference(target, neighbor, core_value)


def mmp_report_scope_note(
    detected_rows: pd.DataFrame, report_rows: pd.DataFrame,
    expanded_per_core: int = 5,
) -> str:
    """Describe exactly how much of the detected MMP result HTML displays."""
    detected_unique = (
        int(detected_rows["mmp_id"].nunique())
        if "mmp_id" in detected_rows else len(detected_rows)
    )
    report_unique = (
        int(report_rows["mmp_id"].nunique())
        if "mmp_id" in report_rows else len(report_rows)
    )
    connection_rows = len(detected_rows)
    folded = 0
    if len(report_rows) and "exact_core_smiles" in report_rows:
        keys = report_rows["exact_core_smiles"].map(canonical_core_key)
        folded = int(sum(
            max(0, int(count) - expanded_per_core)
            for count in keys.value_counts(dropna=False)
        ))

    if detected_unique == 0:
        selection = "このTargetに接続するMMPは検出されませんでした。"
    elif detected_unique == report_unique:
        selection = (
            f"検出した一意MMP {detected_unique}件をすべて本レポートに掲載しています。"
        )
    else:
        selection = (
            f"一意MMPを{detected_unique}件検出し、同一Target–Neighborに複数のCoreがある場合は"
            f"最小変換へ整理した{report_unique}件を本レポートに掲載しています。"
        )
    if connection_rows != detected_unique:
        selection += (
            f" 同じTargetが複数のanalysis unitに属するため、詳細CSVでは"
            f"{connection_rows}接続行として記録されています。"
        )
    if folded:
        selection += (
            f" 各CoreのFavorable Δ上位{expanded_per_core}件を初期表示し、"
            f"残り{folded}件はCore内で折りたたんでいます。"
        )
    elif report_unique:
        selection += " 掲載対象はすべて初期表示しています。"
    if detected_unique:
        selection += " 全列と整理前の全接続行は詳細CSVを参照してください。"
    return selection


def render_target_overview_gallery(
    targets: pd.DataFrame, data: pd.DataFrame, compound_id_column: str,
    smiles_column: str, endpoint_column: str, output: Path,
) -> tuple[str, list[Path]]:
    """Show one Target structure for every analysis unit, four per row."""
    from rdkit import Chem
    from rdkit.Chem import Draw

    if targets.empty:
        return "<p class='muted'>Target構造なし</p>", []
    lookup = data.drop_duplicates(compound_id_column).set_index(
        compound_id_column
    )
    molecules = []
    legends = []
    ordered = targets.sort_values(
        ["analysis_unit_id", "target_compound_id"], kind="mergesort"
    )
    for record in ordered.itertuples():
        target_id = str(getattr(record, "target_compound_id"))
        if target_id not in lookup.index:
            continue
        molecule = Chem.MolFromSmiles(str(lookup.at[target_id, smiles_column]))
        if molecule is None:
            continue
        endpoint_value = lookup.at[target_id, endpoint_column]
        molecules.append(molecule)
        legends.append(
            f"{getattr(record, 'analysis_unit_id')}\n{target_id}\n"
            f"Endpoint={display_value(endpoint_value)}"
        )
    if not molecules:
        return "<p class='muted'>描画可能なTarget構造なし</p>", []
    path = output / "mmp_target_overview.svg"
    path.write_text(str(Draw.MolsToGridImage(
        molecules, molsPerRow=4, subImgSize=(270, 230),
        legends=legends, useSVG=True,
    )), encoding="utf-8")
    return (
        f"<figure><img class='report-figure' src='{image_uri(path)}' "
        "alt='Target structures by analysis unit'><figcaption>"
        "各analysis unitのTargetを4列で表示しています。</figcaption></figure>",
        [path],
    )


def render_target_neighbor_structures(
    target_id: str, target_smiles: str, report_pairs: pd.DataFrame,
    output: Path, filename_prefix: str,
) -> tuple[str, str, list[Path]]:
    """Render Target alone, then an initially collapsed aligned Neighbor grid."""
    from rdkit.Chem import Draw, rdDepictor

    artifacts: list[Path] = []
    target_molecule = depiction_molecule(target_smiles)
    if target_molecule is None:
        target_html = "<p class='muted'>Target構造を描画できませんでした。</p>"
    else:
        rdDepictor.Compute2DCoords(target_molecule)
        target_path = output / f"mmp_target_structure_{filename_prefix}.svg"
        target_path.write_text(str(Draw.MolsToGridImage(
            [target_molecule], molsPerRow=1, subImgSize=(420, 270),
            legends=[f"TARGET {target_id}"], useSVG=True,
        )), encoding="utf-8")
        artifacts.append(target_path)
        target_html = (
            f"<figure class='single-target-structure'><img src='"
            f"{image_uri(target_path)}' alt='Target {html.escape(target_id)}'>"
            "</figure>"
        )

    neighbor_molecules = []
    neighbor_legends = []
    if len(report_pairs):
        neighbors = report_pairs.sort_values(
            ["favorable_delta_report", "neighbor_compound_id", "mmp_id"],
            ascending=[False, True, True], na_position="last", kind="mergesort",
        ).drop_duplicates("neighbor_compound_id")
        for record in neighbors.itertuples():
            neighbor_id = str(getattr(record, "neighbor_compound_id", "—"))
            neighbor = depiction_molecule(getattr(record, "neighbor_smiles", None))
            if neighbor is None:
                continue
            align_neighbor_depiction_to_target(
                target_molecule, neighbor,
                getattr(record, "exact_core_smiles", None),
            )
            delta = display_value(
                getattr(record, "favorable_delta_report", None)
            )
            neighbor_molecules.append(neighbor)
            neighbor_legends.append(
                f"{neighbor_id}\nFavorable Δ={delta}"
            )
    if neighbor_molecules:
        neighbor_path = output / f"mmp_neighbor_structures_{filename_prefix}.svg"
        neighbor_path.write_text(str(Draw.MolsToGridImage(
            neighbor_molecules, molsPerRow=4, subImgSize=(270, 230),
            legends=neighbor_legends, useSVG=True,
        )), encoding="utf-8")
        artifacts.append(neighbor_path)
        neighbor_html = (
            "<details class='neighbor-structure-gallery'><summary>"
            f"Neighbor構造を表示（{len(neighbor_molecules)}件）</summary>"
            f"<figure><img src='{image_uri(neighbor_path)}' "
            "alt='Target-aligned Neighbor structures'><figcaption>"
            "各Neighborは上のTargetと共通する構造を基準に向きを揃えています。"
            "</figcaption></figure></details>"
        )
    else:
        neighbor_html = "<p class='muted'>Neighbor構造なし</p>"
    return target_html, neighbor_html, artifacts


def render_transformation_gallery(
    frame: pd.DataFrame, output: Path, filename_prefix: str,
) -> tuple[str, list[Path]]:
    """Render Neighbor → Target → Before → After for report-visible MMPs."""
    from rdkit import Chem
    from rdkit.Chem import Draw

    if frame.empty:
        return "<p class='muted'>表示対象のMMP変換なし</p>", []
    rows: list[str] = []
    artifacts: list[Path] = []
    placeholder = Chem.MolFromSmiles("*")
    for position, record in enumerate(frame.itertuples(), 1):
        mmp_id = str(getattr(record, "mmp_id", f"MMP-{position}"))
        neighbor_id = str(getattr(record, "neighbor_compound_id", "—"))
        neighbor_molecule = depiction_molecule(
            getattr(record, "neighbor_smiles", None)
        )
        target_molecule = depiction_molecule(
            getattr(record, "target_smiles", None)
        )
        align_target_depiction_to_neighbor(
            neighbor_molecule, target_molecule,
            getattr(record, "exact_core_smiles", None),
        )
        molecules = [
            neighbor_molecule,
            target_molecule,
            depiction_molecule(getattr(record, "variable_neighbor", None)),
            depiction_molecule(getattr(record, "variable_target", None)),
        ]
        molecules = [molecule or placeholder for molecule in molecules]
        suffix = hashlib.sha256(
            f"{mmp_id}\x1f{neighbor_id}".encode("utf-8")
        ).hexdigest()[:10]
        image_path = output / (
            f"mmp_transform_{filename_prefix}_{position:03d}_{suffix}.svg"
        )
        image_path.write_text(
            str(Draw.MolsToGridImage(
                molecules, molsPerRow=4, subImgSize=(270, 220),
                legends=[
                    f"Neighbor {neighbor_id}",
                    f"Target {getattr(record, 'target_compound_id', '—')}",
                    "Before fragment (Neighbor)",
                    "After fragment (Target)",
                ],
                useSVG=True,
            )),
            encoding="utf-8",
        )
        delta = display_value(getattr(record, "favorable_delta_report", None))
        rows.append(
            "<article style='border-top:1px solid #dedbd3;padding-top:14px;"
            "margin-top:14px'>"
            f"<h3>{html.escape(mmp_id)} · Neighbor "
            f"{html.escape(neighbor_id)}</h3>"
            "<p class='muted'>Neighbor → Target / Favorable Δ: "
            f"{html.escape(delta)}</p>"
            f"<img src='{image_uri(image_path)}' "
            "alt='Neighbor, Target, before fragment, and after fragment structures'>"
            "</article>"
        )
        artifacts.append(image_path)
    return "".join(rows), artifacts


def render_core_group_gallery(
    frame: pd.DataFrame, output: Path, filename_prefix: str,
) -> tuple[str, list[Path]]:
    """Group MMP transformations into attachment-aware exact-core cards."""
    from rdkit.Chem import Draw

    if frame.empty:
        return "<p class='muted'>表示対象のMMP変換なし</p>", []
    grouped = frame.copy()
    grouped["_core_group_key"] = grouped["exact_core_smiles"].map(
        canonical_core_key
    )
    grouped["_delta_sort"] = pd.to_numeric(
        grouped.get("favorable_delta_report"), errors="coerce"
    )
    core_order = (
        grouped.groupby("_core_group_key", dropna=False)["_delta_sort"]
        .max().sort_values(ascending=False, na_position="last").index
    )
    cards: list[str] = []
    artifacts: list[Path] = []
    for core_position, core_key in enumerate(core_order, 1):
        part = grouped.loc[grouped["_core_group_key"].eq(core_key)].sort_values(
            ["_delta_sort", "neighbor_compound_id", "mmp_id"],
            ascending=[False, True, True], na_position="last", kind="mergesort",
        )
        core_molecule = depiction_molecule(core_key)
        core_path = output / (
            f"mmp_core_{filename_prefix}_{core_position:03d}.svg"
        )
        core_image = "<p class='muted'>Coreを描画できませんでした。</p>"
        if core_molecule is not None:
            core_path.write_text(
                str(Draw.MolsToGridImage(
                    [core_molecule], molsPerRow=1, subImgSize=(320, 200),
                    legends=[f"Core group {core_position}"], useSVG=True,
                )),
                encoding="utf-8",
            )
            artifacts.append(core_path)
            core_image = (
                f"<img class='core-structure-image' src='{image_uri(core_path)}' "
                f"alt='Common core group {core_position}'>"
            )
        expanded = part.head(5)
        folded = part.iloc[5:]
        expanded_gallery, expanded_artifacts = render_transformation_gallery(
            expanded, output, f"{filename_prefix}_core{core_position:03d}_top"
        )
        artifacts.extend(expanded_artifacts)
        folded_html = ""
        if len(folded):
            folded_gallery, folded_artifacts = render_transformation_gallery(
                folded, output,
                f"{filename_prefix}_core{core_position:03d}_remaining",
            )
            artifacts.extend(folded_artifacts)
            folded_html = (
                f"<details><summary>残り{len(folded)}件を表示</summary>"
                f"{compact_mmp_table(folded, 'basic', len(folded))}"
                f"{folded_gallery}</details>"
            )
        max_delta = part["_delta_sort"].max()
        cards.append(
            "<article class='card' style='margin-top:16px'>"
            f"<h3>Core group {core_position}</h3>"
            f"<p><b>Canonical core:</b> <code style='white-space:normal;"
            f"overflow-wrap:anywhere'>{html.escape(str(core_key))}</code></p>"
            "<div class='core-summary-layout'>"
            f"<div>{core_image}</div>"
            f"{mmp_metric_stack([('MMP rows', len(part)), ('Max Favorable Δ', max_delta)])}"
            "</div>"
            f"<h4>Favorable Δ 上位{len(expanded)}件</h4>"
            f"{compact_mmp_table(expanded, 'basic', 5)}"
            f"{expanded_gallery}{folded_html}</article>"
        )
    return "".join(cards), artifacts


def fragment_job_count(available_cpu_cores: int, requested_jobs: int | None) -> int:
    maximum = min(8, int(available_cpu_cores))
    jobs = int(requested_jobs) if requested_jobs is not None else maximum
    if jobs < 1 or jobs > maximum:
        raise ValueError("--fragment-jobs must be between 1 and min(8, --available-cpu-cores)")
    return jobs


def value_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return clean_json(value.item())
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def attachment_topology_signature(molecule: Any) -> tuple[str, ...]:
    """Return a deterministic signature for every dummy-atom attachment site."""
    signatures: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0:
            continue
        for neighbor in dummy.GetNeighbors():
            bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
            signatures.append(
                ":".join(
                    (
                        str(neighbor.GetAtomicNum()),
                        "aromatic" if neighbor.GetIsAromatic() else "aliphatic",
                        "ring" if neighbor.IsInRing() else "chain",
                        str(bond.GetBondType()) if bond is not None else "UNKNOWN",
                    )
                )
            )
    return tuple(sorted(signatures))


def export_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def global_build(args: argparse.Namespace, outdir: Path, *, persist_database: bool) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    valid, coverage, warnings = load_input(input_path, args.id_column, args.smiles_column, args.endpoint_column, args.max_compounds)
    if not (0 < args.min_core_fraction <= 1):
        raise ValueError("--min-core-fraction must satisfy 0 < value <= 1")
    if args.min_core_heavy_atoms < 1 or args.max_variable_heavy_atoms < 1:
        raise ValueError("Core and variable heavy-atom limits must be positive")
    if not (0 <= args.min_radius <= args.max_radius <= 5):
        raise ValueError("Environment radius must satisfy 0 <= min <= max <= 5")
    if not args.extended_search and (args.num_cuts > 2 or args.max_radius > 2):
        raise ValueError("3 cuts or radius 3-5 require explicit --extended-search")
    jobs = fragment_job_count(args.available_cpu_cores, args.fragment_jobs)
    _, native_work = build_native_database(
        valid, outdir / "_work", jobs=jobs, num_cuts=args.num_cuts,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        extended_core_fraction=args.min_core_fraction,
        min_radius=args.min_radius, max_radius=args.max_radius, cut_smarts=args.cut_smarts,
        max_variable_heavy_atoms=args.max_variable_heavy_atoms,
    )
    endpoint_map = dict(zip(valid["compound_id"], valid["endpoint"]))
    details, contexts, filter_stats = extract_pairs(
        native_work, endpoint_map, higher_is_better=args.higher_is_better,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        min_core_fraction=args.min_core_fraction,
    )
    parameter_record = {
        "num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts,
        "min_core_heavy_atoms": args.min_core_heavy_atoms,
        "min_core_fraction": args.min_core_fraction,
        "max_variable_heavy_atoms": args.max_variable_heavy_atoms,
        "min_radius": args.min_radius, "max_radius": args.max_radius,
        "extended_search": args.extended_search,
    }
    if len(details):
        details["_compound_pair_key"] = details["compound_id_from"].astype(str) + "\x1f" + details["compound_id_to"].astype(str)
        details["transform_pair_support"] = details.groupby("transform_id")["_compound_pair_key"].transform("nunique")
        details["transform_independent_core_support"] = details.groupby("transform_id")["core_id"].transform("nunique")
        details["core_pair_support"] = details.groupby("core_id")["_compound_pair_key"].transform("nunique")
        details["compound_pair_transform_count"] = details.groupby(["compound_id_from", "compound_id_to"])["transform_id"].transform("nunique")
        compound_support = pd.concat([
            details[["compound_id_from", "mmp_id"]].rename(columns={"compound_id_from": "compound_id"}),
            details[["compound_id_to", "mmp_id"]].rename(columns={"compound_id_to": "compound_id"}),
        ]).groupby("compound_id")["mmp_id"].nunique()
        details["compound_from_mmp_support"] = details["compound_id_from"].map(compound_support)
        details["compound_to_mmp_support"] = details["compound_id_to"].map(compound_support)
        low_support = details["transform_pair_support"] < 3
        details.loc[low_support & details["quality_flags"].eq(""), "quality_flags"] = "low_transform_support"
        details.loc[low_support & details["quality_flags"].ne(""), "quality_flags"] += "|low_transform_support"
        details = details.drop(columns=["_compound_pair_key"])
    details["source_node_id"] = args.node_id or ""
    details["input_sha256"] = sha256_file(input_path)
    details["parameter_hash"] = value_hash(parameter_record)
    details["engine_version"] = "mmpdb-3.1.4"
    metadata = {
        "schema_version": "1.0.0", "engine": "mmpdb", "engine_version": "3.1.4",
        "input_path": str(input_path), "input_sha256": sha256_file(input_path),
        "id_column": args.id_column, "smiles_column": args.smiles_column,
        "endpoint_column": args.endpoint_column, "higher_is_better": args.higher_is_better,
        "core_policy": {"min_heavy_atoms": args.min_core_heavy_atoms, "min_fraction_both_compounds": args.min_core_fraction, "max_variable_heavy_atoms": args.max_variable_heavy_atoms},
        "fragment_policy": {"num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts, "salt_remover": "<none>", "smallest_transformation_only": False, "symmetric": False, "extended_search": args.extended_search},
        "parameter_hash": value_hash(parameter_record),
        "environment_radius": [args.min_radius, args.max_radius],
        "input_count": int(len(coverage)), "endpoint_available_count": int(coverage["endpoint_available"].sum()),
        "mmp_count": int(len(details)), "filter_stats": filter_stats,
        "created_at": utc_now(),
    }
    counts = {
        "input compounds": len(coverage), "MMP rows": len(details),
        "transforms": int(details["transform_id"].nunique()) if len(details) else 0,
        "exact cores": int(details["core_id"].nunique()) if len(details) else 0,
    }
    artifacts: list[str] = []
    if persist_database:
        summaries = summary_tables(details, contexts, coverage)
        export_frame(details, outdir / "mmp_pair_detail.csv")
        coverage.to_csv(outdir / "compound_coverage.csv", index=False)
        for name, frame in summaries.items():
            frame.to_csv(outdir / f"{name}.csv", index=False)
        stable_database = outdir / "mmp_database.sqlite"
        write_stable_database(stable_database, details, contexts, coverage, metadata)
        artifacts = [
            "mmp_database.sqlite", "mmp_pair_detail.csv",
            "pair_summary.csv", "transform_summary.csv", "core_summary.csv",
            "transform_core_summary.csv", "context_summary.csv",
            "coverage_summary.csv", "compound_coverage.csv",
        ]
        storage_profile = {
            "schema_version": "1.0.0",
            "database_bytes": stable_database.stat().st_size,
            "detail_csv_bytes": (outdir / "mmp_pair_detail.csv").stat().st_size,
            "native_work_database_bytes": native_work.stat().st_size,
            "native_work_database_retained": False,
            "table_rows": {
                "compounds": int(len(coverage)), "mmp_pairs": int(len(details)),
                "mmp_contexts": int(len(contexts)),
                "transforms": int(details["transform_id"].nunique()) if len(details) else 0,
                "cores": int(details["core_id"].nunique()) if len(details) else 0,
            },
            "filter_stats": filter_stats,
            "created_at": utc_now(),
        }
        write_json(outdir / "mmp_storage_profile.json", storage_profile)
        artifacts.append("mmp_storage_profile.json")
    negative_result = not bool(details["favorable_delta"].notna().any()) if len(details) else True
    return {
        "input": str(input_path), "input_hash": sha256_file(input_path), "endpoint": args.endpoint_column,
        "higher_is_better": args.higher_is_better, "scope": "global", "cluster_id": None,
        "primary": "mmp_pair_detail.csv", "counts": counts, "negative_result": negative_result,
        "warnings": warnings, "artifacts": artifacts, "details": details,
        "core_policy": metadata["core_policy"], "source_nodes": args.source_node_id, "clustering_node_ids": [],
        "sample_count": int(coverage["endpoint_available"].sum()),
    }


def run_execution_request() -> int:
    """Execute the 0.1.10 human-centred MMP contract.

    Type-I and Type-II expose only target-connected one-cut pairs.  They still
    fragment the Run dataset so every observed neighbour can be found, but do
    not persist comprehensive summaries or SQLite.  Type-III is the explicit
    complete database/export mode.
    """
    request, outdir, capability = parse_request()
    parameters = request.get("parameters", {})
    role = str(parameters.get("role", "type-i")).lower()
    if role not in {"type-i", "type-ii", "type-iii"}:
        raise ValueError("MMP parameters.role must be one of: type-i, type-ii, type-iii")
    data, compound_id, smiles, endpoint = request_dataset(request)
    higher_is_better = bool(request.get("endpoint", {}).get("higher_is_better"))
    cuts = int(parameters.get("cuts", 1))
    if cuts != 1:
        raise ValueError("CONDUCTOR 0.1.10 MMP Type-I/II/III require cuts=1 for interpretability")
    radius_min = int(parameters.get("radius_min", 0)); radius_max = int(parameters.get("radius_max", 2))
    if not (0 <= radius_min <= radius_max <= 2):
        raise ValueError("MMP radius must satisfy 0 <= radius_min <= radius_max <= 2")
    identity = request["identity"]
    dataset_input = next((item for item in request.get("inputs", []) if item.get("role") == "dataset"), None)
    if not dataset_input:
        raise ValueError("MMP Execution Request requires one dataset input role")
    args = argparse.Namespace(
        role=role, input=str(Path(dataset_input["path"]).resolve()),
        id_column=compound_id, smiles_column=smiles, endpoint_column=endpoint,
        higher_is_better=higher_is_better, max_compounds=int(parameters.get("max_compounds", 2000)),
        available_cpu_cores=int(request.get("resources", {}).get("node_cpu_cores", 1)),
        fragment_jobs=None, num_cuts=1, extended_search=False, cut_smarts="default",
        min_core_heavy_atoms=int(parameters.get("min_core_heavy_atoms", 8)),
        min_core_fraction=float(parameters.get("min_core_fraction", .5)),
        max_variable_heavy_atoms=int(parameters.get("max_variable_heavy_atoms", 10)),
        min_radius=radius_min, max_radius=radius_max,
        node_id=identity["node_id"], source_node_id=[item.get("source_node_id") for item in request.get("inputs", []) if item.get("source_node_id")],
    )
    database_input = next((item for item in request.get("inputs", []) if item.get("role") == "mmp_database"), None)
    reused_database = False
    build_warnings: list[str] = []
    if database_input is not None:
        if role != "type-ii":
            raise ValueError("An existing Type-III mmp_database input is accepted only for Type-II")
        database_path = Path(str(database_input.get("path", ""))).resolve()
        if not database_path.is_file():
            raise FileNotFoundError(f"Explicit Type-III MMP database does not exist: {database_path}")
        details, database_metadata = load_database(database_path)
        expected_hash = str(database_metadata.get("input_sha256", ""))
        actual_hash = sha256_file(Path(dataset_input["path"]).resolve())
        if expected_hash != actual_hash:
            raise ValueError("Explicit Type-III MMP database was built from a different input CSV")
        if str(database_metadata.get("endpoint_column")) != endpoint or bool(database_metadata.get("higher_is_better")) != higher_is_better:
            raise ValueError("Explicit Type-III MMP database endpoint contract does not match this Run")
        if database_metadata.get("schema_version") != "1.0.0" or int(database_metadata.get("fragment_policy", {}).get("num_cuts", 0)) != 1:
            raise ValueError("Explicit Type-III MMP database is not a CONDUCTOR 0.1.10 one-cut database")
        database_radius = [int(value) for value in database_metadata.get("environment_radius", [])]
        if database_radius != [radius_min, radius_max]:
            raise ValueError(
                f"Explicit Type-III MMP database radius {database_radius} does not match requested radius {[radius_min, radius_max]}"
            )
        reused_database = True
    else:
        build = global_build(args, outdir, persist_database=role == "type-iii")
        details = build["details"]
        build_warnings = list(build.get("warnings", []))
        shutil.rmtree(outdir / "_work", ignore_errors=True)
    details_path = outdir / "mmp_pair_detail.csv"
    top_k = int(parameters.get("top_k", 1))
    if top_k < 1:
        raise ValueError("MMP top_k must be at least 1")
    if role == "type-i" and top_k != 1:
        raise ValueError(
            "Standard MMP Type-I requires top_k=1. Use On-demand Type-II "
            "with explicitly selected top compounds for a larger K."
        )
    target_rows: list[dict[str, str]] = []
    if role == "type-i":
        if not any(
            item.get("role") == "analysis_unit_membership"
            for item in request.get("inputs", [])
        ):
            raise ValueError(
                "Standard MMP Type-I requires analysis_unit_membership"
            )
        units = analysis_units(request, include_global=False)
        target_rows = select_type_i_targets(
            data, compound_id, endpoint, higher_is_better, units
        )
    elif role == "type-ii":
        requested = parameters.get("target_compound_ids") or []
        if isinstance(requested, str): requested = [requested]
        requested = [str(value) for value in requested]
        if len(requested) != len(set(requested)):
            raise ValueError("Type-II target_compound_ids must be unique")
        known = set(data[compound_id])
        missing = [value for value in requested if value not in known]
        if missing: raise ValueError(f"Type-II target compound_id values are not present in this Run: {missing}")
        target_rows = [{"analysis_unit_id": "HIT_TO_LEAD", "target_compound_id": value, "target_rank": str(index + 1)} for index, value in enumerate(requested)]
        if not target_rows: raise ValueError("Type-II requires parameters.target_compound_ids")
    else:
        target_rows = [{"analysis_unit_id": "DATABASE", "target_compound_id": "", "target_rank": ""}]
    targets = pd.DataFrame(
        target_rows,
        columns=["analysis_unit_id", "target_compound_id", "target_rank"],
    )
    if role == "type-iii":
        target_pairs = details.copy(); target_pairs.insert(0, "analysis_unit_id", "DATABASE"); target_pairs.insert(1, "target_compound_id", "")
    else:
        parts = []
        for _, target in targets.iterrows():
            mask = details["compound_id_from"].astype(str).eq(target["target_compound_id"]) | details["compound_id_to"].astype(str).eq(target["target_compound_id"])
            part = details.loc[mask].copy()
            part.insert(0, "analysis_unit_id", target["analysis_unit_id"]); part.insert(1, "target_compound_id", target["target_compound_id"]); part.insert(2, "target_rank", target["target_rank"])
            target_is_to=part["compound_id_to"].astype(str).eq(str(target["target_compound_id"]))
            part["neighbor_compound_id"]=part["compound_id_from"].where(target_is_to,part["compound_id_to"])
            part["target_smiles"]=part["smiles_to"].where(target_is_to,part["smiles_from"])
            part["neighbor_smiles"]=part["smiles_from"].where(target_is_to,part["smiles_to"])
            part["target_endpoint"]=part["endpoint_to"].where(target_is_to,part["endpoint_from"])
            part["neighbor_endpoint"]=part["endpoint_from"].where(target_is_to,part["endpoint_to"])
            raw=pd.to_numeric(part["favorable_delta"],errors="coerce")
            part["favorable_delta_toward_target"]=raw.where(target_is_to,-raw)
            part["favorable_delta_from_target_to_neighbor"]=-part["favorable_delta_toward_target"]
            part["variable_neighbor"]=part["variable_from"].where(target_is_to,part["variable_to"])
            part["variable_target"]=part["variable_to"].where(target_is_to,part["variable_from"])
            parts.append(part)
        if parts:
            target_pairs = pd.concat(parts, ignore_index=True)
        else:
            # Preserve a readable CSV schema even when no analysis unit has an
            # Endpoint-valid target (a legitimate negative result).
            target_pairs = details.head(0).copy()
            target_pairs.insert(0, "analysis_unit_id", pd.Series(dtype=str))
            target_pairs.insert(1, "target_compound_id", pd.Series(dtype=str))
            target_pairs.insert(2, "target_rank", pd.Series(dtype=str))
            for column in (
                "neighbor_compound_id", "target_smiles", "neighbor_smiles",
                "target_endpoint", "neighbor_endpoint",
                "favorable_delta_toward_target",
                "favorable_delta_from_target_to_neighbor",
                "variable_neighbor", "variable_target",
            ):
                target_pairs[column] = pd.Series(dtype=object)
    primary = details_path if role == "type-iii" else outdir / "mmp_target_pairs.csv"
    targets_path = outdir / "mmp_targets.csv"
    if role != "type-iii": targets.to_csv(targets_path, index=False)
    if role != "type-iii" and len(target_pairs):
        effect_column = "favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"
        favorable = pd.to_numeric(target_pairs[effect_column], errors="coerce")
        target_pairs["effect_direction"] = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        target_pairs["effect_class"] = "unfavorable_observed"
        target_pairs.loc[favorable.gt(0), "effect_class"] = "favorable_observed"
        target_pairs.loc[favorable.isna() | favorable.eq(0), "effect_class"] = "neutral_or_missing"
        target_pairs.to_csv(primary, index=False)
    elif role != "type-iii":
        target_pairs.to_csv(primary,index=False)
    if role != "type-iii":
        if len(target_pairs):
            target_counts = target_pairs.groupby(["analysis_unit_id", "target_compound_id"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"),
                favorable_toward_target_fraction=("favorable_delta_toward_target", lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
                favorable_from_target_to_neighbor_fraction=("favorable_delta_from_target_to_neighbor", lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
            ).reset_index()
            target_summary = targets.merge(target_counts, on=["analysis_unit_id", "target_compound_id"], how="left")
        else:
            target_summary = targets.copy(); target_summary["mmp_pair_count"] = 0; target_summary["favorable_toward_target_fraction"] = 0.0; target_summary["favorable_from_target_to_neighbor_fraction"] = 0.0
        target_summary["mmp_pair_count"] = target_summary["mmp_pair_count"].fillna(0).astype(int)
        for column in ("favorable_toward_target_fraction", "favorable_from_target_to_neighbor_fraction"):
            target_summary[column] = target_summary[column].fillna(0.0)
        effect_fraction = target_summary["favorable_toward_target_fraction"] if role == "type-i" else target_summary["favorable_from_target_to_neighbor_fraction"]
        target_summary["effect_direction"] = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        target_summary["effect_summary"] = "mixed"
        target_summary.loc[effect_fraction.ge(.6), "effect_summary"] = "favorable_observed"
        target_summary.loc[effect_fraction.eq(0), "effect_summary"] = "no_favorable_observed"
        target_summary["underexplored"] = target_summary["mmp_pair_count"].lt(3)
        target_summary["target_endpoint"] = target_summary[
            "target_compound_id"
        ].map(dict(zip(data[compound_id].astype(str), data[endpoint])))
    else:
        target_summary = targets
    target_summary_path = outdir / "mmp_target_summary.csv"
    if role != "type-iii": target_summary.to_csv(target_summary_path, index=False)
    extra_artifacts = [targets_path, target_summary_path] if role != "type-iii" else []
    if role != "type-iii":
        summary_effect_column = "favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"
        summary_effect_direction = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        if len(target_pairs):
            transform_summary = target_pairs.groupby(["analysis_unit_id", "target_compound_id", "transform_id", "transform_smirks"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"), median_favorable_delta=(summary_effect_column, "median"),
                favorable_observed_fraction=(summary_effect_column, lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
                exact_core_count=("core_id", "nunique"),
            ).reset_index()
            core_summary = target_pairs.groupby(["analysis_unit_id", "target_compound_id", "core_id", "exact_core_smiles"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"), median_favorable_delta=(summary_effect_column, "median"), transform_count=("transform_id", "nunique"),
            ).reset_index()
        else:
            transform_summary = pd.DataFrame(columns=["analysis_unit_id","target_compound_id","transform_id","transform_smirks","mmp_pair_count","median_favorable_delta","favorable_observed_fraction","exact_core_count"])
            core_summary = pd.DataFrame(columns=["analysis_unit_id","target_compound_id","core_id","exact_core_smiles","mmp_pair_count","median_favorable_delta","transform_count"])
        transform_summary["effect_direction"] = summary_effect_direction
        core_summary["effect_direction"] = summary_effect_direction
        transform_path=outdir/"mmp_target_transform_summary.csv"; core_path=outdir/"mmp_target_core_summary.csv"; transform_summary.to_csv(transform_path,index=False); core_summary.to_csv(core_path,index=False); extra_artifacts.extend([transform_path,core_path])
    if role == "type-ii" and len(target_pairs):
        from rdkit import Chem, DataStructs
        from rdkit.Chem import rdFMCS
        target_cores=sorted(set(target_pairs["exact_core_smiles"].dropna().astype(str))); all_cores=sorted(set(details["exact_core_smiles"].dropna().astype(str)))
        matches=[]
        for target_core in target_cores:
            target_mol=Chem.MolFromSmiles(target_core); target_fp=Chem.RDKFingerprint(target_mol) if target_mol else None
            if target_mol is None: continue
            target_heavy=max(1,sum(atom.GetAtomicNum()>1 for atom in target_mol.GetAtoms())); target_topology=attachment_topology_signature(target_mol)
            for reference_core in all_cores:
                if reference_core==target_core: continue
                reference_mol=Chem.MolFromSmiles(reference_core)
                if reference_mol is None or attachment_topology_signature(reference_mol)!=target_topology: continue
                similarity=float(DataStructs.TanimotoSimilarity(target_fp,Chem.RDKFingerprint(reference_mol)))
                if similarity < float(parameters.get("near_core_tanimoto",.70)): continue
                mcs=rdFMCS.FindMCS([target_mol,reference_mol],timeout=3,ringMatchesRingOnly=True,completeRingsOnly=True)
                if mcs.canceled:
                    continue
                reference_heavy=max(1,sum(atom.GetAtomicNum()>1 for atom in reference_mol.GetAtoms())); mcs_heavy=sum(atom.GetAtomicNum()>1 for atom in Chem.MolFromSmarts(mcs.smartsString).GetAtoms()) if mcs.smartsString else 0
                coverage_target=mcs_heavy/target_heavy; coverage_reference=mcs_heavy/reference_heavy
                if min(coverage_target,coverage_reference) >= float(parameters.get("near_core_mcs_coverage",.60)):
                    matches.append({"target_core":target_core,"exact_core_smiles":reference_core,"attachment_topology":"|".join(target_topology),"core_tanimoto":similarity,"mcs_coverage_target":coverage_target,"mcs_coverage_reference":coverage_reference})
        match_frame=pd.DataFrame(matches)
        if len(match_frame):
            near=details.merge(match_frame,on="exact_core_smiles",how="inner")
            near["absolute_favorable_delta"] = pd.to_numeric(near["favorable_delta"], errors="coerce").abs()
            near=near.sort_values(["core_tanimoto","absolute_favorable_delta"],ascending=[False,False]).head(int(parameters.get("near_core_reference_limit",5000)))
        else:
            near=pd.DataFrame(columns=[
                "target_core", "exact_core_smiles", "attachment_topology",
                "core_tanimoto", "mcs_coverage_target", "mcs_coverage_reference",
            ])
        near_path=outdir/"mmp_near_core_references.csv"; near.to_csv(near_path,index=False); extra_artifacts.append(near_path)
    report = outdir / "mmp_report.html"
    target_report_links = []
    transformation_artifacts: list[Path] = []
    structure_artifacts: list[Path] = []
    if role != "type-iii":
        from rdkit import Chem
        from rdkit.Chem import Draw

        for _, target in targets.drop_duplicates("target_compound_id").iterrows():
            target_id = str(target["target_compound_id"])
            part = (
                target_pairs.loc[
                    target_pairs["target_compound_id"].astype(str).eq(target_id)
                ].copy()
                if len(target_pairs) else pd.DataFrame()
            )
            unit_labels = ", ".join(sorted(set(
                targets.loc[
                    targets["target_compound_id"].astype(str).eq(target_id),
                    "analysis_unit_id",
                ].astype(str)
            )))
            report_pairs = orient_report_rows_target_to(
                select_minimal_transform_rows(part)
            )
            safe_prefix = (
                "".join(
                    ch if ch.isalnum() or ch in "-_" else "_"
                    for ch in target_id
                )[:64]
                or "target"
            )
            # Distinct IDs can normalize to the same filename (for example A/B
            # and A?B).  Preserve the readable prefix while binding every
            # target report to a collision-resistant ID-derived suffix.
            safe = (
                f"{safe_prefix}_"
                f"{hashlib.sha256(target_id.encode('utf-8')).hexdigest()[:12]}"
            )
            display_effect = "favorable_delta_report"
            display_label = "Δ neighbor→target"
            target_smiles = str(
                data.loc[
                    data[compound_id].astype(str).eq(target_id), smiles
                ].iloc[0]
            )
            target_structure_html, neighbor_structure_html, structure_paths = (
                render_target_neighbor_structures(
                    target_id, target_smiles, report_pairs, outdir, safe
                )
            )
            structure_artifacts.extend(structure_paths)
            visible_pairs = report_pairs.sort_values(
                ["neighbor_compound_id", "mmp_id"],
                ascending=[True, True],
                kind="mergesort",
            ) if len(report_pairs) else report_pairs
            transformation_gallery, gallery_artifacts = (
                render_core_group_gallery(visible_pairs, outdir, safe)
            )
            transformation_artifacts.extend(gallery_artifacts)
            direction_note = (
                f"{display_label}が正なら、NeighborからTargetへの変換が"
                "Favorableです。Targetは表示上常にToへ正規化しています。"
                "0件も正しいNegative Resultです。"
            )
            target_body = render_mmp_template(
                "mmp_target_report_template.html",
                {
                    "role_label": html.escape(role),
                    "target_id": html.escape(target_id),
                    "analysis_units": html.escape(unit_labels),
                    "target_smiles": html.escape(target_smiles),
                    "target_structure_image": target_structure_html,
                    "neighbor_structure_gallery": neighbor_structure_html,
                    "basic_information_table": compact_mmp_table(
                        visible_pairs, "basic", 100
                    ),
                    "mmp_detail_table": compact_mmp_table(
                        visible_pairs, "detail", 100
                    ),
                    "direction_note": html.escape(direction_note),
                    "transformation_gallery": transformation_gallery,
                    "display_scope_note": html.escape(
                        mmp_report_scope_note(part, visible_pairs)
                    ),
                    "full_csv_path": html.escape(primary.name, quote=True),
                },
            )
            page_path = outdir / f"mmp_target_{safe}.html"
            page_path.write_text(
                html_page(f"MMP target {target_id}", target_body),
                encoding="utf-8",
            )
            target_report_links.append((target_id, page_path))
        report_index_path = outdir / "mmp_report_index.json"
        report_records = []
        for target_id, page_path in target_report_links:
            target_summary_row = target_summary.loc[
                target_summary["target_compound_id"].astype(str).eq(target_id)
            ].head(1)
            target_endpoint_value = (
                target_summary_row.iloc[0].get("target_endpoint")
                if len(target_summary_row) else None
            )
            pair_count = (
                int(target_summary_row.iloc[0].get("mmp_pair_count", 0))
                if len(target_summary_row) else 0
            )
            for unit_id in sorted(set(
                targets.loc[
                    targets["target_compound_id"].astype(str).eq(target_id),
                    "analysis_unit_id",
                ].astype(str)
            )):
                report_records.append({
                    "analysis_unit_id": unit_id,
                    "target_compound_id": target_id,
                    "target_rank": 1,
                    "target_endpoint": target_endpoint_value,
                    "mmp_pair_count": pair_count,
                    "report_path": page_path.name,
                })
        write_json(report_index_path, {
            "schema_version": "1.0.0",
            "role": role,
            "unit_reports": report_records,
            "overview_path": report.name,
        })
        extra_artifacts.append(report_index_path)
    links = "".join(
        f"<li><a href='{html.escape(path.name, quote=True)}'>"
        f"{html.escape(target_id)}</a></li>"
        for target_id, path in target_report_links
    )
    report_target_summary = target_summary.copy()
    if role != "type-iii" and len(report_target_summary):
        report_effect_fraction = report_target_summary[
            "favorable_toward_target_fraction"
        ]
        report_target_summary["effect_direction"] = "neighbor_to_target"
        report_target_summary["effect_summary"] = "mixed"
        report_target_summary.loc[
            report_effect_fraction.ge(.6), "effect_summary"
        ] = "favorable_observed"
        report_target_summary.loc[
            report_effect_fraction.eq(0), "effect_summary"
        ] = "no_favorable_observed"
    effect_note = (
        "隣接化合物からTop対象へ向かう方向"
        if role == "type-i"
        else "隣接化合物から指定Targetへ向かう方向"
        if role == "type-ii"
        else "Databaseのcanonical方向"
    )
    scope_note = (
        f"1-cut / environment radius {radius_min}–{radius_max}。"
        f"主effectは{effect_note}でFavorableを正とします。"
        + (
            "定型Type-Iは各Series／fallback ClusterのTop 1だけを対象とします。"
            if role == "type-i" else ""
        )
    )
    target_gallery, target_gallery_artifacts = (
        render_target_overview_gallery(
            targets, data, compound_id, smiles, endpoint, outdir
        ) if role != "type-iii" else (
            "<p class='muted'>Type-IIIにはTarget選抜がありません。</p>", []
        )
    )
    structure_artifacts.extend(target_gallery_artifacts)
    overview_body = render_mmp_template(
        "mmp_overview_report_template.html",
        {
            "role": html.escape(role),
            "scope_note": html.escape(scope_note),
            "scope_metrics": mmp_metric_grid([
                ("Targets", len(targets) if role != "type-iii" else "database"),
                ("Target-connected MMP rows", len(target_pairs)),
                ("Cuts", 1),
                ("Environment radius", f"{radius_min}–{radius_max}"),
            ]),
            "target_table": compact_mmp_table(
                report_target_summary, "overview",
                max(1, len(report_target_summary))
            ),
            "target_gallery": target_gallery,
            "target_links": (
                f"<ul>{links}</ul>"
                if links else "<p class='muted'>対象別レポートなし</p>"
            ),
            "full_csv_path": html.escape(primary.name, quote=True),
        },
    )
    report.write_text(
        html_page("MMP analysis", overview_body), encoding="utf-8"
    )
    extra_artifacts.extend([path for _, path in target_report_links]); extra_artifacts.extend(structure_artifacts); extra_artifacts.extend(transformation_artifacts)
    if role == "type-iii":
        extra_artifacts.extend(path for path in outdir.iterdir() if path.is_file() and path not in {primary,report})
    else:
        # Type-I/II are human-centred target analyses. The complete database and
        # global summary exports belong exclusively to explicit Type-III.
        keep={primary.name,targets_path.name,target_summary_path.name,"mmp_target_transform_summary.csv","mmp_target_core_summary.csv","mmp_near_core_references.csv","mmp_report.html","mmp_report_index.json",*[path.name for _, path in target_report_links],*[path.name for path in structure_artifacts],*[path.name for path in transformation_artifacts]}
        for path in list(outdir.iterdir()):
            if path.name not in keep:
                if path.is_dir(): shutil.rmtree(path,ignore_errors=True)
                else: path.unlink(missing_ok=True)
    finish_request(request, outdir, capability, primary=primary, summary={"role": role, "target_count": len(targets) if role != "type-iii" else None, "target_connected_pair_rows": len(target_pairs), "database_pair_rows": len(details) if role == "type-iii" else None, "targets_without_mmp": int((target_summary.get("mmp_pair_count", pd.Series(dtype=int)) == 0).sum()) if role != "type-iii" else None, "cuts": 1, "radius": [radius_min, radius_max], "reused_explicit_type_iii_database": reused_database, "negative_result": len(target_pairs) == 0}, report=report, extra_artifacts=extra_artifacts, warnings=build_warnings)
    return 0


def run() -> int:
    if sys.argv[1:] in (["--help"], ["-h"]):
        print("Usage: run.py --request <execution_request.json>")
        return 0
    if sys.argv[1:2] != ["--request"] or len(sys.argv) != 3:
        raise SystemExit(
            "Usage: run.py --request <execution_request.json>. "
            "Use the Launcher with --conductor-request in managed execution."
        )
    return run_execution_request()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
