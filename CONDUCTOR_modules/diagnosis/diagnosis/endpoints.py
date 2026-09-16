"""Stage 1: Endpoint 分布、カラム間の重なり、欠測パターンと選択バイアス。

目的:
  - 各 Endpoint の分布と有効件数を把握する（B-0 の前提）
  - 評価系カラム間に重なりがあるか（統合可能性の判定）
  - 欠測が系統的か（選択バイアス。0.2.1 仕様 11.1 の必須診断）
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from .inputs import Dataset


def _describe(values: np.ndarray) -> dict[str, Any]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"n_valid": 0}
    q = np.percentile(finite, [0, 5, 25, 50, 75, 95, 100])
    return {
        "n_valid": int(finite.size),
        "mean": float(np.mean(finite)),
        "std": float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0,
        "min": float(q[0]),
        "p05": float(q[1]),
        "q1": float(q[2]),
        "median": float(q[3]),
        "q3": float(q[4]),
        "p95": float(q[5]),
        "max": float(q[6]),
        "iqr": float(q[4] - q[2]),
        "range": float(q[6] - q[0]),
    }


def run(ds: Dataset) -> dict[str, Any]:
    result: dict[str, Any] = {"n_compounds": ds.n, "distributions": {}, "overlap": [], "selection_bias": []}

    for eid, values in ds.endpoints.items():
        spec = ds.specs[eid]
        desc = _describe(values)
        desc["role"] = spec.role
        desc["higher_is_better"] = spec.higher_is_better
        desc["coverage_fraction"] = round(desc.get("n_valid", 0) / max(ds.n, 1), 4)
        result["distributions"][eid] = desc

    eids = list(ds.endpoints.keys())

    # --- カラム間の重なり（統合可能性） ---
    for i in range(len(eids)):
        for j in range(i + 1, len(eids)):
            a, b = eids[i], eids[j]
            va, vb = ds.endpoints[a], ds.endpoints[b]
            ma, mb = np.isfinite(va), np.isfinite(vb)
            both = int(np.sum(ma & mb))
            entry: dict[str, Any] = {
                "endpoint_a": a,
                "endpoint_b": b,
                "n_a_only": int(np.sum(ma & ~mb)),
                "n_b_only": int(np.sum(~ma & mb)),
                "n_both": both,
                "n_neither": int(np.sum(~ma & ~mb)),
            }
            if both >= 3:
                r = stats.pearsonr(va[ma & mb], vb[ma & mb])
                entry["pearson_r_on_overlap"] = float(r.statistic)
                entry["pearson_p_on_overlap"] = float(r.pvalue)
                entry["mean_offset_b_minus_a"] = float(
                    np.mean(vb[ma & mb] - va[ma & mb])
                )
                entry["bridgeable"] = both >= 20
            else:
                entry["bridgeable"] = False
            entry["verdict"] = (
                "橋渡し可能（重なり十分）"
                if entry["bridgeable"]
                else "橋渡し不可。別 Endpoint として扱うこと"
            )
            result["overlap"].append(entry)

    # --- 選択バイアス: ある Endpoint の測定有無で他 Endpoint の分布が違うか ---
    for target in eids:
        mt = np.isfinite(ds.endpoints[target])
        for other in eids:
            if other == target:
                continue
            vo = ds.endpoints[other]
            measured = vo[mt & np.isfinite(vo)]
            unmeasured = vo[(~mt) & np.isfinite(vo)]
            if measured.size < 5 or unmeasured.size < 5:
                continue
            u = stats.mannwhitneyu(measured, unmeasured, alternative="two-sided")
            result["selection_bias"].append(
                {
                    "measured_endpoint": target,
                    "compared_on": other,
                    "n_measured_group": int(measured.size),
                    "n_unmeasured_group": int(unmeasured.size),
                    "median_measured": float(np.median(measured)),
                    "median_unmeasured": float(np.median(unmeasured)),
                    "median_difference": float(
                        np.median(measured) - np.median(unmeasured)
                    ),
                    "mannwhitney_p": float(u.pvalue),
                    "systematic": bool(u.pvalue < 0.01),
                }
            )

    n_biased = sum(1 for e in result["selection_bias"] if e["systematic"])
    result["summary"] = {
        "n_endpoints": len(eids),
        "n_endpoint_pairs_with_overlap": sum(
            1 for e in result["overlap"] if e["n_both"] > 0
        ),
        "n_bridgeable_pairs": sum(1 for e in result["overlap"] if e["bridgeable"]),
        "n_systematic_missingness_detected": n_biased,
    }
    return result
