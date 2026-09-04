from __future__ import annotations

import json
import math
import hashlib
import html as html_lib
import shutil
from pathlib import Path
from string import Template
from typing import Any

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

from batch_skill_common import (
    analysis_units, bh_qvalues, dataset, description_table, favorable_definition,
    finish, frame_html, html_page, image_uri, input_path, inputs, membership_sets,
    numeric_features, parse_request, read_table, write_json,
)


SELECTION_BIAS_NOTE = "本比較はEndpoint enrichmentで選抜した解析単位を同じEndpointで評価しており、独立検証や因果関係を示しません。"

REPORT_TABLE_COLUMNS = {
    "at_a_glance": ["metric", "count"],
    "selected_clusters": [
        "cluster_id", "description", "clustering", "sample_count",
        "favorable_count_fraction", "candidate_series_id", "analysis_unit_id",
    ],
    "series": [
        "series_id", "source_cluster_count", "compound_count",
        "favorable_fraction", "applied_ff_threshold", "accepted",
        "final_analysis_units",
    ],
    "analysis_units": [
        "analysis_unit_id", "scope_kind", "source_cluster_count",
        "compound_count", "endpoint_valid_count", "favorable_fraction",
        "fallback_reason",
    ],
    "source_clusters": [
        "cluster_id", "description_id", "clustering_id", "sample_count",
        "favorable_count", "favorable_fraction", "odds_ratio", "q_value_bh",
    ],
    "membership_support": [
        "compound_id", "support_count", "support_fraction",
    ],
    "A003": [
        "analysis_unit_id", "feature", "description_id", "sample_count", "pearson_r",
        "spearman_r", "correlation_gain", "report_status",
    ],
    "A003_detail": [
        "feature", "description_id", "sample_count", "pearson_r", "spearman_r",
        "max_abs_correlation",
    ],
    "A005": [
        "analysis_unit_id", "member_count", "model_count", "status", "oof_r2",
        "global_oof_on_same_series_r2", "local_minus_global_r2", "oof_mae",
        "global_minus_local_mae", "report_status", "reason",
    ],
    "A006": [
        "analysis_unit_id", "sample_count", "status", "median_sali", "p95_sali",
        "internal_cliff_count", "boundary_cliff_count",
        "boundary_favorable_direction", "report_status", "reason",
    ],
    "A007": [
        "analysis_unit_id", "method", "clustering_id", "cluster_id", "structure",
        "support_count", "source_member_count", "mcs_canceled", "status", "reason",
    ],
    "execution": [
        "capability_id", "node_status", "duration_seconds", "evaluated_units",
        "result_rows", "succeeded_units", "not_applicable_units", "failed_units",
        "reason",
    ],
}

REPORT_SECTION_TITLES = {
    "A003": "A003 Interpretable descriptor contrast",
    "A005": "A005 Multi-Description feature model",
    "A006": "A006 SALI / activity-cliff landscape",
}

DETAIL_SECTION_TITLES = {
    **REPORT_SECTION_TITLES,
    "A007": "A007 Structural signature",
}

REPORT_COLUMN_LABELS = {
    "metric": "Summary item",
    "count": "Count",
    "cluster_id": "Cluster ID",
    "description": "Description",
    "clustering": "Clustering",
    "sample_count": "N",
    "favorable_count_fraction": "Favorable count (FF)",
    "favorable_count": "Favorable count",
    "favorable_fraction": "FF",
    "odds_ratio": "Odds ratio",
    "fisher_pvalue": "Fisher p",
    "q_value_bh": "BH q",
    "analysis_unit_id": "Analysis unit",
    "candidate_series_id": "Candidate Series",
    "series_id": "Series ID",
    "source_cluster_count": "Source Clusters",
    "compound_count": "Union N",
    "endpoint_valid_count": "Endpoint valid N",
    "source_cluster_mean_ff": "Source mean FF",
    "union_ff_delta_from_source_mean": "Union FF delta",
    "quality_warning": "Quality warning",
    "applied_ff_threshold": "Applied FF criterion",
    "final_analysis_units": "Final analysis unit",
    "fallback_reason": "Fallback reason",
    "support_count": "Support count",
    "support_fraction": "Support fraction",
    "duration_seconds": "Duration (s)",
    "feature": "Feature",
    "description_id": "Description ID",
    "pearson_r": "Pearson r",
    "spearman_r": "Spearman r",
    "max_abs_correlation": "Max |r|",
    "member_count": "Member N",
    "model_count": "Model N",
    "report_status": "判定",
    "method": "Key structure source",
    "boundary_favorable_direction": "Boundary favorable direction",
}

REPORT_VALUE_LABELS = {
    "method": {
        "source_structural_cluster": "Source Clusterの登録構造",
        "fallback_murcko": "Murcko scaffold",
        "fallback_mcs": "Maximum Common Substructure (MCS)",
        "unit_error": "構造取得エラー",
    },
}

REPORT_TABLE_TITLES = {
    "at_a_glance": "概要Table",
    "selected_clusters": "選抜Cluster Table",
    "series": "Candidate Series Table",
    "analysis_units": "Analysis unit Table",
    "source_clusters": "Source Cluster Table",
    "membership_support": "Membership Support Table",
    "A003": "A003結果Table",
    "A003_detail": "A003相関上位Table",
    "A005": "A005結果Table",
    "A006": "A006結果Table",
    "A007": "A007構造Signature Table",
    "execution": "実行状況Table",
}

REPORT_COLUMN_HELP = {
    "metric": "集計項目。",
    "count": "該当する件数または使用parameter。",
    "cluster_id": "CONDUCTORが割り当てたCluster ID。",
    "description": "Cluster作成に使ったDescription ID。",
    "clustering": "Cluster作成に使ったClustering ID。",
    "description_id": "特徴表現を示すDescription ID。",
    "clustering_id": "クラスタリング手法を示すClustering ID。",
    "sample_count": "評価に含まれた化合物数。",
    "favorable_count_fraction": "Favorable化合物数とFavorable Fraction（FF）。",
    "favorable_count": "Favorable cutoffを満たした化合物数。",
    "favorable_fraction": "Endpoint有効化合物に占めるFavorable化合物の割合。",
    "odds_ratio": "Globalと比べたFavorable化合物の濃縮度。1より大きいほど濃縮。",
    "q_value_bh": "Fisher検定のp値をBenjamini–Hochberg法で多重検定補正した値。小さいほど濃縮の統計的根拠が強い補助指標。",
    "candidate_series_id": "Clusterをまとめて評価したCandidate Series ID。",
    "analysis_unit_id": "後続の定型解析で扱うSeriesまたはfallback ClusterのID。",
    "series_id": "Candidateまたは採用SeriesのID。",
    "source_cluster_count": "Seriesを構成するSource Cluster数。",
    "compound_count": "Source Clusterの和集合に含まれる化合物数。",
    "endpoint_valid_count": "Endpointが欠損していない化合物数。",
    "applied_ff_threshold": "Series採用に適用したFF基準値。",
    "accepted": "Candidate Seriesが採用基準を満たしたか。",
    "final_analysis_units": "採用Series、または棄却後に戻したCluster ID。",
    "scope_kind": "analysis unitの種別（global、series、cluster）。",
    "fallback_reason": "Seriesとして採用せずClusterを解析単位に戻した理由。",
    "feature": "評価した解釈可能な特徴量名。",
    "description_id": "特徴量を計算したDescription ID。",
    "pearson_r": "特徴量とEndpointの線形相関係数。絶対値が1に近いほど強い。",
    "spearman_r": "特徴量とEndpointの順位相関係数。絶対値が1に近いほど強い。",
    "max_abs_correlation": "Pearson rとSpearman rの絶対値の大きい方。",
    "correlation_gain": "Localの最大|r|からGlobalの最大|r|を引いた差。",
    "member_count": "analysis unitに所属する全化合物数。",
    "model_count": "EndpointとDescriptionが揃い、モデル評価に使用できた化合物数。",
    "status": "Operatorの実行状態。",
    "oof_r2": "Localモデルのout-of-fold R²。大きいほど未学習化合物への予測説明力が高い。",
    "global_oof_on_same_series_r2": "同じ化合物に対するGlobalモデルのout-of-fold R²。",
    "local_minus_global_r2": "Local OOF R² − Global OOF R²。正で大きいほどLocalモデルに利点がある。",
    "oof_mae": "Localモデルのout-of-fold平均絶対誤差。小さいほど良い。",
    "global_minus_local_mae": "Global OOF MAE − Local OOF MAE。正ならLocalモデルの誤差が小さい。",
    "report_status": "定義済み数値基準の通過状況。",
    "reason": "未実施、適用外、失敗などの理由。",
    "median_sali": "unit内部のSALI中央値。大きいほど、類似構造間でEndpointが変化しやすい。単独では合否判定に使わない。",
    "p95_sali": "unit内部SALIの95パーセンタイル。局所的に強いactivity cliffの大きさを示す補助指標。",
    "internal_cliff_count": "unit内の2化合物が、ECFP4 Tanimoto similarity ≥ 0.75かつabsolute Endpoint差 ≥ 1.0 × Global Endpoint IQRを満たしたpair数。",
    "boundary_cliff_count": "unit内化合物とunit外化合物のpairが、ECFP4 Tanimoto similarity ≥ 0.75かつabsolute Endpoint差 ≥ 1.0 × Global Endpoint IQRを満たした件数。",
    "boundary_favorable_direction": "Boundary cliffのうちunit側化合物がFavorableだった件数／Boundary cliff全件数。",
    "method": "Key structureの取得方法。",
    "structure": "Key structureのSMILESまたはSMARTS。",
    "support_count": "Key structureを支持する化合物数。",
    "source_member_count": "対象analysis unitの化合物数。",
    "mcs_canceled": "MCS探索がtimeoutで中断されたか。",
    "capability_id": "実行したCapability ID。",
    "node_status": "Runtime上のNode状態。",
    "duration_seconds": "Node実行時間（秒）。",
    "evaluated_units": "評価したanalysis unit数。",
    "result_rows": "主結果Tableの行数。",
    "succeeded_units": "成功したanalysis unit数。",
    "not_applicable_units": "入力数不足などで適用外となったanalysis unit数。",
    "failed_units": "失敗したanalysis unit数。",
}

STRICT_CRITERIA = {
    "A003": "|Pearson r|または|Spearman r| ≥ 0.60、Globalとの差 ≥ 0.20、かつ相関のBH q ≤ 0.05",
    "A005": "local OOF R² ≥ 0.20、Global同一化合物OOFとの差 ≥ 0.20、かつlocal OOF MAEがGlobal以下",
    "A006": "ECFP4 Tanimoto similarity ≥ 0.75、absolute Endpoint差 ≥ 1.0 × Global Endpoint IQRのboundary pairが3件以上、かつunit側Favorable割合 ≥ 0.80",
}

OPERATOR_EXPLANATIONS = {
    "A003": (
        "各analysis unit内で、解釈可能なD001、D012、D015、D016、D019特徴量とEndpointの相関が"
        "Globalより明瞭になる特徴量を調べます。"
    ),
    "A005": (
        "複数Descriptionを用いたLocalモデルが、同じ化合物を評価したGlobalモデル"
        "よりEndpointをよく予測できるかをout-of-foldで比較します。"
        "LocalとGlobalは同じ候補群（D001、D002、D006、D013、D016、D019）から開始しますが、"
        "欠損・定数列の除外とfeature selectionは各analysis unit・各outer CV foldのtraining dataだけで行うため、"
        "実際に採用される特徴量は異なる場合があります。各foldではunivariate F-test上位最大24特徴量をRidge回帰へ使用します。"
        "基準未達を含め、各analysis unitの最良結果を1件ずつ掲載します。"
    ),
    "A006": (
        "当該analysis unitが活性enrichmentの境界になっているかを簡易判別します。"
        "unit内とunit外の化合物を一つずつ組にし、D002のECFP4"
        "（Morgan radius 2、2048 bit）で構造類似性を評価します。Tanimoto similarity ≥ 0.75にもかかわらず、"
        "absolute Endpoint差が1.0 × Global Endpoint IQR以上ある"
        "boundary pairを探します。各pairでunit内化合物のEndpointが相手よりFavorableである"
        "向きを数え、3 pair以上かつ80%以上が同じFavorable方向なら基準通過です。"
        "これはunit全体の優位を証明するものではなく、構造的に近いunit外化合物との局所比較で、"
        "unit側へのFavorableなactivity cliffが境界上に反復していることを示します。"
        "基準未達もunitの有用性を否定するものではありません。"
    ),
}

STRUCTURAL_CLUSTERING_IDS = {"C001", "C002", "C003", "C004"}
VECTOR_CLUSTERING_IDS = {"C005", "C006", "C007", "C008", "C009", "C010"}
A003_DESCRIPTION_PANEL = ("D001", "D012", "D015", "D016", "D019")
A003_MORDRED_2D_FEATURES = {
    "nAcid", "nBase", "nAromAtom", "nAromBond", "RotRatio", "apol", "bpol",
    "nB", "nC", "nN", "nO", "nS", "nP", "nF", "nCl", "nBr", "nI", "nX",
    "nRing", "nHRing", "nARing", "nFRing", "nFHRing", "nFARing",
    *(f"n{size}Ring" for size in range(3, 13)),
}
A003_MORDRED_3D_FEATURES = {
    "GeomDiameter", "GeomRadius", "GeomShapeIndex", "GeomPetitjeanIndex",
    "PNSA1", "PPSA1", "DPSA1", "TASA", "TPSA", "RASA", "RPSA", "RNCS", "RPCS",
}
CLUSTERING_DISPLAY_NAMES = {
    "C001": "Murcko scaffold", "C002": "MCS",
    "C003": "BRICS", "C004": "RECAP", "C005": "Vector Butina",
    "C006": "Vector hierarchical", "C007": "Vector DBSCAN",
    "C008": "Vector Louvain", "C009": "Vector Leiden",
    "C010": "Vector connected components", "C012": "Series Leiden",
}


def render_report_template(name: str, values: dict[str, Any]) -> str:
    path = Path(__file__).resolve().parents[1] / "templates" / name
    if not path.is_file():
        raise FileNotFoundError(f"A009 report template is missing: {path}")
    return Template(path.read_text(encoding="utf-8")).substitute(
        {key: str(value) for key, value in values.items()}
    )


def report_value(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict, tuple, set)) and pd.isna(value)):
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "yes" if bool(value) else "no"
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        if numeric != 0 and abs(numeric) < .001:
            return f"{numeric:.3e}"
        return f"{numeric:.4g}"
    return str(value)


def compact_table(
    frame: pd.DataFrame, table_kind: str, limit: int = 200, *,
    collapsed: bool = True, include_column_help: bool = True,
) -> str:
    if (
        table_kind == "A006"
        and "boundary_favorable_direction" not in frame.columns
        and "boundary_cliff_count" in frame.columns
    ):
        frame = frame.copy()
        denominator = pd.to_numeric(
            frame["boundary_cliff_count"], errors="coerce"
        ).fillna(0).round().astype(int)
        if "boundary_favorable_count" in frame.columns:
            numerator = pd.to_numeric(
                frame["boundary_favorable_count"], errors="coerce"
            ).fillna(0).round().astype(int)
        else:
            fraction = pd.to_numeric(
                frame.get(
                    "boundary_favorable_direction_fraction",
                    pd.Series(np.nan, index=frame.index),
                ),
                errors="coerce",
            ).fillna(0)
            numerator = (fraction * denominator).round().astype(int)
        frame["boundary_favorable_direction"] = [
            f"{favorable} / {total}"
            for favorable, total in zip(numerator, denominator)
        ]
    columns = [column for column in REPORT_TABLE_COLUMNS[table_kind] if column in frame.columns]
    if not columns:
        return frame_html(pd.DataFrame(), limit)
    view = frame.loc[:, columns].copy()
    for column in view.columns:
        labels = REPORT_VALUE_LABELS.get(column, {})
        view[column] = view[column].map(
            lambda value: labels.get(str(value), report_value(value))
        )
    view = view.rename(columns=REPORT_COLUMN_LABELS)
    table = frame_html(view, limit)
    help_items = "".join(
        f"<dt>{html_lib.escape(REPORT_COLUMN_LABELS.get(column, column))}</dt>"
        f"<dd>{html_lib.escape(REPORT_COLUMN_HELP.get(column, '補助出力列。'))}</dd>"
        for column in columns
    )
    help_panel = (
        "<details class='column-help'><summary>列の説明</summary>"
        f"<dl>{help_items}</dl></details>"
    ) if include_column_help else ""
    if not collapsed:
        return table + help_panel
    title = REPORT_TABLE_TITLES.get(table_kind, "結果Table")
    visible_count = min(len(view), limit)
    return (
        "<details class='report-table'><summary>"
        f"{html_lib.escape(title)}を表示（{visible_count}件）</summary>"
        f"{table}{help_panel}</details>"
    )


def metric_grid(items: list[tuple[str, Any]]) -> str:
    cards = "".join(
        f"<div class='metric'><span class='muted'>{html_lib.escape(label)}</span>"
        f"<b>{html_lib.escape(report_value(value))}</b></div>"
        for label, value in items
    )
    return f"<div class='metric-grid'>{cards}</div>"


def metric_help(items: list[tuple[str, str]]) -> str:
    definitions = "".join(
        f"<dt>{html_lib.escape(label)}</dt>"
        f"<dd>{html_lib.escape(description)}</dd>"
        for label, description in items
    )
    return (
        "<details class='column-help'><summary>Summary itemの説明</summary>"
        f"<dl>{definitions}</dl></details>"
    )


def bullet_list(items: list[str], *, css_class: str = "") -> str:
    class_attribute = f" class='{html_lib.escape(css_class)}'" if css_class else ""
    content = "".join(f"<li>{html_lib.escape(item)}</li>" for item in items)
    return f"<ul{class_attribute}>{content or '<li>該当なし</li>'}</ul>"


def endpoint_distribution_statistics(
    values: pd.Series, higher_is_better: bool,
) -> dict[str, float]:
    """Return direction-aware statistics shown inside the Endpoint figure."""
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {
            "mean": math.nan,
            "median": math.nan,
            "q20": math.nan,
            "q80": math.nan,
            "favorable_top20_cutoff": math.nan,
            "unfavorable_bottom20_cutoff": math.nan,
        }
    q20 = float(numeric.quantile(.2))
    q80 = float(numeric.quantile(.8))
    return {
        "mean": float(numeric.mean()),
        "median": float(numeric.median()),
        "q20": q20,
        "q80": q80,
        "favorable_top20_cutoff": q80 if higher_is_better else q20,
        "unfavorable_bottom20_cutoff": q20 if higher_is_better else q80,
    }


def boolean_mask(values: pd.Series, label: str) -> pd.Series:
    """Parse a serialized Boolean column without treating 'False' as truthy."""
    normalized = values.astype("string").str.strip().str.lower()
    true_values = {"true", "1", "1.0", "yes"}
    false_values = {"false", "0", "0.0", "no", ""}
    invalid = normalized.notna() & ~normalized.isin(true_values | false_values)
    if invalid.any():
        examples = sorted(set(normalized.loc[invalid].astype(str)))[:10]
        raise ValueError(f"{label} contains invalid Boolean values: {examples}")
    return normalized.isin(true_values)


def registry_join(result: pd.DataFrame, request: dict[str, Any]) -> pd.DataFrame:
    path = input_path(request, "cluster_registry", required=False)
    if path is None or result.empty:
        return result
    registry = read_table(path, ["cluster_id", "source_cluster_id", "source_node_id"])
    if "cluster_id" not in registry.columns:
        return result
    registry["cluster_id"] = registry["cluster_id"].astype(str)
    result["cluster_id"] = result["cluster_id"].astype(str)
    extra = [column for column in registry.columns if column == "cluster_id" or column not in result.columns]
    return result.merge(registry[extra], on="cluster_id", how="left")


