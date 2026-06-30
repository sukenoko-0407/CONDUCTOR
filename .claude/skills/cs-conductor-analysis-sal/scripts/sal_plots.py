from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _sample(df: pd.DataFrame, max_points: int, random_state: int = 42) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    return df.sample(n=max_points, random_state=random_state)


def write_figures(
    outdir: Path,
    edge_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[str]:
    fig_cfg = config.get("figures", {}) or {}
    if not bool(fig_cfg.get("enabled", True)):
        return []
    warnings: list[str] = []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return [f"matplotlib unavailable; skipped SAL figures: {exc}"]

    figure_dir = outdir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    dpi = int(fig_cfg.get("dpi", 160))
    max_points = int(fig_cfg.get("max_points_per_plot", 20000))
    edge_df = pd.DataFrame(edge_rows)
    local_df = pd.DataFrame(local_rows)
    summary_df = pd.DataFrame(summary_rows)

    if edge_df.empty or summary_df.empty:
        return ["No edge or summary rows available; skipped SAL figures."]

    order_column = "primary_comparison_rank" if "primary_comparison_rank" in summary_df.columns else "median_sali"
    ordered_reps = summary_df.sort_values(order_column)["representation_id"].astype(str).tolist()

    try:
        top = summary_df.sort_values("primary_comparison_rank")
        y = np.arange(len(top))
        plt.figure(figsize=(9, max(4, len(top) * 0.35)))
        plt.barh(y, top["primary_comparison_rank_score"], height=0.55)
        plt.yticks(y, top["representation_id"])
        plt.xlabel("Mean rank across distance-independent kNN property metrics")
        plt.title("Primary Representation Comparison")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(figure_dir / "primary_representation_comparison.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write primary_representation_comparison.png: {exc}")

    try:
        data = []
        labels = []
        for rep in ordered_reps:
            values = edge_df.loc[edge_df["representation_id"].astype(str) == rep, "normalized_sali"].replace([np.inf, -np.inf], np.nan).dropna()
            if values.empty:
                continue
            cap = values.quantile(0.99)
            data.append(values.clip(upper=cap).to_numpy())
            labels.append(rep)
        plt.figure(figsize=(max(8, len(labels) * 0.55), 5))
        if data:
            plt.boxplot(data, showfliers=False)
            plt.xticks(range(1, len(labels) + 1), labels, rotation=45, ha="right")
        plt.ylabel("Distance-percentile-normalized SALI (clipped at representation p99)")
        plt.title("Normalized SALI Diagnostic by Representation")
        plt.tight_layout()
        plt.savefig(figure_dir / "sali_distribution_by_representation.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write sali_distribution_by_representation.png: {exc}")

    try:
        top = summary_df.sort_values("median_normalized_sali")
        y = np.arange(len(top))
        plt.figure(figsize=(8, max(4, len(top) * 0.35)))
        plt.barh(y - 0.18, top["median_normalized_sali"], height=0.35, label="median normalized SALI")
        plt.barh(y + 0.18, top["p90_normalized_sali"], height=0.35, label="p90 normalized SALI")
        plt.yticks(y, top["representation_id"])
        plt.xlabel("Distance-percentile-normalized SALI")
        plt.title("Normalized SALI Diagnostic Ranking")
        plt.legend()
        plt.tight_layout()
        plt.savefig(figure_dir / "sali_ranking.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write sali_ranking.png: {exc}")

    try:
        plot_df = _sample(edge_df, max_points)
        plt.figure(figsize=(7, 5))
        scatter = plt.scatter(plot_df["distance"], plot_df["abs_delta_property"], c=plot_df["normalized_sali"], s=8, alpha=0.45, cmap="viridis")
        plt.xlabel("Neighbor distance")
        plt.ylabel("Absolute property delta")
        plt.title("Distance vs Absolute Property Delta")
        plt.colorbar(scatter, label="normalized SALI")
        plt.tight_layout()
        plt.savefig(figure_dir / "distance_vs_abs_delta_property.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write distance_vs_abs_delta_property.png: {exc}")

    try:
        plot_df = _sample(local_df, max_points)
        reps = ordered_reps
        color_map = {rep: idx for idx, rep in enumerate(reps)}
        colors = plot_df["representation_id"].astype(str).map(color_map).fillna(0).to_numpy()
        plt.figure(figsize=(7, 5))
        scatter = plt.scatter(plot_df["local_median_property"], plot_df["local_property_variance"], c=colors, s=10, alpha=0.55, cmap="tab20")
        plt.xlabel("Local median property")
        plt.ylabel("Local property variance")
        plt.title("Local Variance vs Local Property")
        cbar = plt.colorbar(scatter, ticks=range(len(reps)))
        cbar.ax.set_yticklabels(reps)
        plt.tight_layout()
        plt.savefig(figure_dir / "local_variance_vs_local_property.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write local_variance_vs_local_property.png: {exc}")

    try:
        metrics = [
            ("median_abs_delta_property_among_knn", "lower better"),
            ("median_local_property_variance", "lower better"),
            ("neighbor_property_autocorrelation", "higher better"),
            ("distance_property_spearman_correlation", "higher better"),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(12, max(7, len(summary_df) * 0.28)), constrained_layout=True)
        for ax, (metric, direction) in zip(axes.ravel(), metrics):
            reverse = direction == "higher better"
            part = summary_df.sort_values(metric, ascending=not reverse)
            y = np.arange(len(part))
            ax.barh(y, part[metric])
            ax.set_yticks(y)
            ax.set_yticklabels(part["representation_id"])
            ax.invert_yaxis()
            ax.set_title(f"{metric} ({direction})")
        fig.suptitle("Auxiliary Structure-Activity Landscape Metrics")
        fig.savefig(figure_dir / "auxiliary_metric_summary.png", dpi=dpi)
        plt.close(fig)
    except Exception as exc:
        warnings.append(f"Failed to write auxiliary_metric_summary.png: {exc}")

    return warnings
