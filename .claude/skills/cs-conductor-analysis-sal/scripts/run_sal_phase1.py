from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from sal_config import (
    default_outdir,
    descriptor_dir,
    detect_id_column,
    detect_property_column,
    match_representation,
)
from sal_features import load_representation_matrix, valid_property_table
from sal_io import load_config, read_csv, utc_now_iso, write_csv, write_json
from sal_metrics import build_metric_ranking, compute_sal_metrics, knn_indices, pairwise_distance
from sal_plots import write_figures


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR.parent / "config" / "default_sal_phase1_config.json"
SKILL_NAME = "cs-conductor-analysis-sal"
SKILL_VERSION = "0.1.0"
ANALYSIS_NAME = "Structure-Activity Landscape"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CONDUCTOR Structure-Activity Landscape Phase1 analysis."
    )
    parser.add_argument("--input", required=True, help="Original compound CSV containing ID and property columns.")
    parser.add_argument("--config", help="Optional user override config JSON.")
    parser.add_argument("--id-column", help="Compound ID column in the original CSV.")
    parser.add_argument("--property-column", help="Numeric property column, such as pIC50.")
    parser.add_argument("--descriptions-dir", help="Descriptor CSV directory. Defaults to descriptions/<input_stem>.")
    parser.add_argument("--outdir", help="Output directory. Defaults to analysis/<input_stem>/structure_activity_landscape.")
    parser.add_argument("--k", type=int, help="Override kNN neighbor count.")
    return parser.parse_args()


def descriptor_paths(desc_dir: Path, config: dict[str, Any]) -> list[Path]:
    desc_cfg = config.get("description_inputs", {}) or {}
    if not bool(desc_cfg.get("enabled", True)):
        return []
    glob_pattern = str(desc_cfg.get("file_glob", "*.csv"))
    skip_files = {str(name).lower() for name in desc_cfg.get("skip_files", [])}
    paths = [
        path
        for path in sorted(desc_dir.glob(glob_pattern))
        if path.is_file() and path.name.lower() not in skip_files
    ]
    return paths


