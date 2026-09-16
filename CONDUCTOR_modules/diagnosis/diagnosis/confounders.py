"""Stage 11: 交絡の強さ。

  A20: 交絡（MW / logP / TPSA）は実在するか。Endpoint 分散の何%を説明するか
  A21: 交絡調整後に非自明な信号が残るか

0.1.x で「通っても通らなくても注目に値しない」状態を生んだのは、
範囲制限下でなお残る相関がほぼ確実にサイズか脂溶性の軸だったからである。

ここで測るのは2点。

  (1) 交絡が Endpoint をどれだけ説明するか（強すぎると全 Finding が trivial になる）
  (2) 文脈内でも交絡が効くか（Global だけの効果なら文脈解析は汚染されない）
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .contexts import _tier1_matrix
from .inputs import Dataset
from .structure import murcko

_CONFOUNDERS = ["MolWt", "MolLogP", "TPSA"]
_TIER1_INDEX = {
    "MolWt": 0, "MolLogP": 1, "TPSA": 2, "NumHAcceptors": 3, "NumHDonors": 4,
    "NumRotatableBonds": 5, "RingCount": 6, "NumAromaticRings": 7,
    "FractionCSP3": 8, "HeavyAtomCount": 9, "NHOHCount": 10, "NOCount": 11,
}


def _r2(X: np.ndarray, y: np.ndarray) -> float | None:
    m = np.isfinite(y)
    if m.sum() < 20:
        return None
    Xm = np.column_stack([np.ones(m.sum()), X[m]])
    ym = y[m]
    try:
        beta, *_ = np.linalg.lstsq(Xm, ym, rcond=None)
    except np.linalg.LinAlgError:
        return None
    pred = Xm @ beta
    ss_res = float(np.sum((ym - pred) ** 2))
    ss_tot = float(np.sum((ym - ym.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else None


def run(ds: Dataset) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]
    t1 = _tier1_matrix(ds.smiles)

    result: dict[str, Any] = {"primary_endpoint": primary}

    # --- 個別の交絡と Endpoint の相関 ---
    singles = {}
    for name in _CONFOUNDERS:
        col = t1[:, _TIER1_INDEX[name]]
        m = np.isfinite(endpoint)
        if m.sum() >= 20 and np.std(col[m]) > 0:
            r = float(np.corrcoef(col[m], endpoint[m])[0, 1])
            singles[name] = {"pearson_r": round(r, 4), "r2": round(r * r, 4)}
    result["individual"] = singles

    # --- 3交絡をまとめた説明力 ---
    cols = [_TIER1_INDEX[n] for n in _CONFOUNDERS]
    r2_global = _r2(t1[:, cols], endpoint)
    result["global_confounder_r2"] = {
        "description": "MW / logP / TPSA が Endpoint 分散の何割を説明するか",
        "r2": round(r2_global, 4) if r2_global is not None else None,
        "verdict": (
            "強い。多くの Finding が trivial 判定になる" if (r2_global or 0) >= 0.3
            else "中程度。非自明性フィルタが意味を持つ" if (r2_global or 0) >= 0.1
            else "弱い。交絡調整はほとんど効かない"
        ),
    }

    # --- Tier1 全体（交絡の上限） ---
    r2_all = _r2(t1, endpoint)
    result["all_tier1_r2"] = round(r2_all, 4) if r2_all is not None else None

    # --- 文脈内でも交絡が効くか（骨格内で評価） ---
    scaffolds = [murcko(m) for m in ds.mols]
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(scaffolds):
        if s and np.isfinite(endpoint[i]):
            groups.setdefault(s, []).append(i)
    big = [idx for idx in groups.values() if len(idx) >= 20]

    within = []
    for idx in big:
        r2 = _r2(t1[np.ix_(idx, cols)], endpoint[idx])
        if r2 is not None:
            within.append(r2)
    if within:
        arr = np.asarray(within)
        result["within_scaffold_confounder_r2"] = {
            "description": (
                "骨格内でも交絡が Endpoint を説明するか。"
                "Global でだけ効くなら文脈解析は汚染されにくい"
            ),
            "n_scaffolds_evaluated": int(arr.size),
            "median": round(float(np.median(arr)), 4),
            "p90": round(float(np.percentile(arr, 90)), 4),
            "n_above_0_3": int(np.sum(arr >= 0.3)),
        }
    else:
        result["within_scaffold_confounder_r2"] = {
            "error": "20化合物以上の骨格が不足"
        }

    return result
