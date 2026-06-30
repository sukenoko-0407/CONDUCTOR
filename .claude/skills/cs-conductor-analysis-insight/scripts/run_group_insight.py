from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from insight_config import default_outdir, descriptions_dir, group_dir
from insight_groups import load_membership_matrix, load_registry, valid_property_table
from insight_io import load_config, read_csv, utc_now_iso, write_csv, write_json, write_text
from insight_metrics import add_ranks, compute_group_metrics, metric_ranking_rows
from insight_overlap import compute_overlap
from insight_plots import write_figures
from insight_report import build_top_groups_report
from insight_structural_diversity import structural_diversity_rows


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR.parent / "config" / "default_insight_config.json"
SKILL_NAME = "cs-conductor-analysis-insight"
SKILL_VERSION = "0.1.0"
ANALYSIS_NAME = "Group Insight Analysis"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CONDUCTOR Group Insight Phase2 analysis.")
    parser.add_argument("--input", required=True, help="Original compound CSV containing ID and property columns.")
    parser.add_argument("--config", help="Optional user override config JSON.")
    parser.add_argument("--id-column", help="Compound ID column in the original CSV.")
    parser.add_argument("--property-column", help="Numeric property column, such as pIC50.")
    parser.add_argument("--groups-dir", help="Grouping output directory. Defaults to groups/<input_stem>.")
    parser.add_argument("--descriptions-dir", help="Descriptor CSV directory. Defaults to descriptions/<input_stem>.")
    parser.add_argument("--outdir", help="Output directory. Defaults to analysis/<input_stem>/group_insight.")
    parser.add_argument("--top-n-report", type=int, help="Override number of groups in top_groups_report.md.")
    return parser.parse_args()


def output_files(outdir: Path) -> list[str]:
    return sorted(str(path.relative_to(outdir).as_posix()) for path in outdir.rglob("*") if path.is_file())


