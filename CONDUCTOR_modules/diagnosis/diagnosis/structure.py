"""Stage 2-3: 構造多様性と測定ノイズ床の推定。

目的:
  - 環系・骨格の多様性（L2 環系置換 / L7 の成立余地を測る）
  - Tanimoto 分布（Cliff 判定の距離下限 B-17 を決める材料）
  - 測定ノイズ床の推定（B-0。ここが決まると B-13 / B-14 が連動する）
"""

from __future__ import annotations

import collections
from typing import Any, Iterable

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold

from .inputs import Dataset


# --------------------------------------------------------------------------
# 環系の同定（縮環・スピロを一つの環系として扱う）
# --------------------------------------------------------------------------
def ring_systems(mol: Chem.Mol) -> list[frozenset[int]]:
    """原子を共有する環をまとめ、環系ごとの原子集合を返す。"""
    rings = [set(r) for r in mol.GetRingInfo().AtomRings()]
    if not rings:
        return []
    merged: list[set[int]] = []
    for ring in rings:
        overlapping = [m for m in merged if m & ring]
        if not overlapping:
            merged.append(set(ring))
            continue
        combined = set(ring)
        for m in overlapping:
            combined |= m
            merged.remove(m)
        merged.append(combined)
    return [frozenset(m) for m in merged]


def ring_system_smiles(mol: Chem.Mol, atoms: Iterable[int]) -> str | None:
    """環系のみを取り出した SMILES（環系の種類を数えるための鍵）。"""
    try:
        return Chem.MolFragmentToSmiles(mol, atomsToUse=sorted(atoms), canonical=True)
    except Exception:
        return None


def murcko(mol: Chem.Mol) -> str | None:
    try:
        return Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol))
    except Exception:
        return None


def _fp_generator():
    return rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def fingerprints(mols: list[Chem.Mol]):
    gen = _fp_generator()
    return [gen.GetFingerprint(m) for m in mols]


def _histogram(values: np.ndarray, bins: list[float]) -> dict[str, int]:
    counts, edges = np.histogram(values, bins=bins)
    return {
        f"{edges[i]:.2f}-{edges[i + 1]:.2f}": int(counts[i]) for i in range(len(counts))
    }


def run_diversity(ds: Dataset) -> dict[str, Any]:
    result: dict[str, Any] = {}

    # --- 環系 ---
    per_mol_counts: list[int] = []
    ring_sys_counter: collections.Counter = collections.Counter()
    for mol in ds.mols:
        systems = ring_systems(mol)
        per_mol_counts.append(len(systems))
        for atoms in systems:
            smi = ring_system_smiles(mol, atoms)
            if smi:
                ring_sys_counter[smi] += 1

    result["ring_systems"] = {
        "distinct_ring_systems": len(ring_sys_counter),
        "mean_ring_systems_per_molecule": float(np.mean(per_mol_counts))
        if per_mol_counts
        else 0.0,
        "ring_system_count_distribution": dict(
            collections.Counter(per_mol_counts).most_common()
        ),
        "occurrence_of_top_ring_systems": [
            int(c) for _, c in ring_sys_counter.most_common(20)
        ],
        "n_ring_systems_occurring_once": sum(
            1 for c in ring_sys_counter.values() if c == 1
        ),
        "n_ring_systems_occurring_5plus": sum(
            1 for c in ring_sys_counter.values() if c >= 5
        ),
    }

    # --- Murcko 骨格 ---
    murcko_counter: collections.Counter = collections.Counter()
    for mol in ds.mols:
        s = murcko(mol)
        if s:
            murcko_counter[s] += 1
    sizes = sorted(murcko_counter.values(), reverse=True)
    result["murcko_scaffolds"] = {
        "distinct_scaffolds": len(murcko_counter),
        "largest_scaffold_size": int(sizes[0]) if sizes else 0,
        "n_scaffolds_with_1_compound": sum(1 for c in sizes if c == 1),
        "n_scaffolds_with_5plus": sum(1 for c in sizes if c >= 5),
        "n_scaffolds_with_10plus": sum(1 for c in sizes if c >= 10),
        "top20_scaffold_sizes": [int(c) for c in sizes[:20]],
        "fraction_in_top10_scaffolds": round(
            float(sum(sizes[:10]) / max(sum(sizes), 1)), 4
        ),
    }

    # --- Tanimoto 分布（全ペア。1000化合物なら約50万ペアで許容範囲） ---
    fps = fingerprints(ds.mols)
    sims: list[float] = []
    for i in range(len(fps) - 1):
        sims.extend(DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1 :]))
    sims_arr = np.asarray(sims, dtype=float)
    if sims_arr.size:
        result["tanimoto"] = {
            "n_pairs": int(sims_arr.size),
            "mean": float(np.mean(sims_arr)),
            "median": float(np.median(sims_arr)),
            "p90": float(np.percentile(sims_arr, 90)),
            "p99": float(np.percentile(sims_arr, 99)),
            "max": float(np.max(sims_arr)),
            "histogram": _histogram(
                sims_arr, [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.01]
            ),
            "n_pairs_ge_0_75": int(np.sum(sims_arr >= 0.75)),
            "n_pairs_ge_0_90": int(np.sum(sims_arr >= 0.90)),
        }
    else:
        result["tanimoto"] = {"n_pairs": 0}

    return result