def add_summary_ranks(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not summary_rows:
        return []
    df = pd.DataFrame(summary_rows)
    for metric, ascending, output_column in [
        ("median_abs_delta_property_among_knn", True, "rank_by_median_abs_delta_property_among_knn"),
        ("median_local_property_variance", True, "rank_by_median_local_property_variance"),
        ("neighbor_property_autocorrelation", False, "rank_by_neighbor_property_autocorrelation"),
        ("median_normalized_sali", True, "rank_by_median_normalized_sali"),
        ("median_sali", True, "rank_by_median_sali"),
        ("p90_sali", True, "rank_by_p90_sali"),
        ("p95_sali", True, "rank_by_p95_sali"),
    ]:
        df[output_column] = df[metric].rank(method="min", ascending=ascending, na_option="bottom").astype(int)
    primary_rank_columns = [
        "rank_by_median_abs_delta_property_among_knn",
        "rank_by_median_local_property_variance",
        "rank_by_neighbor_property_autocorrelation",
    ]
    df["primary_comparison_rank_score"] = df[primary_rank_columns].mean(axis=1)
    df["primary_comparison_rank"] = (
        df["primary_comparison_rank_score"].rank(method="min", ascending=True, na_option="bottom").astype(int)
    )
    return df.to_dict(orient="records")


def output_files(outdir: Path) -> list[str]:
    return sorted(str(path.relative_to(outdir).as_posix()) for path in outdir.rglob("*") if path.is_file())


def run() -> int:
    args = parse_args()
    config = load_config(args.config, DEFAULT_CONFIG_PATH)
    if args.k is not None:
        if args.k < 1:
            raise ValueError("--k must be >= 1.")
        config.setdefault("knn", {})["k"] = int(args.k)

    input_path = Path(args.input)
    original_df = read_csv(input_path)
    id_column = detect_id_column(list(original_df.columns), args.id_column)
    property_column = detect_property_column(list(original_df.columns), config, args.property_column)
    property_table, warnings = valid_property_table(original_df, id_column, property_column)
    excluded_property_row_count = int(len(original_df) - len(property_table))
    if len(property_table) < 2:
        raise ValueError("At least two compounds with numeric property values are required.")

    desc_dir = descriptor_dir(input_path, config, args.descriptions_dir)
    if not desc_dir.exists():
        raise FileNotFoundError(f"Descriptor directory not found: {desc_dir}")
    paths = descriptor_paths(desc_dir, config)
    if not paths:
        raise FileNotFoundError(f"No descriptor CSV files found in: {desc_dir}")

    outdir = default_outdir(input_path, config, args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    all_edge_rows: list[dict[str, Any]] = []
    all_local_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    processed_descriptors: list[str] = []
    skipped_descriptors: list[str] = []

    k = int((config.get("knn", {}) or {}).get("k", 10))
    feature_cfg = config.get("feature_processing", {}) or {}

    for descriptor_path in paths:
        matched = match_representation(descriptor_path.name, config)
        if matched is None:
            skipped_descriptors.append(descriptor_path.name)
            warnings.append(f"{descriptor_path.name}: no representation metric config matched; skipped.")
            continue

        representation_id, rep_cfg = matched
        metric = str(rep_cfg.get("metric", "euclidean"))
        try:
            ids, properties, matrix, feature_count, load_warnings = load_representation_matrix(
                descriptor_path, property_table, rep_cfg, feature_cfg
            )
            warnings.extend(load_warnings)
            if len(ids) < 2:
                warnings.append(f"{descriptor_path.name}: fewer than two matched compounds; skipped.")
                skipped_descriptors.append(descriptor_path.name)
                continue

            distance = pairwise_distance(matrix, metric)
            neighbors = knn_indices(distance, k)
            edge_rows, local_rows, summary, distribution = compute_sal_metrics(
                representation_id,
                descriptor_path.name,
                ids,
                properties,
                distance,
                neighbors,
                config,
            )
            summary.update(
                {
                    "metric": metric,
                    "scaling": str(rep_cfg.get("scaling", "none")),
                    "feature_count": int(feature_count),
                    "property_column": property_column,
                    "id_column": id_column,
                }
            )
            distribution.update({"metric": metric, "scaling": str(rep_cfg.get("scaling", "none"))})
            all_edge_rows.extend(edge_rows)
            all_local_rows.extend(local_rows)
            summary_rows.append(summary)
            distribution_rows.append(distribution)
            processed_descriptors.append(descriptor_path.name)
        except Exception as exc:
            skipped_descriptors.append(descriptor_path.name)
            warnings.append(f"{descriptor_path.name}: failed: {exc}")

    if not summary_rows:
        write_json(outdir / "sal_warnings.json", {"warnings": warnings})
        raise RuntimeError("No descriptor representations were successfully analyzed.")

    summary_rows = add_summary_ranks(summary_rows)
    ranking_rows = build_metric_ranking(summary_rows)

    summary_columns = [
        "representation_id",
        "descriptor_file",
        "metric",
        "scaling",
        "compound_count",
        "feature_count",
        "effective_k",
        "primary_comparison_rank",
        "primary_comparison_rank_score",
        "median_sali",
        "p90_sali",
        "p95_sali",
        "median_normalized_sali",
        "p90_normalized_sali",
        "p95_normalized_sali",
        "median_local_property_variance",
        "p90_local_property_variance",
        "median_abs_delta_property_among_knn",
        "distance_property_spearman_correlation",
        "neighbor_property_autocorrelation",
        "neighbor_property_spearman_autocorrelation",
        "rank_by_median_abs_delta_property_among_knn",
        "rank_by_median_normalized_sali",
        "rank_by_median_sali",
        "rank_by_p90_sali",
        "rank_by_p95_sali",
        "rank_by_median_local_property_variance",
        "rank_by_neighbor_property_autocorrelation",
        "property_column",
        "id_column",
    ]
    write_csv(outdir / "sal_representation_summary.csv", summary_rows, summary_columns)
    write_csv(outdir / "sal_knn_edges.csv", all_edge_rows)
    write_csv(outdir / "sal_local_metrics.csv", all_local_rows)
    write_csv(outdir / "sal_sali_distribution.csv", distribution_rows)
    write_csv(outdir / "sal_metric_ranking.csv", ranking_rows)

    figure_warnings = write_figures(outdir, all_edge_rows, all_local_rows, summary_rows, config)
    warnings.extend(figure_warnings)
    write_json(outdir / "sal_warnings.json", {"warnings": warnings})
    manifest = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "analysis_name": ANALYSIS_NAME,
        "created_at": utc_now_iso(),
        "input_csv": str(input_path),
        "config_path": str(Path(args.config)) if args.config else None,
        "default_config_path": str(DEFAULT_CONFIG_PATH),
        "descriptor_directory": str(desc_dir),
        "output_directory": str(outdir),
        "id_column": id_column,
        "property_column": property_column,
        "input_row_count": int(len(original_df)),
        "property_valid_compound_count": int(len(property_table)),
        "excluded_property_row_count": excluded_property_row_count,
        "knn_k": k,
        "primary_comparison_basis": [
            "median_abs_delta_property_among_knn",
            "median_local_property_variance",
            "neighbor_property_autocorrelation",
        ],
        "sali_role": "raw SALI is a within-representation cliff diagnostic; normalized SALI is secondary.",
        "processed_descriptors": processed_descriptors,
        "skipped_descriptors": skipped_descriptors,
        "representation_configs_used": {
            str(row["representation_id"]): {
                "descriptor_file": str(row["descriptor_file"]),
                "metric": str(row["metric"]),
                "scaling": str(row["scaling"]),
            }
            for row in summary_rows
        },
        "outputs": output_files(outdir),
    }
    write_json(outdir / "sal_manifest.json", manifest)

    best = sorted(summary_rows, key=lambda row: row["primary_comparison_rank_score"])[0]
    print(f"Wrote SAL Phase1 analysis: {outdir}")
    print(
        "Best primary comparison score: "
        f"{best['representation_id']} ({best['primary_comparison_rank_score']:.3g}, metric={best['metric']})"
    )
    if warnings:
        print(f"Warnings: {len(warnings)} written to {outdir / 'sal_warnings.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
