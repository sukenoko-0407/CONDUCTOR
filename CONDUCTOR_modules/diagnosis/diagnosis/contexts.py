"""Stage 9: 文脈カタログのサイズ・重複度・翻訳可能性。

  A5/A6: 文脈カタログは適切なサイズか。互いに重複しすぎていないか
         → 多重比較の族サイズと Jaccard 重複排除の要否が決まる
  A7:    Tier 3 由来の文脈を Tier 1/2 記述子の語へ翻訳できるか 【死活的】
         → 「翻訳できない文脈を含む Finding は報告しない」と決めたため、
           翻訳率が低ければ Finding の大半が消える。0.1.x の「厳しすぎて 0件」の再演になる
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_predict

from .inputs import Dataset
from .landscape import SPACE_DEFS, _distance_matrix
from .structure import murcko

# 翻訳に使う Tier 1 記述子（人間が読んで意味が取れるもの）
_TIER1 = [
    "MolWt", "MolLogP", "TPSA", "NumHAcceptors", "NumHDonors",
    "NumRotatableBonds", "RingCount", "NumAromaticRings", "FractionCSP3",
    "HeavyAtomCount", "NHOHCount", "NOCount",
]


def _tier1_matrix(smiles: list[str]) -> np.ndarray:
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    funcs = dict(Descriptors.descList)
    rows = []
    for smi in smiles:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            rows.append([np.nan] * len(_TIER1))
            continue
        vals = []
        for name in _TIER1:
            try:
                v = float(funcs[name](mol))
                vals.append(v if np.isfinite(v) else np.nan)
            except Exception:
                vals.append(np.nan)
        rows.append(vals)
    mat = np.asarray(rows, dtype=float)
    col_median = np.nanmedian(mat, axis=0)
    inds = np.where(~np.isfinite(mat))
    mat[inds] = np.take(col_median, inds[1])
    std = mat.std(axis=0)
    std[std <= 0] = 1.0
    return (mat - mat.mean(axis=0)) / std


def build_catalog(
    ds: Dataset, descriptor_set: str, n_clusters_grid: list[int], n_jobs: int
) -> dict[str, Any]:
    """文脈カタログを構築し、メンバーシップを返す。"""
    contexts: dict[str, np.ndarray] = {}
    provenance: dict[str, str] = {}

    # (1) クラスタ由来
    for space_id, kind, _tier, _struct in SPACE_DEFS[descriptor_set]:
        dist = _distance_matrix(space_id, kind, ds.smiles, n_jobs)
        if dist is None:
            continue
        for nc in n_clusters_grid:
            if nc >= ds.n:
                continue
            labels = AgglomerativeClustering(
                n_clusters=nc, metric="precomputed", linkage="average"
            ).fit_predict(dist.astype(float))
            for c in range(nc):
                members = labels == c
                if members.sum() >= 5:
                    cid = f"CL|{space_id}|k{nc}|c{c}"
                    contexts[cid] = members
                    provenance[cid] = "cluster"

    # (2) Tier 1 特徴量の分位分割
    t1 = _tier1_matrix(ds.smiles)
    for j, name in enumerate(_TIER1):
        col = t1[:, j]
        for q in (0.25, 0.5, 0.75):
            thr = np.quantile(col, q)
            members = col <= thr
            if 5 <= members.sum() <= ds.n - 5:
                cid = f"QT|{name}|q{int(q*100)}"
                contexts[cid] = members
                provenance[cid] = "quantile"

    # (3) 骨格クラス
    scaffolds = [murcko(m) for m in ds.mols]
    uniq = {s for s in scaffolds if s}
    for s in uniq:
        members = np.asarray([x == s for x in scaffolds])
        if members.sum() >= 5:
            cid = f"SC|{abs(hash(s)) % 10**8}"
            contexts[cid] = members
            provenance[cid] = "scaffold"

    return {"contexts": contexts, "provenance": provenance}


def run(
    ds: Dataset, descriptor_set: str, n_clusters_grid: list[int], n_jobs: int,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = catalog or build_catalog(ds, descriptor_set, n_clusters_grid, n_jobs)
    contexts = catalog["contexts"]
    provenance = catalog["provenance"]

    result: dict[str, Any] = {
        "n_contexts_total": len(contexts),
        "by_provenance": {
            k: sum(1 for v in provenance.values() if v == k)
            for k in ("cluster", "quantile", "scaffold")
        },
    }

    sizes = np.asarray([int(m.sum()) for m in contexts.values()])
    if sizes.size:
        result["size_distribution"] = {
            "median": int(np.median(sizes)),
            "min": int(sizes.min()),
            "max": int(sizes.max()),
            "n_ge10": int(np.sum(sizes >= 10)),
            "n_ge30": int(np.sum(sizes >= 30)),
            "n_ge100": int(np.sum(sizes >= 100)),
        }

    # --- A6: 重複度。多重比較の族サイズを実質的に決める ---
    ids = list(contexts)
    if len(ids) > 1200:  # 総当たりが重い場合は無作為抽出で推定
        rng = np.random.default_rng(0)
        ids = list(rng.choice(ids, 1200, replace=False))
        result["jaccard_note"] = "文脈数が多いため 1200 件を無作為抽出して推定"

    mat = np.vstack([contexts[i] for i in ids])
    inter = mat.astype(np.int32) @ mat.astype(np.int32).T
    card = mat.sum(axis=1).astype(np.int32)
    union = card[:, None] + card[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        jac = np.where(union > 0, inter / union, 0.0)
    iu = np.triu_indices(len(ids), k=1)
    vals = jac[iu]
    result["redundancy"] = {
        "description": "文脈ペアの Jaccard。高いペアが多いほど実質的な独立文脈数は少ない",
        "n_pairs": int(vals.size),
        "median": float(np.median(vals)),
        "p99": float(np.percentile(vals, 99)),
        "n_pairs_ge_0_8": int(np.sum(vals >= 0.8)),
        "n_pairs_ge_0_9": int(np.sum(vals >= 0.9)),
        "n_contexts_with_a_near_duplicate_0_9": int(
            np.sum((jac >= 0.9).sum(axis=1) > 1)
        ),
    }

    # --- A7: 翻訳可能性 【死活的】 ---
    t1 = _tier1_matrix(ds.smiles)
    cluster_ids = [i for i in ids if provenance[i] == "cluster"]
    rng = np.random.default_rng(1)
    sample = list(rng.choice(cluster_ids, min(200, len(cluster_ids)), replace=False)) \
        if cluster_ids else []

    aucs: list[float] = []
    for cid in sample:
        y = contexts[cid].astype(int)
        if y.sum() < 8 or (len(y) - y.sum()) < 8:
            continue
        try:
            pred = cross_val_predict(
                LogisticRegression(max_iter=2000, C=1.0),
                t1, y, cv=3, method="predict_proba",
            )[:, 1]
            aucs.append(float(roc_auc_score(y, pred)))
        except Exception:
            continue

    if aucs:
        arr = np.asarray(aucs)
        result["translation"] = {
            "description": (
                "Tier 3 由来クラスタを Tier 1 記述子から判別できるか（3-fold CV AUC）。"
                "翻訳できない文脈を含む Finding は報告しない規則のため、"
                "この分布が低いと Finding の大半が消える"
            ),
            "n_contexts_evaluated": int(arr.size),
            "auc_median": float(np.median(arr)),
            "auc_p10": float(np.percentile(arr, 10)),
            "auc_p90": float(np.percentile(arr, 90)),
            "fraction_auc_ge_0_70": float(np.mean(arr >= 0.70)),
            "fraction_auc_ge_0_80": float(np.mean(arr >= 0.80)),
            "fraction_auc_ge_0_90": float(np.mean(arr >= 0.90)),
        }
    else:
        result["translation"] = {"error": "評価可能なクラスタ文脈が無い"}

    return result
