from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_descriptor_clusters import build_descriptor_clusters
from build_fragment_groups import build_fragment_groups
from build_human_groups import build_human_groups
from build_mcs_groups import build_mcs_groups
from build_meta_groups import build_meta_groups
from build_murcko_groups import build_murcko_groups
from build_similarity_groups import build_similarity_groups
from detect_columns import detect_columns
from export_graph_packet import export_graph_packet
from grouping_io import (
    load_config,
    read_csv,
    utc_now_iso,
    validate_json_artifact,
    write_context_aliases,
    write_csv,
    write_json,
)
from grouping_models import relation_rows_from_overlap
from select_groups import select_groups
from standardize_compounds import standardize_compounds


SKILL_VERSION = "0.1.0"


def repo_root() -> Path:
    return SCRIPT_DIR.parents[3]


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def repo_default_config_path() -> Path:
    return SCRIPT_DIR.parent / "config" / "default_grouping_config.json"


def add_relation_ids(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, row in enumerate(relations, start=1):
        row["relation_id"] = f"REL_{index:04d}"
    return relations


def required_columns_or_raise(schema: dict[str, Any]) -> tuple[str, str]:
    id_column = schema.get("id_column")
    smiles_column = schema.get("smiles_column")
    missing = []
    if not id_column:
        missing.append("Molecule ID column")
    if not smiles_column:
        missing.append("SMILES column")
    if missing:
        raise RuntimeError("Required column detection failed: " + ", ".join(missing))
    return str(id_column), str(smiles_column)


def build_group_summary(registry: list[dict[str, Any]], compounds: Any, excluded_count: int) -> dict[str, Any]:
    by_type = Counter(str(row.get("group_type", "unknown")) for row in registry)
    by_source = Counter(str(row.get("group_source", "unknown")) for row in registry)
    return {
        "compound_count": int(len(compounds)),
        "excluded_compound_count": excluded_count,
        "group_count": len(registry),
        "group_count_by_type": dict(sorted(by_type.items())),
        "group_count_by_source": dict(sorted(by_source.items())),
    }


def build_membership_matrix(compounds: Any, registry: list[dict[str, Any]], membership: list[dict[str, Any]]) -> Any:
    compound_ids = sorted(compounds["compound_id"].astype(str).tolist())
    group_ids = sorted(str(row["group_id"]) for row in registry)
    matrix = {compound_id: {group_id: 0 for group_id in group_ids} for compound_id in compound_ids}
    compound_id_set = set(compound_ids)
    group_id_set = set(group_ids)
    for row in membership:
        compound_id = str(row["compound_id"])
        group_id = str(row["group_id"])
        if compound_id in compound_id_set and group_id in group_id_set:
            matrix[compound_id][group_id] = 1
    rows = [{"compound_id": compound_id, **matrix[compound_id]} for compound_id in compound_ids]
    try:
        import pandas as pd

        return pd.DataFrame(rows, columns=["compound_id", *group_ids])
    except Exception:
        return rows


def apply_group_filters(
    registry: list[dict[str, Any]],
    membership: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = config.get("group_filters", {}) or {}
    min_count = int(cfg.get("min_compound_count", 1))
    apply_sources = {str(source) for source in cfg.get("apply_to_sources", ["*"])}

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for group in registry:
        source = str(group.get("group_source", ""))
        applies = "*" in apply_sources or source in apply_sources
        compound_count = int(group.get("compound_count", 0))
        if applies and compound_count < min_count:
            dropped.append(group)
        else:
            kept.append(group)

    kept_group_ids = {str(group["group_id"]) for group in kept}
    filtered_membership = [row for row in membership if str(row.get("group_id")) in kept_group_ids]

    dropped_by_source = Counter(str(group.get("group_source", "unknown")) for group in dropped)
    dropped_by_type = Counter(str(group.get("group_type", "unknown")) for group in dropped)
    report = {
        "min_compound_count": min_count,
        "apply_to_sources": sorted(apply_sources),
        "input_group_count": len(registry),
        "kept_group_count": len(kept),
        "dropped_group_count": len(dropped),
        "dropped_group_count_by_source": dict(sorted(dropped_by_source.items())),
        "dropped_group_count_by_type": dict(sorted(dropped_by_type.items())),
    }
    return kept, filtered_membership, report


def validate_input_ids(df: Any, id_column: str) -> None:
    values = df[id_column]
    missing_mask = values.isna() | values.astype(str).str.strip().eq("")
    if bool(missing_mask.any()):
        rows = [int(index) + 1 for index in df.index[missing_mask].tolist()[:10]]
        raise ValueError(f"Input ID validation failed: missing IDs in column '{id_column}' at row(s): {rows}")

    normalized = values.astype(str).str.strip()
    duplicate_mask = normalized.duplicated(keep=False)
    if bool(duplicate_mask.any()):
        examples = sorted(normalized[duplicate_mask].unique().tolist())[:10]
        raise ValueError(f"Input ID validation failed: duplicate IDs in column '{id_column}': {examples}")


def default_outdir(input_path: str, config: dict[str, Any]) -> Path:
    outputs = config.get("outputs", {}) or {}
    base_dir = Path(str(outputs.get("base_dir", "groups")))
    if not base_dir.is_absolute():
        base_dir = repo_root() / base_dir
    subdir = outputs.get("subdir")
    if subdir:
        return base_dir / str(subdir)
    return base_dir / Path(input_path).stem


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Grouping Skill artifact generation.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--config")
    parser.add_argument("--id-column")
    parser.add_argument("--smiles-column")
    parser.add_argument("--grouping-columns")
    parser.add_argument("--is-virtual-column")
    parser.add_argument("--include-virtual-in-mcs", action="store_true")
    parser.add_argument("--skip-mcs", action="store_true")
    parser.add_argument("--skip-similarity", action="store_true")
    parser.add_argument("--write-context-aliases", action="store_true")
    args = parser.parse_args()

    default_config = repo_default_config_path()
    config = load_config(args.config, default_config)
    input_columns = config.setdefault("input_columns", {})
    if args.id_column:
        input_columns["id_column"] = args.id_column
    if args.smiles_column:
        input_columns["smiles_column"] = args.smiles_column
    if args.is_virtual_column:
        input_columns["is_virtual_column"] = args.is_virtual_column
    if args.grouping_columns:
        input_columns["grouping_columns"] = parse_list(args.grouping_columns)
    if args.include_virtual_in_mcs:
        config["group_builders"]["mcs_group_builder"]["include_virtual_in_mcs_mining"] = True
    if args.skip_mcs:
        config["group_builders"]["mcs_group_builder"]["enabled"] = False
    if args.skip_similarity:
        config["group_builders"]["similarity_group_builder"]["enabled"] = False

    warnings: list[str] = []
    df = read_csv(args.input)
    schema, report, detection_warnings = detect_columns(df, input_columns)
    warnings.extend(detection_warnings)

    if schema.get("ambiguous"):
        warnings.append(f"Ambiguous columns detected: {schema['ambiguous']}")

    id_column, smiles_column = required_columns_or_raise(schema)
    validate_input_ids(df, id_column)

    outdir = Path(args.outdir) if args.outdir else default_outdir(args.input, config)
    outdir.mkdir(parents=True, exist_ok=True)
    write_json(outdir / "detected_schema.json", schema)
    write_json(outdir / "column_detection_report.json", report)
    write_json(outdir / "column_detection_warnings.json", detection_warnings)

    compounds, excluded, standardize_warnings = standardize_compounds(
        df,
        id_column=id_column,
        smiles_column=smiles_column,
        is_virtual_column=schema.get("is_virtual_column"),
    )
    warnings.extend(standardize_warnings)
    write_csv(outdir / "compounds_master.csv", compounds)
    write_csv(outdir / "excluded_compounds.csv", excluded)

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []

    builders = config.get("group_builders", {})
    if builders.get("human_group_builder", {}).get("enabled", True):
        hum_reg, hum_mem, hum_warnings = build_human_groups(compounds, schema.get("grouping_columns", []))
        registry.extend(hum_reg)
        membership.extend(hum_mem)
        warnings.extend(hum_warnings)

    if builders.get("murcko_group_builder", {}).get("enabled", True):
        murcko_reg, murcko_mem, murcko_warnings = build_murcko_groups(compounds, builders.get("murcko_group_builder", {}))
        registry.extend(murcko_reg)
        membership.extend(murcko_mem)
        warnings.extend(murcko_warnings)

    if builders.get("mcs_group_builder", {}).get("enabled", True):
        mcs_reg, mcs_mem, mcs_warnings = build_mcs_groups(compounds, builders.get("mcs_group_builder", {}), outdir=outdir)
        registry.extend(mcs_reg)
        membership.extend(mcs_mem)
        warnings.extend(mcs_warnings)

    if builders.get("brics_recap_fragment_builder", {}).get("enabled", True):
        frag_reg, frag_mem, frag_warnings = build_fragment_groups(compounds, builders.get("brics_recap_fragment_builder", {}), outdir=outdir)
        registry.extend(frag_reg)
        membership.extend(frag_mem)
        warnings.extend(frag_warnings)

    if builders.get("similarity_group_builder", {}).get("enabled", True):
        sim_reg, sim_mem, sim_warnings = build_similarity_groups(compounds, builders.get("similarity_group_builder", {}), outdir=outdir)
        registry.extend(sim_reg)
        membership.extend(sim_mem)
        warnings.extend(sim_warnings)

    if builders.get("descriptor_clustering_builder", {}).get("enabled", True):
        desc_reg, desc_mem, desc_warnings = build_descriptor_clusters(
            compounds,
            args.input,
            config.get("description_inputs", {}),
            builders.get("descriptor_clustering_builder", {}),
            outdir=outdir,
        )
        registry.extend(desc_reg)
        membership.extend(desc_mem)
        warnings.extend(desc_warnings)

    relation_cfg = config.get("relations", {}) or {}
    relations = relation_rows_from_overlap(
        membership,
        min_jaccard=float(relation_cfg.get("min_jaccard", 0.5)),
        max_relations=int(relation_cfg.get("max_relations", 50000)) if relation_cfg.get("max_relations", 50000) is not None else None,
    )
    if builders.get("meta_group_builder", {}).get("enabled", True):
        meta_reg, meta_mem, meta_rel, meta_warnings = build_meta_groups(
            compounds,
            registry,
            membership,
            builders.get("meta_group_builder", {}),
        )
        registry.extend(meta_reg)
        membership.extend(meta_mem)
        relations.extend(meta_rel)
        warnings.extend(meta_warnings)

    registry, membership, filter_report = apply_group_filters(registry, membership, config)
    if filter_report["dropped_group_count"]:
        warnings.append(
            f"Group filter dropped {filter_report['dropped_group_count']} groups with compound_count < {filter_report['min_compound_count']}."
        )
    kept_group_ids = {str(group["group_id"]) for group in registry}
    relations = [
        row
        for row in relations
        if str(row.get("source_group_id")) in kept_group_ids and str(row.get("target_group_id")) in kept_group_ids
    ]

    max_relations = relation_cfg.get("max_relations", 50000)
    if max_relations is not None:
        max_relation_count = int(max_relations)
        if max_relation_count > 0 and len(relations) > max_relation_count:
            warnings.append(f"Group relations were capped at max_relations={max_relation_count}; {len(relations) - max_relation_count} relations were omitted.")
            relations = relations[:max_relation_count]

    relations = add_relation_ids(relations)
    selected = select_groups(registry)
    group_summary = build_group_summary(registry, compounds, len(excluded))
    membership_matrix = build_membership_matrix(compounds, registry, membership)
    graph_packet = export_graph_packet(registry, relations, membership)

    write_json(outdir / "group_registry.json", registry)
    write_csv(outdir / "group_membership.csv", membership, ["group_id", "compound_id", "membership_source", "membership_reason"])
    write_csv(outdir / "group_membership_matrix.csv", membership_matrix)
    write_json(outdir / "group_relations.json", relations)
    write_json(outdir / "selected_groups.json", selected)
    write_json(outdir / "group_summary.json", group_summary)
    if bool((config.get("group_filters", {}) or {}).get("write_filter_report", True)):
        write_json(outdir / "group_filter_report.json", filter_report)
    if config.get("outputs", {}).get("write_graph_packet", True):
        write_json(outdir / "group_graph_packet.json", graph_packet)
    schema_dir = SCRIPT_DIR.parent / "schemas"
    validation_warnings: list[str] = []
    validation_warnings.extend(validate_json_artifact(registry, schema_dir / "group_registry.schema.json"))
    validation_warnings.extend(validate_json_artifact(relations, schema_dir / "group_relations.schema.json"))
    validation_warnings.extend(validate_json_artifact(selected, schema_dir / "selected_groups.schema.json"))
    warnings.extend(validation_warnings)

    if args.write_context_aliases or config.get("outputs", {}).get("write_context_aliases", True):
        write_context_aliases(outdir)

    outputs = sorted(path.name for path in outdir.iterdir() if path.is_file())
    if "grouping_manifest.json" not in outputs:
        outputs.append("grouping_manifest.json")
        outputs.sort()
    manifest = {
        "skill_name": "grouping",
        "skill_version": SKILL_VERSION,
        "input_file": str(Path(args.input)),
        "detected_columns": {
            "id_column": id_column,
            "smiles_column": smiles_column,
            "is_virtual_column": schema.get("is_virtual_column"),
            "grouping_columns": schema.get("grouping_columns", []),
        },
        "config_file": str(Path(args.config)) if args.config else str(default_config),
        "mcs_group_builder_config": builders.get("mcs_group_builder", {}),
        "description_inputs": config.get("description_inputs", {}),
        "relations_config": relation_cfg,
        "group_filter_report": filter_report,
        "outputs": outputs,
        "warnings": warnings,
        "created_at": utc_now_iso(),
    }
    manifest_validation = validate_json_artifact(manifest, schema_dir / "grouping_manifest.schema.json")
    if manifest_validation:
        manifest["warnings"].extend(manifest_validation)
    write_json(outdir / "grouping_warnings.json", manifest["warnings"])
    write_json(outdir / "grouping_manifest.json", manifest)

    print("Grouping completed.")
    print(f"Molecule ID column: {id_column}")
    print(f"SMILES column: {smiles_column}")
    print(f"User grouping columns: {', '.join(schema.get('grouping_columns', [])) or '(none)'}")
    print(f"Compounds processed: {len(compounds)}")
    print(f"Excluded compounds: {len(excluded)}")
    print(f"Groups generated: {dict(sorted(Counter(row['group_source'] for row in registry).items()))}")
    print(f"Outputs: {outdir}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
