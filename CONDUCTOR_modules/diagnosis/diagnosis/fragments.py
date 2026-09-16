"""Stage 8: フラグメント統計と λ_frag。

L2b（フラグメント寄与・Free-Wilson 型）が主力レンズになったが、その前提は未検証である。

  A11: フラグメントは文脈を跨いで繰り返し現れるか
       → 現れなければ L2b は「文脈横断で集約する」という核心を失う
  A12: 寄与はフラグメント類似度空間で滑らかか
       → 滑らかなら平滑化・未試験フラグメントへの外挿が可能
       → 滑らかでなければフラグメント水準の cliff であり個別推定が必要

変換が繰り返されなかった事実を、そのままフラグメントへ外挿してはならない。
変換の繰り返しは「2つのフラグメントが同じ文脈で共起する」ことを要求するが、
フラグメントの繰り返しは「現れる」だけでよい。要求が違うため結論も変わりうる。
"""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from .inputs import Dataset
from .transforms import _build_index


def build_fragment_table(ds: Dataset, max_cuts: int) -> dict[str, Any]:
    """末端置換の fragmentation から (系列, フラグメント, 化合物) 表を作る。"""
    index = _build_index(ds, max_cuts)
    bucket = index["terminal_substitution"]

    # series_key -> {fragment: [compound_index, ...]}
    series: dict[str, dict[str, list[int]]] = {}
    for key, members in bucket.items():
        frags: dict[str, list[int]] = collections.defaultdict(list)
        for idx, var in members:
            frags[var].append(idx)
        if len(frags) >= 2:  # R 基が2種類以上ある系列だけが情報を持つ
            series[key] = dict(frags)
    return {"series": series, "index": index}


def _contribution_table(
    series: dict[str, dict[str, list[int]]], endpoint: np.ndarray
) -> tuple[dict[str, list[float]], dict[str, set[str]]]:
    """系列平均からの偏差としてフラグメント寄与を集める。

    系列平均を引く操作が骨格主効果を除去するため、骨格交絡の制御を兼ねる。
    """
    contrib: dict[str, list[float]] = collections.defaultdict(list)
    frag_series: dict[str, set[str]] = collections.defaultdict(set)

    for skey, frags in series.items():
        vals: list[float] = []
        for idxs in frags.values():
            vals.extend(endpoint[i] for i in idxs if np.isfinite(endpoint[i]))
        if len(vals) < 2:
            continue
        mean = float(np.mean(vals))
        for frag, idxs in frags.items():
            fv = [endpoint[i] for i in idxs if np.isfinite(endpoint[i])]
            if not fv:
                continue
            contrib[frag].append(float(np.mean(fv)) - mean)
            frag_series[frag].add(skey)
    return dict(contrib), dict(frag_series)


def _lambda_fragment(
    frag_ids: list[str], values: np.ndarray, k: int = 5
) -> dict[str, Any]:
    """寄与がフラグメント類似度空間で滑らかか（λ_frag）。

    高い → 類似フラグメントは似た寄与を持つ。平滑化と未試験フラグメントへの外挿が可能
    低い → フラグメント水準の cliff。個別推定が必要
    """
    mols = [Chem.MolFromSmiles(f) for f in frag_ids]
    ok = [i for i, m in enumerate(mols) if m is not None]
    if len(ok) < k + 5:
        return {"error": "有効フラグメントが少なすぎる", "n": len(ok)}

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    fps = [gen.GetFingerprint(mols[i]) for i in ok]
    vals = values[ok]
    var = float(np.var(vals, ddof=1))
    if var <= 0:
        return {"error": "寄与の分散が 0"}

    errors: list[float] = []
    for a in range(len(fps)):
        sims = np.asarray(DataStructs.BulkTanimotoSimilarity(fps[a], fps), dtype=float)
        sims[a] = -1.0
        nb = np.argsort(-sims)[:k]
        if sims[nb].max() <= 0:
            continue
        w = sims[nb].clip(min=0)
        if w.sum() <= 0:
            continue
        pred = float(np.average(vals[nb], weights=w))
        errors.append((vals[a] - pred) ** 2)

    if not errors:
        return {"error": "近傍を構成できない"}
    mse = float(np.mean(errors))
    return {
        "n_fragments": len(ok),
        "contribution_variance": var,
        "loo_mse": mse,
        "lambda_frag": 1.0 - mse / var,
        "neighbor_k": k,
    }


def run(ds: Dataset, max_cuts: int, table: dict[str, Any] | None = None) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]

    table = table or build_fragment_table(ds, max_cuts)
    series = table["series"]
    contrib, frag_series = _contribution_table(series, endpoint)

    result: dict[str, Any] = {
        "primary_endpoint": primary,
        "n_series_with_2plus_fragments": len(series),
        "n_distinct_fragments": len(contrib),
    }

    # --- A11: フラグメントは文脈を跨いで繰り返すか 【最重要】 ---
    counts = np.asarray([len(v) for v in frag_series.values()], dtype=int)
    if counts.size:
        result["fragment_context_coverage"] = {
            "description": "各フラグメントが現れる系列（文脈）の数。L2b の成否を決める",
            "median": int(np.median(counts)),
            "mean": float(np.mean(counts)),
            "max": int(counts.max()),
            "n_in_1_context": int(np.sum(counts == 1)),
            "n_in_2plus": int(np.sum(counts >= 2)),
            "n_in_5plus": int(np.sum(counts >= 5)),
            "n_in_10plus": int(np.sum(counts >= 10)),
            "fraction_in_2plus": float(np.mean(counts >= 2)),
            "fraction_in_5plus": float(np.mean(counts >= 5)),
        }

    # --- 系列の深さ分布 ---
    depths = np.asarray([len(f) for f in series.values()], dtype=int)
    if depths.size:
        result["series_depth"] = {
            "median": int(np.median(depths)),
            "max": int(depths.max()),
            "n_ge3": int(np.sum(depths >= 3)),
            "n_ge5": int(np.sum(depths >= 5)),
            "n_ge10": int(np.sum(depths >= 10)),
            "n_ge20": int(np.sum(depths >= 20)),
        }

    # --- A12: 寄与は類似度空間で滑らかか ---
    testable = {f: v for f, v in contrib.items() if len(v) >= 2}
    result["n_fragments_with_2plus_observations"] = len(testable)
    if len(testable) >= 20:
        ids = list(testable)
        means = np.asarray([float(np.mean(testable[f])) for f in ids])
        result["lambda_fragment"] = _lambda_fragment(ids, means, k=5)
        result["contribution_spread"] = {
            "sd_across_fragments": float(np.std(means, ddof=1)),
            "p10": float(np.percentile(means, 10)),
            "median": float(np.median(means)),
            "p90": float(np.percentile(means, 90)),
        }
        # 同一フラグメントが文脈によって寄与を変えるか（L2b が探す信号そのもの）
        multi = {f: v for f, v in testable.items() if len(v) >= 3}
        if multi:
            within = np.asarray([float(np.std(v, ddof=1)) for v in multi.values()])
            result["within_fragment_variation"] = {
                "description": (
                    "同じフラグメントの寄与が文脈によってどれだけばらつくか。"
                    "大きいほど L2b（文脈依存）の信号がある"
                ),
                "n_fragments": len(multi),
                "median_sd": float(np.median(within)),
                "p90_sd": float(np.percentile(within, 90)),
            }
    else:
        result["lambda_fragment"] = {"error": "観測2回以上のフラグメントが 20 未満"}

    return result
