from __future__ import annotations

import json
import math
import html as html_lib
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from batch_skill_common import (
    analysis_units, bh_qvalues, dataset, description_table, favorable_definition,
    finish, frame_html, html_page, image_uri, input_path, inputs, membership_sets,
    numeric_features, parse_request, read_table, write_json,
)


SELECTION_BIAS_NOTE = "本比較はEndpoint enrichmentで選抜した解析単位を同じEndpointで評価しており、独立検証や因果関係を示しません。"


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


def run_c012(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
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
        series_rows.append({"series_id": series_id, "source_cluster_count": len(source_clusters), "compound_count": len(union), "endpoint_valid_count": len(valid), "favorable_count": fav_count, "favorable_fraction": ff, "accepted": accepted, "fallback_reason": "" if accepted else "series_ff_below_threshold"})
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
    series_registry = pd.DataFrame(series_rows, columns=["series_id","source_cluster_count","compound_count","endpoint_valid_count","favorable_count","favorable_fraction","accepted","fallback_reason"])
    series_registry.to_csv(output / "series_registry.csv", index=False)
    pd.DataFrame(cluster_rows, columns=["series_id","candidate_series_id","cluster_id"]).to_csv(output / "series_cluster_membership.csv", index=False)
    pd.DataFrame(support_rows, columns=["series_id","compound_id","support_count","support_fraction"]).to_csv(output / "compound_series_support.csv", index=False)
    pd.DataFrame(membership_rows).to_csv(output / "analysis_unit_membership.csv", index=False)
    pd.DataFrame(unit_rows).to_csv(output / "analysis_unit_registry.csv", index=False)
    pd.DataFrame(edge_rows, columns=["cluster_id_a","cluster_id_b","overlap_count","jaccard_weight","containment_a_in_b","containment_b_in_a","overlap_coefficient"]).to_csv(output / "series_edges.csv", index=False)
    global_valid_count = int(frame[endpoint].notna().sum())
    oversized = [row["analysis_unit_id"] for row in unit_rows[1:] if global_valid_count and row["endpoint_valid_count"] / global_valid_count > .5]
    summary = {"selected_cluster_count": len(selected_ids), "series_count": len(communities), "accepted_series_count": accepted_series_count, "rejected_series_count": rejected_series, "analysis_unit_count": len(accepted_members), "fallback_to_selected_clusters": fallback, "edge_count": len(edges), "edge_weight": "Jaccard", "favorable_threshold": threshold, "min_ff_evaluate": min_n, "favorable_fraction_threshold": min_ff, "global_endpoint_valid_count": global_valid_count, "analysis_units_over_50_percent_of_global": oversized}
    write_json(output / "series_summary.json", summary)
    primary = output / "series_registry.csv"
    report = output / "clustering_report.html"; report.write_text(html_page("C012 Series", f"<h1>Enriched ClusterのSeries化</h1><div class='card'><p>Selected clusters: {len(selected_ids)} / accepted analysis units: {len(accepted_members)}</p></div><div class='card'>{frame_html(pd.DataFrame(unit_rows))}</div>"), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary=summary, report=report, extra_artifacts=[output / "analysis_unit_membership.csv", output / "analysis_unit_registry.csv", output / "series_cluster_membership.csv", output / "compound_series_support.csv", output / "series_edges.csv", output / "series_summary.json"])


def correlations(x: pd.Series, y: pd.Series) -> tuple[float, float, float, float]:
    from scipy.stats import pearsonr, spearmanr
    valid = x.notna() & y.notna()
    if valid.sum() < 4 or x[valid].nunique() < 2 or y[valid].nunique() < 2:
        return np.nan, np.nan, np.nan, np.nan
    pcc = pearsonr(x[valid], y[valid]); spr = spearmanr(x[valid], y[valid])
    return float(pcc.statistic), float(pcc.pvalue), float(spr.statistic), float(spr.pvalue)


def run_a003(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from scipy.stats import mannwhitneyu
    parameters = request.get("parameters", {})
    correlation_threshold = float(parameters.get("correlation_threshold", .4))
    correlation_gain_threshold = float(parameters.get("correlation_gain_threshold", .2))
    median_iqr_threshold = float(parameters.get("median_iqr_threshold", .75))
    q_threshold = float(parameters.get("q_threshold", .05))
    if correlation_threshold <= 0 or correlation_gain_threshold < 0 or median_iqr_threshold <= 0 or not (0 < q_threshold <= 1):
        raise ValueError("A003 thresholds must be positive and q_threshold must satisfy 0 < q <= 1")
    data, cid, _, endpoint = dataset(request); desc, did = description_table(request, "D001"); merged = data[[cid, endpoint]].merge(desc, left_on=cid, right_on=did, how="inner")
    features, columns = numeric_features(merged, [cid, did, endpoint]); units = analysis_units(request)
    global_ids = units["GLOBAL"]; global_index = merged[cid].isin(global_ids); global_iqr = features.loc[global_index].quantile(.75) - features.loc[global_index].quantile(.25)
    global_stats: dict[str, tuple[float,float,float,float]] = {col: correlations(features[col], merged[endpoint]) for col in columns}
    rows: list[dict[str, Any]] = []
    for unit_id, members in units.items():
        mask = merged[cid].isin(members)
        if mask.sum() < 5: continue
        for column in columns:
            pcc, pp, spr, sp = correlations(features.loc[mask, column], merged.loc[mask, endpoint]); gpcc, _, gspr, _ = global_stats[column]
            shift = float(features.loc[mask, column].median() - features.loc[global_index, column].median()); scale = float(global_iqr.get(column, np.nan)); norm = shift / scale if np.isfinite(scale) and scale > 0 else np.nan
            inside = features.loc[mask, column].dropna(); outside = features.loc[global_index & ~mask, column].dropna()
            shift_p = float(mannwhitneyu(inside, outside, alternative="two-sided").pvalue) if len(inside) >= 3 and len(outside) >= 3 and pd.concat([inside, outside]).nunique() > 1 else np.nan
            rows.append({"analysis_unit_id": unit_id, "feature": column, "sample_count": int(mask.sum()), "pearson_r": pcc, "pearson_p": pp, "spearman_r": spr, "spearman_p": sp, "global_pearson_r": gpcc, "global_spearman_r": gspr, "max_abs_correlation": max(abs(pcc) if np.isfinite(pcc) else 0, abs(spr) if np.isfinite(spr) else 0), "correlation_gain": max(abs(pcc)-abs(gpcc) if np.isfinite(pcc) and np.isfinite(gpcc) else -np.inf, abs(spr)-abs(gspr) if np.isfinite(spr) and np.isfinite(gspr) else -np.inf), "median_shift": shift, "median_shift_global_iqr": norm, "shift_pvalue": shift_p})
    base_columns = [
        "analysis_unit_id", "feature", "sample_count", "pearson_r", "pearson_p",
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
    candidates = result.loc[result["analysis_unit_id"].astype(str).ne("GLOBAL")] if len(result) else result
    hit_count = int(candidates.get("strict_hit", pd.Series(dtype=bool)).sum()); near = candidates.loc[~candidates.get("strict_hit", False)].head(1) if len(candidates) else candidates
    note = f"厳格基準を満たす候補は{hit_count}件。" if hit_count else ("厳格基準を満たす候補はなく、最も近い候補は " + (f"{near.iloc[0]['analysis_unit_id']} / {near.iloc[0]['feature']} (|r|max={near.iloc[0]['max_abs_correlation']:.3f})。" if len(near) else "ありません。"))
    report = output / "operator_report.html"; report.write_text(html_page("A003 Series descriptor contrast", f"<h1>Series vs Global: D001</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(result.loc[result.get('strict_hit', False)] if len(result) else result, 200)}</div>"), encoding="utf-8")
    finish(request, output, cap, primary=primary, summary={"tested_feature_unit_pairs": len(result), "strict_hit_count": hit_count, "near_miss": near.to_dict("records") if len(near) else []}, report=report)


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
        member=coords["compound_id"].isin(units[unit_id]); fig,ax=plt.subplots(figsize=(5.2,4.2)); ax.scatter(coords.loc[~member,x],coords.loc[~member,y],s=12,c="#aeb7b8",alpha=.42); ax.scatter(coords.loc[member,x],coords.loc[member,y],s=22,c="#a65b3b",alpha=.85); ax.set_title(f"{method}: {unit_id} (n={int(member.sum())})"); ax.set_xlabel(x); ax.set_ylabel(y); fig.tight_layout(); fig.savefig(path,dpi=150); plt.close(fig)
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
    if min_n < 5 or min_r2_gain < 0:
        raise ValueError("A005 requires min_local_samples >= 5 and strict_r2_gain_min >= 0")
    for unit_id,members in units.items():
        part=merged.loc[merged[cid].isin(members)&merged[endpoint].notna()].copy(); n=len(part)
        try:
            if n < (10 if unit_id=="GLOBAL" else min_n): metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"status":"not_applicable","reason":f"sample_count<{10 if unit_id=='GLOBAL' else min_n}"}); continue
            x=part[feature_cols].apply(pd.to_numeric,errors="coerce"); y=part[endpoint].to_numpy(float)
            if x.shape[1]==0: metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"status":"not_applicable","reason":"no_usable_features"}); continue
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
                metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"status":"not_applicable","reason":"no_training_fold_had_usable_features"})
                continue
            local_r2=float(r2_score(y,pred)); local_mae=float(mean_absolute_error(y,pred)); local_spearman=float(pd.Series(y).corr(pd.Series(pred),method="spearman"))
            row={"analysis_unit_id":unit_id,"sample_count":n,"status":"succeeded","feature_count":len(stable),"oof_r2":local_r2,"oof_mae":local_mae,"oof_spearman":local_spearman,"selected_features":";".join(stable),"selection_contract":"inside_outer_cv"}
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
            metrics.append({"analysis_unit_id":unit_id,"sample_count":n,"status":"unit_failed","reason":f"{type(exc).__name__}: {exc}"})
    result=pd.DataFrame(metrics)
    if len(result) and "strict_improvement" in result:
        result["strict_improvement"]=boolean_mask(result["strict_improvement"], "strict_improvement"); result=result.sort_values(["strict_improvement","near_miss_score","analysis_unit_id"],ascending=[False,False,True],na_position="last")
    primary=output/"A005_series_feature_model.csv"; result.to_csv(primary,index=False); pred_path=output/"oof_predictions.csv"; pd.DataFrame(predictions, columns=["analysis_unit_id","compound_id","observed","oof_prediction"]).to_csv(pred_path,index=False)
    local=result.loc[result["analysis_unit_id"].astype(str).ne("GLOBAL")] if len(result) else result
    local_flags=boolean_mask(local["strict_improvement"], "strict_improvement") if "strict_improvement" in local else pd.Series(False,index=local.index)
    hits=local.loc[local_flags]; near=local.loc[~local_flags].head(1)
    note=f"Global OOFより厳格に改善したSeriesは{len(hits)}件。" if len(hits) else (f"厳格基準を満たさず、最も近い候補は{near.iloc[0]['analysis_unit_id']}（local OOF R2={near.iloc[0].get('oof_r2',np.nan):.3f}）。" if len(near) else "評価可能なSeriesはありません。")
    report=output/"operator_report.html"; report.write_text(html_page("A005 models",f"<h1>Global / Series低容量OOFモデル</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(hits)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"analysis_unit_count":len(result),"modeled_unit_count":int(result.get('status',pd.Series(dtype=str)).eq('succeeded').sum()),"strict_improvement_count":len(hits),"unit_failure_count":int(result.get('status',pd.Series(dtype=str)).eq('unit_failed').sum()),"validation":"out-of-fold predictions; Global comparator uses the same Series compounds' Global OOF predictions; no random holdout metric","near_miss":near.to_dict('records') if len(near) else []},report=report,extra_artifacts=[pred_path])


def run_a006(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from sklearn.metrics import pairwise_distances

    parameters = request.get("parameters", {})
    metric = str(parameters.get("metric", "tanimoto")).lower()
    if metric != "tanimoto":
        raise ValueError("A006 uses D002 Morgan bits and therefore requires metric='tanimoto'")
    similarity_threshold = float(parameters.get("similarity_threshold", .8))
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
        boundary_count = 0; boundary_direction = np.nan
        if unit_id != "GLOBAL" and len(boundary_indices):
            boundary_similarity = sim[np.ix_(indices, boundary_indices)]
            boundary_delta = delta[np.ix_(indices, boundary_indices)]
            boundary_mask = (boundary_similarity >= similarity_threshold) & (boundary_delta >= endpoint_delta_threshold)
            boundary_count = int(boundary_mask.sum())
            if boundary_count:
                inside_values = endpoint_values[indices][:, None]; outside_values = endpoint_values[boundary_indices][None, :]
                favorable = (inside_values > outside_values) if higher else (inside_values < outside_values)
                boundary_direction = float(favorable[boundary_mask].mean())
                positions = np.argwhere(boundary_mask)
                for inside_position, outside_position in positions:
                    left = indices[inside_position]; right = boundary_indices[outside_position]
                    pair_rows.append({"analysis_unit_id":unit_id,"pair_scope":"boundary","compound_id_a":merged.at[left,cid],"compound_id_b":merged.at[right,cid],"similarity":sim[left,right],"endpoint_delta":delta[left,right],"sali":sali[left,right],"series_side_favorable":bool(favorable[inside_position,outside_position])})
        strict = boundary_count >= minimum_support_pairs and np.isfinite(boundary_direction) and boundary_direction >= direction_fraction_threshold
        direction_credit = min(boundary_direction / max(direction_fraction_threshold, np.finfo(float).eps), 1.0) if np.isfinite(boundary_direction) else 0.0
        rows.append({"analysis_unit_id":unit_id,"sample_count":len(indices),"median_sali":float(np.median(values)) if len(values) else np.nan,"p95_sali":float(np.quantile(values,.95)) if len(values) else np.nan,"internal_cliff_count":int(internal_mask.sum()),"boundary_cliff_count":boundary_count,"boundary_favorable_direction_fraction":boundary_direction,"strict_boundary_hit":strict,"near_miss_score":min(boundary_count/minimum_support_pairs,1.0)*direction_credit,"status":"succeeded"})
    result = pd.DataFrame(rows)
    primary = output / "A006_series_landscape.csv"; result.to_csv(primary, index=False)
    pd.DataFrame(pair_rows, columns=["analysis_unit_id","pair_scope","compound_id_a","compound_id_b","similarity","endpoint_delta","sali","series_side_favorable"]).to_csv(pair_path, index=False)
    local = result.loc[result.get("analysis_unit_id", pd.Series(dtype=str)).astype(str).ne("GLOBAL")] if len(result) else result
    hit_flags = boolean_mask(local["strict_boundary_hit"], "strict_boundary_hit") if "strict_boundary_hit" in local else pd.Series(False, index=local.index)
    hits = local.loc[hit_flags]
    sort_columns = [column for column in ("near_miss_score", "boundary_cliff_count") if column in local.columns]
    near = local.sort_values(sort_columns, ascending=[False] * len(sort_columns), na_position="last").head(1) if len(local) and sort_columns else local.head(1)
    note = f"厳格な境界Cliff候補は{len(hits)}件。" if len(hits) else (f"厳格基準を満たさず、最も近い候補は{near.iloc[0]['analysis_unit_id']}（boundary cliffs={near.iloc[0].get('boundary_cliff_count',0)}）。" if len(near) else "評価対象なし。")
    report = output / "operator_report.html"
    report.write_text(html_page("A006 landscape",f"<h1>SALI / internal-boundary cliff</h1><div class='card'><p>{note}</p><p class='muted'>{SELECTION_BIAS_NOTE}</p></div><div class='card'>{frame_html(hits)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"analysis_unit_count":len(result),"strict_boundary_hit_count":len(hits),"global_endpoint_iqr":global_iqr,"cliff_pair_rows":len(pair_rows)},report=report,extra_artifacts=[pair_path])


def run_a007(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold
    data, cid, smiles, _ = dataset(request)
    units = analysis_units(request)
    registry_path = input_path(request, "cluster_registry", required=False)
    source_path = input_path(request, "series_cluster_membership", required=False)
    registry = read_table(registry_path, ["cluster_id", "source_cluster_id", "source_node_id"]) if registry_path else pd.DataFrame()
    source = read_table(source_path, ["series_id", "cluster_id"]) if source_path else pd.DataFrame()
    structural = {"C001", "C002", "C003", "C004"}
    timeout_seconds = int(request.get("parameters", {}).get("mcs_timeout_seconds", 60))
    if timeout_seconds < 1:
        raise ValueError("A007 mcs_timeout_seconds must be at least 1")
    rows: list[dict[str, Any]] = []
    for unit_id, members in units.items():
        if unit_id == "GLOBAL":
            continue
        try:
            found: list[dict[str, Any]] = []
            if not source.empty and not registry.empty and "series_id" in source and unit_id in set(source["series_id"].astype(str)):
                ids = source.loc[source["series_id"].astype(str).eq(unit_id), "cluster_id"].astype(str)
                part = registry.loc[registry["cluster_id"].astype(str).isin(ids) & registry["clustering_id"].astype(str).isin(structural)]
                for _, row in part.iterrows():
                    found.append({"analysis_unit_id":unit_id,"method":"source_structural_cluster","clustering_id":row.get("clustering_id"),"cluster_id":row.get("cluster_id"),"structure":row.get("structure_definition",row.get("definition","")),"support_count":row.get("sample_count"),"source_member_count":len(members),"mcs_canceled":False,"status":"succeeded","reason":""})
            if not found:
                scaffolds: dict[str, int] = {}
                subset = data.loc[data[cid].isin(members), smiles]
                mols = []
                for value in subset:
                    mol = Chem.MolFromSmiles(str(value))
                    if mol is None:
                        continue
                    mols.append(mol)
                    scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol)
                    if scaffold:
                        scaffolds[scaffold] = scaffolds.get(scaffold, 0) + 1
                for structure, count in sorted(scaffolds.items(), key=lambda item: (-item[1], item[0])):
                    found.append({"analysis_unit_id":unit_id,"method":"fallback_murcko","clustering_id":"C001","cluster_id":"","structure":structure,"support_count":count,"source_member_count":len(members),"mcs_canceled":False,"status":"succeeded","reason":""})
                if len(mols) >= 3:
                    from rdkit.Chem import rdFMCS
                    # Use every valid molecule. The timeout is explicit because
                    # silent sampling would change the Series-level MCS question.
                    mcs = rdFMCS.FindMCS(mols, timeout=timeout_seconds, ringMatchesRingOnly=True, completeRingsOnly=True)
                    query = Chem.MolFromSmarts(mcs.smartsString) if mcs.smartsString else None
                    mcs_heavy = sum(atom.GetAtomicNum() > 1 for atom in query.GetAtoms()) if query else 0
                    coverages = [mcs_heavy / max(1, sum(atom.GetAtomicNum() > 1 for atom in mol.GetAtoms())) for mol in mols]
                    found.append({"analysis_unit_id":unit_id,"method":"fallback_mcs","clustering_id":"C002","cluster_id":"","structure":mcs.smartsString,"support_count":len(mols),"source_member_count":len(members),"mcs_canceled":bool(mcs.canceled),"mcs_heavy_atoms":mcs_heavy,"mcs_min_coverage":min(coverages),"mcs_median_coverage":float(np.median(coverages)),"mcs_trivial":mcs_heavy < 3,"status":"partial_timeout" if mcs.canceled else "succeeded","reason":"MCS timeout reached" if mcs.canceled else ""})
                else:
                    found.append({"analysis_unit_id":unit_id,"method":"fallback_mcs","clustering_id":"C002","cluster_id":"","structure":"","support_count":len(mols),"source_member_count":len(members),"mcs_canceled":False,"status":"not_applicable","reason":"fewer than 3 valid molecules"})
            rows.extend(found)
        except Exception as exc:
            rows.append({"analysis_unit_id":unit_id,"method":"unit_error","clustering_id":"","cluster_id":"","structure":"","support_count":0,"source_member_count":len(members),"mcs_canceled":False,"status":"unit_failed","reason":f"{type(exc).__name__}: {exc}"})
    columns = ["analysis_unit_id","method","clustering_id","cluster_id","structure","support_count","source_member_count","mcs_canceled","mcs_heavy_atoms","mcs_min_coverage","mcs_median_coverage","mcs_trivial","status","reason"]
    result = pd.DataFrame(rows, columns=columns)
    primary = output / "A007_series_structural_signature.csv"
    result.to_csv(primary, index=False)
    report = output / "operator_report.html"
    report.write_text(html_page("A007 structures",f"<h1>Series構造由来とfallback key structures</h1><div class='card'>{frame_html(result,300)}</div>"),encoding="utf-8")
    finish(request,output,cap,primary=primary,summary={"row_count":len(result),"analysis_unit_count":result['analysis_unit_id'].nunique() if len(result) else 0,"mcs_timeout_count":int(result.get('mcs_canceled',pd.Series(dtype=bool)).fillna(False).sum()),"unit_failure_count":int(result.get('status',pd.Series(dtype=str)).eq('unit_failed').sum())},report=report)


def run_a009(request: dict[str, Any], output: Path, cap: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt
    profile=read_table(input_path(request,"cluster_profile"), ["cluster_id"]); enrichment=read_table(input_path(request,"cluster_enrichment"), ["cluster_id"]); series=read_table(input_path(request,"series_registry"), ["series_id"]); units_path=input_path(request,"analysis_unit_membership",required=False); selected=enrichment.loc[boolean_mask(enrichment["selected_for_series"], "selected_for_series")].copy() if len(enrichment) and "selected_for_series" in enrichment else enrichment.iloc[0:0].copy()
    series_clusters_path=input_path(request,"series_cluster_membership",required=False); unit_registry_path=input_path(request,"analysis_unit_registry",required=False); support_path=input_path(request,"compound_series_support",required=False)
    series_clusters=read_table(series_clusters_path, ["series_id", "candidate_series_id", "cluster_id"]) if series_clusters_path else pd.DataFrame()
    if len(series_clusters) and len(selected):
        if {"series_id","cluster_id"}.issubset(series_clusters.columns):
            selected=selected.merge(series_clusters[["series_id","cluster_id"]],on="cluster_id",how="left")
    sources=[]
    for item in inputs(request,"source"):
        path=Path(item["path"])
        if path.suffix.lower()==".csv":
            try:
                sources.append((item.get("source_capability_id","source"),read_table(path, ["compound_id", "analysis_unit_id", "cluster_id", "series_id"])))
            except Exception as exc:
                raise ValueError(
                    f"A009 could not read the succeeded upstream CSV {path} "
                    f"({item.get('source_capability_id', 'source')}): {exc}"
                ) from exc
    data,_,_,endpoint=dataset(request)
    histogram=output/"endpoint_histogram.png"; fig,ax=plt.subplots(figsize=(7.2,3.8)); ax.hist(pd.to_numeric(data[endpoint],errors="coerce").dropna(),bins=24,color="#526a73",edgecolor="white"); ax.set_title(f"Endpoint distribution: {endpoint}"); ax.set_xlabel(endpoint); ax.set_ylabel("Count"); fig.tight_layout(); fig.savefig(histogram,dpi=150); plt.close(fig)
    series_map=output/"series_map.png"; accepted=series.loc[boolean_mask(series["accepted"], "accepted")].copy() if len(series) and "accepted" in series else series.copy(); fig,ax=plt.subplots(figsize=(max(7.2,min(14,.55*max(1,len(accepted)))),4.2))
    if len(accepted):
        accepted=accepted.sort_values("favorable_fraction",ascending=False); ax.bar(accepted["series_id"].astype(str),accepted["favorable_fraction"],color="#8b654f"); ax.axhline(.5,color="#37474f",linestyle="--",linewidth=1); ax.tick_params(axis="x",rotation=70)
    else: ax.text(.5,.5,"No accepted Series; Cluster fallback is used",ha="center",va="center")
    ax.set_title("Accepted Series favorable fraction"); ax.set_ylabel("Favorable fraction"); fig.tight_layout(); fig.savefig(series_map,dpi=150); plt.close(fig)
    contact_sheets=[]
    for item in inputs(request,"source"):
        if item.get("source_capability_id")!="A004": continue
        source_dir=Path(item["path"]).parent
        for name in ("pca_series_contact_sheet.png","umap_series_contact_sheet.png"):
            source_image=source_dir/name
            if source_image.is_file():
                target_image=output/name; shutil.copy2(source_image,target_image); contact_sheets.append(target_image)
    unit_ids=[]; unit_registry=read_table(unit_registry_path, ["analysis_unit_id"]) if unit_registry_path else pd.DataFrame(); support=read_table(support_path, ["series_id", "compound_id"]) if support_path else pd.DataFrame()
    if len(unit_registry) and "analysis_unit_id" not in unit_registry.columns:
        raise ValueError("analysis_unit_registry must contain analysis_unit_id")
    if len(support) and "series_id" not in support.columns:
        raise ValueError("compound_series_support must contain series_id")
    if units_path:
        units_frame=read_table(units_path, ["analysis_unit_id", "compound_id"])
        if "analysis_unit_id" in units_frame: unit_ids=[value for value in sorted(units_frame["analysis_unit_id"].astype(str).unique()) if value!="GLOBAL"]
    def report_view(capability_id:str, source_frame:pd.DataFrame, unit_id:str|None=None)->tuple[pd.DataFrame,str]:
        frame=source_frame
        if unit_id is not None and "analysis_unit_id" in frame:
            frame=frame.loc[frame["analysis_unit_id"].astype(str).eq(unit_id)]
        elif capability_id in {"A003","A005","A006"} and "analysis_unit_id" in frame:
            frame=frame.loc[frame["analysis_unit_id"].astype(str).ne("GLOBAL")]
        rules={"A003":"strict_hit","A005":"strict_improvement","A006":"strict_boundary_hit"}; flag=rules.get(capability_id)
        if flag and flag in frame:
            hits=frame.loc[boolean_mask(frame[flag], flag)]
            if len(hits): return hits, f"厳格基準を満たす候補: {len(hits)}件"
            order="near_miss_score" if "near_miss_score" in frame else "boundary_cliff_count" if "boundary_cliff_count" in frame else None
            near=frame.sort_values(order,ascending=False,na_position="last").head(1) if order and len(frame) else frame.head(1)
            label=str(near.iloc[0].get("feature",near.iloc[0].get("analysis_unit_id","候補"))) if len(near) else "なし"
            return near.iloc[0:0], f"厳格基準を満たす候補はなく、最も近い候補は{label}でした。"
        return frame, ""
    highlights={}
    for name,source_frame in sources:
        if str(name) in {"A004","A008"}: continue
        chosen,note=report_view(str(name),source_frame)
        highlights[str(name)]={"note":note,"rows":chosen.head(10).to_dict("records")}
    index={"schema_version":"1.0.0","selected_cluster_count":len(selected),"series_count":len(accepted),"analysis_unit_count":len(unit_ids),"selected_cluster_preview":selected.head(25).to_dict("records"),"series_overview":series.head(24).to_dict("records"),"analysis_unit_overview":unit_registry.head(100).to_dict("records"),"operator_highlights":highlights,"detail_reports":[]}
    contact_html="".join(f"<img src='{image_uri(path)}'>" for path in contact_sheets)
    body=f"<h1>CONDUCTOR 定型解析 Summary</h1><div class='card'><h2>Endpoint</h2><img src='{image_uri(histogram)}'></div><div class='card'><h2>Endpoint-enriched Clusters</h2><p>選抜ClusterをDescription・Clustering由来、N、FF、odds ratio、p/q、Seriesとともに示します。</p><p class='muted'>{SELECTION_BIAS_NOTE}</p>{frame_html(selected,500)}</div><div class='card'><h2>Series / fallback Cluster</h2><img src='{image_uri(series_map)}'>{frame_html(unit_registry if len(unit_registry) else series,100)}</div><div class='card'><h2>PCA / UMAP contact sheets</h2>{contact_html or '<p class=\"muted\">Projection画像なし</p>'}</div>"
    detail_artifacts=[]
    for unit_id in unit_ids:
        unit_info=unit_registry.loc[unit_registry["analysis_unit_id"].astype(str).eq(unit_id)] if len(unit_registry) else pd.DataFrame()
        source_info=pd.DataFrame()
        if {"series_id","cluster_id"}.issubset(series_clusters.columns):
            source_info=series_clusters.loc[series_clusters["series_id"].astype(str).eq(unit_id)].merge(enrichment,on="cluster_id",how="left")
        support_info=support.loc[support["series_id"].astype(str).eq(unit_id)] if len(support) else pd.DataFrame()
        definition=f"<h2>Analysis unit定義</h2>{frame_html(unit_info,5)}<h2>Source Cluster</h2>{frame_html(source_info,100)}<h2>Membership support</h2>{frame_html(support_info,100)}"
        sections=[definition]
        for name,frame in sources:
            if str(name) in {"A004","A008"}: continue
            part,note=report_view(str(name),frame,unit_id)
            sections.append(f"<h2>{html_lib.escape(str(name))}</h2><p>{html_lib.escape(note)}</p>{frame_html(part,100)}")
        images=[]
        for item in inputs(request,"source"):
            if item.get("source_capability_id")!="A004": continue
            candidate=Path(item["path"]).parent/f"projection_{unit_id}.png"
            if candidate.is_file():
                images.append(f"<h2>PCA / UMAP</h2><img src='{image_uri(candidate)}'>")
        path=output/f"series_{unit_id}.html"; path.write_text(html_page(f"Analysis unit {unit_id}",f"<h1>Analysis unit {unit_id}</h1>"+"".join(images+sections)),encoding="utf-8"); index["detail_reports"].append({"analysis_unit_id":unit_id,"path":path.name}); detail_artifacts.append(path)
    detail_links="".join(f"<li><a href='{html_lib.escape(item['path'])}'>{html_lib.escape(item['analysis_unit_id'])}</a></li>" for item in index["detail_reports"])
    body += f"<div class='card'><h2>Analysis unit詳細Report</h2><ul>{detail_links or '<li>該当するSeries / fallback Clusterなし</li>'}</ul></div>"
    report=output/"standard_summary.html"; report.write_text(html_page("CONDUCTOR standard report",body),encoding="utf-8"); primary=output/"standard_report_index.json"; write_json(primary,index); finish(request,output,cap,primary=primary,summary=index,report=report,extra_artifacts=[histogram,series_map,*contact_sheets,*detail_artifacts])


def main() -> int:
    request, output, capability = parse_request(); cid = capability["capability_id"]
    dispatch = {"A001":run_a001,"A002":run_a002,"C012":run_c012,"A003":run_a003,"A004":run_a004,"A005":run_a005,"A006":run_a006,"A007":run_a007,"A009":run_a009}
    if cid not in dispatch: raise ValueError(f"Unsupported batch capability: {cid}")
    dispatch[cid](request, output, capability)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
