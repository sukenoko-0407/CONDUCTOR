from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _sample(df: pd.DataFrame, n: int, random_state: int = 42) -> pd.DataFrame:
    if len(df) <= n:
        return df
    return df.sample(n=n, random_state=random_state)


def write_figures(
    outdir: Path,
    summary_df: pd.DataFrame,
    member_df: pd.DataFrame,
    membership_df: pd.DataFrame,
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
        return [f"matplotlib unavailable; skipped insight figures: {exc}"]

    if summary_df.empty:
        return ["No summary rows available; skipped insight figures."]

    figure_dir = outdir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    dpi = int(fig_cfg.get("dpi", 160))
    max_groups = int(fig_cfg.get("max_groups_per_plot", 80))
    plot_df = _sample(summary_df.sort_values("insight_priority_rank"), max_groups)

    try:
        plt.figure(figsize=(7, 5))
        colors = pd.factorize(plot_df["group_source"].astype(str))[0]
        sizes = np.clip(plot_df["group_size"].astype(float).to_numpy(), 10, 250)
        plt.scatter(plot_df["group_size"], plot_df["high_active_fraction_delta"], c=colors, s=sizes, alpha=0.65, cmap="tab20")
        plt.xlabel("Group size")
        plt.ylabel("High-active fraction delta")
        plt.title("Activity Enrichment vs Group Size")
        plt.tight_layout()
        plt.savefig(figure_dir / "activity_enrichment_vs_group_size.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write activity_enrichment_vs_group_size.png: {exc}")

    try:
        top = summary_df.sort_values("insight_priority_rank").head(min(20, len(summary_df)))
        labels = top["group_id"].astype(str).tolist()
        data = [
            member_df.loc[member_df["group_id"].astype(str) == group_id, "property"].astype(float).to_numpy()
            for group_id in labels
        ]
        plt.figure(figsize=(max(8, len(labels) * 0.45), 5))
        plt.boxplot(data, showfliers=False)
        plt.xticks(range(1, len(labels) + 1), labels, rotation=60, ha="right")
        plt.ylabel("Property")
        plt.title("Top Group Property Distributions")
        plt.tight_layout()
        plt.savefig(figure_dir / "top_group_property_distributions.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write top_group_property_distributions.png: {exc}")

    try:
        div_df = plot_df.dropna(subset=["mean_ecfp4_tanimoto"])
        if div_df.empty:
            warnings.append("Skipped high_activity_vs_ecfp4_tanimoto.png because ECFP4 diversity is unavailable.")
        else:
            plt.figure(figsize=(7, 5))
            colors = pd.factorize(div_df["group_source"].astype(str))[0]
            sizes = np.clip(div_df["group_size"].astype(float).to_numpy(), 10, 250)
            plt.scatter(div_df["mean_ecfp4_tanimoto"], div_df["high_active_fraction_delta"], c=colors, s=sizes, alpha=0.65, cmap="tab20")
            plt.xlabel("Mean ECFP4 Tanimoto within group")
            plt.ylabel("High-active fraction delta")
            plt.title("High Activity vs ECFP4 Similarity")
            plt.tight_layout()
            plt.savefig(figure_dir / "high_activity_vs_ecfp4_tanimoto.png", dpi=dpi)
            plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write high_activity_vs_ecfp4_tanimoto.png: {exc}")

    try:
        div_df = plot_df.dropna(subset=["structural_diversity_score", "property_iqr"])
        if div_df.empty:
            warnings.append("Skipped structural_diversity_vs_consistency.png because ECFP4 diversity is unavailable.")
        else:
            consistency = 1.0 / (1.0 + div_df["property_iqr"].astype(float))
            plt.figure(figsize=(7, 5))
            scatter = plt.scatter(
                div_df["structural_diversity_score"],
                consistency,
                c=div_df["high_active_fraction_delta"],
                s=np.clip(div_df["group_size"].astype(float).to_numpy(), 10, 250),
                alpha=0.65,
                cmap="viridis",
            )
            plt.xlabel("Structural diversity score")
            plt.ylabel("Activity consistency proxy: 1 / (1 + IQR)")
            plt.title("Structural Diversity vs Activity Consistency")
            plt.colorbar(scatter, label="High-active fraction delta")
            plt.tight_layout()
            plt.savefig(figure_dir / "structural_diversity_vs_consistency.png", dpi=dpi)
            plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write structural_diversity_vs_consistency.png: {exc}")

    try:
        top = summary_df.sort_values("insight_priority_rank").head(int((config.get("overlap", {}) or {}).get("top_n_for_heatmap", 50)))
        group_ids = top["group_id"].astype(str).tolist()
        if len(group_ids) >= 2:
            x = membership_df[group_ids].to_numpy(dtype=np.int32)
            sizes = x.sum(axis=0)
            intersections = x.T @ x
            unions = sizes[:, None] + sizes[None, :] - intersections
            jaccard = np.divide(intersections, unions, out=np.zeros_like(intersections, dtype=float), where=unions != 0)
            plt.figure(figsize=(max(6, len(group_ids) * 0.22), max(5, len(group_ids) * 0.22)))
            plt.imshow(jaccard, cmap="magma", vmin=0, vmax=1)
            plt.colorbar(label="Jaccard overlap")
            plt.xticks(range(len(group_ids)), group_ids, rotation=90, fontsize=6)
            plt.yticks(range(len(group_ids)), group_ids, fontsize=6)
            plt.title("Top Group Overlap Heatmap")
            plt.tight_layout()
            plt.savefig(figure_dir / "top_group_overlap_heatmap.png", dpi=dpi)
            plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write top_group_overlap_heatmap.png: {exc}")

    try:
        top = summary_df.sort_values("insight_priority_rank").head(max_groups)
        counts = top["group_source"].astype(str).value_counts().sort_values()
        plt.figure(figsize=(8, max(4, len(counts) * 0.35)))
        plt.barh(counts.index, counts.values)
        plt.xlabel("Top group count")
        plt.title("Group Source Summary")
        plt.tight_layout()
        plt.savefig(figure_dir / "group_source_summary.png", dpi=dpi)
        plt.close()
    except Exception as exc:
        warnings.append(f"Failed to write group_source_summary.png: {exc}")

    return warnings
