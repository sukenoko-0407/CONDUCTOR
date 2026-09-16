"""Stage 5-6: 変換3クラス、Cliff からの変換抽出率、L7 系列の成立性。

目的:
  - 末端置換 / リンカー置換 / 環系置換の pair 数     → L2 の実行可能性
  - core 類似度を緩めたときの pair 数の伸び（近似）  → 6b
  - 構造空間ごとの Cliff 数と変換抽出率              → 6c。Cliff 起点経路の成立性
  - 骨格ごとの R 基系列長、系列ペアの共通 R 基数     → L7 の実行可能性
  - MMP neutral ペアの分散（ノイズ床 手法3）         → B-0

注意: 診断では attachment point の対応付けを厳密に行わない（全 dummy を [*] に潰す）。
      pair 数はわずかに過大評価になりうる。実装本体では対応付けが必要。
"""

from __future__ import annotations

import collections
import itertools
from typing import Any

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from .inputs import Dataset
from .structure import ring_systems

_MIN_CONSTANT_HEAVY = 4
_MAX_VARIABLE_FRACTION = 0.6


def _heavy(frag: Chem.Mol) -> int:
    return sum(1 for a in frag.GetAtoms() if a.GetAtomicNum() > 0)


def _cut(mol: Chem.Mol, bonds: list[int]) -> list[Chem.Mol] | None:
    parts = _cut_with_indices(mol, bonds)
    return [f for f, _ in parts] if parts else None


def _cut_with_indices(
    mol: Chem.Mol, bonds: list[int]
) -> list[tuple[Chem.Mol, tuple[int, ...]]] | None:
    """切断し、(fragment, 元分子での原子インデックス) を返す。

    FragmentOnBonds は元の原子インデックスを保持し、dummy を末尾へ追加する。
    したがってインデックス集合との積で「どの断片が目的の部分か」を一意に決められる。
    """
    if not bonds:
        return None
    try:
        broken = Chem.FragmentOnBonds(
            mol, bonds, addDummies=True, dummyLabels=[(0, 0)] * len(bonds)
        )
        idx_groups = Chem.GetMolFrags(broken)
        frags = Chem.GetMolFrags(broken, asMols=True, sanitizeFrags=False)
        return list(zip(frags, idx_groups))
    except Exception:
        return None


def _smi(frag: Chem.Mol) -> str | None:
    try:
        return Chem.MolToSmiles(frag)
    except Exception:
        return None


def _acyclic_single_bonds(mol: Chem.Mol) -> list[int]:
    return [
        b.GetIdx()
        for b in mol.GetBonds()
        if not b.IsInRing()
        and b.GetBondType() == Chem.BondType.SINGLE
        and b.GetBeginAtom().GetAtomicNum() > 0
        and b.GetEndAtom().GetAtomicNum() > 0
    ]


def _n_dummies(frag: Chem.Mol) -> int:
    return sum(1 for a in frag.GetAtoms() if a.GetAtomicNum() == 0)


