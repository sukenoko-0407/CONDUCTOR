"""Stage 4: 記述子空間、局所平坦性 λ、L1a / L1b の成立性。

目的:
  - λ の分布と近傍サイズ k 依存性          → B-1, B-2
  - L1a（空間 × クラスタリングの全クラスタで平坦）が実在するか → B-18
  - L1b（一部クラスタのみ平坦）がどれだけ出るか

閾値は決め打ちしない。判断に必要な「分布」を返す。
"""

from __future__ import annotations

import multiprocessing as mp
from typing import Any

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import Descriptors, rdFingerprintGenerator, rdMolDescriptors
from sklearn.cluster import AgglomerativeClustering

from .inputs import Dataset

# 空間定義: (space_id, 種別, Tier, 構造性)
#   構造性 structural = 近さが抽出可能な構造差分を意味する（Cliff 抽出に使える）
SPACE_DEFS = {
    "fast": [
        ("D001_rdkit2d", "descriptor", 1, "non_structural"),
        ("D002_morgan", "fingerprint", 3, "structural"),
        ("D003_maccs", "fingerprint", 2, "structural"),
        ("D004_atompair", "fingerprint", 3, "structural"),
        ("D005_torsion", "fingerprint", 3, "structural"),
        ("D006_fragment", "descriptor", 1, "non_structural"),
    ],
    "full": [
        ("D001_rdkit2d", "descriptor", 1, "non_structural"),
        ("D002_morgan", "fingerprint", 3, "structural"),
        ("D003_maccs", "fingerprint", 2, "structural"),
        ("D004_atompair", "fingerprint", 3, "structural"),
        ("D005_torsion", "fingerprint", 3, "structural"),
        ("D006_fragment", "descriptor", 1, "non_structural"),
        ("D007_rdkit_path", "fingerprint", 3, "structural"),
        ("D008_pattern", "fingerprint", 3, "structural"),
        ("D015_rdkit2d_extended", "descriptor", 2, "non_structural"),
    ],
}

_FRAGMENT_NAMES = [n for n, _ in Descriptors.descList if n.startswith("fr_")]
_BASIC_2D_NAMES = [
    "MolWt", "MolLogP", "TPSA", "NumHAcceptors", "NumHDonors",
    "NumRotatableBonds", "RingCount", "NumAromaticRings", "FractionCSP3",
    "HeavyAtomCount", "NHOHCount", "NOCount", "LabuteASA", "BalabanJ",
    "BertzCT", "Chi0v", "Chi1v", "Kappa1", "Kappa2", "Kappa3",
]
_DESC_FUNCS = dict(Descriptors.descList)


def _compute_one(smiles: str, space_id: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    if space_id == "D002_morgan":
        return rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(mol)
    if space_id == "D003_maccs":
        return rdMolDescriptors.GetMACCSKeysFingerprint(mol)
    if space_id == "D004_atompair":
        return rdFingerprintGenerator.GetAtomPairGenerator(fpSize=2048).GetFingerprint(mol)
    if space_id == "D005_torsion":
        return rdFingerprintGenerator.GetTopologicalTorsionGenerator(fpSize=2048).GetFingerprint(mol)
    if space_id == "D007_rdkit_path":
        return rdFingerprintGenerator.GetRDKitFPGenerator(fpSize=2048).GetFingerprint(mol)
    if space_id == "D008_pattern":
        return Chem.PatternFingerprint(mol, fpSize=2048)
    if space_id == "D001_rdkit2d":
        return [_safe(_DESC_FUNCS[n], mol) for n in _BASIC_2D_NAMES]
    if space_id == "D006_fragment":
        return [_safe(_DESC_FUNCS[n], mol) for n in _FRAGMENT_NAMES]
    if space_id == "D015_rdkit2d_extended":
        return [_safe(f, mol) for _, f in Descriptors.descList]
    raise ValueError(space_id)


def _safe(fn, mol) -> float:
    try:
        v = fn(mol)
        return float(v) if np.isfinite(v) else np.nan
    except Exception:
        return float("nan")


def _worker(args):
    smiles_chunk, space_id = args
    return [_compute_one(s, space_id) for s in smiles_chunk]


def _distance_matrix(space_id: str, kind: str, smiles: list[str], n_jobs: int) -> np.ndarray | None:
    chunks = [smiles[i::n_jobs] for i in range(n_jobs)] if n_jobs > 1 else [smiles]
    if n_jobs > 1:
        with mp.Pool(n_jobs) as pool:
            parts = pool.map(_worker, [(c, space_id) for c in chunks])
        values: list[Any] = [None] * len(smiles)
        for wi, part in enumerate(parts):
            for pos, val in enumerate(part):
                values[wi + pos * n_jobs] = val
    else:
        values = _worker((smiles, space_id))

    if any(v is None for v in values):
        return None

    n = len(values)
    if kind == "fingerprint":
        dist = np.zeros((n, n), dtype=np.float32)
        for i in range(n - 1):
            sims = DataStructs.BulkTanimotoSimilarity(values[i], values[i + 1 :])
            d = 1.0 - np.asarray(sims, dtype=np.float32)
            dist[i, i + 1 :] = d
            dist[i + 1 :, i] = d
        return dist

    mat = np.asarray(values, dtype=float)
    # 全欠損・定数列を除去し、標準化
    keep = ~np.all(~np.isfinite(mat), axis=0)
    mat = mat[:, keep]
    col_median = np.nanmedian(mat, axis=0)
    inds = np.where(~np.isfinite(mat))
    mat[inds] = np.take(col_median, inds[1])
    std = np.std(mat, axis=0)
    mat = mat[:, std > 1e-12]
    if mat.shape[1] == 0:
        return None
    mat = (mat - mat.mean(axis=0)) / mat.std(axis=0)
    sq = np.sum(mat**2, axis=1)
    d2 = np.maximum(sq[:, None] + sq[None, :] - 2.0 * (mat @ mat.T), 0.0)
    return np.sqrt(d2, dtype=np.float32)


def _loo_flatness(endpoint: np.ndarray, members: np.ndarray, global_var: float) -> float | None:
    """集合内部の leave-one-out 予測誤差から平坦性を返す。対象化合物は含めない。"""
    vals = endpoint[members]
    vals = vals[np.isfinite(vals)]
    if vals.size < 3 or global_var <= 0:
        return None
    total = vals.sum()
    loo_mean = (total - vals) / (vals.size - 1)
    mse = float(np.mean((vals - loo_mean) ** 2))
    return 1.0 - mse / global_var


def _lambda_per_compound(
    dist: np.ndarray, endpoint: np.ndarray, k: int, global_var: float
) -> np.ndarray:
    n = dist.shape[0]
    out = np.full(n, np.nan)
    order = np.argsort(dist, axis=1)
    for i in range(n):
        neigh = order[i][order[i] != i][:k]
        val = _loo_flatness(endpoint, neigh, global_var)
        if val is not None:
            out[i] = val
    return out


def _summ(arr: np.ndarray) -> dict[str, Any]:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"n": 0}
    return {
        "n": int(finite.size),
        "mean": float(np.mean(finite)),
        "p10": float(np.percentile(finite, 10)),
        "median": float(np.median(finite)),
        "p90": float(np.percentile(finite, 90)),
        "max": float(np.max(finite)),
        "fraction_above_0_3": float(np.mean(finite > 0.3)),
        "fraction_above_0_5": float(np.mean(finite > 0.5)),
        "fraction_above_0_7": float(np.mean(finite > 0.7)),
    }


