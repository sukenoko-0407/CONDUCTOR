"""Stage 10: パイプラインのドライランと帰無較正。

初回の診断が測ったのは「入力データの性質」だった。ここで測るのは
**設計した解析がこのデータで何を出すか** である。

Finding を出すのではなく、Finding の歩留まりを測る。

  実データ    段階A N件 → 翻訳可能 → 非自明
  並べ替え    段階A M件 → 翻訳可能 → 非自明      ← これが期待偽陽性

両者の差が実シグナルである。M が N に迫るなら閾値が間違っている。

構造に依存する量（文脈、フラグメント、距離行列）は一度だけ計算し、
Endpoint だけを差し替えて並べ替えを回す。これにより B 回反復が安価になる。
"""

from __future__ import annotations

import collections
from typing import Any, Callable

import numpy as np
from scipy import stats

from .contexts import _TIER1, _tier1_matrix, build_catalog
from .fragments import _contribution_table, build_fragment_table
from .inputs import Dataset
from .landscape import SPACE_DEFS, _distance_matrix
from .structure import murcko


# --------------------------------------------------------------------------
# 並べ替え
# --------------------------------------------------------------------------
def permute_global(endpoint: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = endpoint.copy()
    finite = np.where(np.isfinite(out))[0]
    out[finite] = out[rng.permutation(finite)]
    return out


def permute_within_blocks(
    endpoint: np.ndarray, blocks: list[Any], rng: np.random.Generator
) -> np.ndarray:
    """ブロック構造を保った並べ替え。骨格主効果を帰無側へ残す。"""
    out = endpoint.copy()
    by_block: dict[Any, list[int]] = collections.defaultdict(list)
    for i, b in enumerate(blocks):
        if np.isfinite(endpoint[i]) and b is not None:
            by_block[b].append(i)
    for idxs in by_block.values():
        if len(idxs) > 1:
            out[idxs] = endpoint[rng.permutation(idxs)]
    return out


# --------------------------------------------------------------------------
# 段階A スクリーン（簡約版）
# --------------------------------------------------------------------------
def _loo_lambda(values: np.ndarray, global_var: float) -> float | None:
    v = values[np.isfinite(values)]
    if v.size < 3 or global_var <= 0:
        return None
    loo = (v.sum() - v) / (v.size - 1)
    return 1.0 - float(np.mean((v - loo) ** 2)) / global_var


def screen_l1b(endpoint, contexts, dists, global_var, thresholds) -> dict[str, int]:
    """空間 S が条件 C のもとで活性を説明するか。近傍予測で測る。"""
    counts = {str(t): 0 for t in thresholds}
    for members in contexts.values():
        idx = np.where(members)[0]
        if idx.size < 8:
            continue
        ep = endpoint[idx]
        if np.sum(np.isfinite(ep)) < 8:
            continue
        for dist in dists:
            sub = dist[np.ix_(idx, idx)]
            k = min(5, idx.size - 1)
            order = np.argsort(sub, axis=1)
            preds, obs = [], []
            for a in range(idx.size):
                if not np.isfinite(ep[a]):
                    continue
                nb = [b for b in order[a] if b != a][:k]
                nv = ep[nb]
                nv = nv[np.isfinite(nv)]
                if nv.size:
                    preds.append(float(nv.mean()))
                    obs.append(float(ep[a]))
            if len(obs) < 8:
                continue
            mse = float(np.mean((np.asarray(obs) - np.asarray(preds)) ** 2))
            lam = 1.0 - mse / global_var
            for t in thresholds:
                if lam >= t:
                    counts[str(t)] += 1
    return counts


def screen_l6(endpoint, contexts, favorable_mask, thresholds) -> dict[str, int]:
    """クラスタの活性濃縮（0.1.x の FF 選抜に相当）。"""
    counts = {str(t): 0 for t in thresholds}
    valid = np.isfinite(endpoint)
    global_ff = float(np.mean(favorable_mask[valid])) if valid.any() else 0.0
    for members in contexts.values():
        sel = members & valid
        n = int(sel.sum())
        if n < 10:
            continue
        ff = float(np.mean(favorable_mask[sel]))
        if ff <= global_ff:
            continue
        a = int(np.sum(favorable_mask[sel]))
        b = n - a
        c = int(np.sum(favorable_mask[valid])) - a
        d = int(valid.sum()) - n - c
        try:
            p = stats.fisher_exact([[a, b], [c, d]], alternative="greater")[1]
        except Exception:
            continue
        for t in thresholds:
            if ff >= 0.5 and p <= t:
                counts[str(t)] += 1
    return counts


def screen_l3(endpoint, dists, global_var, z_thresholds) -> dict[str, int]:
    """局所期待からの逸脱。2空間以上で同時に逸脱する化合物を数える。"""
    n = endpoint.shape[0]
    hits = {str(t): np.zeros(n, dtype=int) for t in z_thresholds}
    for dist in dists:
        order = np.argsort(dist, axis=1)
        resid = np.full(n, np.nan)
        for i in range(n):
            if not np.isfinite(endpoint[i]):
                continue
            nb = [b for b in order[i] if b != i][:10]
            nv = endpoint[nb]
            nv = nv[np.isfinite(nv)]
            if nv.size >= 5:
                resid[i] = endpoint[i] - float(nv.mean())
        sd = float(np.nanstd(resid, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            continue
        z = np.abs(resid) / sd
        for t in z_thresholds:
            hits[str(t)] += (z >= t).astype(int)
    return {t: int(np.sum(v >= 2)) for t, v in hits.items()}


def screen_l5(endpoint, contexts, tier1, axis_of, q_thresholds) -> dict[str, int]:
    """文脈間の符号矛盾。同一分割軸から生じた文脈ペアに限定する。"""
    counts = {str(t): 0 for t in q_thresholds}
    by_axis: dict[str, list[str]] = collections.defaultdict(list)
    for cid, axis in axis_of.items():
        by_axis[axis].append(cid)

    pvals: list[float] = []
    for axis, ids in by_axis.items():
        if len(ids) < 2 or len(ids) > 40:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                ma, mb = contexts[ids[a]], contexts[ids[b]]
                for j in range(tier1.shape[1]):
                    ra = _corr(tier1[ma, j], endpoint[ma])
                    rb = _corr(tier1[mb, j], endpoint[mb])
                    if ra is None or rb is None:
                        continue
                    if ra[0] * rb[0] >= 0 or min(abs(ra[0]), abs(rb[0])) < 0.3:
                        continue
                    p = _fisher_z_diff(ra, rb)
                    if p is not None:
                        pvals.append(p)
    if pvals:
        q = _bh(np.asarray(pvals))
        for t in q_thresholds:
            counts[str(t)] = int(np.sum(q <= t))
    return counts


def _corr(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 10 or np.std(x[m]) <= 0 or np.std(y[m]) <= 0:
        return None
    return float(np.corrcoef(x[m], y[m])[0, 1]), int(m.sum())


def _fisher_z_diff(ra, rb) -> float | None:
    (r1, n1), (r2, n2) = ra, rb
    if n1 < 6 or n2 < 6 or abs(r1) >= 1 or abs(r2) >= 1:
        return None
    z1, z2 = np.arctanh(r1), np.arctanh(r2)
    se = np.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
    return float(2 * (1 - stats.norm.cdf(abs(z1 - z2) / se)))


def _bh(p: np.ndarray) -> np.ndarray:
    n = p.size
    order = np.argsort(p)
    q = np.empty(n)
    prev = 1.0
    for rank in range(n - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * n / (rank + 1))
        q[i] = prev
    return q


def screen_l2b(endpoint, series, thresholds) -> dict[str, int]:
    """フラグメント寄与。文脈横断で一貫した効果を持つフラグメントを数える。"""
    contrib, frag_series = _contribution_table(series, endpoint)
    counts = {str(t): 0 for t in thresholds}
    for frag, vals in contrib.items():
        if len(vals) < 3:
            continue
        arr = np.asarray(vals)
        se = float(np.std(arr, ddof=1)) / np.sqrt(arr.size) if arr.size > 1 else np.inf
        if se <= 0 or not np.isfinite(se):
            continue
        t_stat = abs(float(arr.mean())) / se
        for t in thresholds:
            if t_stat >= t:
                counts[str(t)] += 1
    return counts


# --------------------------------------------------------------------------
# ドライラン本体
# --------------------------------------------------------------------------
def run(
    ds: Dataset, descriptor_set: str, n_clusters_grid: list[int], n_jobs: int,
    max_cuts: int, n_permutations: int = 20,
) -> dict[str, Any]:
    primary = next(
        (eid for eid, s in ds.specs.items() if s.role == "primary"),
        next(iter(ds.endpoints)),
    )
    endpoint = ds.endpoints[primary]
    finite = endpoint[np.isfinite(endpoint)]
    if finite.size < 30:
        return {"error": "primary Endpoint の有効件数が不足"}

    global_var = float(np.var(finite, ddof=1))
    spec = ds.specs[primary]
    cut = np.percentile(finite, 80 if spec.higher_is_better else 20)
    favorable = (endpoint >= cut) if spec.higher_is_better else (endpoint <= cut)
    favorable = favorable & np.isfinite(endpoint)

    # --- 構造依存の量を一度だけ計算する ---
    catalog = build_catalog(ds, descriptor_set, n_clusters_grid, n_jobs)
    contexts = catalog["contexts"]
    axis_of = {
        cid: cid.rsplit("|", 1)[0] if cid.startswith("CL") else cid.split("|")[1]
        for cid in contexts
    }
    dists = []
    for space_id, kind, _t, _s in SPACE_DEFS[descriptor_set][:3]:
        d = _distance_matrix(space_id, kind, ds.smiles, n_jobs)
        if d is not None:
            dists.append(d)
    tier1 = _tier1_matrix(ds.smiles)
    series = build_fragment_table(ds, max_cuts)["series"]
    blocks = [murcko(m) for m in ds.mols]

    lam_t = [0.3, 0.5, 0.7]
    q_t = [0.01, 0.05, 0.10]
    z_t = [2.5, 3.0, 3.5]
    t_t = [2.0, 3.0, 4.0]

    def screen(ep: np.ndarray) -> dict[str, dict[str, int]]:
        return {
            "L1b": screen_l1b(ep, contexts, dists, global_var, lam_t),
            "L2b": screen_l2b(ep, series, t_t),
            "L3": screen_l3(ep, dists, global_var, z_t),
            "L5": screen_l5(ep, contexts, tier1, axis_of, q_t),
            "L6": screen_l6(ep, contexts, favorable, q_t),
        }

    import sys as _sys
    import time as _time

    def _log(msg: str) -> None:
        print(f"    [dryrun] {msg}", flush=True, file=_sys.stderr)

    _log(f"文脈 {len(contexts)} / 空間 {len(dists)} / 系列 {len(series)} で開始")
    t0 = _time.time()
    observed = screen(endpoint)
    per_screen = _time.time() - t0
    _log(f"実データのスクリーン完了 ({per_screen:.1f}s)")
    _log(f"並べ替え {n_permutations} 回 × 2 種 → 推定 {per_screen * n_permutations * 2 / 60:.1f} 分")

    rng = np.random.default_rng(20260916)
    null_global: list[dict] = []
    null_block: list[dict] = []
    for _p in range(n_permutations):
        null_global.append(screen(permute_global(endpoint, rng)))
        ep_b = permute_within_blocks(endpoint, blocks, rng)
        fav_b = ((ep_b >= cut) if spec.higher_is_better else (ep_b <= cut)) & np.isfinite(ep_b)
        null_block.append({
            "L1b": screen_l1b(ep_b, contexts, dists, global_var, lam_t),
            "L2b": screen_l2b(ep_b, series, t_t),
            "L3": screen_l3(ep_b, dists, global_var, z_t),
            "L5": screen_l5(ep_b, contexts, tier1, axis_of, q_t),
            "L6": screen_l6(ep_b, contexts, fav_b, q_t),
        })
        if (_p + 1) % 5 == 0 or _p + 1 == n_permutations:
            _log(f"並べ替え {_p + 1}/{n_permutations} 完了 "
                 f"（経過 {(_time.time() - t0) / 60:.1f} 分）")

    def summarize(nulls: list[dict]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for lens in observed:
            out[lens] = {}
            for thr in observed[lens]:
                vals = [n[lens][thr] for n in nulls]
                out[lens][thr] = float(np.mean(vals))
        return out

    mean_global = summarize(null_global)
    mean_block = summarize(null_block)

    lenses: dict[str, Any] = {}
    for lens in observed:
        rows = []
        for thr in observed[lens]:
            obs = observed[lens][thr]
            ng = mean_global[lens][thr]
            nb = mean_block[lens][thr]
            rows.append({
                "threshold": thr,
                "observed": obs,
                "null_global_mean": round(ng, 1),
                "null_block_mean": round(nb, 1),
                "excess_over_block_null": round(obs - nb, 1),
                "enrichment_vs_block_null": round(obs / nb, 2) if nb > 0 else None,
                "empirical_fdr_vs_block": round(min(nb / obs, 1.0), 3) if obs > 0 else None,
            })
        lenses[lens] = rows

    return {
        "primary_endpoint": primary,
        "n_permutations": n_permutations,
        "n_contexts": len(contexts),
        "n_spaces_used": len(dists),
        "n_series": len(series),
        "note": (
            "observed が null_block_mean に迫るなら閾値が不適切。"
            "enrichment は実データ候補数 / ブロック並べ替え帰無の候補数。"
            "empirical_fdr は帰無/実測で、そのまま期待偽陽性率の目安になる。"
        ),
        "lenses": lenses,
    }