def cluster_statistics(request: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, cid, _, endpoint = dataset(request)
    membership = input_path(request, "clustering") or input_path(request, "cluster_membership_matrix")
    _, groups = membership_sets(membership)
    higher = bool(request.get("endpoint", {}).get("higher_is_better"))
    parameters = request.get("parameters", {})
    high_quantile = float(parameters.get("high_quantile", .8))
    threshold, favorable = favorable_definition(frame, endpoint, higher, high_quantile)
    valid_values = frame[endpoint].dropna(); low_quantile = float(parameters.get("low_quantile", .2))
    unfavorable_threshold = float(valid_values.quantile(low_quantile if higher else 1.0-low_quantile))
    unfavorable = frame[endpoint].le(unfavorable_threshold) if higher else frame[endpoint].ge(unfavorable_threshold)
    values = frame.set_index(cid)[endpoint]
    fav = pd.Series(favorable.to_numpy(), index=frame[cid])
    global_valid = values.dropna()
    rows: list[dict[str, Any]] = []
    for cluster_id, member_ids in sorted(groups.items()):
        selected = values.reindex(sorted(member_ids)).dropna()
        favorable_count = int(fav.reindex(selected.index).fillna(False).sum()); unfavorable_count = int(pd.Series(unfavorable.to_numpy(),index=frame[cid]).reindex(selected.index).fillna(False).sum())
        rows.append({
            "cluster_id": cluster_id, "sample_count": int(len(selected)),
            "favorable_count": favorable_count,
            "favorable_fraction": favorable_count / len(selected) if len(selected) else np.nan,
            "unfavorable_count": unfavorable_count,
            "unfavorable_fraction": unfavorable_count / len(selected) if len(selected) else np.nan,
            "endpoint_mean": float(selected.mean()) if len(selected) else np.nan,
            "endpoint_median": float(selected.median()) if len(selected) else np.nan,
            "endpoint_std": float(selected.std(ddof=1)) if len(selected) > 1 else np.nan,
            "endpoint_iqr": float(selected.quantile(.75) - selected.quantile(.25)) if len(selected) else np.nan,
            "endpoint_min": float(selected.min()) if len(selected) else np.nan,
            "endpoint_max": float(selected.max()) if len(selected) else np.nan,
        })
    profile_columns = [
        "cluster_id", "sample_count", "favorable_count", "favorable_fraction",
        "unfavorable_count", "unfavorable_fraction", "endpoint_mean",
        "endpoint_median", "endpoint_std", "endpoint_iqr", "endpoint_min",
        "endpoint_max",
    ]
    # A Run with no registered Cluster is a valid scientific Negative Result.
    # Preserve a readable header-only contract so A002, C012, reporting, and
    # Interpretation can still finish without inventing any Cluster.
    result = registry_join(pd.DataFrame(rows, columns=profile_columns), request)
    min_n = int(parameters.get("min_ff_evaluate", 10)); min_ff = float(parameters.get("favorable_fraction_threshold", .5))
    if not result.empty:
        result["ff_evaluation_eligible"] = result["sample_count"].ge(min_n)
        result["selected_for_series"] = result["ff_evaluation_eligible"] & result["favorable_fraction"].ge(min_ff)
        # Human-facing FF rank applies only to Clusters that satisfy the explicit
        # min_ff_evaluate contract. Smaller Clusters remain in the full table for
        # traceability, but must not outrank statistically usable candidates.
        result = result.sort_values(["ff_evaluation_eligible", "favorable_fraction", "sample_count", "cluster_id"], ascending=[False, False, False, True]).reset_index(drop=True)
        result["ff_rank"] = np.nan
        eligible = boolean_mask(result["ff_evaluation_eligible"], "ff_evaluation_eligible")
        result.loc[eligible, "ff_rank"] = np.arange(1, int(eligible.sum()) + 1)
    else:
        result["ff_evaluation_eligible"] = pd.Series(dtype=bool)
        result["selected_for_series"] = pd.Series(dtype=bool)
        result["ff_rank"] = pd.Series(dtype=float)
    summary = {
        "cluster_count": len(result), "selected_cluster_count": int(result.get("selected_for_series", pd.Series(dtype=bool)).sum()),
        "global_sample_count": int(global_valid.size), "global_favorable_fraction": float(favorable[frame[endpoint].notna()].mean()),
        "favorable_threshold": threshold, "favorable_comparator": ">=" if higher else "<=", "unfavorable_threshold": unfavorable_threshold, "unfavorable_comparator": "<=" if higher else ">=",
        "favorable_quantile": high_quantile if higher else 1.0-high_quantile, "theoretical_favorable_fraction": 1.0-high_quantile,
        "min_ff_evaluate": min_n, "favorable_fraction_threshold": min_ff,
    }
    return result, summary


def run_a001(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    result, summary = cluster_statistics(request)
    primary = output / "A001_cluster_profile.csv"; result.to_csv(primary, index=False)
    selected = result.loc[result.get("selected_for_series", False)].copy() if not result.empty else result
    selected_path = output / "selected_clusters.csv"; selected.to_csv(selected_path, index=False)
    body = f"<h1>全Cluster Endpoint profile</h1><div class='card'><p>Global favorable fraction: <b>{summary['global_favorable_fraction']:.3f}</b> / selected: <b>{summary['selected_cluster_count']}</b></p></div><div class='card'><h2>FF順位</h2>{frame_html(result, 300)}</div>"
    report = output / "operator_report.html"; report.write_text(html_page("A001 Cluster profile", body), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary=summary, report=report, extra_artifacts=[selected_path])


def fisher_enrichment(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    from scipy.stats import fisher_exact
    odds, pvalue = fisher_exact([[a, b], [c, d]], alternative="greater")
    return float(odds), float(pvalue)


def run_a002(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from scipy.stats import mannwhitneyu
    profile, summary = cluster_statistics(request)
    frame, cid, _, endpoint = dataset(request)
    higher = bool(request.get("endpoint", {}).get("higher_is_better"))
    threshold, favorable = favorable_definition(frame, endpoint, higher, float(request.get("parameters", {}).get("high_quantile", .8)))
    membership = input_path(request, "clustering") or input_path(request, "cluster_membership_matrix")
    _, groups = membership_sets(membership)
    valid_ids = set(frame.loc[frame[endpoint].notna(), cid].astype(str)); favorable_ids = set(frame.loc[favorable & frame[endpoint].notna(), cid].astype(str))
    endpoint_values=frame.set_index(cid)[endpoint]; global_median=float(endpoint_values.dropna().median()); stats: list[dict[str, Any]] = []
    for cluster_id, members in groups.items():
        inside = members & valid_ids; outside = valid_ids - inside
        a = len(inside & favorable_ids); b = len(inside - favorable_ids); c = len(outside & favorable_ids); d = len(outside - favorable_ids)
        odds, pvalue = fisher_enrichment(a, b, c, d); inside_values=endpoint_values.reindex(sorted(inside)).dropna(); outside_values=endpoint_values.reindex(sorted(outside)).dropna()
        mw=float(mannwhitneyu(inside_values,outside_values,alternative="two-sided").pvalue) if len(inside_values)>=3 and len(outside_values)>=3 and pd.concat([inside_values,outside_values]).nunique()>1 else np.nan
        stats.append({"cluster_id": cluster_id, "odds_ratio": odds, "fisher_pvalue": pvalue, "mann_whitney_pvalue": mw, "median_difference_from_global": float(inside_values.median()-global_median) if len(inside_values) else np.nan})
    enrichment = pd.DataFrame(stats)
    if not enrichment.empty:
        enrichment["q_value_bh"] = bh_qvalues(enrichment["fisher_pvalue"])
        enrichment["mann_whitney_q_bh"] = bh_qvalues(enrichment["mann_whitney_pvalue"])
        result = profile.merge(enrichment, on="cluster_id", how="left")
    else:
        result = profile.assign(odds_ratio=np.nan, fisher_pvalue=np.nan, q_value_bh=np.nan, mann_whitney_pvalue=np.nan, mann_whitney_q_bh=np.nan, median_difference_from_global=np.nan)
    result = result.sort_values(["selected_for_series", "favorable_fraction", "q_value_bh"], ascending=[False, False, True]) if not result.empty else result
    primary = output / "A002_cluster_enrichment.csv"; result.to_csv(primary, index=False)
    summary.update({"favorable_threshold": threshold, "q_value_role": "auxiliary; not a selection gate"})
    report = output / "operator_report.html"; report.write_text(html_page("A002 Cluster enrichment", f"<h1>全Cluster enrichment</h1><div class='card'>{frame_html(result, 300)}</div>"), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary=summary, report=report)


def leiden_membership(vertex_count: int, edges: list[tuple[int, int]], weights: list[float], resolution: float, seed: int) -> list[int]:
    if vertex_count == 0:
        return []
    if not edges:
        return list(range(vertex_count))
    try:
        import igraph as ig
        import leidenalg
        graph = ig.Graph(n=vertex_count, edges=edges, directed=False)
        partition = leidenalg.find_partition(
            graph, leidenalg.RBConfigurationVertexPartition, weights=weights,
            resolution_parameter=resolution, seed=seed,
        )
        return list(partition.membership)
    except ImportError as exc:
        raise RuntimeError("weighted Leiden requires python-igraph and leidenalg in this Skill environment") from exc


def evaluate_series_configuration(
    *,
    cluster_sets: dict[str, set[str]],
    enrichment: pd.DataFrame,
    frame: pd.DataFrame,
    compound_id_column: str,
    endpoint_column: str,
    higher_is_better: bool,
    min_ff_evaluate: int,
    resolution: float,
    random_seed: int,
    cluster_ff_threshold: float,
    multi_cluster_ff_threshold: float,
) -> dict[str, Any]:
    """Evaluate one C012 condition without writing artifacts."""
    selection = enrichment.copy()
    counts = pd.to_numeric(selection["sample_count"], errors="coerce")
    fractions = pd.to_numeric(selection["favorable_fraction"], errors="coerce")
    selected = selection.loc[
        counts.ge(min_ff_evaluate) & fractions.ge(cluster_ff_threshold)
    ].copy()
    selected_ids = sorted(selected["cluster_id"].astype(str))
    selected_ff = dict(zip(
        selected["cluster_id"].astype(str),
        pd.to_numeric(selected["favorable_fraction"], errors="coerce"),
    ))
    edges: list[tuple[int, int]] = []
    weights: list[float] = []
    edge_rows: list[dict[str, Any]] = []
    for left_index, left_id in enumerate(selected_ids):
        left = cluster_sets[left_id]
        for right_index in range(left_index + 1, len(selected_ids)):
            right_id = selected_ids[right_index]
            right = cluster_sets[right_id]
            overlap = len(left & right)
            if overlap == 0:
                continue
            union_count = len(left | right)
            weight = overlap / union_count if union_count else 0.0
            edges.append((left_index, right_index))
            weights.append(weight)
            edge_rows.append({
                "cluster_id_a": left_id,
                "cluster_id_b": right_id,
                "overlap_count": overlap,
                "jaccard_weight": weight,
                "containment_a_in_b": overlap / len(left) if left else 0.0,
                "containment_b_in_a": overlap / len(right) if right else 0.0,
                "overlap_coefficient": (
                    overlap / min(len(left), len(right)) if left and right else 0.0
                ),
            })
    assignments = leiden_membership(
        len(selected_ids), edges, weights, resolution, random_seed
    )
    communities: dict[int, list[str]] = {}
    for cluster_id, community in zip(selected_ids, assignments):
        communities.setdefault(community, []).append(cluster_id)
    ordered_communities = [
        sorted(source_clusters)
        for _, source_clusters in sorted(
            communities.items(), key=lambda item: min(item[1])
        )
    ]
    threshold, favorable = favorable_definition(
        frame, endpoint_column, higher_is_better
    )
    valid_map = dict(zip(frame[compound_id_column], frame[endpoint_column].notna()))
    favorable_map = dict(zip(frame[compound_id_column], favorable))
    global_valid = frame[endpoint_column].notna()
    global_ff = float(favorable.loc[global_valid].mean())
    series_rows: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    accepted_members: dict[str, set[str]] = {}
    rejected_source_clusters: list[tuple[str, str]] = []
    for serial, source_clusters in enumerate(ordered_communities, 1):
        series_id = f"S{serial:06d}"
        union = set().union(*(cluster_sets[item] for item in source_clusters))
        valid = {item for item in union if valid_map.get(item, False)}
        favorable_count = sum(
            bool(favorable_map.get(item, False)) for item in valid
        )
        favorable_fraction = favorable_count / len(valid) if valid else 0.0
        source_values = [
            float(selected_ff[item]) for item in source_clusters
            if np.isfinite(selected_ff.get(item, np.nan))
        ]
        source_min = min(source_values) if source_values else np.nan
        source_mean = float(np.mean(source_values)) if source_values else np.nan
        source_max = max(source_values) if source_values else np.nan
        applied_threshold = (
            multi_cluster_ff_threshold
            if len(source_clusters) >= 2 else cluster_ff_threshold
        )
        accepted = favorable_fraction >= applied_threshold
        final_units: list[str] = []
        if accepted:
            accepted_members[series_id] = union
            final_units = [series_id]
            for cluster_id in source_clusters:
                cluster_rows.append({
                    "series_id": series_id,
                    "candidate_series_id": series_id,
                    "cluster_id": cluster_id,
                })
            for compound_id in sorted(union):
                support_count = sum(
                    compound_id in cluster_sets[item] for item in source_clusters
                )
                support_rows.append({
                    "series_id": series_id,
                    "compound_id": compound_id,
                    "support_count": support_count,
                    "support_fraction": support_count / len(source_clusters),
                })
        else:
            for cluster_id in source_clusters:
                fallback_id = f"CLU_{cluster_id}"
                final_units.append(fallback_id)
                rejected_source_clusters.append((series_id, cluster_id))
        series_rows.append({
            "series_id": series_id,
            "source_cluster_count": len(source_clusters),
            "source_cluster_ids": "|".join(source_clusters),
            "compound_count": len(union),
            "endpoint_valid_count": len(valid),
            "favorable_count": favorable_count,
            "favorable_fraction": favorable_fraction,
            "global_favorable_fraction": global_ff,
            "ff_delta_from_global": favorable_fraction - global_ff,
            "ff_enrichment_ratio": (
                favorable_fraction / global_ff if global_ff > 0 else np.nan
            ),
            "source_cluster_min_ff": source_min,
            "source_cluster_mean_ff": source_mean,
            "source_cluster_max_ff": source_max,
            "union_ff_delta_from_source_mean": (
                favorable_fraction - source_mean
                if np.isfinite(source_mean) else np.nan
            ),
            "applied_ff_threshold": applied_threshold,
            "acceptance_basis": (
                "multi_cluster_relaxed_0.40"
                if len(source_clusters) >= 2 and applied_threshold < cluster_ff_threshold
                else "standard_0.50"
            ),
            "accepted": accepted,
            "final_analysis_units": "|".join(final_units),
            "fallback_reason": "" if accepted else "series_ff_below_applied_threshold",
        })
    for candidate_series_id, cluster_id in sorted(set(rejected_source_clusters)):
        fallback_id = f"CLU_{cluster_id}"
        accepted_members[fallback_id] = cluster_sets[cluster_id]
        cluster_rows.append({
            "series_id": fallback_id,
            "candidate_series_id": candidate_series_id,
            "cluster_id": cluster_id,
        })
        support_rows.extend({
            "series_id": fallback_id,
            "compound_id": compound_id,
            "support_count": 1,
            "support_fraction": 1.0,
        } for compound_id in sorted(cluster_sets[cluster_id]))
    unit_rows = [{
        "analysis_unit_id": "GLOBAL",
        "scope_kind": "global",
        "compound_count": int(len(frame)),
        "endpoint_valid_count": int(global_valid.sum()),
        "favorable_fraction": global_ff,
        "source_cluster_count": 0,
    }]
    membership_rows = [{
        "compound_id": value,
        "analysis_unit_id": "GLOBAL",
        "membership_value": True,
    } for value in frame[compound_id_column]]
    for unit_id, members in accepted_members.items():
        valid = {item for item in members if valid_map.get(item, False)}
        favorable_fraction = (
            sum(bool(favorable_map.get(item, False)) for item in valid) / len(valid)
            if valid else 0.0
        )
        is_fallback = unit_id.startswith("CLU_")
        unit_rows.append({
            "analysis_unit_id": unit_id,
            "scope_kind": "cluster" if is_fallback else "series",
            "fallback_reason": (
                "series_ff_below_applied_threshold" if is_fallback else ""
            ),
            "compound_count": len(members),
            "endpoint_valid_count": len(valid),
            "favorable_fraction": favorable_fraction,
            "source_cluster_count": (
                1 if is_fallback
                else sum(row["series_id"] == unit_id for row in cluster_rows)
            ),
        })
        membership_rows.extend({
            "compound_id": value,
            "analysis_unit_id": unit_id,
            "membership_value": True,
        } for value in sorted(members))
    ff_deltas = [
        float(row["union_ff_delta_from_source_mean"])
        for row in series_rows
        if np.isfinite(row["union_ff_delta_from_source_mean"])
    ]
    accepted_ff = [
        float(row["favorable_fraction"])
        for row in series_rows if row["accepted"]
    ]
    return {
        "selected": selected,
        "selected_ids": selected_ids,
        "edge_rows": edge_rows,
        "series_rows": series_rows,
        "cluster_rows": cluster_rows,
        "support_rows": support_rows,
        "unit_rows": unit_rows,
        "membership_rows": membership_rows,
        "accepted_members": accepted_members,
        "summary": {
            "min_ff_evaluate": min_ff_evaluate,
            "leiden_resolution": resolution,
            "selected_cluster_count": len(selected_ids),
            "candidate_series_count": len(series_rows),
            "accepted_series_count": sum(row["accepted"] for row in series_rows),
            "relaxed_series_count": sum(
                row["accepted"] and row["acceptance_basis"] == "multi_cluster_relaxed_0.40"
                and row["favorable_fraction"] < cluster_ff_threshold
                for row in series_rows
            ),
            "rejected_series_count": sum(not row["accepted"] for row in series_rows),
            "fallback_cluster_count": sum(
                unit_id.startswith("CLU_") for unit_id in accepted_members
            ),
            "analysis_unit_count": len(accepted_members),
            "median_series_ff": float(np.median(accepted_ff)) if accepted_ff else None,
            "series_with_ff_decrease_count": sum(value < 0 for value in ff_deltas),
            "median_union_ff_delta_from_source_mean": (
                float(np.median(ff_deltas)) if ff_deltas else None
            ),
            "edge_count": len(edge_rows),
            "favorable_threshold": threshold,
            "cluster_ff_threshold": cluster_ff_threshold,
            "multi_cluster_ff_threshold": multi_cluster_ff_threshold,
            "global_favorable_fraction": global_ff,
        },
    }


def _run_c012_legacy(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    _, cluster_sets = membership_sets(input_path(request, "cluster_membership_matrix"))
    profile = read_table(input_path(request, "cluster_profile"), ["cluster_id"]); enrichment = read_table(input_path(request, "cluster_enrichment"), ["cluster_id"])
    registry = read_table(input_path(request, "cluster_registry"), ["cluster_id", "source_cluster_id", "source_node_id"])
    required_profile = {"cluster_id", "sample_count", "favorable_fraction", "selected_for_series"}
    for label, table in (("cluster_profile", profile), ("cluster_enrichment", enrichment)):
        missing = sorted(required_profile - set(table.columns))
        if missing:
            raise ValueError(f"C012 input {label} is missing required columns: {missing}")
        if table["cluster_id"].isna().any() or table["cluster_id"].astype(str).duplicated().any():
            raise ValueError(f"C012 input {label} has null or duplicate cluster_id values")
        counts = pd.to_numeric(table["sample_count"], errors="coerce")
        fractions = pd.to_numeric(table["favorable_fraction"], errors="coerce")
        if counts.isna().any() or counts.lt(0).any() or fractions.isna().any() or not bool(fractions.between(0, 1).all()):
            raise ValueError(f"C012 input {label} has invalid sample_count or favorable_fraction values")
        boolean_mask(table["selected_for_series"], f"{label}.selected_for_series")
    if not {"cluster_id", "sample_count"}.issubset(registry.columns) or registry["cluster_id"].isna().any() or registry["cluster_id"].astype(str).duplicated().any():
        raise ValueError("C012 cluster_registry requires unique, non-null cluster_id and sample_count values")
    profile_ids = set(profile["cluster_id"].astype(str))
    enrichment_ids = set(enrichment["cluster_id"].astype(str))
    registry_ids = set(registry["cluster_id"].astype(str))
    membership_ids = set(cluster_sets)
    if not (profile_ids == enrichment_ids == registry_ids == membership_ids):
        raise ValueError(
            "C012 Cluster inputs disagree. "
            f"profile_only={sorted(profile_ids - enrichment_ids)[:10]}, "
            f"enrichment_only={sorted(enrichment_ids - profile_ids)[:10]}, "
            f"registry_vs_membership={sorted(registry_ids ^ membership_ids)[:10]}"
        )
    registry_indexed = registry.copy()
    registry_indexed["cluster_id"] = registry_indexed["cluster_id"].astype(str)
    registry_counts = pd.to_numeric(registry_indexed.set_index("cluster_id")["sample_count"], errors="coerce")
    invalid_registry_counts = {
        cluster_id: {"registry": registry_counts.get(cluster_id), "membership": len(cluster_sets[cluster_id])}
        for cluster_id in sorted(membership_ids)
        if pd.isna(registry_counts.get(cluster_id))
        or float(registry_counts.get(cluster_id)) != float(len(cluster_sets[cluster_id]))
    }
    if invalid_registry_counts:
        raise ValueError(f"C012 cluster_registry sample_count disagrees with membership: {dict(list(invalid_registry_counts.items())[:10])}")
    consistency = profile[["cluster_id", "sample_count", "favorable_fraction", "selected_for_series"]].merge(
        enrichment[["cluster_id", "sample_count", "favorable_fraction", "selected_for_series"]],
        on="cluster_id", suffixes=("_profile", "_enrichment"), validate="one_to_one",
    )
    numeric_consistent = np.isclose(
        pd.to_numeric(consistency["sample_count_profile"], errors="coerce"),
        pd.to_numeric(consistency["sample_count_enrichment"], errors="coerce"),
        equal_nan=True,
    ) & np.isclose(
        pd.to_numeric(consistency["favorable_fraction_profile"], errors="coerce"),
        pd.to_numeric(consistency["favorable_fraction_enrichment"], errors="coerce"),
        equal_nan=True,
    )
    selected_consistent = boolean_mask(consistency["selected_for_series_profile"], "selected_for_series_profile").eq(
        boolean_mask(consistency["selected_for_series_enrichment"], "selected_for_series_enrichment")
    )
    if not bool(np.all(numeric_consistent)) or not bool(selected_consistent.all()):
        raise ValueError("C012 A001 profile and A002 enrichment disagree on Cluster statistics or selection")
    parameters = request.get("parameters", {}); min_n = int(parameters.get("min_ff_evaluate", 10)); min_ff = float(parameters.get("favorable_fraction_threshold", .5))
    selection = enrichment.copy()
    if "selected_for_series" not in selection:
        selection["selected_for_series"] = selection["sample_count"].ge(min_n) & selection["favorable_fraction"].ge(min_ff)
    selected = selection.loc[boolean_mask(selection["selected_for_series"], "selected_for_series")].copy()
    selected_ids = [str(value) for value in selected["cluster_id"]]
    selected_ff = dict(zip(
        selected["cluster_id"].astype(str),
        pd.to_numeric(selected["favorable_fraction"], errors="coerce"),
    ))
    edges: list[tuple[int, int]] = []; weights: list[float] = []; edge_rows: list[dict[str, Any]] = []
    for i, left_id in enumerate(selected_ids):
        left = cluster_sets[left_id]
        for j in range(i + 1, len(selected_ids)):
            right_id = selected_ids[j]; right = cluster_sets[right_id]; overlap = len(left & right)
            if overlap == 0:
                continue
            union = len(left | right); weight = overlap / union if union else 0.0
            containment_left = overlap / len(left) if left else 0.0; containment_right = overlap / len(right) if right else 0.0
            edges.append((i, j)); weights.append(weight)
            edge_rows.append({"cluster_id_a": left_id, "cluster_id_b": right_id, "overlap_count": overlap, "jaccard_weight": weight, "containment_a_in_b": containment_left, "containment_b_in_a": containment_right, "overlap_coefficient": overlap / min(len(left),len(right)) if left and right else 0.0})
    assignments = leiden_membership(len(selected_ids), edges, weights, float(parameters.get("leiden_resolution", 1.0)), int(parameters.get("random_seed", 61453)))
    communities: dict[int, list[str]] = {}
    for cluster_id, community in zip(selected_ids, assignments): communities.setdefault(community, []).append(cluster_id)
    frame, cid, _, endpoint = dataset(request); higher = bool(request.get("endpoint", {}).get("higher_is_better")); threshold, favorable = favorable_definition(frame, endpoint, higher)
    valid_map = dict(zip(frame[cid], frame[endpoint].notna())); fav_map = dict(zip(frame[cid], favorable))
    series_rows: list[dict[str, Any]] = []; cluster_rows: list[dict[str, Any]] = []; support_rows: list[dict[str, Any]] = []
    accepted_members: dict[str, set[str]] = {}
    rejected_source_clusters: list[tuple[str, str]] = []
    rejected_series = 0
    for serial, (_, source_clusters) in enumerate(sorted(communities.items(), key=lambda item: min(item[1])), 1):
        series_id = f"S{serial:06d}"; union = set().union(*(cluster_sets[item] for item in source_clusters))
        valid = {item for item in union if valid_map.get(item, False)}; fav_count = sum(bool(fav_map.get(item, False)) for item in valid); ff = fav_count / len(valid) if valid else 0.0
        source_ff_values = [
            float(selected_ff[item])
            for item in source_clusters if np.isfinite(selected_ff.get(item, np.nan))
        ]
        source_ff_min = min(source_ff_values) if source_ff_values else np.nan
        source_ff_mean = float(np.mean(source_ff_values)) if source_ff_values else np.nan
        source_ff_max = max(source_ff_values) if source_ff_values else np.nan
        accepted = ff >= min_ff
        if accepted:
            accepted_members[series_id] = union
            for cluster_id in source_clusters:
                cluster_rows.append({"series_id": series_id, "candidate_series_id": series_id, "cluster_id": cluster_id})
            for compound_id in sorted(union):
                count = sum(compound_id in cluster_sets[item] for item in source_clusters)
                support_rows.append({"series_id": series_id, "compound_id": compound_id, "support_count": count, "support_fraction": count / len(source_clusters)})
        else:
            rejected_series += 1
            rejected_source_clusters.extend((series_id, cluster_id) for cluster_id in source_clusters)
        series_rows.append({
            "series_id": series_id,
            "source_cluster_count": len(source_clusters),
            "compound_count": len(union),
            "endpoint_valid_count": len(valid),
            "favorable_count": fav_count,
            "favorable_fraction": ff,
            "source_cluster_min_ff": source_ff_min,
            "source_cluster_mean_ff": source_ff_mean,
            "source_cluster_max_ff": source_ff_max,
            "union_ff_delta_from_source_mean": (
                ff - source_ff_mean if np.isfinite(source_ff_mean) else np.nan
            ),
            "accepted": accepted,
            "fallback_reason": "" if accepted else "series_ff_below_threshold",
        })
    accepted_series_count = len(accepted_members)
    # A Series whose union loses enrichment must not silently discard its enriched
    # source Clusters. Only rejected communities fall back to Cluster units.
    for candidate_series_id, cluster_id in sorted(set(rejected_source_clusters)):
        fallback_id = f"CLU_{cluster_id}"
        accepted_members[fallback_id] = cluster_sets[cluster_id]
        cluster_rows.append({"series_id": fallback_id, "candidate_series_id": candidate_series_id, "cluster_id": cluster_id})
        support_rows.extend({"series_id": fallback_id, "compound_id": compound_id, "support_count": 1, "support_fraction": 1.0} for compound_id in sorted(cluster_sets[cluster_id]))
    fallback = bool(rejected_source_clusters) or not communities
    if not communities:
        accepted_members = {f"CLU_{cluster_id}": cluster_sets[cluster_id] for cluster_id in selected_ids}
    unit_rows = [{
        "analysis_unit_id": "GLOBAL", "scope_kind": "global",
        "compound_count": int(len(frame)),
        "endpoint_valid_count": int(frame[endpoint].notna().sum()),
        "favorable_fraction": float(favorable[frame[endpoint].notna()].mean()),
        "source_cluster_count": 0,
    }]
    membership_rows = [{"compound_id": value, "analysis_unit_id": "GLOBAL", "membership_value": True} for value in frame[cid]]
    for unit_id, members in accepted_members.items():
        valid = {item for item in members if valid_map.get(item, False)}; ff = sum(bool(fav_map.get(item, False)) for item in valid) / len(valid) if valid else 0.0
        is_cluster_fallback = unit_id.startswith("CLU_")
        unit_rows.append({
            "analysis_unit_id": unit_id,
            "scope_kind": "cluster" if is_cluster_fallback else "series",
            "fallback_reason": "series_ff_below_threshold" if is_cluster_fallback else "",
            "compound_count": len(members),
            "endpoint_valid_count": len(valid),
            "favorable_fraction": ff,
            "source_cluster_count": 1 if is_cluster_fallback else sum(row["series_id"] == unit_id for row in cluster_rows),
        })
        membership_rows.extend({"compound_id": value, "analysis_unit_id": unit_id, "membership_value": True} for value in sorted(members))
    series_registry = pd.DataFrame(series_rows, columns=[
        "series_id", "source_cluster_count", "compound_count",
        "endpoint_valid_count", "favorable_count", "favorable_fraction",
        "source_cluster_min_ff", "source_cluster_mean_ff",
        "source_cluster_max_ff", "union_ff_delta_from_source_mean",
        "accepted", "fallback_reason",
    ])
    series_registry.to_csv(output / "series_registry.csv", index=False)
    pd.DataFrame(cluster_rows, columns=["series_id","candidate_series_id","cluster_id"]).to_csv(output / "series_cluster_membership.csv", index=False)
    pd.DataFrame(support_rows, columns=["series_id","compound_id","support_count","support_fraction"]).to_csv(output / "compound_series_support.csv", index=False)
    pd.DataFrame(membership_rows).to_csv(output / "analysis_unit_membership.csv", index=False)
    pd.DataFrame(unit_rows).to_csv(output / "analysis_unit_registry.csv", index=False)
    pd.DataFrame(edge_rows, columns=["cluster_id_a","cluster_id_b","overlap_count","jaccard_weight","containment_a_in_b","containment_b_in_a","overlap_coefficient"]).to_csv(output / "series_edges.csv", index=False)
    global_valid_count = int(frame[endpoint].notna().sum())
    oversized = [row["analysis_unit_id"] for row in unit_rows[1:] if global_valid_count and row["endpoint_valid_count"] / global_valid_count > .5]
    fallback_cluster_count = sum(
        unit_id.startswith("CLU_") for unit_id in accepted_members
    )
    ff_deltas = [
        float(row["union_ff_delta_from_source_mean"])
        for row in series_rows
        if np.isfinite(row["union_ff_delta_from_source_mean"])
    ]
    summary = {
        "selected_cluster_count": len(selected_ids),
        "series_count": len(communities),
        "accepted_series_count": accepted_series_count,
        "rejected_series_count": rejected_series,
        "fallback_cluster_count": fallback_cluster_count,
        "analysis_unit_count": len(accepted_members),
        "fallback_to_selected_clusters": fallback,
        "series_with_ff_decrease_count": sum(value < 0 for value in ff_deltas),
        "median_union_ff_delta_from_source_mean": (
            float(np.median(ff_deltas)) if ff_deltas else None
        ),
        "edge_count": len(edges),
        "edge_weight": "Jaccard",
        "favorable_threshold": threshold,
        "min_ff_evaluate": min_n,
        "favorable_fraction_threshold": min_ff,
        "global_endpoint_valid_count": global_valid_count,
        "analysis_units_over_50_percent_of_global": oversized,
    }
    write_json(output / "series_summary.json", summary)
    primary = output / "series_registry.csv"
    report = output / "clustering_report.html"
    report.write_text(html_page(
        "C012 Series",
        f"<h1>Enriched ClusterのSeries化</h1>"
        f"<div class='card'>{metric_grid([('Selected Clusters', len(selected_ids)), ('Candidate Series', len(communities)), ('Accepted Series', accepted_series_count), ('Rejected Series', rejected_series), ('Fallback Clusters', fallback_cluster_count), ('Analysis units', len(accepted_members))])}"
        f"<p class='muted'>Series FFはsource Clusterの和集合で再計算します。source平均FFより低下したSeries: {summary['series_with_ff_decrease_count']} / median差分: {report_value(summary['median_union_ff_delta_from_source_mean'])}</p></div>"
        f"<div class='card'><h2>Series FF diagnostics</h2>{compact_table(series_registry, 'series', max(1, len(series_registry)))}</div>"
        f"<div class='card'><h2>Analysis units</h2>{compact_table(pd.DataFrame(unit_rows), 'analysis_units', max(1, len(unit_rows)))}</div>",
    ), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary=summary, report=report, extra_artifacts=[output / "analysis_unit_membership.csv", output / "analysis_unit_registry.csv", output / "series_cluster_membership.csv", output / "compound_series_support.csv", output / "series_edges.csv", output / "series_summary.json"])


def run_c012(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    """Evaluate the approved C012 grid and materialize one chosen condition."""
    output.mkdir(parents=True, exist_ok=True)
    _, cluster_sets = membership_sets(input_path(request, "cluster_membership_matrix"))
    profile = read_table(input_path(request, "cluster_profile"), ["cluster_id"])
    enrichment = read_table(input_path(request, "cluster_enrichment"), ["cluster_id"])
    registry = read_table(
        input_path(request, "cluster_registry"),
        ["cluster_id", "source_cluster_id", "source_node_id"],
    )
    required = {"cluster_id", "sample_count", "favorable_fraction"}
    for label, table in (("cluster_profile", profile), ("cluster_enrichment", enrichment)):
        missing = sorted(required - set(table.columns))
        if missing:
            raise ValueError(f"C012 input {label} is missing required columns: {missing}")
        if table["cluster_id"].isna().any() or table["cluster_id"].astype(str).duplicated().any():
            raise ValueError(f"C012 input {label} has null or duplicate cluster_id values")
        counts = pd.to_numeric(table["sample_count"], errors="coerce")
        fractions = pd.to_numeric(table["favorable_fraction"], errors="coerce")
        if (
            counts.isna().any() or counts.lt(0).any()
            or fractions.isna().any() or not bool(fractions.between(0, 1).all())
        ):
            raise ValueError(f"C012 input {label} has invalid Cluster statistics")
    identity_sets = (
        set(profile["cluster_id"].astype(str)),
        set(enrichment["cluster_id"].astype(str)),
        set(registry["cluster_id"].astype(str)),
        set(cluster_sets),
    )
    if len({frozenset(value) for value in identity_sets}) != 1:
        raise ValueError("C012 Cluster inputs disagree on the registered Cluster IDs")
    registry_counts = pd.to_numeric(
        registry.assign(cluster_id=registry["cluster_id"].astype(str))
        .set_index("cluster_id")["sample_count"],
        errors="coerce",
    )
    invalid_counts = [
        cluster_id for cluster_id in sorted(cluster_sets)
        if pd.isna(registry_counts.get(cluster_id))
        or int(registry_counts.get(cluster_id)) != len(cluster_sets[cluster_id])
    ]
    if invalid_counts:
        raise ValueError(
            f"C012 registry counts disagree with membership: {invalid_counts[:10]}"
        )
    crosscheck = profile[["cluster_id", "sample_count", "favorable_fraction"]].merge(
        enrichment[["cluster_id", "sample_count", "favorable_fraction"]],
        on="cluster_id", suffixes=("_profile", "_enrichment"), validate="one_to_one",
    )
    if not bool(np.all(np.isclose(
        pd.to_numeric(crosscheck["sample_count_profile"], errors="coerce"),
        pd.to_numeric(crosscheck["sample_count_enrichment"], errors="coerce"),
        equal_nan=True,
    ))) or not bool(np.all(np.isclose(
        pd.to_numeric(crosscheck["favorable_fraction_profile"], errors="coerce"),
        pd.to_numeric(crosscheck["favorable_fraction_enrichment"], errors="coerce"),
        equal_nan=True,
    ))):
        raise ValueError("C012 A001 and A002 disagree on Cluster statistics")

    frame, compound_id_column, _, endpoint_column = dataset(request)
    higher_is_better = bool(request.get("endpoint", {}).get("higher_is_better"))
    parameters = request.get("parameters", {})
    cluster_ff_threshold = float(parameters.get("favorable_fraction_threshold", .5))
    multi_cluster_ff_threshold = float(
        parameters.get("multi_cluster_favorable_fraction_threshold", .4)
    )
    if not (0 <= multi_cluster_ff_threshold <= cluster_ff_threshold <= 1):
        raise ValueError(
            "C012 FF thresholds must satisfy 0 <= multi-cluster <= cluster <= 1"
        )
    seed = int(parameters.get("random_seed", 61453))
    resolution_grid = [
        float(value) for value in parameters.get(
            "resolution_grid", [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
        )
    ]
    min_n_grid = [
        int(value) for value in parameters.get(
            "min_ff_evaluate_grid", [10, 15, 20, 25, 30]
        )
    ]
    if resolution_grid != sorted(set(resolution_grid)) or not resolution_grid or resolution_grid[-1] > 3.0:
        raise ValueError("C012 resolution_grid must be unique, ascending, and at most 3.0")
    if min_n_grid != sorted(set(min_n_grid)) or not min_n_grid:
        raise ValueError("C012 min_ff_evaluate_grid must be unique and ascending")
    automatic_limit = int(parameters.get("max_units_for_auto_standard", 24))
    absolute_limit = int(parameters.get("absolute_max_analysis_units", 100))
    confirmed = bool(parameters.get("configuration_confirmed", False))
    search_enabled = bool(parameters.get("parameter_search_enabled", False)) and not confirmed
    evaluated: dict[tuple[int, float], dict[str, Any]] = {}

    def evaluate(min_n: int, resolution: float) -> dict[str, Any]:
        key = (int(min_n), float(resolution))
        if key not in evaluated:
            evaluated[key] = evaluate_series_configuration(
                cluster_sets=cluster_sets,
                enrichment=enrichment,
                frame=frame,
                compound_id_column=compound_id_column,
                endpoint_column=endpoint_column,
                higher_is_better=higher_is_better,
                min_ff_evaluate=key[0],
                resolution=key[1],
                random_seed=seed,
                cluster_ff_threshold=cluster_ff_threshold,
                multi_cluster_ff_threshold=multi_cluster_ff_threshold,
            )
        return evaluated[key]

    default_result = evaluate(min_n_grid[0], resolution_grid[0])
    default_clusters = set(default_result["selected_ids"])
    default_compounds = set().union(
        *(cluster_sets[item] for item in default_clusters)
    ) if default_clusters else set()
    automatic_choice: tuple[int, float] | None = None
    if search_enabled:
        for resolution in resolution_grid:
            result = evaluate(min_n_grid[0], resolution)
            if automatic_choice is None and result["summary"]["analysis_unit_count"] <= automatic_limit:
                automatic_choice = (min_n_grid[0], resolution)
        if automatic_choice is None:
            for min_n in min_n_grid[1:]:
                for resolution in resolution_grid:
                    evaluate(min_n, resolution)
    requested_choice = (
        int(parameters.get("min_ff_evaluate", min_n_grid[0])),
        float(parameters.get("leiden_resolution", resolution_grid[0])),
    )
    chosen_key = automatic_choice or requested_choice
    chosen = evaluate(*chosen_key)
    selection_required = bool(search_enabled and automatic_choice is None)
    if confirmed and chosen["summary"]["analysis_unit_count"] > absolute_limit:
        raise ValueError(
            f"C012 selected condition has {chosen['summary']['analysis_unit_count']} units; "
            f"the absolute limit is {absolute_limit}"
        )

    grid_rows: list[dict[str, Any]] = []
    for (min_n, resolution), result in sorted(evaluated.items()):
        selected_ids = set(result["selected_ids"])
        selected_compounds = set().union(
            *(cluster_sets[item] for item in selected_ids)
        ) if selected_ids else set()
        summary = result["summary"]
        grid_rows.append({
            "min_ff_evaluate": min_n,
            "leiden_resolution": resolution,
            "selected_cluster_count": summary["selected_cluster_count"],
            "candidate_series_count": summary["candidate_series_count"],
            "accepted_series_count": summary["accepted_series_count"],
            "relaxed_series_count": summary["relaxed_series_count"],
            "rejected_series_count": summary["rejected_series_count"],
            "fallback_cluster_count": summary["fallback_cluster_count"],
            "analysis_unit_count": summary["analysis_unit_count"],
            "cluster_coverage": (
                len(selected_ids & default_clusters) / len(default_clusters)
                if default_clusters else 1.0
            ),
            "compound_coverage": (
                len(selected_compounds & default_compounds) / len(default_compounds)
                if default_compounds else 1.0
            ),
            "median_series_ff": summary["median_series_ff"],
            "within_auto_limit": summary["analysis_unit_count"] <= automatic_limit,
            "within_absolute_limit": summary["analysis_unit_count"] <= absolute_limit,
        })
    search = {
        "schema_version": "1.0.0",
        "status": "awaiting_human_selection" if selection_required else "selected",
        "selection_required": selection_required,
        "automatic_selection": automatic_choice is not None,
        "automatic_limit": automatic_limit,
        "absolute_limit": absolute_limit,
        "resolution_grid": resolution_grid,
        "min_ff_evaluate_grid": min_n_grid,
        "chosen_condition": {
            "min_ff_evaluate": chosen_key[0],
            "leiden_resolution": chosen_key[1],
        },
        "evaluations": grid_rows,
    }
    write_json(output / "series_parameter_search.json", search)
    if selection_required:
        preview_summary = {
            **chosen["summary"],
            "series_count": chosen["summary"]["candidate_series_count"],
            "analysis_unit_count": chosen["summary"]["analysis_unit_count"],
            "favorable_fraction_threshold": cluster_ff_threshold,
            "selection_required": True,
            "automatic_selection": False,
            "configuration_confirmed": False,
            "chosen_condition": None,
            "preview_condition": search["chosen_condition"],
            "parameter_search_file": "series_parameter_search.json",
        }
        summary_path = output / "series_summary.json"
        write_json(summary_path, preview_summary)
        finish(
            request, output, cap,
            primary=output / "series_parameter_search.json",
            summary=preview_summary,
            extra_artifacts=[summary_path],
        )
        return
    series_columns = [
        "series_id", "source_cluster_count", "source_cluster_ids",
        "compound_count", "endpoint_valid_count", "favorable_count",
        "favorable_fraction", "global_favorable_fraction",
        "ff_delta_from_global", "ff_enrichment_ratio",
        "source_cluster_min_ff", "source_cluster_mean_ff",
        "source_cluster_max_ff", "union_ff_delta_from_source_mean",
        "applied_ff_threshold", "acceptance_basis", "accepted",
        "final_analysis_units", "fallback_reason",
    ]
    pd.DataFrame(chosen["series_rows"], columns=series_columns).to_csv(
        output / "series_registry.csv", index=False
    )
    pd.DataFrame(
        chosen["cluster_rows"],
        columns=["series_id", "candidate_series_id", "cluster_id"],
    ).to_csv(output / "series_cluster_membership.csv", index=False)
    pd.DataFrame(
        chosen["support_rows"],
        columns=["series_id", "compound_id", "support_count", "support_fraction"],
    ).to_csv(output / "compound_series_support.csv", index=False)
    pd.DataFrame(chosen["membership_rows"]).to_csv(
        output / "analysis_unit_membership.csv", index=False
    )
    pd.DataFrame(chosen["unit_rows"]).to_csv(
        output / "analysis_unit_registry.csv", index=False
    )
    pd.DataFrame(
        chosen["edge_rows"],
        columns=[
            "cluster_id_a", "cluster_id_b", "overlap_count", "jaccard_weight",
            "containment_a_in_b", "containment_b_in_a", "overlap_coefficient",
        ],
    ).to_csv(output / "series_edges.csv", index=False)
    chosen["selected"].to_csv(output / "selected_clusters_effective.csv", index=False)
    summary = {
        **chosen["summary"],
        "series_count": chosen["summary"]["candidate_series_count"],
        "analysis_unit_count": chosen["summary"]["analysis_unit_count"],
        "favorable_fraction_threshold": cluster_ff_threshold,
        "selection_required": selection_required,
        "automatic_selection": automatic_choice is not None,
        "configuration_confirmed": confirmed or automatic_choice is not None,
        "chosen_condition": search["chosen_condition"],
        "parameter_search_file": "series_parameter_search.json",
    }
    write_json(output / "series_summary.json", summary)
    report = output / "clustering_report.html"
    report.write_text(html_page(
        "C012 Series",
        f"<h1>Endpoint濃縮ClusterのSeries化</h1>"
        f"<div class='card'>{metric_grid([('Selected Clusters', summary['selected_cluster_count']), ('Candidate Series', summary['candidate_series_count']), ('Accepted Series', summary['accepted_series_count']), ('Relaxed Series', summary['relaxed_series_count']), ('Fallback Clusters', summary['fallback_cluster_count']), ('Final local analysis units', summary['analysis_unit_count'])])}"
        f"<p>{'人間によるparameter選択待ちのpreviewです。' if selection_required else '選択済み条件の結果です。'}</p></div>"
        f"<div class='card'><h2>Candidate Series</h2>{compact_table(pd.DataFrame(chosen['series_rows']), 'series', max(1, len(chosen['series_rows'])))}</div>",
    ), encoding="utf-8")
    primary = output / "series_registry.csv"
    finish(
        request, output, cap, primary=primary, summary=summary, report=report,
        extra_artifacts=[
            output / "analysis_unit_membership.csv",
            output / "analysis_unit_registry.csv",
            output / "series_cluster_membership.csv",
            output / "compound_series_support.csv",
            output / "series_edges.csv",
            output / "selected_clusters_effective.csv",
            output / "series_summary.json",
            output / "series_parameter_search.json",
        ],
    )


def correlations(x: pd.Series, y: pd.Series) -> tuple[float, float, float, float]:
    from scipy.stats import pearsonr, spearmanr
    valid = x.notna() & y.notna()
    if valid.sum() < 4 or x[valid].nunique() < 2 or y[valid].nunique() < 2:
        return np.nan, np.nan, np.nan, np.nan
    pcc = pearsonr(x[valid], y[valid]); spr = spearmanr(x[valid], y[valid])
    return float(pcc.statistic), float(pcc.pvalue), float(spr.statistic), float(spr.pvalue)


def rank_a003_correlations(
    frame: pd.DataFrame, limit: int | None = None,
) -> pd.DataFrame:
    """Rank A003 rows deterministically by the strongest absolute correlation."""
    if frame.empty:
        return frame.copy()
    ranked = frame.copy()
    if "max_abs_correlation" in ranked:
        strength = pd.to_numeric(
            ranked["max_abs_correlation"], errors="coerce"
        )
    else:
        coefficients = pd.concat([
            pd.to_numeric(
                ranked.get(
                    "pearson_r", pd.Series(np.nan, index=ranked.index)
                ),
                errors="coerce",
            ).abs(),
            pd.to_numeric(
                ranked.get(
                    "spearman_r", pd.Series(np.nan, index=ranked.index)
                ),
                errors="coerce",
            ).abs(),
        ], axis=1)
        strength = coefficients.max(axis=1)
        ranked["max_abs_correlation"] = strength
    ranked = ranked.loc[strength.notna()].copy()
    if ranked.empty:
        return ranked
    ranked["_correlation_strength"] = strength.loc[ranked.index]
    ranked["_correlation_q"] = pd.to_numeric(
        ranked.get(
            "correlation_q_bh", pd.Series(np.nan, index=ranked.index)
        ),
        errors="coerce",
    ).fillna(np.inf)
    ranked["_feature_sort"] = ranked.get(
        "feature", pd.Series("", index=ranked.index)
    ).astype(str)
    ranked = ranked.sort_values(
        ["_correlation_strength", "_correlation_q", "_feature_sort"],
        ascending=[False, True, True], kind="mergesort",
    ).drop(columns=[
        "_correlation_strength", "_correlation_q", "_feature_sort",
    ])
    return ranked.head(limit) if limit is not None else ranked


def a003_feature_panel(
    request: dict[str, Any], data: pd.DataFrame, compound_id: str,
    endpoint: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, dict[str, str]]]:
    """Join the approved interpretable Description panel for A003."""
    provided: dict[str, dict[str, Any]] = {}
    for item in inputs(request, "description"):
        source = str(item.get("source_capability_id", ""))
        if source in A003_DESCRIPTION_PANEL:
            if source in provided:
                raise ValueError(f"A003 received duplicate Description input: {source}")
            provided[source] = item
    missing = [source for source in A003_DESCRIPTION_PANEL if source not in provided]
    if missing:
        raise ValueError(
            "A003 requires the complete interpretable Description panel; missing: "
            + ", ".join(missing)
        )

    merged = data[[compound_id, endpoint]].copy()
    metadata: dict[str, dict[str, str]] = {}
    feature_keys: list[str] = []
    for source in A003_DESCRIPTION_PANEL:
        frame, description_compound_id = description_table(request, source)
        numeric, columns = numeric_features(frame, [description_compound_id])
        if source == "D015":
            columns = [
                column for column in columns
                if column.removeprefix("mordred__") in A003_MORDRED_2D_FEATURES
            ]
        elif source == "D016":
            columns = [
                column for column in columns
                if column.removeprefix("mordred__") in A003_MORDRED_3D_FEATURES
            ]
        if not columns:
            raise ValueError(f"A003 Description {source} has no approved usable features")
        block = numeric.loc[:, columns].copy()
        renamed: dict[str, str] = {}
        for column in columns:
            feature_key = f"{source}::{column}"
            renamed[column] = feature_key
            feature_keys.append(feature_key)
            metadata[feature_key] = {
                "description_id": source,
                "feature": column,
            }
        block = block.rename(columns=renamed)
        block.insert(0, compound_id, frame[description_compound_id].astype(str))
        merged = merged.merge(block, on=compound_id, how="inner", validate="one_to_one")
    return merged, merged.loc[:, feature_keys], feature_keys, metadata


def render_a003_correlation_plots(
    merged: pd.DataFrame, features: pd.DataFrame, endpoint: str,
    compound_id: str, units: dict[str, set[str]], result: pd.DataFrame,
    output: Path, top_n: int = 3,
) -> tuple[Path, list[Path]]:
    """Create one up-to-three-panel scatter figure for every analysis unit."""
    import matplotlib.pyplot as plt

    index_path = output / "A003_top_correlation_plots.json"
    plots: list[Path] = []
    entries: list[dict[str, Any]] = []
    for unit_id in sorted(value for value in units if value != "GLOBAL"):
        unit_rows = result.loc[
            result["analysis_unit_id"].astype(str).eq(unit_id)
        ] if len(result) else result
        top = rank_a003_correlations(unit_rows, top_n)
        if top.empty:
            continue
        member_mask = merged[compound_id].isin(units[unit_id])
        figure, axes = plt.subplots(
            1, len(top), figsize=(4.4 * len(top), 3.9), squeeze=False,
        )
        plotted_features: list[dict[str, Any]] = []
        for rank, ((_, row), axis) in enumerate(
            zip(top.iterrows(), axes[0]), 1
        ):
            feature = str(row["feature"])
            description_id = str(row.get("description_id", ""))
            feature_key = str(row.get("feature_key", f"{description_id}::{feature}"))
            x = pd.to_numeric(features.loc[member_mask, feature_key], errors="coerce")
            y = pd.to_numeric(merged.loc[member_mask, endpoint], errors="coerce")
            valid = x.notna() & y.notna()
            x_valid = x.loc[valid]
            y_valid = y.loc[valid]
            axis.scatter(
                x_valid, y_valid, s=24, alpha=.78, color="#526a73",
                edgecolors="white", linewidths=.35,
            )
            if len(x_valid) >= 2 and x_valid.nunique() >= 2:
                slope, intercept = np.polyfit(x_valid, y_valid, 1)
                line_x = np.linspace(float(x_valid.min()), float(x_valid.max()), 100)
                axis.plot(
                    line_x, slope * line_x + intercept,
                    color="#a44a22", linewidth=1.25,
                )
            pearson = report_value(row.get("pearson_r"))
            spearman = report_value(row.get("spearman_r"))
            axis.set_title(
                f"#{rank} {description_id} / {feature}\n"
                f"Pearson={pearson} / Spearman={spearman}",
                fontsize=9,
            )
            axis.set_xlabel(feature)
            axis.set_ylabel(endpoint)
            axis.grid(alpha=.18)
            plotted_features.append({
                "rank": rank, "description_id": description_id,
                "feature": feature,
                "sample_count": int(valid.sum()),
                "pearson_r": row.get("pearson_r"),
                "spearman_r": row.get("spearman_r"),
                "max_abs_correlation": row.get("max_abs_correlation"),
                "correlation_q_bh": row.get("correlation_q_bh"),
            })
        figure.suptitle(f"{unit_id}: top {len(top)} feature–Endpoint correlations")
        figure.tight_layout()
        safe_prefix = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in unit_id
        )[:64] or "unit"
        suffix = hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:10]
        plot_path = output / f"A003_top_correlations_{safe_prefix}_{suffix}.png"
        figure.savefig(plot_path, dpi=160)
        plt.close(figure)
        plots.append(plot_path)
        entries.append({
            "analysis_unit_id": unit_id,
            "path": plot_path.name,
            "features": plotted_features,
        })
    write_json(index_path, {
        "schema_version": "1.0.0", "ranking": "max_abs_correlation",
        "top_n": top_n, "plots": entries,
    })
    return index_path, plots


def run_a003(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from scipy.stats import mannwhitneyu
    parameters = request.get("parameters", {})
    correlation_threshold = float(parameters.get("correlation_threshold", .6))
    correlation_gain_threshold = float(parameters.get("correlation_gain_threshold", .2))
    median_iqr_threshold = float(parameters.get("median_iqr_threshold", .75))
    q_threshold = float(parameters.get("q_threshold", .05))
    if correlation_threshold <= 0 or correlation_gain_threshold < 0 or median_iqr_threshold <= 0 or not (0 < q_threshold <= 1):
        raise ValueError("A003 thresholds must be positive and q_threshold must satisfy 0 < q <= 1")
    data, cid, _, endpoint = dataset(request)
    merged, features, columns, feature_metadata = a003_feature_panel(
        request, data, cid, endpoint
    )
    units = analysis_units(request)
    global_ids = units["GLOBAL"]; global_index = merged[cid].isin(global_ids); global_iqr = features.loc[global_index].quantile(.75) - features.loc[global_index].quantile(.25)
    global_stats: dict[str, tuple[float,float,float,float]] = {col: correlations(features[col], merged[endpoint]) for col in columns}
    rows: list[dict[str, Any]] = []
    for unit_id, members in units.items():
        mask = merged[cid].isin(members)
        if mask.sum() < 5: continue
        for column in columns:
            feature_info = feature_metadata[column]
            pcc, pp, spr, sp = correlations(features.loc[mask, column], merged.loc[mask, endpoint]); gpcc, _, gspr, _ = global_stats[column]
            shift = float(features.loc[mask, column].median() - features.loc[global_index, column].median()); scale = float(global_iqr.get(column, np.nan)); norm = shift / scale if np.isfinite(scale) and scale > 0 else np.nan
            inside = features.loc[mask, column].dropna(); outside = features.loc[global_index & ~mask, column].dropna()
            shift_p = float(mannwhitneyu(inside, outside, alternative="two-sided").pvalue) if len(inside) >= 3 and len(outside) >= 3 and pd.concat([inside, outside]).nunique() > 1 else np.nan
            rows.append({"analysis_unit_id": unit_id, "description_id": feature_info["description_id"], "feature": feature_info["feature"], "feature_key": column, "sample_count": int(mask.sum()), "pearson_r": pcc, "pearson_p": pp, "spearman_r": spr, "spearman_p": sp, "global_pearson_r": gpcc, "global_spearman_r": gspr, "max_abs_correlation": max(abs(pcc) if np.isfinite(pcc) else 0, abs(spr) if np.isfinite(spr) else 0), "correlation_gain": max(abs(pcc)-abs(gpcc) if np.isfinite(pcc) and np.isfinite(gpcc) else -np.inf, abs(spr)-abs(gspr) if np.isfinite(spr) and np.isfinite(gspr) else -np.inf), "median_shift": shift, "median_shift_global_iqr": norm, "shift_pvalue": shift_p})
    base_columns = [
        "analysis_unit_id", "description_id", "feature", "feature_key",
        "sample_count", "pearson_r", "pearson_p",
        "spearman_r", "spearman_p", "global_pearson_r", "global_spearman_r",
        "max_abs_correlation", "correlation_gain", "median_shift",
        "median_shift_global_iqr", "shift_pvalue",
    ]
    result = pd.DataFrame(rows, columns=base_columns)
    if not result.empty:
        result["pearson_q_bh"] = bh_qvalues(result["pearson_p"])
        result["spearman_q_bh"] = bh_qvalues(result["spearman_p"])
        result["correlation_q_bh"] = result[["pearson_q_bh","spearman_q_bh"]].min(axis=1)
        result["shift_q_bh"] = bh_qvalues(result["shift_pvalue"])
        result["shift_hit"] = result["median_shift_global_iqr"].abs().ge(median_iqr_threshold) & result["shift_q_bh"].le(q_threshold)
        pearson_gain = result["pearson_r"].abs() - result["global_pearson_r"].abs()
        spearman_gain = result["spearman_r"].abs() - result["global_spearman_r"].abs()
        result["pearson_hit"] = result["pearson_r"].abs().ge(correlation_threshold) & pearson_gain.ge(correlation_gain_threshold) & result["pearson_q_bh"].le(q_threshold)
        result["spearman_hit"] = result["spearman_r"].abs().ge(correlation_threshold) & spearman_gain.ge(correlation_gain_threshold) & result["spearman_q_bh"].le(q_threshold)
        result["correlation_hit"] = result["pearson_hit"] | result["spearman_hit"]
        result["strict_hit"] = result["shift_hit"] | result["correlation_hit"]
        gain_denominator = max(correlation_gain_threshold, np.finfo(float).eps)
        pearson_credit = pd.concat([(result["pearson_r"].abs() / correlation_threshold).clip(upper=1), (pearson_gain / gain_denominator).clip(lower=0, upper=1), (q_threshold / result["pearson_q_bh"]).clip(upper=1).fillna(0)], axis=1).min(axis=1)
        spearman_credit = pd.concat([(result["spearman_r"].abs() / correlation_threshold).clip(upper=1), (spearman_gain / gain_denominator).clip(lower=0, upper=1), (q_threshold / result["spearman_q_bh"]).clip(upper=1).fillna(0)], axis=1).min(axis=1)
        shift_q_credit = (q_threshold / result["shift_q_bh"]).clip(upper=1).fillna(0)
        shift_credit = pd.concat([(result["median_shift_global_iqr"].abs() / median_iqr_threshold).clip(upper=1), shift_q_credit], axis=1).min(axis=1)
        result["near_miss_score"] = pd.concat([pearson_credit, spearman_credit, shift_credit], axis=1).max(axis=1)
        result = result.sort_values(["strict_hit","near_miss_score","max_abs_correlation","analysis_unit_id","feature"], ascending=[False,False,False,True,True])
    primary = output / "A003_series_descriptor_contrast.csv"; result.to_csv(primary, index=False)
    plot_index, correlation_plots = render_a003_correlation_plots(
        merged, features, endpoint, cid, units, result, output, top_n=3
    )
    candidates = result.loc[result["analysis_unit_id"].astype(str).ne("GLOBAL")] if len(result) else result
    hit_count = int(candidates.get("strict_hit", pd.Series(dtype=bool)).sum()); near = candidates.loc[~candidates.get("strict_hit", False)].head(1) if len(candidates) else candidates
    note = f"数値基準を満たす候補は{hit_count}件。" if hit_count else ("数値基準を満たす候補はなく、参考・基準未達の最上位候補は " + (f"{near.iloc[0]['analysis_unit_id']} / {near.iloc[0]['feature']} (|r|max={near.iloc[0]['max_abs_correlation']:.3f})。" if len(near) else "ありません。"))
    report = output / "operator_report.html"; report.write_text(html_page("A003 Series descriptor contrast", f"<h1>Series vs Global: interpretable Description panel</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(result.loc[result.get('strict_hit', False)] if len(result) else result, 200)}</div>"), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary={"description_panel":list(A003_DESCRIPTION_PANEL),"selected_feature_counts":{source:sum(info["description_id"] == source for info in feature_metadata.values()) for source in A003_DESCRIPTION_PANEL},"tested_feature_unit_pairs": len(result), "strict_hit_count": hit_count, "near_miss": near.to_dict("records") if len(near) else [], "correlation_plot_count": len(correlation_plots), "correlation_plot_top_n": 3, "criteria":{"correlation_threshold":correlation_threshold,"correlation_gain_threshold":correlation_gain_threshold,"median_iqr_threshold":median_iqr_threshold,"q_threshold":q_threshold}}, report=report, extra_artifacts=[plot_index, *correlation_plots])


def projection_coordinates(matrix: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    from sklearn.decomposition import PCA
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    warnings: list[str] = []
    clean = StandardScaler().fit_transform(SimpleImputer(strategy="median").fit_transform(matrix))
    component_count = min(2, clean.shape[0], clean.shape[1])
    if component_count < 1:
        empty = np.full((len(matrix), 2), np.nan)
        return empty, empty.copy(), ["Projection requires at least one usable feature and one compound"]
    pca_raw = PCA(n_components=component_count, random_state=seed).fit_transform(clean)
    pca = np.zeros((len(matrix), 2), dtype=float)
    pca[:, :component_count] = pca_raw
    try:
        if len(matrix) < 3:
            raise ValueError("UMAP requires at least three compounds")
        import umap
        binary = np.isin(matrix[~np.isnan(matrix)], [0, 1]).all() if np.isfinite(matrix).any() else False
        metric = "jaccard" if binary else "cosine"
        umap_xy = umap.UMAP(n_components=2, metric=metric, random_state=seed, n_neighbors=min(15, max(2, len(matrix)-1))).fit_transform(np.nan_to_num(matrix, nan=0.0))
    except Exception as exc:
        umap_xy = np.full((len(matrix), 2), np.nan); warnings.append(f"UMAP unavailable: {exc}")
    return pca, umap_xy, warnings


def run_a004(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt
    data, cid, _, endpoint = dataset(request); desc, did = description_table(request, "D002"); merged = data[[cid,endpoint]].merge(desc, left_on=cid, right_on=did, how="inner")
    matrix, columns = numeric_features(merged, [cid,did,endpoint]); seed = int(request.get("parameters", {}).get("random_seed",61453))
    if columns:
        pca, umap_xy, warnings = projection_coordinates(matrix.to_numpy(dtype=float), seed)
    else:
        pca = np.full((len(merged), 2), np.nan); umap_xy = np.full((len(merged), 2), np.nan)
        warnings = ["Projection was not applicable because no feature had at least three finite values"]
    coords = pd.DataFrame({"compound_id":merged[cid],"endpoint":merged[endpoint],"pca_1":pca[:,0],"pca_2":pca[:,1],"umap_1":umap_xy[:,0],"umap_2":umap_xy[:,1]}); primary=output/"A004_projection_coordinates.csv"; coords.to_csv(primary,index=False)
    units=analysis_units(request); pca_images=[]; umap_images=[]; combined=[]
    def plot_one(unit_id:str, method:str, x:str,y:str,path:Path)->None:
        member=coords["compound_id"].isin(units[unit_id]); fig,ax=plt.subplots(figsize=(5.2,4.2)); ax.scatter(coords.loc[~member,x],coords.loc[~member,y],s=12,c="#aeb7b8",alpha=.42); ax.scatter(coords.loc[member,x],coords.loc[member,y],s=22,c="#ff7f0e",alpha=.85); ax.set_title(f"{method}: {unit_id} (n={int(member.sum())})"); ax.set_xlabel(x); ax.set_ylabel(y); fig.tight_layout(); fig.savefig(path,dpi=150); plt.close(fig)
    for unit_id in [item for item in units if item!="GLOBAL"]:
        safe="".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in unit_id); pp=output/f"pca_{safe}.png"; up=output/f"umap_{safe}.png"; plot_one(unit_id,"PCA","pca_1","pca_2",pp); plot_one(unit_id,"UMAP","umap_1","umap_2",up); pca_images.append(pp); umap_images.append(up)
        image=plt.imread(pp); image2=plt.imread(up); fig,axes=plt.subplots(1,2,figsize=(10.4,4.2)); axes[0].imshow(image); axes[1].imshow(image2); [ax.axis("off") for ax in axes]; fig.tight_layout(); cp=output/f"projection_{safe}.png"; fig.savefig(cp,dpi=150); plt.close(fig); combined.append(cp)
    def sheet(paths:list[Path], name:str)->Path:
        target=output/name
        if not paths:
            fig, ax = plt.subplots(figsize=(8, 3)); ax.text(.5, .5, "No accepted Series", ha="center", va="center"); ax.axis("off"); fig.tight_layout(); fig.savefig(target, dpi=150); plt.close(fig); return target
        rows=math.ceil(len(paths)/4); fig,axes=plt.subplots(rows,4,figsize=(16,4*rows)); axes=np.asarray(axes).reshape(-1)
        for ax,path in zip(axes,paths): ax.imshow(plt.imread(path)); ax.axis("off")
        for ax in axes[len(paths):]: ax.axis("off")
        fig.tight_layout(); fig.savefig(target,dpi=150); plt.close(fig); return target
    pca_sheet=sheet(pca_images,"pca_series_contact_sheet.png"); umap_sheet=sheet(umap_images,"umap_series_contact_sheet.png")
    report=output/"operator_report.html"; report.write_text(html_page("A004 projection",f"<h1>D002 Morgan空間のPCA / UMAP</h1><div class='card'><p>Global fitを全Series overlayで共有しています。</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'><img src='{image_uri(pca_sheet)}'><img src='{image_uri(umap_sheet)}'></div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"compound_count":len(coords),"feature_count":len(columns),"analysis_unit_count":len(units)-1},report=report,extra_artifacts=[*pca_images,*umap_images,*combined,pca_sheet,umap_sheet],warnings=warnings)


def render_a005_oof_comparison_plots(
    predictions: pd.DataFrame, metrics: pd.DataFrame, output: Path,
) -> tuple[Path, list[Path]]:
    """Render Local and matched Global OOF prediction panels per local unit."""
    import matplotlib.pyplot as plt

    index_path = output / "A005_oof_comparison_plots.json"
    artifacts: list[Path] = []
    records: list[dict[str, Any]] = []
    if predictions.empty:
        write_json(index_path, {"schema_version": "1.0.0", "plots": records})
        return index_path, artifacts
    global_predictions = predictions.loc[
        predictions["analysis_unit_id"].astype(str).eq("GLOBAL"),
        ["compound_id", "oof_prediction"],
    ].rename(columns={"oof_prediction": "global_oof_prediction"})
    for unit_id in sorted(
        value for value in predictions["analysis_unit_id"].astype(str).unique()
        if value != "GLOBAL"
    ):
        local = predictions.loc[
            predictions["analysis_unit_id"].astype(str).eq(unit_id)
        ].merge(global_predictions, on="compound_id", how="inner", validate="one_to_one")
        local = local.dropna(
            subset=["observed", "oof_prediction", "global_oof_prediction"]
        )
        if local.empty:
            continue
        values = np.concatenate([
            local["observed"].to_numpy(float),
            local["oof_prediction"].to_numpy(float),
            local["global_oof_prediction"].to_numpy(float),
        ])
        lower, upper = float(np.nanmin(values)), float(np.nanmax(values))
        padding = max((upper - lower) * .06, .05)
        limits = (lower - padding, upper + padding)
        metric_row = metrics.loc[
            metrics["analysis_unit_id"].astype(str).eq(unit_id)
        ] if len(metrics) and "analysis_unit_id" in metrics else pd.DataFrame()
        local_r2 = metric_row.iloc[0].get("oof_r2") if len(metric_row) else np.nan
        global_r2 = (
            metric_row.iloc[0].get("global_oof_on_same_series_r2")
            if len(metric_row) else np.nan
        )
        figure, axes = plt.subplots(1, 2, figsize=(8.8, 4.1), sharex=True, sharey=True)
        panels = (
            (axes[0], "oof_prediction", "Local", local_r2, "#ff7f0e"),
            (axes[1], "global_oof_prediction", "Global", global_r2, "#526a73"),
        )
        for axis, prediction_column, label, r2, color in panels:
            axis.scatter(
                local["observed"], local[prediction_column], s=28,
                color=color, alpha=.8, edgecolors="white", linewidths=.4,
            )
            axis.plot(limits, limits, linestyle="--", color="#69767c", linewidth=1)
            axis.set_xlim(limits); axis.set_ylim(limits)
            axis.set_title(f"{label} OOF / R²={report_value(r2)}")
            axis.set_xlabel("Observed Endpoint")
            axis.grid(alpha=.18)
        axes[0].set_ylabel("OOF predicted Endpoint")
        figure.suptitle(f"{unit_id}: OOF prediction comparison (N={len(local)})")
        figure.tight_layout()
        safe = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in unit_id
        )[:64] or "unit"
        suffix = hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:10]
        path = output / f"A005_oof_comparison_{safe}_{suffix}.png"
        figure.savefig(path, dpi=160)
        plt.close(figure)
        artifacts.append(path)
        records.append({
            "analysis_unit_id": unit_id,
            "path": path.name,
            "sample_count": len(local),
        })
    write_json(index_path, {"schema_version": "1.0.0", "plots": records})
    return index_path, artifacts


def run_a005(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from sklearn.feature_selection import f_regression
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import KFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    data,cid,_,endpoint=dataset(request); blocks=[]
    for item in inputs(request,"description"):
        source=str(item.get("source_capability_id") or "DXXX"); frame=read_table(Path(item["path"]), ["compound_id","id","molecule_id"]); ids=[c for c in frame.columns if str(c).lower() in {"compound_id","id","molecule_id"}]
        if not ids: continue
        did=ids[0]; num,cols=numeric_features(frame,[did]); num.columns=[f"{source}::{col}" for col in cols]; num.insert(0,cid,frame[did].astype(str)); blocks.append(num)
    merged=data[[cid,endpoint]].copy()
    for block in blocks: merged=merged.merge(block,on=cid,how="inner")
    parameters=request.get("parameters",{}); feature_cols=[c for c in merged.columns if c not in {cid,endpoint}]; units=analysis_units(request); min_n=int(parameters.get("min_local_samples",30)); seed=int(parameters.get("random_seed",61453)); min_local_r2=float(parameters.get("strict_local_oof_r2_min",.2)); min_r2_gain=float(parameters.get("strict_r2_gain_min",.2)); require_mae=bool(parameters.get("require_local_mae_not_worse",True)); metrics=[]; predictions=[]; global_oof: dict[str,float]={}
    feature_available = (
        merged[feature_cols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
        if feature_cols else pd.Series(False, index=merged.index)
    )
    if min_n < 5 or min_r2_gain < 0:
        raise ValueError("A005 requires min_local_samples >= 5 and strict_r2_gain_min >= 0")
    for unit_id,members in units.items():
        member_count=len(members)
        part=merged.loc[merged[cid].isin(members)&merged[endpoint].notna()&feature_available].copy(); n=len(part)
        try:
            required_n=10 if unit_id=="GLOBAL" else min_n
            if n < required_n: metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"member_count":member_count,"model_count":n,"status":"not_applicable","reason":f"model_n<{required_n}"}); continue
            x=part[feature_cols].apply(pd.to_numeric,errors="coerce"); y=part[endpoint].to_numpy(float)
            if x.shape[1]==0: metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"member_count":member_count,"model_count":n,"status":"not_applicable","reason":"no_usable_features"}); continue
            # Selection is independently fitted inside every outer fold; held-out
            # endpoint values cannot affect the selected feature set.
            folds=min(5,max(3,n//10)); cv=KFold(n_splits=folds,shuffle=True,random_state=seed); pred=np.full(n,np.nan); selected_counts: dict[str,int]={}
            for train_idx,test_idx in cv.split(x):
                train_x=x.iloc[train_idx]; test_x=x.iloc[test_idx]; train_y=y[train_idx]
                # Determine usable columns from the training fold only.  This
                # prevents SimpleImputer from silently dropping an all-missing
                # fold column and shifting the reported feature names relative
                # to the fitted matrix columns.
                fold_keep=train_x.notna().sum().ge(3) & train_x.nunique(dropna=True).gt(1)
                train_x=train_x.loc[:,fold_keep]; test_x=test_x.loc[:,fold_keep]
                if train_x.shape[1]==0:
                    pred[test_idx]=float(np.mean(train_y))
                    continue
                imputer=SimpleImputer(strategy="median"); train_matrix=imputer.fit_transform(train_x); test_matrix=imputer.transform(test_x)
                scores=np.nan_to_num(f_regression(train_matrix,train_y)[0],nan=0.0); top=np.argsort(scores)[::-1][:min(24,train_x.shape[1],max(3,len(train_idx)//4))]
                selected=[train_x.columns[index] for index in top]
                for feature in selected: selected_counts[feature]=selected_counts.get(feature,0)+1
                model=make_pipeline(StandardScaler(),Ridge(alpha=10.0)); model.fit(train_matrix[:,top],train_y); pred[test_idx]=model.predict(test_matrix[:,top])
            stable=sorted(selected_counts,key=lambda feature:(-selected_counts[feature],feature))
            if not stable:
                metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"member_count":member_count,"model_count":n,"status":"not_applicable","reason":"no_training_fold_had_usable_features"})
                continue
            local_r2=float(r2_score(y,pred)); local_mae=float(mean_absolute_error(y,pred)); local_spearman=float(pd.Series(y).corr(pd.Series(pred),method="spearman"))
            row={"analysis_unit_id":unit_id,"sample_count":n,"member_count":member_count,"model_count":n,"status":"succeeded","feature_count":len(stable),"oof_r2":local_r2,"oof_mae":local_mae,"oof_spearman":local_spearman,"selected_features":";".join(stable),"selection_contract":"inside_outer_cv"}
            if unit_id=="GLOBAL":
                global_oof=dict(zip(part[cid].astype(str),pred))
            else:
                baseline=np.asarray([global_oof.get(str(value),np.nan) for value in part[cid]],dtype=float); comparable=np.isfinite(baseline)
                if comparable.sum() >= 3:
                    global_r2=float(r2_score(y[comparable],baseline[comparable])); global_mae=float(mean_absolute_error(y[comparable],baseline[comparable])); global_spearman=float(pd.Series(y[comparable]).corr(pd.Series(baseline[comparable]),method="spearman"))
                    row.update({"global_oof_on_same_series_r2":global_r2,"global_oof_on_same_series_mae":global_mae,"global_oof_on_same_series_spearman":global_spearman,"local_minus_global_r2":local_r2-global_r2,"global_minus_local_mae":global_mae-local_mae})
                    mae_condition = local_mae <= global_mae if require_mae else True
                    row["strict_improvement"]=bool(local_r2>=min_local_r2 and local_r2-global_r2>=min_r2_gain and mae_condition)
                    local_r2_credit = local_r2 / max(min_local_r2, np.finfo(float).eps) if local_r2 > 0 else 0
                    gain_credit = (local_r2-global_r2) / max(min_r2_gain, np.finfo(float).eps) if local_r2 > global_r2 else 0
                    mae_credit = global_mae/local_mae if require_mae and local_mae>0 else 1
                    row["near_miss_score"]=min(local_r2_credit,gain_credit,mae_credit)
                else:
                    row.update({"status":"not_applicable","reason":"global_oof_predictions_missing_for_series","strict_improvement":False,"near_miss_score":0.0})
            metrics.append(row)
            predictions.extend({"analysis_unit_id":unit_id,"compound_id":compound,"observed":obs,"oof_prediction":estimate} for compound,obs,estimate in zip(part[cid],y,pred))
        except Exception as exc:
            metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"member_count":member_count,"model_count":n,"status":"unit_failed","reason":f"{type(exc).__name__}: {exc}"})
    result=pd.DataFrame(metrics)
    if len(result) and "strict_improvement" in result:
        result["strict_improvement"]=boolean_mask(result["strict_improvement"], "strict_improvement"); result=result.sort_values(["strict_improvement","near_miss_score","analysis_unit_id"],ascending=[False,False,True],na_position="last")
    primary=output/"A005_series_feature_model.csv"; result.to_csv(primary,index=False); pred_path=output/"oof_predictions.csv"; prediction_frame=pd.DataFrame(predictions, columns=["analysis_unit_id","compound_id","observed","oof_prediction"]); prediction_frame.to_csv(pred_path,index=False)
    plot_index, comparison_plots = render_a005_oof_comparison_plots(
        prediction_frame, result, output
    )
    local=result.loc[result["analysis_unit_id"].astype(str).ne("GLOBAL")] if len(result) else result
    local_flags=boolean_mask(local["strict_improvement"], "strict_improvement") if "strict_improvement" in local else pd.Series(False,index=local.index)
    hits=local.loc[local_flags]; near=local.loc[~local_flags].head(1)
    note=f"数値基準を満たしたanalysis unitは{len(hits)}件。" if len(hits) else (f"数値基準を満たさず、参考・基準未達の最上位候補は{near.iloc[0]['analysis_unit_id']}（local OOF R2={near.iloc[0].get('oof_r2',np.nan):.3f}）。" if len(near) else "評価可能なanalysis unitはありません。")
    report=output/"operator_report.html"; report.write_text(html_page("A005 models",f"<h1>Global / Series低容量OOFモデル</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(hits)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"analysis_unit_count":len(result),"modeled_unit_count":int(result.get('status',pd.Series(dtype=str)).eq('succeeded').sum()),"strict_improvement_count":len(hits),"unit_failure_count":int(result.get('status',pd.Series(dtype=str)).eq('unit_failed').sum()),"minimum_model_n":min_n,"model_n_definition":"valid Endpoint, successful Description ID join, and at least one available model feature","candidate_description_panel":sorted({str(item.get("source_capability_id") or "DXXX") for item in inputs(request,"description")}),"feature_selection":"same initial candidate panel for Local and Global; independently fitted training-fold-only usability filtering and univariate F-test; up to 24 features; Ridge(alpha=10)","criteria":{"local_oof_r2_min":min_local_r2,"local_minus_global_r2_min":min_r2_gain,"require_local_mae_not_worse":require_mae},"validation":"out-of-fold predictions; Global comparator uses the same analysis-unit compounds' Global OOF predictions; no random holdout metric","near_miss":near.to_dict('records') if len(near) else []},report=report,extra_artifacts=[pred_path,plot_index,*comparison_plots])


def run_a006(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from sklearn.metrics import pairwise_distances

    parameters = request.get("parameters", {})
    metric = str(parameters.get("metric", "tanimoto")).lower()
    if metric != "tanimoto":
        raise ValueError("A006 uses D002 Morgan bits and therefore requires metric='tanimoto'")
    similarity_threshold = float(parameters.get("similarity_threshold", .75))
    minimum_support_pairs = int(parameters.get("minimum_support_pairs", 3))
    direction_fraction_threshold = float(parameters.get("direction_fraction_threshold", .8))
    if not (0 <= similarity_threshold <= 1) or minimum_support_pairs < 1 or not (0 <= direction_fraction_threshold <= 1):
        raise ValueError("A006 similarity/direction thresholds must be in [0,1] and minimum_support_pairs >= 1")
    data, cid, _, endpoint = dataset(request)
    desc, did = description_table(request, "D002")
    merged = data[[cid, endpoint]].merge(desc, left_on=cid, right_on=did, how="inner").dropna(subset=[endpoint]).reset_index(drop=True)
    x, feature_columns = numeric_features(merged, [cid, did, endpoint])
    pair_path = output / "A006_cliff_pairs.csv"
    if len(merged) < 2 or not feature_columns:
        units = analysis_units(request)
        result = pd.DataFrame([
            {"analysis_unit_id": unit_id, "sample_count": int(merged[cid].isin(members).sum()), "status": "not_applicable", "reason": "insufficient_compounds_or_features"}
            for unit_id, members in units.items()
        ])
        primary = output / "A006_series_landscape.csv"; result.to_csv(primary, index=False)
        pd.DataFrame(columns=["analysis_unit_id","pair_scope","compound_id_a","compound_id_b","similarity","endpoint_delta","sali","series_side_favorable"]).to_csv(pair_path, index=False)
        report = output / "operator_report.html"
        report.write_text(html_page("A006 landscape", "<h1>SALI / internal-boundary cliff</h1><div class='card'><p>化合物数または有効D002特徴量が不足し、評価対象外でした。</p></div>"), encoding="utf-8")
        finish(request, output, cap, primary=primary, summary={"analysis_unit_count":len(result),"strict_boundary_hit_count":0,"negative_result":True}, report=report, extra_artifacts=[pair_path])
        return
    matrix = x.fillna(0).to_numpy(bool)
    sim = 1 - pairwise_distances(matrix, metric="jaccard")
    endpoint_values = merged[endpoint].to_numpy(float)
    delta = np.abs(endpoint_values[:, None] - endpoint_values[None, :])
    sali = delta / np.maximum(1 - sim, 1e-6)
    global_iqr = float(merged[endpoint].quantile(.75) - merged[endpoint].quantile(.25))
    units = analysis_units(request)
    id_to_index = {str(value): index for index, value in enumerate(merged[cid])}
    rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    if not np.isfinite(global_iqr) or global_iqr <= 0:
        result = pd.DataFrame([{"analysis_unit_id": unit_id, "sample_count": sum(item in id_to_index for item in members), "status": "not_applicable", "reason": "global_endpoint_iqr_is_zero"} for unit_id, members in units.items()])
        result.to_csv(output / "A006_series_landscape.csv", index=False)
        pd.DataFrame(columns=["analysis_unit_id","pair_scope","compound_id_a","compound_id_b","similarity","endpoint_delta","sali","series_side_favorable"]).to_csv(pair_path, index=False)
        report = output / "operator_report.html"
        report.write_text(html_page("A006 landscape", f"<h1>SALI / internal-boundary cliff</h1><div class='card'><p>Global Endpoint IQRが0のため、Cliff閾値を定義できませんでした。</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div>"), encoding="utf-8")
        finish(request, output, cap, primary=output / "A006_series_landscape.csv", summary={"analysis_unit_count":len(result),"strict_boundary_hit_count":0,"global_endpoint_iqr":global_iqr,"negative_result":True}, report=report, extra_artifacts=[pair_path])
        return
    endpoint_delta_parameter = parameters.get("endpoint_delta_threshold", "1.0_global_iqr")
    if isinstance(endpoint_delta_parameter, str) and endpoint_delta_parameter.endswith("_global_iqr"):
        try:
            endpoint_delta_threshold = float(endpoint_delta_parameter.removesuffix("_global_iqr")) * global_iqr
        except ValueError as exc:
            raise ValueError("A006 endpoint_delta_threshold must be '<positive>_global_iqr' or a positive number") from exc
    else:
        endpoint_delta_threshold = float(endpoint_delta_parameter)
    if not np.isfinite(endpoint_delta_threshold) or endpoint_delta_threshold <= 0:
        raise ValueError("A006 endpoint_delta_threshold must resolve to a positive finite value")
    higher = bool(request.get("endpoint", {}).get("higher_is_better"))
    for unit_id, members in units.items():
        indices = np.array([id_to_index[item] for item in members if item in id_to_index], dtype=int)
        if len(indices) < 3:
            rows.append({"analysis_unit_id":unit_id,"sample_count":len(indices),"status":"not_applicable","reason":"sample_count<3"})
            continue
        tri = np.triu_indices(len(indices), 1)
        internal_a, internal_b = indices[tri[0]], indices[tri[1]]
        values = sali[internal_a, internal_b]
        internal_mask = (sim[internal_a, internal_b] >= similarity_threshold) & (delta[internal_a, internal_b] >= endpoint_delta_threshold)
        for left, right in zip(internal_a[internal_mask], internal_b[internal_mask]):
            pair_rows.append({"analysis_unit_id":unit_id,"pair_scope":"internal","compound_id_a":merged.at[left,cid],"compound_id_b":merged.at[right,cid],"similarity":sim[left,right],"endpoint_delta":delta[left,right],"sali":sali[left,right],"series_side_favorable":np.nan})
        index_set = set(indices)
        boundary_indices = np.array([index for index in range(len(merged)) if index not in index_set], dtype=int)
        boundary_count = 0; boundary_favorable_count = 0; boundary_direction = np.nan
        if unit_id != "GLOBAL" and len(boundary_indices):
            boundary_similarity = sim[np.ix_(indices, boundary_indices)]
            boundary_delta = delta[np.ix_(indices, boundary_indices)]
            boundary_mask = (boundary_similarity >= similarity_threshold) & (boundary_delta >= endpoint_delta_threshold)
            boundary_count = int(boundary_mask.sum())
            if boundary_count:
                inside_values = endpoint_values[indices][:, None]; outside_values = endpoint_values[boundary_indices][None, :]
                favorable = (inside_values > outside_values) if higher else (inside_values < outside_values)
                boundary_favorable_count = int(favorable[boundary_mask].sum())
                boundary_direction = float(boundary_favorable_count / boundary_count)
                positions = np.argwhere(boundary_mask)
                for inside_position, outside_position in positions:
                    left = indices[inside_position]; right = boundary_indices[outside_position]
                    pair_rows.append({"analysis_unit_id":unit_id,"pair_scope":"boundary","compound_id_a":merged.at[left,cid],"compound_id_b":merged.at[right,cid],"similarity":sim[left,right],"endpoint_delta":delta[left,right],"sali":sali[left,right],"series_side_favorable":bool(favorable[inside_position,outside_position])})
        strict = boundary_count >= minimum_support_pairs and np.isfinite(boundary_direction) and boundary_direction >= direction_fraction_threshold
        direction_credit = min(boundary_direction / max(direction_fraction_threshold, np.finfo(float).eps), 1.0) if np.isfinite(boundary_direction) else 0.0
        rows.append({"analysis_unit_id":unit_id,"sample_count":len(indices),"median_sali":float(np.median(values)) if len(values) else np.nan,"p95_sali":float(np.quantile(values,.95)) if len(values) else np.nan,"internal_cliff_count":int(internal_mask.sum()),"boundary_cliff_count":boundary_count,"boundary_favorable_count":boundary_favorable_count,"boundary_favorable_direction_fraction":boundary_direction,"strict_boundary_hit":strict,"near_miss_score":min(boundary_count/minimum_support_pairs,1.0)*direction_credit,"status":"succeeded"})
    result = pd.DataFrame(rows)
    primary = output / "A006_series_landscape.csv"; result.to_csv(primary, index=False)
    pd.DataFrame(pair_rows, columns=["analysis_unit_id","pair_scope","compound_id_a","compound_id_b","similarity","endpoint_delta","sali","series_side_favorable"]).to_csv(pair_path, index=False)
    local = result.loc[result.get("analysis_unit_id", pd.Series(dtype=str)).astype(str).ne("GLOBAL")] if len(result) else result
    hit_flags = boolean_mask(local["strict_boundary_hit"], "strict_boundary_hit") if "strict_boundary_hit" in local else pd.Series(False, index=local.index)
    hits = local.loc[hit_flags]
    sort_columns = [column for column in ("near_miss_score", "boundary_cliff_count") if column in local.columns]
    near = local.sort_values(sort_columns, ascending=[False] * len(sort_columns), na_position="last").head(1) if len(local) and sort_columns else local.head(1)
    note = (
        f"数値基準を満たす境界Cliff候補は{len(hits)}件。"
        if len(hits)
        else (
            f"数値基準を満たさず、参考・基準未達の最上位候補は"
            f"{near.iloc[0]['analysis_unit_id']}（boundary cliffs="
            f"{near.iloc[0].get('boundary_cliff_count', 0)}）。"
            if len(near) else "評価対象なし。"
        )
    )
    report = output / "operator_report.html"
    report.write_text(html_page("A006 landscape",f"<h1>SALI / internal-boundary cliff</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(hits)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"analysis_unit_count":len(result),"strict_boundary_hit_count":len(hits),"global_endpoint_iqr":global_iqr,"cliff_pair_rows":len(pair_rows),"criteria":{"similarity_threshold":similarity_threshold,"endpoint_delta_threshold":endpoint_delta_threshold,"endpoint_delta_definition":str(endpoint_delta_parameter),"minimum_support_pairs":minimum_support_pairs,"direction_fraction_threshold":direction_fraction_threshold},"sali_absolute_cutoff":"none; interpret with similarity, Endpoint delta, support, and direction"},report=report,extra_artifacts=[pair_path])


def run_a007(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold
    data, cid, smiles, _ = dataset(request)
    units = analysis_units(request)
    registry_path = input_path(request, "cluster_registry", required=False)
    source_path = input_path(request, "series_cluster_membership", required=False)
    cluster_membership_path = input_path(
        request, "cluster_membership_long", required=False
    )
    registry = read_table(registry_path, ["cluster_id", "source_cluster_id", "source_node_id"]) if registry_path else pd.DataFrame()
    source = read_table(source_path, ["series_id", "cluster_id"]) if source_path else pd.DataFrame()
    cluster_membership = (
        read_table(cluster_membership_path, ["compound_id", "cluster_id"])
        if cluster_membership_path else pd.DataFrame()
    )
    timeout_seconds = int(request.get("parameters", {}).get("mcs_timeout_seconds", 60))
    if timeout_seconds < 1:
        raise ValueError("A007 mcs_timeout_seconds must be at least 1")

    def is_structural_cluster(row: pd.Series) -> bool:
        input_kind = str(row.get("input_kind", "") or "").strip().lower()
        clustering_id = str(row.get("clustering_id", "") or "").strip()
        return input_kind == "structure" or clustering_id in STRUCTURAL_CLUSTERING_IDS

    def source_rows_for_unit(unit_id: str) -> pd.DataFrame:
        if registry.empty or "cluster_id" not in registry:
            return pd.DataFrame()
        direct = registry.loc[registry["cluster_id"].astype(str).eq(unit_id)]
        if len(direct):
            return direct.copy()
        if {"series_id", "cluster_id"}.issubset(source.columns):
            cluster_ids = source.loc[
                source["series_id"].astype(str).eq(unit_id), "cluster_id"
            ].astype(str)
            return registry.loc[
                registry["cluster_id"].astype(str).isin(cluster_ids)
            ].copy()
        return pd.DataFrame()

    def members_for_source_cluster(
        cluster_id: str, unit_members: set[str], source_count: int,
    ) -> set[str]:
        if len(cluster_membership) and {
            "compound_id", "cluster_id"
        }.issubset(cluster_membership.columns):
            selected = cluster_membership.loc[
                cluster_membership["cluster_id"].astype(str).eq(cluster_id)
            ]
            if "membership_value" in selected:
                selected = selected.loc[
                    boolean_mask(selected["membership_value"], "membership_value")
                ]
            result = set(selected["compound_id"].dropna().astype(str))
            if result:
                return result
        # A single source Cluster has the same membership as its analysis unit.
        # Multi-Cluster Series require the canonical long membership so that
        # vector-derived signatures are not calculated from the Series union.
        if source_count == 1:
            return set(unit_members)
        raise ValueError(
            "cluster_membership_long is required to derive Murcko/MCS for "
            f"vector source Cluster {cluster_id} in a multi-Cluster Series"
        )

    def derived_structure_rows(
        unit_id: str, source_cluster_id: str, member_ids: set[str],
    ) -> list[dict[str, Any]]:
        subset = data.loc[data[cid].astype(str).isin(member_ids), smiles]
        molecules = []
        scaffolds: dict[str, int] = {}
        for value in subset:
            molecule = Chem.MolFromSmiles(str(value))
            if molecule is None:
                continue
            molecules.append(molecule)
            scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=molecule)
            if scaffold:
                scaffolds[scaffold] = scaffolds.get(scaffold, 0) + 1
        derived: list[dict[str, Any]] = []
        dominant_scaffold = (
            sorted(scaffolds.items(), key=lambda item: (-item[1], item[0]))[0]
            if scaffolds else ("", 0)
        )
        derived.append({
            "analysis_unit_id": unit_id, "method": "fallback_murcko",
            "clustering_id": "C001", "cluster_id": source_cluster_id,
            "structure": dominant_scaffold[0],
            "support_count": dominant_scaffold[1],
            "source_member_count": len(member_ids), "mcs_canceled": False,
            "status": "succeeded" if dominant_scaffold[0] else "not_applicable",
            "reason": "" if dominant_scaffold[0] else "no Murcko scaffold",
        })
        if len(molecules) >= 3:
            from rdkit.Chem import rdFMCS
            # Use every valid molecule. The timeout is explicit because silent
            # sampling would change the source-Cluster MCS question.
            mcs = rdFMCS.FindMCS(
                molecules, timeout=timeout_seconds,
                ringMatchesRingOnly=True, completeRingsOnly=True,
            )
            query = Chem.MolFromSmarts(mcs.smartsString) if mcs.smartsString else None
            mcs_heavy = (
                sum(atom.GetAtomicNum() > 1 for atom in query.GetAtoms())
                if query else 0
            )
            coverages = [
                mcs_heavy / max(
                    1, sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())
                )
                for molecule in molecules
            ]
            derived.append({
                "analysis_unit_id": unit_id, "method": "fallback_mcs",
                "clustering_id": "C002", "cluster_id": source_cluster_id,
                "structure": mcs.smartsString,
                "support_count": len(molecules),
                "source_member_count": len(member_ids),
                "mcs_canceled": bool(mcs.canceled),
                "mcs_heavy_atoms": mcs_heavy,
                "mcs_min_coverage": min(coverages),
                "mcs_median_coverage": float(np.median(coverages)),
                "mcs_trivial": mcs_heavy < 3,
                "status": "partial_timeout" if mcs.canceled else "succeeded",
                "reason": "MCS timeout reached" if mcs.canceled else "",
            })
        else:
            derived.append({
                "analysis_unit_id": unit_id, "method": "fallback_mcs",
                "clustering_id": "C002", "cluster_id": source_cluster_id,
                "structure": "", "support_count": len(molecules),
                "source_member_count": len(member_ids), "mcs_canceled": False,
                "status": "not_applicable",
                "reason": "fewer than 3 valid molecules",
            })
        return derived

    rows: list[dict[str, Any]] = []
    for unit_id, members in units.items():
        if unit_id == "GLOBAL":
            continue
        try:
            found: list[dict[str, Any]] = []
            source_rows = source_rows_for_unit(unit_id)
            if len(source_rows):
                for _, source_row in source_rows.sort_values(
                    "cluster_id", kind="mergesort"
                ).iterrows():
                    source_cluster_id = str(source_row.get("cluster_id", ""))
                    if is_structural_cluster(source_row):
                        structure_value = source_row.get(
                            "structure_definition",
                            source_row.get("definition", ""),
                        )
                        structure = (
                            "" if structure_value is None or pd.isna(structure_value)
                            else str(structure_value).strip()
                        )
                        found.append({
                            "analysis_unit_id": unit_id,
                            "method": "source_structural_cluster",
                            "clustering_id": source_row.get("clustering_id"),
                            "cluster_id": source_cluster_id,
                            "structure": structure,
                            "support_count": source_row.get("sample_count"),
                            "source_member_count": source_row.get(
                                "sample_count", len(members)
                            ),
                            "mcs_canceled": False,
                            "status": "succeeded" if structure else "not_applicable",
                            "reason": "" if structure else (
                                "source structural Cluster has no registered key structure"
                            ),
                        })
                    else:
                        source_members = members_for_source_cluster(
                            source_cluster_id, set(members), len(source_rows)
                        )
                        found.extend(derived_structure_rows(
                            unit_id, source_cluster_id, source_members
                        ))
            else:
                # Compatibility path for standalone A007 requests without
                # provenance. Such a unit has no registered structural key.
                found.extend(derived_structure_rows(unit_id, "", set(members)))
            rows.extend(found)
        except Exception as exc:
            rows.append({"analysis_unit_id":unit_id,"method":"unit_error","clustering_id":"","cluster_id":"","structure":"","support_count":0,"source_member_count":len(members),"mcs_canceled":False,"status":"unit_failed","reason":f"{type(exc).__name__}: {exc}"})
    columns = ["analysis_unit_id","method","clustering_id","cluster_id","structure","support_count","source_member_count","mcs_canceled","mcs_heavy_atoms","mcs_min_coverage","mcs_median_coverage","mcs_trivial","status","reason"]
    result = pd.DataFrame(rows, columns=columns)
    primary = output / "A007_series_structural_signature.csv"
    result.to_csv(primary, index=False)
    image_records: list[dict[str, Any]] = []
    image_artifacts: list[Path] = []
    if len(result):
        for unit_id, part in result.groupby("analysis_unit_id", sort=True):
            ranked = part.copy()
            ranked["_support"] = pd.to_numeric(
                ranked["support_count"], errors="coerce"
            ).fillna(0)
            ranked = ranked.sort_values(
                ["_support", "structure"], ascending=[False, True],
                kind="mergesort",
            ).head(5)
            safe_unit = "".join(
                character if character.isalnum() or character in "-_" else "_"
                for character in str(unit_id)
            )[:64] or "unit"
            image_path = output / f"A007_structures_{safe_unit}.png"
            _, rendered = molecule_grid([
                (
                    key_structure_legend(row, str(unit_id)),
                    str(row.get("structure", "")),
                )
                for _, row in ranked.iterrows()
            ], image_path, molecules_per_row=5)
            image_records.append({
                "analysis_unit_id": str(unit_id),
                "path": image_path.name if image_path.is_file() else None,
                "requested_count": len(ranked),
                "rendered_count": rendered,
            })
            if image_path.is_file():
                image_artifacts.append(image_path)
    image_index = output / "A007_structure_images.json"
    write_json(image_index, {
        "schema_version": "1.0.0", "selection": "support_descending",
        "top_n": 5, "images": image_records,
    })
    report = output / "operator_report.html"
    report.write_text(html_page("A007 structures",f"<h1>Series構造由来とfallback key structures</h1><div class='card'>{frame_html(result,300)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"row_count":len(result),"analysis_unit_count":result['analysis_unit_id'].nunique() if len(result) else 0,"mcs_timeout_count":int(result.get('mcs_canceled',pd.Series(dtype=bool)).fillna(False).sum()),"unit_failure_count":int(result.get('status',pd.Series(dtype=str)).eq('unit_failed').sum()),"structure_image_count":len(image_artifacts),"structure_image_top_n":5},report=report,extra_artifacts=[image_index,*image_artifacts])



def id_legend(frame: pd.DataFrame) -> str:
    known_names = {
        "D001": "RDKit 2D", "D002": "Morgan", "D003": "MACCS",
        "D004": "Atom-pair", "D005": "Topological torsion",
        "D006": "RDKit fragment", "D007": "RDKit path",
        "D008": "RDKit pattern", "D009": "RDKit layered",
        "D010": "Avalon", "D011": "Gobbi Pharm2D",
        "D012": "RDKit 3D", "D013": "USR/USRCAT",
        "D014": "Basic 3D shape", "D015": "Mordred 2D",
        "D016": "Mordred 3D", "D019": "xTB", "D020": "ChemBERTa",
        **CLUSTERING_DISPLAY_NAMES,
    }
    values: dict[str, str] = {}
    for id_column, name_column in (
        ("description_id", "description_name"),
        ("clustering_id", "clustering_name"),
    ):
        if id_column not in frame.columns:
            continue
        for _, row in frame.iterrows():
            clustering_value = row.get("clustering_id", "")
            clustering_id = (
                "" if clustering_value is None or pd.isna(clustering_value)
                else str(clustering_value).strip()
            )
            input_kind_value = row.get("input_kind", "")
            input_kind = (
                "" if input_kind_value is None or pd.isna(input_kind_value)
                else str(input_kind_value).strip().lower()
            )
            if (
                id_column == "description_id"
                and (
                    clustering_id in STRUCTURAL_CLUSTERING_IDS
                    or input_kind == "structure"
                )
            ):
                continue
            identifier_value = row.get(id_column, "")
            name_value = row.get(name_column, "")
            identifier = (
                "" if identifier_value is None or pd.isna(identifier_value)
                else str(identifier_value).strip()
            )
            name = (
                "" if name_value is None or pd.isna(name_value)
                else str(name_value).strip()
            )
            if identifier and identifier.lower() != "nan":
                values[identifier] = (
                    known_names.get(identifier)
                    or (name if name and name.lower() != "nan" else "名称情報なし")
                )
    if not values:
        content = '<p class="muted">特徴量／クラスタリングの説明情報なし</p>'
    else:
        content = "<ul>" + "".join(
            f"<li><b>{html_lib.escape(identifier)}</b>: {html_lib.escape(values[identifier])}</li>"
            for identifier in sorted(values)
        ) + "</ul>"
    return (
        "<details class='column-help id-legend'>"
        "<summary>特徴量／クラスタリングの説明</summary>"
        f"{content}</details>"
    )


def report_cluster_provenance(frame: pd.DataFrame) -> pd.DataFrame:
    """Hide inapplicable Description provenance for structure clustering."""
    result = frame.copy()
    if result.empty or "clustering_id" not in result:
        return result
    structural = result["clustering_id"].astype(str).isin(
        STRUCTURAL_CLUSTERING_IDS
    )
    if "input_kind" in result:
        structural = structural | result["input_kind"].astype(str).str.lower().eq(
            "structure"
        )
    for column in ("description_id", "description_name", "description"):
        if column in result:
            result.loc[structural, column] = np.nan
    return result


def source_clusters_for_analysis_unit(
    unit_id: str,
    unit_info: pd.DataFrame,
    series_clusters: pd.DataFrame,
    enrichment: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve source-cluster metadata for both Series and Cluster units."""
    scope_kind = ""
    if len(unit_info) and "scope_kind" in unit_info.columns:
        scope_kind = str(unit_info.iloc[0].get("scope_kind", "") or "").strip().lower()

    if scope_kind == "cluster" and "cluster_id" in enrichment.columns:
        return enrichment.loc[
            enrichment["cluster_id"].astype(str).eq(unit_id)
        ].copy()

    if {"series_id", "cluster_id"}.issubset(series_clusters.columns):
        source_info = series_clusters.loc[
            series_clusters["series_id"].astype(str).eq(unit_id)
        ].merge(enrichment, on="cluster_id", how="left")
        if len(source_info):
            return source_info

    # Older registries may omit scope_kind. A direct cluster-ID match is the
    # deterministic fallback and prevents a real Cluster unit from losing its
    # Description/Clustering explanation in the detail report.
    if "cluster_id" in enrichment.columns:
        return enrichment.loc[
            enrichment["cluster_id"].astype(str).eq(unit_id)
        ].copy()
    return pd.DataFrame()


def key_structure_legend(row: pd.Series, unit_id: str) -> str:
    """Use the source Cluster ID instead of an internal method/support label."""
    cluster_value = row.get("cluster_id", "")
    cluster_id = (
        "" if cluster_value is None or pd.isna(cluster_value)
        else str(cluster_value).strip()
    )
    clustering_value = row.get("clustering_id", "")
    clustering_id = (
        "" if clustering_value is None or pd.isna(clustering_value)
        else str(clustering_value).strip()
    )
    structure_kind = {
        "C001": "Murcko", "C002": "MCS", "C003": "BRICS", "C004": "RECAP",
    }.get(clustering_id)
    method_value = row.get("method", "")
    method = (
        "" if method_value is None or pd.isna(method_value)
        else str(method_value).strip()
    )
    if cluster_id:
        if method in {"fallback_murcko", "fallback_mcs"} and structure_kind:
            return f"{cluster_id} ({structure_kind})"
        return cluster_id
    return f"{unit_id} ({structure_kind})" if structure_kind else unit_id


def structural_signature_explanation(
    unit_id: str, unit_info: pd.DataFrame, source_info: pd.DataFrame,
) -> str:
    """Explain why A007 shows a direct key or a structural fallback."""
    scope_kind = ""
    if len(unit_info) and "scope_kind" in unit_info.columns:
        scope_kind = str(unit_info.iloc[0].get("scope_kind", "") or "").lower()
    clustering_ids = set(
        source_info.get("clustering_id", pd.Series(dtype=str))
        .dropna().astype(str)
    )
    if scope_kind == "series":
        return (
            "当該Seriesを構成する各Source ClusterのKey構造を示します。"
            "構造由来Clusterにはその手法が定義したKey構造だけを使用し、"
            "vector由来Clusterにだけ所属化合物から求めたMurcko scaffoldとMCSを示します。"
            "各構造図のLegendはSource Cluster IDです。"
        )
    if clustering_ids and clustering_ids.issubset(STRUCTURAL_CLUSTERING_IDS):
        method_names = "、".join(
            f"{clustering_id}：{CLUSTERING_DISPLAY_NAMES.get(clustering_id, clustering_id)}"
            for clustering_id in sorted(clustering_ids)
        )
        return (
            f"当該クラスタは構造由来（{method_names}）です。"
            "クラスタリング手法が直接定義したKey構造を以下に示します。"
        )
    if clustering_ids & VECTOR_CLUSTERING_IDS:
        return (
            "当該クラスタはベクトル由来であり、直接の構造Keyを持たないため、"
            "所属化合物のMurcko scaffoldおよびMCSから得たKey構造を以下に示します。"
        )
    return (
        f"当該analysis unit {unit_id}のKey構造を示します。"
        "構造由来なら登録済みKey構造、vector由来ならMurcko scaffoldとMCSを使用します。"
    )


def molecule_grid(
    entries: list[tuple[str, str]], path: Path, *, molecules_per_row: int = 5,
    show_count_caption: bool = True,
) -> tuple[str, int]:
    """Render SMILES/SMARTS entries as one deterministic RDKit PNG grid."""
    if not entries:
        return '<p class="muted">表示可能な構造なし</p>', 0
    from rdkit import Chem
    from rdkit.Chem import Draw

    molecules = []
    legends = []
    for label, structure in entries:
        molecule = Chem.MolFromSmiles(str(structure)) if str(structure).strip() else None
        if molecule is None and str(structure).strip():
            molecule = Chem.MolFromSmarts(str(structure))
        if molecule is None:
            continue
        molecules.append(molecule)
        legends.append(str(label))
    if not molecules:
        return '<p class="muted">構造文字列を2D描画できませんでした。</p>', 0
    image = Draw.MolsToGridImage(
        molecules,
        molsPerRow=molecules_per_row,
        subImgSize=(220, 180),
        legends=legends,
        useSVG=False,
    )
    image.save(path)
    caption = (
        f"<figcaption>{len(molecules)} structures</figcaption>"
        if show_count_caption else ""
    )
    return (
        f"<figure><img src='{image_uri(path)}' alt='2D structure gallery'>"
        f"{caption}</figure>", len(molecules),
    )


def candidate_series_table(frame: pd.DataFrame) -> str:
    headers = [
        "Candidate Series", "Source Cluster N", "Union N", "Union FF",
        "vs Global",
        "Applied FF criterion", "Result", "Final analysis unit",
        "Source Cluster IDs",
    ]
    rows = []
    for _, row in frame.iterrows():
        source_ids = str(row.get("source_cluster_ids", "") or "") or "—"
        accepted_value = row.get("accepted", False)
        accepted = (
            bool(accepted_value) if isinstance(accepted_value, (bool, np.bool_))
            else str(accepted_value).strip().lower() in {"true", "1", "yes"}
        )
        values = [
            row.get("series_id"), row.get("source_cluster_count"),
            row.get("compound_count"), row.get("favorable_fraction"),
            (
                f"Δ {report_value(row.get('ff_delta_from_global'))} / "
                f"{report_value(row.get('ff_enrichment_ratio'))}×"
            ),
            row.get("applied_ff_threshold"),
            "採用" if accepted else "不採用（Clusterへfallback）",
            row.get("final_analysis_units"),
        ]
        cells = "".join(
            f"<td>{html_lib.escape(report_value(value))}</td>" for value in values
        )
        details = (
            "<details><summary>表示</summary><span class='mono'>"
            + html_lib.escape(source_ids.replace("|", ", "))
            + "</span></details>"
        )
        rows.append(f"<tr>{cells}<td>{details}</td></tr>")
    head = "".join(f"<th>{html_lib.escape(value)}</th>" for value in headers)
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}'>Candidate Seriesなし</td></tr>"
    explanations = [
        ("Candidate Series", "Cluster間overlap graphをLeidenでまとめた候補ID。"),
        ("Source Cluster N", "Candidate Seriesを構成するCluster数。"),
        ("Union N", "Source Clusterの和集合に含まれる化合物数。"),
        ("Union FF", "和集合のFavorable Fraction。"),
        ("vs Global", "Global FFとの差、およびGlobal FFに対する比。"),
        ("Applied FF criterion", "このCandidateへ適用したFF基準値。"),
        ("Result", "Series採用、またはClusterへ戻した判定。"),
        ("Final analysis unit", "後続解析で使用するSeries／Cluster ID。"),
        ("Source Cluster IDs", "Candidate Seriesを構成する全Cluster ID。"),
    ]
    help_items = "".join(
        f"<dt>{html_lib.escape(label)}</dt><dd>{html_lib.escape(description)}</dd>"
        for label, description in explanations
    )
    table = (
        "<div class='table-wrap'><table class='sortable'><thead><tr>"
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )
    return (
        "<details class='report-table'><summary>Candidate Series mapを表示"
        f"（{len(frame)}件）</summary>{table}"
        "<details class='column-help'><summary>列の説明</summary>"
        f"<dl>{help_items}</dl></details></details>"
    )


def section_csv_link(path: str | None, label: str = "詳細CSVリンク") -> str:
    if not path:
        return ""
    return (
        f"<p class='muted'><a href='{html_lib.escape(path)}'>"
        f"{html_lib.escape(label)}</a></p>"
    )


def run_a009(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt

    profile_path = input_path(request, "cluster_profile")
    enrichment_path = input_path(request, "cluster_enrichment")
    series_path = input_path(request, "series_registry")
    units_path = input_path(request, "analysis_unit_membership", required=False)
    series_clusters_path = input_path(request, "series_cluster_membership", required=False)
    unit_registry_path = input_path(request, "analysis_unit_registry", required=False)
    support_path = input_path(request, "compound_series_support", required=False)
    series_summary_path = input_path(request, "series_summary", required=False)
    selected_effective_path = input_path(
        request, "selected_clusters_effective", required=False
    )
    mmp_report_index_path = input_path(
        request, "mmp_report_index", required=False
    )

    cluster_profile = read_table(profile_path, ["cluster_id"])
    enrichment = read_table(enrichment_path, ["cluster_id"])
    series = read_table(series_path, ["series_id"])
    series_summary = (
        json.loads(series_summary_path.read_text(encoding="utf-8"))
        if series_summary_path else {}
    )
    selected = (
        read_table(selected_effective_path, ["cluster_id"])
        if selected_effective_path
        else enrichment.loc[
            boolean_mask(enrichment["selected_for_series"], "selected_for_series")
        ].copy()
        if len(enrichment) and "selected_for_series" in enrichment
        else enrichment.iloc[0:0].copy()
    )
    series_clusters = (
        read_table(
            series_clusters_path, ["series_id", "candidate_series_id", "cluster_id"]
        )
        if series_clusters_path else pd.DataFrame()
    )
    unit_registry = (
        read_table(unit_registry_path, ["analysis_unit_id"])
        if unit_registry_path else pd.DataFrame()
    )
    support = (
        read_table(support_path, ["series_id", "compound_id"])
        if support_path else pd.DataFrame()
    )
    if len(unit_registry) and "analysis_unit_id" not in unit_registry.columns:
        raise ValueError("analysis_unit_registry must contain analysis_unit_id")
    if len(support) and "series_id" not in support.columns:
        raise ValueError("compound_series_support must contain series_id")
    if (
        len(series_clusters) and len(selected)
        and {"series_id", "cluster_id"}.issubset(series_clusters.columns)
    ):
        selected = selected.merge(
            series_clusters[
                ["series_id", "candidate_series_id", "cluster_id"]
            ],
            on="cluster_id", how="left", validate="one_to_one",
        )
    selected_display = report_cluster_provenance(selected)
    if len(selected_display):
        selected_display["description"] = selected_display.get(
            "description_id", pd.Series("—", index=selected_display.index)
        ).fillna("—").astype(str)
        selected_display["clustering"] = selected_display.get(
            "clustering_id", pd.Series("—", index=selected_display.index)
        ).fillna("—").astype(str)
        selected_display["favorable_count_fraction"] = [
            f"{report_value(row.get('favorable_count'))} "
            f"({report_value(row.get('favorable_fraction'))})"
            for _, row in selected_display.iterrows()
        ]
        selected_display["analysis_unit_id"] = selected_display.get(
            "series_id", pd.Series("—", index=selected_display.index)
        ).fillna("—")

    source_frames: dict[str, pd.DataFrame] = {}
    source_paths: dict[str, Path] = {}
    a004_source_dir: Path | None = None
    a003_plot_paths: dict[str, Path] = {}
    a005_plot_paths: dict[str, Path] = {}
    for item in inputs(request, "source"):
        capability_id = str(item.get("source_capability_id", "source"))
        path = Path(item["path"])
        if capability_id == "A004":
            a004_source_dir = path.parent
            continue
        if capability_id == "A008" or path.suffix.lower() != ".csv":
            continue
        try:
            source_frames[capability_id] = read_table(
                path, ["compound_id", "analysis_unit_id", "cluster_id", "series_id"]
            )
            source_paths[capability_id] = path
            if capability_id == "A003":
                plot_index_path = path.parent / "A003_top_correlation_plots.json"
                if plot_index_path.is_file():
                    plot_index = json.loads(
                        plot_index_path.read_text(encoding="utf-8")
                    )
                    for plot_record in plot_index.get("plots", []):
                        unit_id = str(
                            plot_record.get("analysis_unit_id", "")
                        )
                        candidate = (
                            path.parent / str(plot_record.get("path", ""))
                        ).resolve()
                        if (
                            unit_id and candidate.is_file()
                            and candidate.parent == path.parent.resolve()
                        ):
                            a003_plot_paths[unit_id] = candidate
            if capability_id == "A005":
                plot_index_path = path.parent / "A005_oof_comparison_plots.json"
                if plot_index_path.is_file():
                    plot_index = json.loads(
                        plot_index_path.read_text(encoding="utf-8")
                    )
                    for plot_record in plot_index.get("plots", []):
                        unit_id = str(plot_record.get("analysis_unit_id", ""))
                        candidate = (
                            path.parent / str(plot_record.get("path", ""))
                        ).resolve()
                        if (
                            unit_id and candidate.is_file()
                            and candidate.parent == path.parent.resolve()
                        ):
                            a005_plot_paths[unit_id] = candidate
        except Exception as exc:
            raise ValueError(
                f"A009 could not read the succeeded upstream CSV {path} "
                f"({capability_id}): {exc}"
            ) from exc

    full_table_dir = output / "tables"
    full_table_dir.mkdir()
    full_table_artifacts: list[Path] = []
    full_table_links: list[tuple[str, str]] = []

    def copy_full_table(label: str, source_path: Path | None, filename: str) -> None:
        if source_path is None:
            return
        target = full_table_dir / filename
        shutil.copy2(source_path, target)
        full_table_artifacts.append(target)
        full_table_links.append((label, target.relative_to(output).as_posix()))

    copy_full_table("A001 全Cluster profile", profile_path, "A001_cluster_profile_full.csv")
    copy_full_table("A002 全Cluster enrichment", enrichment_path, "A002_cluster_enrichment_full.csv")
    copy_full_table("C012 Series registry", series_path, "C012_series_registry_full.csv")
    copy_full_table("Analysis unit registry", unit_registry_path, "analysis_unit_registry_full.csv")
    copy_full_table("Analysis unit membership", units_path, "analysis_unit_membership_full.csv")
    copy_full_table("Series–Cluster membership", series_clusters_path, "series_cluster_membership_full.csv")
    copy_full_table("Compound Series support", support_path, "compound_series_support_full.csv")
    selected_path = full_table_dir / "selected_clusters_full.csv"
    selected.to_csv(selected_path, index=False)
    full_table_artifacts.append(selected_path)
    full_table_links.append(("選抜Cluster", selected_path.relative_to(output).as_posix()))
    for capability_id in DETAIL_SECTION_TITLES:
        copy_full_table(
            f"{capability_id} 詳細結果", source_paths.get(capability_id),
            f"{capability_id}_full.csv",
        )

    data, cid, smiles_column, endpoint = dataset(request)
    higher_is_better = bool(request.get("endpoint", {}).get("higher_is_better"))
    endpoint_threshold, favorable = favorable_definition(
        data, endpoint, higher_is_better
    )
    endpoint_valid_count = int(data[endpoint].notna().sum())
    global_ff = float(favorable.loc[data[endpoint].notna()].mean())
    series_ff_threshold = float(
        series_summary.get("favorable_fraction_threshold", .5)
    )

    endpoint_values = pd.to_numeric(data[endpoint], errors="coerce").dropna()
    endpoint_statistics = endpoint_distribution_statistics(
        endpoint_values, higher_is_better
    )
    histogram = output / "endpoint_histogram.png"
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    ax.hist(endpoint_values, bins=24, color="#526a73", edgecolor="white")
    statistic_lines = (
        ("Mean", endpoint_statistics["mean"], "#246b73", "-"),
        ("Median", endpoint_statistics["median"], "#3f4548", "-"),
        (
            "Favorable cutoff",
            endpoint_statistics["favorable_top20_cutoff"], "#a44a22", "--",
        ),
        (
            "Unfavorable cutoff",
            endpoint_statistics["unfavorable_bottom20_cutoff"], "#526e9b", "--",
        ),
    )
    for label, value, color, linestyle in statistic_lines:
        if np.isfinite(value):
            ax.axvline(
                value, color=color, linestyle=linestyle, linewidth=1.4,
                label=f"{label}: {report_value(value)}",
            )
    ax.set_title(f"Endpoint distribution: {endpoint}")
    ax.set_xlabel(endpoint)
    ax.set_ylabel("Count")
    ax.legend(
        loc="upper right", fontsize=8.5,
        title=(
            f"N = {endpoint_valid_count} | Favorable: "
            + ("higher" if higher_is_better else "lower")
        ),
        title_fontsize=8.5, framealpha=.92,
    )
    fig.tight_layout()
    fig.savefig(histogram, dpi=150)
    plt.close(fig)

    accepted_mask = (
        boolean_mask(series["accepted"], "accepted")
        if len(series) and "accepted" in series
        else pd.Series(True, index=series.index)
    )
    accepted = series.loc[accepted_mask].copy()
    rejected_count = int((~accepted_mask).sum())
    series_display = series.copy()
    if len(series_display):
        series_display["quality_warning"] = [
            "" if accepted_value
            else (
                "FF < "
                f"{report_value(row.get('applied_ff_threshold', series_ff_threshold))}; "
                "source Clusterへfallback"
            )
            for accepted_value, (_, row) in zip(
                accepted_mask, series_display.iterrows()
            )
        ]
    contact_sheets: list[Path] = []
    if a004_source_dir is not None:
        for name in ("pca_series_contact_sheet.png", "umap_series_contact_sheet.png"):
            source_image = a004_source_dir / name
            if source_image.is_file():
                target_image = output / name
                shutil.copy2(source_image, target_image)
                contact_sheets.append(target_image)

    if len(unit_registry):
        unit_ids = [
            value
            for value in sorted(
                unit_registry["analysis_unit_id"].astype(str).unique()
            )
            if value != "GLOBAL"
        ]
    elif units_path:
        units_frame = read_table(units_path, ["analysis_unit_id", "compound_id"])
        unit_ids = (
            [
                value
                for value in sorted(
                    units_frame["analysis_unit_id"].astype(str).unique()
                )
                if value != "GLOBAL"
            ]
            if "analysis_unit_id" in units_frame else []
        )
    else:
        unit_ids = []

    unit_memberships = (
        analysis_units(request)
        if units_path
        else {"GLOBAL": set(data[cid].astype(str))}
    )
    registry_lookup = (
        unit_registry.assign(
            analysis_unit_id=unit_registry["analysis_unit_id"].astype(str)
        ).set_index("analysis_unit_id").to_dict("index")
        if len(unit_registry) else {}
    )
    endpoint_by_id = dict(zip(
        data[str(request["columns"]["compound_id"])].astype(str),
        pd.to_numeric(data[endpoint], errors="coerce"),
    ))
    plot_units: list[tuple[str, str, list[float], float]] = []
    for unit_id in ["GLOBAL", *unit_ids]:
        members = unit_memberships.get(unit_id, set())
        values = [
            float(endpoint_by_id[item]) for item in members
            if item in endpoint_by_id and np.isfinite(endpoint_by_id[item])
        ]
        scope = str(registry_lookup.get(unit_id, {}).get("scope_kind", "global" if unit_id == "GLOBAL" else "series"))
        median = float(np.median(values)) if values else np.nan
        plot_units.append((unit_id, scope, values, median))
    direction = -1 if higher_is_better else 1
    ordered_units = [plot_units[0]] + sorted(
        [item for item in plot_units[1:] if item[1] == "series"],
        key=lambda item: (direction * item[3] if np.isfinite(item[3]) else np.inf, item[0]),
    ) + sorted(
        [item for item in plot_units[1:] if item[1] == "cluster"],
        key=lambda item: (direction * item[3] if np.isfinite(item[3]) else np.inf, item[0]),
    )
    endpoint_boxplot = output / "endpoint_analysis_unit_boxplot.png"
    endpoint_boxplot_width = 1080
    endpoint_boxplot_height = 620
    fig, ax = plt.subplots(
        figsize=(endpoint_boxplot_width / 120, endpoint_boxplot_height / 120)
    )
    box_width = max(.08, min(.5, 12 / max(1, len(ordered_units))))
    box = ax.boxplot(
        [item[2] if item[2] else [np.nan] for item in ordered_units],
        tick_labels=[f"{item[0]}\nN={len(item[2])}" for item in ordered_units],
        patch_artist=True, whis=1.5, showfliers=True, widths=box_width,
    )
    color_by_scope = {"global": "#9aa0a6", "series": "#4e79a7", "cluster": "#f28e2b"}
    for patch, item in zip(box["boxes"], ordered_units):
        patch.set_facecolor(color_by_scope.get(item[1], "#9aa0a6"))
        patch.set_alpha(.82)
    favorable_cutoff = endpoint_statistics["favorable_top20_cutoff"]
    unfavorable_cutoff = endpoint_statistics["unfavorable_bottom20_cutoff"]
    ax.axhline(
        favorable_cutoff, color="#a44a22", linestyle="--", linewidth=1.2,
        label=f"Favorable cutoff: {report_value(favorable_cutoff)}",
    )
    ax.axhline(
        unfavorable_cutoff, color="#526e9b", linestyle="--", linewidth=1.2,
        label=f"Unfavorable cutoff: {report_value(unfavorable_cutoff)}",
    )
    ax.set_ylabel(endpoint)
    ax.set_xlabel("Global / accepted Series / fallback Cluster")
    ax.set_title("Endpoint distribution by final analysis unit")
    tick_font_size = max(4.5, min(7.5, 180 / max(1, len(ordered_units))))
    ax.tick_params(
        axis="x", rotation=90 if len(ordered_units) > 12 else 70,
        labelsize=tick_font_size,
    )
    ax.grid(axis="y", alpha=.18)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=color_by_scope["global"], alpha=.82, label="Global"),
        Patch(facecolor=color_by_scope["series"], alpha=.82, label="Series"),
        Patch(facecolor=color_by_scope["cluster"], alpha=.82, label="Cluster"),
        Line2D([0], [0], color="#a44a22", linestyle="--",
               label=f"Favorable cutoff: {report_value(favorable_cutoff)}"),
        Line2D([0], [0], color="#526e9b", linestyle="--",
               label=f"Unfavorable cutoff: {report_value(unfavorable_cutoff)}"),
    ], loc="best", fontsize=7.5, ncols=2, framealpha=.92)
    fig.tight_layout()
    fig.savefig(endpoint_boxplot, dpi=150)
    plt.close(fig)

    def report_view(
        capability_id: str, source_frame: pd.DataFrame,
        unit_id: str | None = None,
    ) -> tuple[pd.DataFrame, str]:
        frame = source_frame
        if unit_id is not None and "analysis_unit_id" in frame:
            frame = frame.loc[frame["analysis_unit_id"].astype(str).eq(unit_id)]
        elif (
            capability_id in {"A003", "A005", "A006"}
            and "analysis_unit_id" in frame
        ):
            frame = frame.loc[
                frame["analysis_unit_id"].astype(str).ne("GLOBAL")
            ]
        if capability_id == "A003" and unit_id is not None:
            ranked = rank_a003_correlations(frame)
            displayed = ranked.head(10)
            correlation_hit_count = (
                int(boolean_mask(
                    ranked["correlation_hit"], "correlation_hit"
                ).sum())
                if len(ranked) and "correlation_hit" in ranked else 0
            )
            return displayed, (
                f"相関係数順に上位{len(displayed)}件を表示。"
                f"相関条件（|r| ≥ 0.60、Globalとの差 ≥ 0.20、BH q ≤ 0.05）"
                f"該当は{correlation_hit_count}件。上位3件は下の散布図で確認できます。"
            )
        if capability_id == "A005" and unit_id is None:
            if frame.empty:
                return frame, (
                    f"評価可能な候補0件。判定条件: {STRICT_CRITERIA['A005']}。"
                )
            chosen = frame.copy()
            passed = (
                boolean_mask(chosen["strict_improvement"], "strict_improvement")
                if "strict_improvement" in chosen else pd.Series(False, index=chosen.index)
            )
            chosen["report_status"] = np.where(
                passed, "基準通過", "参考・基準未達"
            )
            chosen["_passed"] = passed.astype(int)
            sort_columns = ["_passed"]
            ascending = [False]
            if "near_miss_score" in chosen:
                sort_columns.append("near_miss_score")
                ascending.append(False)
            if "analysis_unit_id" in chosen:
                sort_columns.append("analysis_unit_id")
                ascending.append(True)
            chosen = chosen.sort_values(
                sort_columns, ascending=ascending, na_position="last",
                kind="mergesort",
            )
            if "analysis_unit_id" in chosen:
                chosen = chosen.drop_duplicates("analysis_unit_id", keep="first")
            chosen = chosen.drop(columns="_passed")
            return chosen, (
                f"評価{len(frame)}件、基準通過{int(passed.sum())}件。"
                "基準未達を含め、各analysis unitの最良結果を1件ずつ掲載します。"
                f"判定条件: {STRICT_CRITERIA['A005']}。"
            )
        flag = {
            "A003": "correlation_hit",
            "A005": "strict_improvement",
            "A006": "strict_boundary_hit",
        }.get(capability_id)
        if flag and flag in frame:
            hits = frame.loc[boolean_mask(frame[flag], flag)]
            if len(hits):
                hits = hits.copy()
                hits["report_status"] = "基準通過"
                return hits, (
                    f"評価{len(frame)}件、基準通過{len(hits)}件。"
                    f"判定条件: {STRICT_CRITERIA[capability_id]}。"
                )
            order = (
                "max_abs_correlation"
                if capability_id == "A003" and "max_abs_correlation" in frame
                else "near_miss_score" if "near_miss_score" in frame
                else "boundary_cliff_count"
                if "boundary_cliff_count" in frame else None
            )
            near = (
                frame.sort_values(
                    order, ascending=False, na_position="last"
                ).head(1)
                if order and len(frame) else frame.head(1)
            )
            if len(near):
                near = near.copy()
                near["report_status"] = "参考・基準未達"
                label = str(
                    near.iloc[0].get(
                        "feature",
                        near.iloc[0].get("analysis_unit_id", "候補"),
                    )
                )
                note = (
                    f"評価{len(frame)}件、基準通過0件。"
                    f"参考・基準未達: {label}。判定条件: "
                    f"{STRICT_CRITERIA[capability_id]}。"
                )
            else:
                note = (
                    f"評価可能な候補0件。判定条件: "
                    f"{STRICT_CRITERIA[capability_id]}。"
                )
            return near, note
        if frame.empty:
            return frame, "評価可能な結果はありません。"
        return frame, ""

    highlights: dict[str, Any] = {}
    overall_operator_sections: list[str] = []
    for capability_id, title in REPORT_SECTION_TITLES.items():
        source_frame = source_frames.get(capability_id, pd.DataFrame())
        if capability_id not in source_frames:
            note = "成果物なし（Operator failure/waiveまたは未実行）。"
            chosen = pd.DataFrame()
        else:
            chosen, note = report_view(capability_id, source_frame)
        highlights[capability_id] = {
            "note": note,
            "rows": (
                chosen.to_dict("records") if capability_id == "A005"
                else chosen.head(10).to_dict("records")
            ),
        }
        explanation = OPERATOR_EXPLANATIONS.get(capability_id, "")
        table_limit = max(12, len(chosen)) if capability_id == "A005" else 12
        criteria = STRICT_CRITERIA.get(capability_id, "")
        status_message = (
            f"<p>{html_lib.escape(note)}</p>"
            if capability_id not in source_frames else ""
        )
        overall_operator_sections.append(
            f"<section data-operator='{capability_id}'>"
            f"<h3>{html_lib.escape(title)}</h3>"
            f"{compact_table(chosen, capability_id, table_limit)}"
            f"{status_message}"
            "<details class='section-explanation'><summary>解析内容</summary>"
            f"<p>{html_lib.escape(explanation)}</p>"
            f"<p>判定条件: {html_lib.escape(criteria)}。</p>"
            "</details>"
            f"{section_csv_link(f'tables/{capability_id}_full.csv') if capability_id in source_paths else ''}"
            "</section>"
        )

    execution_rows: list[dict[str, Any]] = []
    execution_context = request.get("subject", {}).get(
        "report_execution", []
    )
    if not execution_context:
        execution_context = [
            {"capability_id": capability_id, "node_status": "succeeded"}
            for capability_id in sorted(source_frames)
        ]
    execution_sources = {
        "A001": cluster_profile,
        "A002": enrichment,
        "C012": series,
        **source_frames,
    }
    for metadata in execution_context:
        capability_id = str(metadata.get("capability_id", ""))
        source_frame = execution_sources.get(capability_id)
        evaluated_units = None
        result_rows = None
        succeeded_units = None
        not_applicable_units = None
        failed_units = None
        if source_frame is not None:
            result_rows = len(source_frame)
            if "analysis_unit_id" in source_frame:
                evaluated_units = int(
                    source_frame["analysis_unit_id"].astype(str).nunique()
                )
            if "status" in source_frame:
                statuses = source_frame["status"].astype(str)
                unit_values = (
                    source_frame["analysis_unit_id"].astype(str)
                    if "analysis_unit_id" in source_frame
                    else pd.Series(
                        source_frame.index.astype(str),
                        index=source_frame.index,
                    )
                )
                succeeded_units = int(
                    unit_values.loc[statuses.eq("succeeded")].nunique()
                )
                not_applicable_units = int(
                    unit_values.loc[statuses.eq("not_applicable")].nunique()
                )
                failed_units = int(
                    unit_values.loc[
                        statuses.isin({"unit_failed", "failed"})
                    ].nunique()
                )
            elif evaluated_units is not None:
                succeeded_units = evaluated_units
                not_applicable_units = 0
                failed_units = 0
        execution_rows.append({
            "capability_id": capability_id,
            "node_status": metadata.get(
                "node_status", metadata.get("status", "unknown")
            ),
            "duration_seconds": metadata.get("duration_seconds"),
            "evaluated_units": evaluated_units,
            "result_rows": result_rows,
            "succeeded_units": succeeded_units,
            "not_applicable_units": not_applicable_units,
            "failed_units": failed_units,
            "reason": metadata.get("reason"),
        })
    execution_frame = pd.DataFrame(execution_rows)

    full_links_html = "<ul>" + "".join(
        f"<li><a href='{html_lib.escape(path)}'>"
        f"{html_lib.escape(label)}</a></li>"
        for label, path in full_table_links
    ) + "</ul>"
    mmp_navigation_by_unit: dict[str, str] = {}
    mmp_report_artifacts: list[Path] = []
    if mmp_report_index_path is not None:
        mmp_index = json.loads(
            mmp_report_index_path.read_text(encoding="utf-8")
        )
        mmp_destination = output / "mmp_reports"
        mmp_destination.mkdir(exist_ok=True)
        for source_artifact in mmp_report_index_path.parent.iterdir():
            if (
                source_artifact.is_file()
                and source_artifact.suffix.lower()
                in {".html", ".svg", ".png", ".csv", ".json"}
            ):
                shutil.copy2(source_artifact, mmp_destination / source_artifact.name)
                mmp_report_artifacts.append(
                    mmp_destination / source_artifact.name
                )
        mmp_backlinks: dict[str, list[str]] = {}
        for record in mmp_index.get("unit_reports", []):
            unit_id = str(record.get("analysis_unit_id", ""))
            target_id = str(record.get("target_compound_id", ""))
            report_path = str(record.get("report_path", ""))
            if not unit_id or not target_id or not report_path:
                continue
            report_relative = Path(report_path)
            if (
                report_relative.is_absolute()
                or len(report_relative.parts) != 1
                or report_relative.name != report_path
            ):
                raise ValueError(
                    "A008 mmp_report_index report_path must be a direct filename: "
                    f"{report_path!r}"
                )
            mmp_navigation_by_unit[unit_id] = (
                "<p><b>Type-I MMP Top 1:</b> "
                f"<a href='mmp_reports/{html_lib.escape(report_path, quote=True)}'>"
                f"{html_lib.escape(target_id)}</a></p>"
            )
            mmp_backlinks.setdefault(report_path, []).append(unit_id)
        for report_path, linked_units in mmp_backlinks.items():
            copied_report = mmp_destination / report_path
            if not copied_report.is_file():
                continue
            links = " / ".join(
                f"<a href='../series_{html_lib.escape(unit_id, quote=True)}.html'>"
                f"A009 {html_lib.escape(unit_id)}</a>"
                for unit_id in sorted(set(linked_units))
            )
            content = copied_report.read_text(encoding="utf-8")
            content = content.replace(
                "</header>", f"<p>A009個別レポートへ戻る: {links}</p></header>", 1
            )
            copied_report.write_text(content, encoding="utf-8")
    detail_artifacts: list[Path] = []
    detail_reports: list[dict[str, str]] = []
    for unit_id in unit_ids:
        unit_info = (
            unit_registry.loc[
                unit_registry["analysis_unit_id"].astype(str).eq(unit_id)
            ]
            if len(unit_registry) else pd.DataFrame()
        )
        source_info = source_clusters_for_analysis_unit(
            unit_id, unit_info, series_clusters, enrichment
        )
        source_info = report_cluster_provenance(source_info)
        projection_html = '<p class="muted">Projection画像なし</p>'
        if a004_source_dir is not None:
            candidate = a004_source_dir / f"projection_{unit_id}.png"
            if candidate.is_file():
                projection_html = (
                    f"<img src='{image_uri(candidate)}' "
                    f"alt='PCA and UMAP projection for "
                    f"{html_lib.escape(unit_id)}'>"
                )
        member_ids = unit_memberships.get(unit_id, set())
        member_frame = data.loc[data[cid].astype(str).isin(member_ids), [cid, smiles_column]].copy()
        member_frame = member_frame.sort_values(cid, kind="mergesort")
        if len(member_frame) > 20:
            stable_seed = 61453 + int(
                hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:16], 16
            )
            positions = np.random.default_rng(stable_seed).choice(
                len(member_frame), size=20, replace=False
            )
            member_frame = member_frame.iloc[sorted(positions)]
        safe_unit = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in unit_id
        )[:64] or "unit"
        compound_gallery_path = output / f"compound_gallery_{safe_unit}.png"
        compound_gallery_html, rendered_compounds = molecule_grid(
            [
                (str(row[cid]), str(row[smiles_column]))
                for _, row in member_frame.iterrows()
            ],
            compound_gallery_path,
            molecules_per_row=5,
        )
        if compound_gallery_path.is_file():
            detail_artifacts.append(compound_gallery_path)
        detail_values: dict[str, Any] = {
            "analysis_unit_id": html_lib.escape(unit_id),
            "unit_information": compact_table(
                unit_info, "analysis_units", 5, collapsed=False
            ),
            "source_clusters": compact_table(
                source_info, "source_clusters", max(1, len(source_info))
            ),
            "source_cluster_legend": id_legend(source_info),
            "compound_gallery_note": html_lib.escape(
                f"当該analysis unitの全{len(member_ids)}化合物のうち、"
                f"再現可能な乱数seedでランダム抽出した{len(member_frame)}化合物を示します"
                + (f"（描画成功{rendered_compounds}件）。" if rendered_compounds != len(member_frame) else "。")
            ),
            "compound_gallery": compound_gallery_html,
            "unit_membership_link": section_csv_link(
                "tables/analysis_unit_membership_full.csv", "所属化合物の詳細CSVリンク"
            ),
            "projection": projection_html,
            "a003_scatter_plots": (
                f"<figure><img src='{image_uri(a003_plot_paths[unit_id])}' "
                f"alt='Top interpretable descriptor versus Endpoint scatter plots for "
                f"{html_lib.escape(unit_id)}'><figcaption>"
                "Max |Pearson r, Spearman r|で順位付けした上位3特徴量。"
                "回帰線は視認補助です。</figcaption></figure>"
                if unit_id in a003_plot_paths
                else "<p class='muted'>A003相関散布図なし</p>"
            ),
            "mmp_navigation": mmp_navigation_by_unit.get(
                unit_id,
                '<p class="muted">Type-I MMP対象またはレポートなし</p>',
            ),
            "a006_explanation": html_lib.escape(OPERATOR_EXPLANATIONS["A006"]),
            "a003_explanation": html_lib.escape(OPERATOR_EXPLANATIONS["A003"]),
            "a005_explanation": html_lib.escape(OPERATOR_EXPLANATIONS["A005"]),
            "a003_criteria": html_lib.escape(STRICT_CRITERIA["A003"]),
            "a005_criteria": html_lib.escape(STRICT_CRITERIA["A005"]),
            "a006_criteria": html_lib.escape(STRICT_CRITERIA["A006"]),
            "a005_status_note": "",
            "a005_prediction_plot": (
                "<h3>OOF予測値と実測値</h3>"
                f"<figure><img src='{image_uri(a005_plot_paths[unit_id])}' "
                f"alt='Local and Global OOF predicted versus observed Endpoint for "
                f"{html_lib.escape(unit_id)}'><figcaption>"
                "左はLocalモデル、右は同じ化合物に対するGlobalモデルです。"
                "いずれも未学習foldへの予測値を示します。</figcaption></figure>"
                if unit_id in a005_plot_paths
                else "<p class='muted'>A005 OOF予測比較図なし</p>"
            ),
            "a007_explanation": html_lib.escape(
                structural_signature_explanation(unit_id, unit_info, source_info)
            ),
            "a007_gallery": '<p class="muted">A007構造画像なし</p>',
            "a003_full_link": section_csv_link(
                "tables/A003_full.csv" if "A003" in source_paths else None
            ),
            "a005_full_link": section_csv_link(
                "tables/A005_full.csv" if "A005" in source_paths else None
            ),
            "a006_full_link": section_csv_link(
                "tables/A006_full.csv" if "A006" in source_paths else None
            ),
            "a007_full_link": section_csv_link(
                "tables/A007_full.csv" if "A007" in source_paths else None
            ),
        }
        for capability_id in DETAIL_SECTION_TITLES:
            source_frame = source_frames.get(capability_id, pd.DataFrame())
            if capability_id not in source_frames:
                part = pd.DataFrame()
                note = "成果物なし（Operator failure/waiveまたは未実行）。"
            else:
                part, note = report_view(
                    capability_id, source_frame, unit_id
                )
            detail_values[f"{capability_id.lower()}_note"] = (
                f"<p>{html_lib.escape(note)}</p>" if note else ""
            )
            suppress_table = False
            if capability_id == "A005" and len(part) and "status" in part.columns and bool(part["status"].astype(str).eq("not_applicable").all()):
                first = part.iloc[0]
                detail_values["a005_status_note"] = (
                    "<p>実施対象外: "
                    f"Member N={html_lib.escape(report_value(first.get('member_count')))}, "
                    f"Model N={html_lib.escape(report_value(first.get('model_count')))}。"
                    f"理由: {html_lib.escape(report_value(first.get('reason')))}。</p>"
                )
                part = part.iloc[0:0]
                suppress_table = True
            if capability_id == "A007" and len(part):
                ranked_structures = part.copy()
                ranked_structures["_support"] = pd.to_numeric(
                    ranked_structures.get("support_count", 0), errors="coerce"
                ).fillna(0)
                ranked_structures = ranked_structures.sort_values(
                    ["_support", "structure"], ascending=[False, True],
                    kind="mergesort",
                ).head(5)
                a007_path = output / f"A007_structures_{safe_unit}.png"
                gallery, _ = molecule_grid([
                    (
                        key_structure_legend(row, unit_id),
                        str(row.get("structure", "")),
                    )
                    for _, row in ranked_structures.iterrows()
                ], a007_path, molecules_per_row=5, show_count_caption=False)
                detail_values["a007_gallery"] = gallery
                if a007_path.is_file():
                    detail_artifacts.append(a007_path)
            detail_values[f"{capability_id.lower()}_table"] = (
                "" if suppress_table else compact_table(
                    part,
                    "A003_detail" if capability_id == "A003" else capability_id,
                    10 if capability_id == "A003" else 12,
                )
            )
        detail_body = render_report_template(
            "series_detail_template.html", detail_values
        )
        path = output / f"series_{unit_id}.html"
        path.write_text(
            html_page(f"Analysis unit {unit_id}", detail_body),
            encoding="utf-8",
        )
        detail_reports.append({
            "analysis_unit_id": unit_id,
            "path": path.name,
        })
        detail_artifacts.append(path)

    fallback_count = (
        int(unit_registry["scope_kind"].astype(str).eq("cluster").sum())
        if len(unit_registry) and "scope_kind" in unit_registry else 0
    )
    series_formation = {
        "selected_cluster_count": len(selected),
        "candidate_series_count": len(series),
        "accepted_series_count": len(accepted),
        "rejected_series_count": rejected_count,
        "fallback_cluster_count": fallback_count,
        "analysis_unit_count": len(unit_ids),
        "favorable_fraction_threshold": series_ff_threshold,
        "series_with_ff_decrease_count": series_summary.get(
            "series_with_ff_decrease_count"
        ),
        "median_union_ff_delta_from_source_mean": series_summary.get(
            "median_union_ff_delta_from_source_mean"
        ),
    }
    endpoint_overview = {
        "endpoint": endpoint,
        "input_count": len(data),
        "endpoint_valid_count": endpoint_valid_count,
        "higher_is_better": higher_is_better,
        "favorable_comparator": ">=" if higher_is_better else "<=",
        "favorable_threshold": endpoint_threshold,
        "mean": endpoint_statistics["mean"],
        "median": endpoint_statistics["median"],
        "q20": endpoint_statistics["q20"],
        "q80": endpoint_statistics["q80"],
        "favorable_top20_cutoff": endpoint_statistics[
            "favorable_top20_cutoff"
        ],
        "unfavorable_bottom20_cutoff": endpoint_statistics[
            "unfavorable_bottom20_cutoff"
        ],
        "global_favorable_fraction": global_ff,
    }
    limitations = [
        SELECTION_BIAS_NOTE,
        "q値は補助表示であり、Cluster一次選抜のgateではありません。",
        (
            "Series membershipはsource Clusterの和集合です。重複するFavorable"
            "化合物と固有の非Favorable化合物の組合せにより、union FFは各source "
            "ClusterのFFより低くなる場合があります。"
        ),
        "MMP（A008）は専用レポートへ分離し、このSummaryには重複収載しません。",
        "HTMLは固定した要約列のみを表示し、全列と全行は詳細CSVへ保持しています。",
    ]
    missing_operators = [
        capability_id
        for capability_id in REPORT_SECTION_TITLES
        if capability_id not in source_frames
    ]
    if missing_operators:
        limitations.append(
            f"Partial report: 成果物がないOperatorは "
            f"{', '.join(missing_operators)} です。"
        )

    detail_links_html = (
        "<ul class='link-grid'>" + "".join(
            f"<li><a href='{html_lib.escape(item['path'])}'>"
            f"{html_lib.escape(item['analysis_unit_id'])}</a></li>"
            for item in detail_reports
        ) + "</ul>"
        if detail_reports
        else "<p class='muted'>該当するSeries / fallback Clusterなし</p>"
    )
    projection_gallery = (
        "".join(
            f"<figure><img src='{image_uri(path)}' "
            f"alt='{html_lib.escape(path.stem)}'></figure>"
            for path in contact_sheets
        )
        or '<p class="muted">Projection画像なし</p>'
    )
    relaxed_series_count = int(series_summary.get("relaxed_series_count", 0) or 0)
    summary_metric_items = [
        ("All Clusters", len(cluster_profile)),
        ("Criterion-selected Clusters", len(selected)),
        ("Candidate Series", len(series)),
        ("Standard-criterion Series", len(accepted) - relaxed_series_count),
        ("Relaxed-criterion Series", relaxed_series_count),
        ("Fallback Clusters", fallback_count),
        ("Final analysis units", len(unit_ids)),
        ("Used min_ff_evaluate", series_summary.get("min_ff_evaluate")),
        ("Used Leiden resolution", series_summary.get("leiden_resolution")),
    ]
    summary_metric_definitions = [
        ("All Clusters", "全Description・Clusteringの組合せから得られたCluster総数。"),
        ("Criterion-selected Clusters", "一次選抜のN条件とFF ≥ 0.50を満たしたCluster数。"),
        ("Candidate Series", "選抜Clusterのoverlap graphをLeidenでまとめた候補Series数。"),
        ("Standard-criterion Series", "適用FF基準0.50で採用したSeries数。"),
        ("Relaxed-criterion Series", "複数Source Clusterからなり、緩和FF基準0.40で採用したSeries数。"),
        ("Fallback Clusters", "Candidate Seriesが適用FF基準を満たさず、個別の最終analysis unitへ戻したSource Cluster数。"),
        ("Final analysis units", "後続の定型解析で評価した採用Seriesとfallback Clusterの合計数。"),
        ("Used min_ff_evaluate", "Cluster一次選抜に使用したEndpoint有効化合物数の下限。"),
        ("Used Leiden resolution", "Candidate Series形成に使用したLeiden resolution。"),
    ]
    series_metric_items = [
        ("Candidate Series", len(series)),
        ("Accepted Series (all)", len(accepted)),
        ("Accepted at standard FF ≥ 0.50", len(accepted) - relaxed_series_count),
        ("Accepted at relaxed multi-Cluster FF ≥ 0.40", relaxed_series_count),
        ("Rejected Series", rejected_count),
        ("Fallback Clusters", fallback_count),
        ("Final local analysis units", len(unit_ids)),
        ("Series with FF decrease", series_summary.get("series_with_ff_decrease_count")),
        ("Median union FF delta", series_summary.get("median_union_ff_delta_from_source_mean")),
    ]
    series_metric_definitions = [
        ("Candidate Series", "選抜Clusterのoverlap graphをLeidenでまとめた候補数。"),
        ("Accepted Series (all)", "標準または緩和FF基準を満たしたCandidate Series総数。"),
        ("Accepted at standard FF ≥ 0.50", "適用FF基準0.50を満たして採用したSeries数。"),
        ("Accepted at relaxed multi-Cluster FF ≥ 0.40", "Source Clusterが2件以上で、緩和FF基準0.40を満たして採用したSeries数。"),
        ("Rejected Series", "適用FF基準を満たさなかったCandidate Series数。"),
        ("Fallback Clusters", "不採用Seriesから個別のanalysis unitへ戻したSource Cluster数。"),
        ("Final local analysis units", "後続解析へ渡した採用Seriesとfallback Clusterの合計数。"),
        ("Series with FF decrease", "Source Clusterの平均FFより和集合FFが低下したCandidate Series数。"),
        ("Median union FF delta", "Candidate Seriesごとの『和集合FF − Source Cluster平均FF』の中央値。"),
    ]
    body = render_report_template("standard_summary_template.html", {
        "summary_metrics": metric_grid(summary_metric_items),
        "summary_metric_help": metric_help(summary_metric_definitions),
        "report_scope": bullet_list([
            "主報告対象: Endpoint enrichment条件を満たした全Cluster",
            "解析単位: 採用Seriesと、棄却Seriesからのfallback Cluster",
            "A003–A007のcanonical resultを定型表示。A008 MMPは専用レポート",
        ]),
        "endpoint_metrics": metric_grid([
            ("Endpoint", endpoint),
            ("Input N", len(data)),
            ("Endpoint valid N", endpoint_valid_count),
            (
                "Direction",
                "higher is better"
                if higher_is_better else "lower is better",
            ),
            ("Favorable threshold", endpoint_threshold),
            ("Measured Global FF", global_ff),
        ]),
        "endpoint_histogram_uri": image_uri(histogram),
        "endpoint_boxplot_uri": image_uri(endpoint_boxplot),
        "endpoint_boxplot_width": endpoint_boxplot_width,
        "cluster_metrics": metric_grid([
            ("All Clusters", len(cluster_profile)),
            ("Selected Clusters", len(selected)),
            ("Selection min N", series_summary.get("min_ff_evaluate")),
            ("Selection min FF", series_ff_threshold),
        ]),
        "selected_clusters_table": compact_table(
            selected_display, "selected_clusters", max(1, len(selected_display))
        ),
        "description_clustering_legend": id_legend(selected_display),
        "selected_clusters_full_link": section_csv_link(
            "tables/selected_clusters_full.csv", "選抜Clusterの詳細CSVリンク"
        ),
        "selected_clusters_note": (
            "表示列を固定しています。省略列を含む全行は「選抜Cluster」CSVにあります。"
        ),
        "series_metrics": metric_grid(series_metric_items),
        "series_metric_help": metric_help(series_metric_definitions),
        "candidate_series_table": candidate_series_table(series_display),
        "series_full_link": section_csv_link(
            "tables/C012_series_registry_full.csv", "Series形成結果の詳細CSVリンク"
        ),
        "series_table": compact_table(
            series_display, "series", max(1, len(series_display))
        ),
        "analysis_units_table": compact_table(
            unit_registry, "analysis_units", max(1, len(unit_registry))
        ),
        "operator_sections": "".join(overall_operator_sections),
        "execution_table": compact_table(
            execution_frame, "execution", max(1, len(execution_frame))
        ),
        "projection_gallery": projection_gallery,
        "detail_links": detail_links_html,
        "full_table_links": full_links_html,
        "limitations": bullet_list(limitations),
    })

    index = {
        "schema_version": "1.0.0",
        "report_template": "standard_summary_template.html",
        "report_sections": [
            "summary", "endpoint-distribution", "selected-clusters",
            "series-formation", "operator-results", "projections",
            "detail-reports",
        ],
        "selected_cluster_count": len(selected),
        "series_count": len(accepted),
        "analysis_unit_count": len(unit_ids),
        "endpoint_overview": endpoint_overview,
        "series_formation": series_formation,
        "execution_metadata": execution_rows,
        "limitations": limitations,
        "selected_cluster_preview": selected.head(25).to_dict("records"),
        "series_overview": series.head(24).to_dict("records"),
        "analysis_unit_overview": unit_registry.head(100).to_dict("records"),
        "operator_highlights": highlights,
        "full_tables": [
            {"label": label, "path": path}
            for label, path in full_table_links
        ],
        "detail_reports": detail_reports,
    }
    report = output / "standard_summary.html"
    report.write_text(
        html_page("CONDUCTOR standard report", body), encoding="utf-8"
    )
    primary = output / "standard_report_index.json"
    write_json(primary, index)
    finish(
        request, output, cap, primary=primary, summary=index, report=report,
        extra_artifacts=[
            histogram, endpoint_boxplot, *contact_sheets,
            *mmp_report_artifacts, *full_table_artifacts,
            *detail_artifacts,
        ],
    )


def main() -> int:
    request, output, capability = parse_request(); cid = capability["capability_id"]
    dispatch = {"A001":run_a001,"A002":run_a002,"C012":run_c012,"A003":run_a003,"A004":run_a004,"A005":run_a005,"A006":run_a006,"A007":run_a007,"A009":run_a009}
    if cid not in dispatch: raise ValueError(f"Unsupported batch capability: {cid}")
    dispatch[cid](request, output, capability)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