def run(ds: Dataset, descriptor_set: str, neighbor_k: list[int],
        n_clusters_grid: list[int], n_jobs: int) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]
    finite = endpoint[np.isfinite(endpoint)]
    global_var = float(np.var(finite, ddof=1)) if finite.size > 1 else 0.0

    result: dict[str, Any] = {
        "primary_endpoint": primary,
        "global_variance": global_var,
        "descriptor_set": descriptor_set,
        "spaces": {},
        "l1a_l1b": {},
    }
    if global_var <= 0:
        result["error"] = "primary Endpoint の分散が 0 または有効値不足"
        return result

    for space_id, kind, tier, structurality in SPACE_DEFS[descriptor_set]:
        dist = _distance_matrix(space_id, kind, ds.smiles, n_jobs)
        if dist is None:
            result["spaces"][space_id] = {"error": "計算失敗"}
            continue

        entry: dict[str, Any] = {
            "tier": tier,
            "structurality": structurality,
            "lambda_by_k": {},
        }
        for k in neighbor_k:
            lam = _lambda_per_compound(dist, endpoint, k, global_var)
            entry["lambda_by_k"][str(k)] = _summ(lam)
        result["spaces"][space_id] = entry

        # --- L1a / L1b ---
        for n_clusters in n_clusters_grid:
            if n_clusters >= ds.n:
                continue
            labels = AgglomerativeClustering(
                n_clusters=n_clusters, metric="precomputed", linkage="average"
            ).fit_predict(dist.astype(float))

            cluster_lams: list[float] = []
            sizes: list[int] = []
            for c in range(n_clusters):
                members = np.where(labels == c)[0]
                sizes.append(int(members.size))
                val = _loo_flatness(endpoint, members, global_var)
                if val is not None:
                    cluster_lams.append(val)

            arr = np.asarray(cluster_lams) if cluster_lams else np.asarray([])
            key = f"{space_id}|k{n_clusters}"
            result["l1a_l1b"][key] = {
                "space": space_id,
                "structurality": structurality,
                "n_clusters_requested": n_clusters,
                "n_clusters_evaluable": int(arr.size),
                "cluster_size_median": int(np.median(sizes)) if sizes else 0,
                "cluster_size_max": int(max(sizes)) if sizes else 0,
                "cluster_lambda": _summ(arr),
                # L1a: 全クラスタが平坦か（複数候補閾値で表示。閾値は後で決める）
                "l1a_min_cluster_lambda": float(np.min(arr)) if arr.size else None,
                "l1b_max_cluster_lambda": float(np.max(arr)) if arr.size else None,
                "n_clusters_above_0_5": int(np.sum(arr > 0.5)) if arr.size else 0,
                "n_clusters_above_0_7": int(np.sum(arr > 0.7)) if arr.size else 0,
            }

    return result