def run_noise_floor(ds: Dataset) -> dict[str, Any]:
    """測定ノイズ床の推定。手法1と2をここで、手法3は transforms 側で行う。"""
    result: dict[str, Any] = {"methods": {}}

    # --- 手法1: 同一 canonical 構造が別 ID で登録されている場合 ---
    by_structure: dict[str, list[int]] = collections.defaultdict(list)
    for idx, smi in enumerate(ds.smiles):
        by_structure[smi].append(idx)
    dup_groups = [v for v in by_structure.values() if len(v) > 1]

    method1: dict[str, Any] = {
        "description": "同一 canonical 構造が別 compound ID で登録されている組の Endpoint 差",
        "n_duplicate_structure_groups": len(dup_groups),
    }
    for eid, values in ds.endpoints.items():
        diffs: list[float] = []
        for group in dup_groups:
            vals = [values[i] for i in group if np.isfinite(values[i])]
            for a in range(len(vals)):
                for b in range(a + 1, len(vals)):
                    diffs.append(abs(vals[a] - vals[b]))
        if diffs:
            arr = np.asarray(diffs)
            method1[eid] = {
                "n_pairs": int(arr.size),
                "median_abs_diff": float(np.median(arr)),
                "p90_abs_diff": float(np.percentile(arr, 90)),
                "estimated_sd": float(np.median(arr) / 1.128) if arr.size else None,
            }
        else:
            method1[eid] = {"n_pairs": 0}
    result["methods"]["duplicate_structures"] = method1

    # --- 手法2: ほぼ同一構造（Tanimoto 高）ペアの Endpoint 差の下側分位 ---
    fps = fingerprints(ds.mols)
    method2: dict[str, Any] = {
        "description": (
            "Tanimoto >= 0.95 の近接ペアにおける Endpoint 差。"
            "真の構造差による変化も含むため、ノイズの上限寄りの推定になる。"
            "下側分位（p10/p25）をノイズ床の目安として読む。"
        )
    }
    near_pairs: list[tuple[int, int]] = []
    for i in range(len(fps) - 1):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1 :])
        for offset, s in enumerate(sims):
            if s >= 0.95:
                near_pairs.append((i, i + 1 + offset))
    method2["n_near_identical_pairs"] = len(near_pairs)

    for eid, values in ds.endpoints.items():
        diffs = [
            abs(values[a] - values[b])
            for a, b in near_pairs
            if np.isfinite(values[a]) and np.isfinite(values[b])
        ]
        if diffs:
            arr = np.asarray(diffs)
            method2[eid] = {
                "n_pairs": int(arr.size),
                "p10_abs_diff": float(np.percentile(arr, 10)),
                "p25_abs_diff": float(np.percentile(arr, 25)),
                "median_abs_diff": float(np.median(arr)),
            }
        else:
            method2[eid] = {"n_pairs": 0}
    result["methods"]["near_identical_pairs"] = method2

    return result