def fragment_molecule(mol: Chem.Mol, max_cuts: int) -> dict[str, list[tuple[str, str]]]:
    """分子を3クラスで fragmentation し、(constant_key, variable_smiles) を返す。"""
    out: dict[str, list[tuple[str, str]]] = {
        "terminal_substitution": [],
        "linker_replacement": [],
        "ring_system_replacement": [],
    }
    total_heavy = mol.GetNumHeavyAtoms()
    if total_heavy < 6:
        return out
    acyclic = _acyclic_single_bonds(mol)

    # --- 1-cut: 末端置換 ---
    for b in acyclic[:max_cuts]:
        frags = _cut(mol, [b])
        if not frags or len(frags) != 2:
            continue
        a, c = frags
        variable, constant = (a, c) if _heavy(a) <= _heavy(c) else (c, a)
        if _heavy(constant) < _MIN_CONSTANT_HEAVY:
            continue
        if _heavy(variable) > _MAX_VARIABLE_FRACTION * total_heavy:
            continue
        ks, vs = _smi(constant), _smi(variable)
        if ks and vs:
            out["terminal_substitution"].append((ks, vs))

    # --- 2-cut: リンカー/コア置換 ---
    budget = max_cuts
    for b1, b2 in itertools.combinations(acyclic, 2):
        if budget <= 0:
            break
        budget -= 1
        frags = _cut(mol, [b1, b2])
        if not frags or len(frags) != 3:
            continue
        middles = [f for f in frags if _n_dummies(f) == 2]
        outers = [f for f in frags if _n_dummies(f) == 1]
        if len(middles) != 1 or len(outers) != 2:
            continue
        variable = middles[0]
        if any(_heavy(f) < _MIN_CONSTANT_HEAVY for f in outers):
            continue
        if _heavy(variable) > _MAX_VARIABLE_FRACTION * total_heavy:
            continue
        outer_smis = sorted(filter(None, (_smi(f) for f in outers)))
        vs = _smi(variable)
        if len(outer_smis) == 2 and vs:
            out["linker_replacement"].append((" | ".join(outer_smis), vs))

    # --- N-cut: 環系置換（exocyclic bond だけを切る） ---
    for atoms in ring_systems(mol):
        exo: list[int] = []
        for b in mol.GetBonds():
            i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
            if (i in atoms) ^ (j in atoms):
                exo.append(b.GetIdx())
        if not exo or len(exo) > 4:
            continue
        parts = _cut_with_indices(mol, exo)
        if not parts or len(parts) < 2:
            continue
        # 環系の原子を含む断片が variable。dummy 数では判別できない
        # （環側も残り側も同じ dummy 数を持ちうるため）。
        ring_parts = [f for f, idxs in parts if set(idxs) & atoms]
        rest = [f for f, idxs in parts if not (set(idxs) & atoms)]
        if len(ring_parts) != 1 or not rest:
            continue
        if _heavy(ring_parts[0]) < 3:
            continue
        if sum(_heavy(f) for f in rest) < _MIN_CONSTANT_HEAVY:
            continue
        if _heavy(ring_parts[0]) > _MAX_VARIABLE_FRACTION * total_heavy:
            continue
        rest_smis = sorted(filter(None, (_smi(f) for f in rest)))
        vs = _smi(ring_parts[0])
        if rest_smis and vs:
            out["ring_system_replacement"].append((" | ".join(rest_smis), vs))

    return out


def _build_index(ds: Dataset, max_cuts: int) -> dict[str, dict[str, list[tuple[int, str]]]]:
    """class -> constant_key -> [(mol_index, variable_smiles)]"""
    index: dict[str, dict[str, list[tuple[int, str]]]] = {
        k: collections.defaultdict(list)
        for k in ("terminal_substitution", "linker_replacement", "ring_system_replacement")
    }
    for idx, mol in enumerate(ds.mols):
        frags = fragment_molecule(mol, max_cuts)
        for cls, entries in frags.items():
            seen: set[tuple[str, str]] = set()
            for key, var in entries:
                if (key, var) in seen:
                    continue
                seen.add((key, var))
                index[cls][key].append((idx, var))
    return index


def _pairs_from_index(bucket: dict[str, list[tuple[int, str]]]) -> list[tuple[int, int, str, str, str]]:
    """同じ constant key を共有し variable が異なる組を pair とする。"""
    pairs = []
    for key, members in bucket.items():
        if len(members) < 2:
            continue
        for (i, vi), (j, vj) in itertools.combinations(members, 2):
            if i == j or vi == vj:
                continue
            pairs.append((i, j, key, vi, vj))
    return pairs