def main() -> int:
    args = parse_args()
    config = load_config(args.config, DEFAULT_CONFIG_PATH)
    if args.top_n_report is not None:
        config.setdefault("ranking", {})["top_n_report"] = int(args.top_n_report)

    input_path = Path(args.input)
    original_df = read_csv(input_path)
    property_table, id_column, property_column, warnings = valid_property_table(
        original_df, config, args.id_column, args.property_column
    )
    if len(property_table) < 2:
        raise ValueError("At least two compounds with numeric property values are required.")

    gdir = group_dir(input_path, config, args.groups_dir)
    group_cfg = config.get("group_inputs", {}) or {}
    membership_path = gdir / str(group_cfg.get("membership_matrix", "group_membership_matrix.csv"))
    registry_path = gdir / str(group_cfg.get("registry", "group_registry.json"))
    if not membership_path.exists():
        raise FileNotFoundError(f"Membership matrix not found: {membership_path}")
    if not registry_path.exists():
        raise FileNotFoundError(f"Group registry not found: {registry_path}")

    membership_df, membership_id_col, group_columns, membership_warnings = load_membership_matrix(membership_path)
    registry, registry_warnings = load_registry(registry_path)
    warnings.extend(membership_warnings)
    warnings.extend(registry_warnings)

    profile_df, enrichment_df, member_df, global_info, group_members, metric_warnings = compute_group_metrics(
        property_table, membership_df, group_columns, registry, config
    )
    warnings.extend(metric_warnings)
    if profile_df.empty:
        raise RuntimeError("No groups remained after property join and configured filters.")

    ddir = descriptions_dir(input_path, config, args.descriptions_dir)
    div_cfg = config.get("structural_diversity", {}) or {}
    ecfp4_path = ddir / str(div_cfg.get("ecfp4_bit_file", "L02_ecfp4_bit.csv"))
    structural_rows, structural_warnings = structural_diversity_rows(group_members, ecfp4_path, config)
    warnings.extend(structural_warnings)
    structural_df = pd.DataFrame(structural_rows)

    summary_df = profile_df.merge(enrichment_df, on=["group_id", "group_size"], how="left")
    if not structural_df.empty:
        summary_df = summary_df.merge(structural_df, on="group_id", how="left")
    else:
        summary_df["structural_diversity_available"] = False
        summary_df["mean_ecfp4_tanimoto"] = pd.NA
        summary_df["median_ecfp4_tanimoto"] = pd.NA
        summary_df["structural_diversity_score"] = pd.NA

    summary_df = add_ranks(summary_df, config)
    overlap_cfg = config.get("overlap", {}) or {}
    ranking_cfg = config.get("ranking", {}) or {}
    if bool(overlap_cfg.get("enabled", True)):
        overlap_df, summary_df = compute_overlap(
            membership_df,
            summary_df,
            float(overlap_cfg.get("jaccard_threshold", 0.8)),
            float(ranking_cfg.get("redundancy_penalty", 5.0)),
            bool(ranking_cfg.get("redundancy_penalty_enabled", True)),
        )
    else:
        overlap_df = pd.DataFrame()
        summary_df["insight_priority_score"] = summary_df["insight_priority_prelim_score"]
        summary_df["insight_priority_rank"] = summary_df["insight_priority_prelim_rank"]

    ranking_rows = metric_ranking_rows(summary_df)
    outdir = default_outdir(input_path, config, args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summary_columns = [
        "group_id",
        "group_label",
        "group_type",
        "group_source",
        "group_size",
        "property_median",
        "property_mean",
        "property_std",
        "property_iqr",
        "median_shift_vs_global",
        "favorable_median_shift_vs_global",
        "high_active_fraction",
        "high_active_fraction_delta",
        "high_active_odds_ratio",
        "high_active_fdr_qvalue",
        "low_active_fraction",
        "low_active_fraction_delta",
        "mannwhitney_pvalue",
        "mannwhitney_fdr_qvalue",
        "rank_biserial_effect",
        "mean_ecfp4_tanimoto",
        "median_ecfp4_tanimoto",
        "structural_diversity_score",
        "structural_diversity_available",
        "activity_enriched_group_rank",
        "structurally_diverse_active_group_rank",
        "consistent_group_rank",
        "interpretable_group_rank",
        "insight_priority_rank",
        "insight_priority_score",
        "max_jaccard_with_higher_ranked_group",
        "redundancy_flag",
        "redundant_with_group_id",
        "interpretability_tier",
        "interpretability_reason",
        "definition_method",
        "definition_source_descriptor_file",
        "definition_parameter_set_id",
    ]

    write_csv(outdir / "group_insight_summary.csv", summary_df.sort_values("insight_priority_rank"), summary_columns)
    write_csv(outdir / "group_property_profile.csv", profile_df)
    write_csv(outdir / "group_enrichment_stats.csv", enrichment_df)
    write_csv(outdir / "group_structural_diversity.csv", structural_df)
    write_csv(outdir / "group_overlap_summary.csv", overlap_df)
    write_csv(outdir / "group_member_details.csv", member_df)
    write_csv(outdir / "group_metric_ranking.csv", ranking_rows)

    top_n = int(ranking_cfg.get("top_n_report", 30))
    write_text(outdir / "top_groups_report.md", build_top_groups_report(summary_df, global_info, top_n))

    figure_warnings = write_figures(outdir, summary_df, member_df, membership_df, config)
    warnings.extend(figure_warnings)
    write_json(outdir / "insight_warnings.json", {"warnings": warnings})

    manifest = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "analysis_name": ANALYSIS_NAME,
        "created_at": utc_now_iso(),
        "input_csv": str(input_path),
        "group_directory": str(gdir),
        "descriptor_directory": str(ddir),
        "output_directory": str(outdir),
        "config_path": str(Path(args.config)) if args.config else None,
        "default_config_path": str(DEFAULT_CONFIG_PATH),
        "id_column": id_column,
        "property_column": property_column,
        "property_direction_higher_is_better": bool((config.get("property", {}) or {}).get("higher_is_better", True)),
        "activity_thresholds": global_info,
        "input_row_count": int(len(original_df)),
        "property_valid_compound_count": int(len(property_table)),
        "group_column_count": int(len(group_columns)),
        "analyzed_group_count": int(len(summary_df)),
        "ecfp4_descriptor_path": str(ecfp4_path),
        "ecfp4_structural_diversity_available": bool(summary_df["structural_diversity_available"].fillna(False).any()),
        "outputs": output_files(outdir),
    }
    write_json(outdir / "insight_manifest.json", manifest)

    best = summary_df.sort_values("insight_priority_rank").iloc[0]
    print(f"Wrote Group Insight analysis: {outdir}")
    print(
        "Best insight priority group: "
        f"{best['group_id']} (rank={best['insight_priority_rank']}, score={best['insight_priority_score']:.4g})"
    )
    if warnings:
        print(f"Warnings: {len(warnings)} written to {outdir / 'insight_warnings.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
