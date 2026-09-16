"""Stage 7: データの非独立性（擬似反復）の概況。F-1。

congeneric な SAR データでは化合物が互いに強く相関しており、実効標本サイズは
化合物数より小さい。独立性を仮定した検定は p 値を楽観的に見積もる。

級内相関 (ICC) から design effect を求め、実効標本サイズを見積もる。
"""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
from rdkit import DataStructs

from .inputs import Dataset
from .structure import fingerprints, murcko, ring_systems, ring_system_smiles


def _icc_and_neff(endpoint: np.ndarray, labels: list[Any]) -> dict[str, Any]:
    """一元配置分散分析による級内相関と実効標本サイズ。"""
    groups: dict[Any, list[float]] = collections.defaultdict(list)
    for value, label in zip(endpoint, labels):
        if np.isfinite(value) and label is not None:
            groups[label].append(float(value))
    groups = {k: v for k, v in groups.items() if v}

    n_total = sum(len(v) for v in groups.values())
    k = len(groups)
    if k < 2 or n_total <= k:
        return {"n_blocks": k, "n_total": n_total, "icc": None, "n_effective": n_total}

    grand = np.mean([x for v in groups.values() for x in v])
    ss_between = sum(len(v) * (np.mean(v) - grand) ** 2 for v in groups.values())
    ss_within = sum(sum((np.asarray(v) - np.mean(v)) ** 2) for v in groups.values())
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n_total - k)

    sizes = np.asarray([len(v) for v in groups.values()], dtype=float)
    m0 = (n_total - (sizes**2).sum() / n_total) / (k - 1)
    if m0 <= 0 or ms_between <= 0:
        icc = 0.0
    else:
        var_between = max((ms_between - ms_within) / m0, 0.0)
        denom = var_between + ms_within
        icc = float(var_between / denom) if denom > 0 else 0.0

    mean_size = n_total / k
    design_effect = 1.0 + (mean_size - 1.0) * icc
    return {
        "n_blocks": k,
        "n_total": n_total,
        "mean_block_size": round(mean_size, 2),
        "max_block_size": int(sizes.max()),
        "icc": round(icc, 4),
        "design_effect": round(design_effect, 3),
        "n_effective": int(round(n_total / design_effect)) if design_effect > 0 else n_total,
    }


def _butina_like(fps, cutoff: float) -> list[int]:
    """単純な逐次クラスタリング（Butina 近似）。ブロック定義の一つとして使う。"""
    n = len(fps)
    assigned = [-1] * n
    cluster = 0
    for i in range(n):
        if assigned[i] != -1:
            continue
        assigned[i] = cluster
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps)
        for j, s in enumerate(sims):
            if assigned[j] == -1 and s >= cutoff:
                assigned[j] = cluster
        cluster += 1
    return assigned


def run(ds: Dataset) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]

    result: dict[str, Any] = {
        "primary_endpoint": primary,
        "n_compounds": ds.n,
        "blockings": {},
        "note": (
            "実効標本サイズが化合物数より大幅に小さい場合、独立性を仮定した検定は"
            "偽陽性を量産する。帰無分布をブロック構造を保った並べ替えで作る必要がある。"
        ),
    }

    # ブロック定義1: Murcko 骨格
    murcko_labels = [murcko(m) for m in ds.mols]
    result["blockings"]["murcko_scaffold"] = _icc_and_neff(endpoint, murcko_labels)
    sizes = collections.Counter(x for x in murcko_labels if x)
    result["blockings"]["murcko_scaffold"]["size_histogram"] = {
        "singleton": sum(1 for c in sizes.values() if c == 1),
        "2-4": sum(1 for c in sizes.values() if 2 <= c <= 4),
        "5-9": sum(1 for c in sizes.values() if 5 <= c <= 9),
        "10-29": sum(1 for c in sizes.values() if 10 <= c <= 29),
        "30plus": sum(1 for c in sizes.values() if c >= 30),
    }

    # ブロック定義2: 最大の環系
    ring_labels: list[str | None] = []
    for mol in ds.mols:
        systems = ring_systems(mol)
        if not systems:
            ring_labels.append(None)
            continue
        largest = max(systems, key=len)
        ring_labels.append(ring_system_smiles(mol, largest))
    result["blockings"]["largest_ring_system"] = _icc_and_neff(endpoint, ring_labels)

    # ブロック定義3: fingerprint クラスタ
    fps = fingerprints(ds.mols)
    for cutoff in (0.6, 0.7, 0.8):
        labels = _butina_like(fps, cutoff)
        key = f"fingerprint_cluster_t{cutoff}"
        result["blockings"][key] = _icc_and_neff(endpoint, labels)

    neffs = [
        v["n_effective"]
        for v in result["blockings"].values()
        if isinstance(v.get("n_effective"), int)
    ]
    if neffs:
        result["summary"] = {
            "n_compounds": ds.n,
            "n_effective_min": int(min(neffs)),
            "n_effective_max": int(max(neffs)),
            "shrinkage_worst_case": round(min(neffs) / max(ds.n, 1), 3),
        }
    return result