def run(ds: Dataset, max_cuts: int, structural_spaces: list[str] | None = None) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]
    finite = endpoint[np.isfinite(endpoint)]
    global_iqr = (
        float(np.percentile(finite, 75) - np.percentile(finite, 25))
        if finite.size > 3
        else 0.0
    )

    result: dict[str, Any] = {
        "primary_endpoint": primary,
        "global_endpoint_iqr": global_iqr,
        "note": "attachment point の対応付けは診断では厳密に行わない。pair 数は過大評価寄り。",
    }

    index = _build_index(ds, max_cuts)

    # --- 変換3クラス別の pair 数 ---
    classes: dict[str, Any] = {}
    all_pairs: dict[str, list] = {}
    for cls, bucket in index.items():
        pairs = _pairs_from_index(bucket)
        all_pairs[cls] = pairs

        deltas = [
            endpoint[j] - endpoint[i]
            for i, j, *_ in pairs
            if np.isfinite(endpoint[i]) and np.isfinite(endpoint[j])
        ]
        transformation_counter: collections.Counter = collections.Counter()
        for _, _, _, vi, vj in pairs:
            transformation_counter[tuple(sorted((vi, vj)))] += 1

        arr = np.asarray(deltas) if deltas else np.asarray([])
        classes[cls] = {
            "n_constant_keys": len(bucket),
            "n_keys_with_2plus_members": sum(1 for v in bucket.values() if len(v) >= 2),
            "n_pairs": len(pairs),
            "n_pairs_with_both_endpoints": int(arr.size),
            "n_distinct_transformations": len(transformation_counter),
            "n_transformations_with_3plus_pairs": sum(
                1 for c in transformation_counter.values() if c >= 3
            ),
            "n_transformations_with_10plus_pairs": sum(
                1 for c in transformation_counter.values() if c >= 10
            ),
            "top20_transformation_support": [
                int(c) for _, c in transformation_counter.most_common(20)
            ],
        }
        if arr.size:
            classes[cls].update(
                {
                    "abs_delta_median": float(np.median(np.abs(arr))),
                    "abs_delta_p90": float(np.percentile(np.abs(arr), 90)),
                    "n_pairs_abs_delta_lt_0_1": int(np.sum(np.abs(arr) < 0.1)),
                    "n_pairs_abs_delta_ge_1_iqr": int(
                        np.sum(np.abs(arr) >= global_iqr) if global_iqr > 0 else 0
                    ),
                }
            )
    result["transformation_classes"] = classes

    # --- ノイズ床 手法3: neutral pair 群の分散 ---
    neutral: dict[str, Any] = {
        "description": "全クラスの MMP pair のうち |Δ| が小さい群の分散。ノイズ床の目安。"
    }
    merged_deltas = [
        endpoint[j] - endpoint[i]
        for cls in all_pairs
        for i, j, *_ in all_pairs[cls]
        if np.isfinite(endpoint[i]) and np.isfinite(endpoint[j])
    ]
    if merged_deltas:
        arr = np.asarray(merged_deltas)
        neutral.update(
            {
                "n_pairs": int(arr.size),
                "sd_all_pairs": float(np.std(arr, ddof=1)),
                "sd_inner_50pct": float(
                    np.std(
                        arr[
                            (arr >= np.percentile(arr, 25))
                            & (arr <= np.percentile(arr, 75))
                        ],
                        ddof=1,
                    )
                ),
                "abs_delta_p10": float(np.percentile(np.abs(arr), 10)),
                "abs_delta_p25": float(np.percentile(np.abs(arr), 25)),
                "abs_delta_median": float(np.median(np.abs(arr))),
            }
        )
    result["noise_floor_method3_mmp_neutral"] = neutral

    # --- core 類似度を緩めた場合の伸び（近似） ---
    result["core_similarity_relaxation"] = _core_relaxation(index)

    # --- Cliff からの変換抽出率 ---
    result["cliff_extraction"] = _cliff_extraction(ds, endpoint, index, global_iqr)

    # --- L7: 系列の成立性 ---
    result["series_feasibility"] = _series_feasibility(index)

    return result


def _core_relaxation(index) -> dict[str, Any]:
    """constant key を厳密一致から Tanimoto 緩和へ広げたときの伸びを近似する。"""
    bucket = index["terminal_substitution"]
    keys = [k for k, v in bucket.items() if len(v) >= 1]
    out: dict[str, Any] = {
        "description": (
            "Attachment 制約付き MCS の代わりに constant fragment の Morgan/Tanimoto を使った近似。"
            "厳密一致から類似一致へ緩めたとき、比較可能なペアがどれだけ増えるかを測る。"
        ),
        "n_constant_keys": len(keys),
    }
    if len(keys) < 2 or len(keys) > 4000:
        out["skipped"] = "constant key 数が少なすぎるか多すぎるため近似を省略"
        return out

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    fps, valid = [], []
    for k in keys:
        m = Chem.MolFromSmiles(k.split(" | ")[0])
        if m is not None:
            fps.append(gen.GetFingerprint(m))
            valid.append(k)

    exact_pairs = sum(len(bucket[k]) * (len(bucket[k]) - 1) // 2 for k in valid)
    thresholds = [0.9, 0.8, 0.7, 0.6]
    added = {str(t): 0 for t in thresholds}
    for i in range(len(fps) - 1):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1 :])
        ni = len(bucket[valid[i]])
        for offset, s in enumerate(sims):
            nj = len(bucket[valid[i + 1 + offset]])
            for t in thresholds:
                if s >= t:
                    added[str(t)] += ni * nj
    out["n_pairs_exact_core"] = exact_pairs
    out["n_additional_pairs_at_core_tanimoto"] = added
    return out


def _cliff_extraction(ds: Dataset, endpoint, index, global_iqr: float) -> dict[str, Any]:
    """構造空間の Cliff から変換を抽出できる割合。6c。"""
    out: dict[str, Any] = {
        "description": (
            "構造空間（Morgan/ECFP4）で Cliff を検出し、そのペアから変換が抽出できるかを測る。"
            "抽出できないペアは構造が離れすぎており、L2 の材料にならない。"
        )
    }
    if global_iqr <= 0:
        out["skipped"] = "Endpoint の IQR が 0"
        return out

    # 変換が抽出できるペア集合（クラス横断）
    extractable: set[tuple[int, int]] = set()
    for bucket in index.values():
        for members in bucket.values():
            if len(members) < 2:
                continue
            for (i, vi), (j, vj) in itertools.combinations(members, 2):
                if i != j and vi != vj:
                    extractable.add((min(i, j), max(i, j)))

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    fps = [gen.GetFingerprint(m) for m in ds.mols]

    rows = []
    for sim_cut in (0.7, 0.75, 0.8, 0.85):
        for delta_mult in (0.5, 1.0, 1.5):
            delta_cut = delta_mult * global_iqr
            n_cliff = 0
            n_extractable = 0
            for i in range(len(fps) - 1):
                if not np.isfinite(endpoint[i]):
                    continue
                sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1 :])
                for offset, s in enumerate(sims):
                    if s < sim_cut:
                        continue
                    j = i + 1 + offset
                    if not np.isfinite(endpoint[j]):
                        continue
                    if abs(endpoint[j] - endpoint[i]) < delta_cut:
                        continue
                    n_cliff += 1
                    if (i, j) in extractable:
                        n_extractable += 1
            rows.append(
                {
                    "tanimoto_min": sim_cut,
                    "delta_min_in_global_iqr": delta_mult,
                    "n_cliff_pairs": n_cliff,
                    "n_with_extractable_transformation": n_extractable,
                    "extraction_rate": round(n_extractable / n_cliff, 4) if n_cliff else None,
                }
            )
    out["grid"] = rows
    return out


def _series_feasibility(index) -> dict[str, Any]:
    """L7: 系列（同一 constant 上の R 基集合）と、系列ペアの共通 R 基数。"""
    bucket = index["terminal_substitution"]
    series = {k: {v for _, v in members} for k, members in bucket.items()}
    series = {k: v for k, v in series.items() if len(v) >= 2}

    lengths = sorted((len(v) for v in series.values()), reverse=True)
    out: dict[str, Any] = {
        "description": (
            "同一 constant（骨格側）上に並ぶ R 基集合を系列とみなす。"
            "系列ペアの共通 R 基数が L7 の成立条件を決める。"
        ),
        "n_series": len(series),
        "series_length_median": int(np.median(lengths)) if lengths else 0,
        "series_length_max": int(lengths[0]) if lengths else 0,
        "n_series_length_ge_3": sum(1 for x in lengths if x >= 3),
        "n_series_length_ge_5": sum(1 for x in lengths if x >= 5),
        "n_series_length_ge_8": sum(1 for x in lengths if x >= 8),
    }

    keys = [k for k, v in series.items() if len(v) >= 3]
    if len(keys) > 1500:
        keys = sorted(keys, key=lambda k: -len(series[k]))[:1500]
        out["series_pair_note"] = "系列数が多いため上位1500系列に限定して集計"

    common_counts: collections.Counter = collections.Counter()
    n_pairs_examined = 0
    for a, b in itertools.combinations(keys, 2):
        n_pairs_examined += 1
        shared = len(series[a] & series[b])
        if shared:
            common_counts[shared] += 1
    out["n_series_pairs_examined"] = n_pairs_examined
    out["n_series_pairs_sharing_3plus_r_groups"] = sum(
        c for k, c in common_counts.items() if k >= 3
    )
    out["n_series_pairs_sharing_5plus_r_groups"] = sum(
        c for k, c in common_counts.items() if k >= 5
    )
    out["common_r_group_count_distribution"] = {
        str(k): int(v) for k, v in sorted(common_counts.items())[:20]
    }
    return out
