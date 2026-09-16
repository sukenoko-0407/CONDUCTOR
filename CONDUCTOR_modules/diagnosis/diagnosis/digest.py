"""手書きで書き写せる圧縮ダイジェストを生成する。

社内マシンから Git push できない前提のため、人間が画面を見て手で転記する。
したがって次を最優先する。

  - 行数を最小にする（目標 40 行以内）
  - 1行1概念、短い固定キー、有効数字2〜3桁
  - 行の順序を固定する（ラベルが崩れても位置で解釈できる）

設計判断に直結しない数値は載せない。全数値は JSON 側にある。
"""

from __future__ import annotations

from typing import Any


def _n(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        if v != v:  # NaN
            return "-"
        return f"{v:.{nd}f}"
    return str(v)


def render(results: dict[str, Any], meta: dict[str, Any]) -> str:
    L: list[str] = []
    A = L.append

    ep = results.get("endpoints", {}) or {}
    div = results.get("diversity", {}) or {}
    noise = results.get("noise", {}) or {}
    tr = results.get("transforms", {}) or {}
    ls = results.get("landscape", {}) or {}
    ind = results.get("independence", {}) or {}
    inp = results.get("input", {}) or {}
    frg = results.get("fragments", {}) or {}
    ctx = results.get("contexts", {}) or {}
    cnf = results.get("confounders", {}) or {}
    dry = results.get("dryrun", {}) or {}

    A("=== CONDUCTOR DIAG DIGEST ===")
    A(f"V 0.2.1 | N {inp.get('retained_compounds', '-')} | SET {meta.get('descriptor_set')} | {meta.get('elapsed_sec')}s")

    # --- Endpoint 分布 ---
    A("[EP] id n median iqr range")
    eids: list[str] = []
    for i, (eid, d) in enumerate(ep.get("distributions", {}).items(), 1):
        eids.append(eid)
        A(f"E{i} {eid} {d.get('n_valid','-')} {_n(d.get('median'))} {_n(d.get('iqr'))} {_n(d.get('range'))}")

    # --- カラム間の重なり ---
    A("[OVL] pair both verdict")
    idx = {e: f"E{i}" for i, e in enumerate(eids, 1)}
    for o in ep.get("overlap", []):
        v = "BRIDGE" if o.get("bridgeable") else "NO_BRIDGE"
        A(f"{idx.get(o['endpoint_a'],'?')}-{idx.get(o['endpoint_b'],'?')} {o['n_both']} {v}")

    # --- 選択バイアス（系統的なものだけ） ---
    A("[BIAS] measured on dmedian p sys")
    rows = [b for b in ep.get("selection_bias", []) if b.get("systematic")]
    if not rows:
        A("none")
    for b in rows[:6]:
        A(f"{idx.get(b['measured_endpoint'],'?')} {idx.get(b['compared_on'],'?')} "
          f"{_n(b['median_difference'])} {b['mannwhitney_p']:.0e} YES")

    # --- ノイズ床 ---
    A("[NOISE] method ep n values")
    m = noise.get("methods", {})
    d1 = m.get("duplicate_structures", {})
    wrote = False
    for eid in eids:
        v = d1.get(eid)
        if isinstance(v, dict) and v.get("n_pairs"):
            A(f"DUP {idx[eid]} {v['n_pairs']} med={_n(v.get('median_abs_diff'))}")
            wrote = True
    if not wrote:
        A("DUP none")
    d2 = m.get("near_identical_pairs", {})
    for eid in eids:
        v = d2.get(eid)
        if isinstance(v, dict) and v.get("n_pairs"):
            A(f"NEAR {idx[eid]} {v['n_pairs']} p10={_n(v.get('p10_abs_diff'))} "
              f"p25={_n(v.get('p25_abs_diff'))} med={_n(v.get('median_abs_diff'))}")
    n3 = tr.get("noise_floor_method3_mmp_neutral", {})
    if n3.get("n_pairs"):
        A(f"MMP {n3['n_pairs']} sd={_n(n3.get('sd_all_pairs'))} "
          f"p10={_n(n3.get('abs_delta_p10'))} p25={_n(n3.get('abs_delta_p25'))}")

    # --- 構造多様性 ---
    rs = div.get("ring_systems", {})
    ms = div.get("murcko_scaffolds", {})
    tn = div.get("tanimoto", {})
    A("[STRUCT]")
    A(f"ring distinct={rs.get('distinct_ring_systems','-')} ge5={rs.get('n_ring_systems_occurring_5plus','-')}")
    A(f"murcko distinct={ms.get('distinct_scaffolds','-')} ge5={ms.get('n_scaffolds_with_5plus','-')} "
      f"ge10={ms.get('n_scaffolds_with_10plus','-')}")
    A(f"tanimoto med={_n(tn.get('median'))} p90={_n(tn.get('p90'))} ge075={tn.get('n_pairs_ge_0_75','-')}")

    # --- 変換3クラス ---
    A("[MMP] class keys pairs transforms tf_ge3")
    short = {"terminal_substitution": "TERM", "linker_replacement": "LINK",
             "ring_system_replacement": "RING"}
    for cls, e in tr.get("transformation_classes", {}).items():
        A(f"{short.get(cls, cls)} {e.get('n_constant_keys','-')} {e.get('n_pairs','-')} "
          f"{e.get('n_distinct_transformations','-')} {e.get('n_transformations_with_3plus_pairs','-')}")

    # --- Core 類似度緩和 ---
    cr = tr.get("core_similarity_relaxation", {})
    if "n_pairs_exact_core" in cr:
        add = cr.get("n_additional_pairs_at_core_tanimoto", {})
        A(f"[CORE] exact={cr['n_pairs_exact_core']} "
          + " ".join(f"t{t}=+{v}" for t, v in add.items()))

    # --- Cliff 抽出率（代表2点のみ） ---
    A("[CLIFF] tanimoto dIQR n extractable rate")
    grid = tr.get("cliff_extraction", {}).get("grid", [])
    for r in grid:
        if (r["tanimoto_min"], r["delta_min_in_global_iqr"]) in ((0.75, 1.0), (0.85, 1.0)):
            A(f"{r['tanimoto_min']} {r['delta_min_in_global_iqr']} {r['n_cliff_pairs']} "
              f"{r['n_with_extractable_transformation']} {_n(r.get('extraction_rate'))}")

    # --- λ と L1a / L1b（空間ごとに1行へ集約） ---
    A("[LAMBDA] space struct lam_med frac>0.5")
    for sid, e in ls.get("spaces", {}).items():
        if "error" in e:
            A(f"{sid} ERR")
            continue
        byk = e.get("lambda_by_k", {})
        key = "10" if "10" in byk else (list(byk)[0] if byk else None)
        s = byk.get(key, {}) if key else {}
        st = "S" if e.get("structurality") == "structural" else "NS"
        A(f"{sid} {st} {_n(s.get('median'))} {_n(s.get('fraction_above_0_5'))}")

    A("[L1AB] space best_min_lam best_max_lam")
    best: dict[str, list[float]] = {}
    for e in ls.get("l1a_l1b", {}).values():
        sp = e["space"]
        lo, hi = e.get("l1a_min_cluster_lambda"), e.get("l1b_max_cluster_lambda")
        if lo is None or hi is None:
            continue
        cur = best.setdefault(sp, [lo, hi])
        cur[0] = max(cur[0], lo)   # L1a: 最も良い構成での「最小クラスタ λ」
        cur[1] = max(cur[1], hi)   # L1b: 最も良い構成での「最大クラスタ λ」
    for sp, (lo, hi) in best.items():
        A(f"{sp} {_n(lo)} {_n(hi)}")

    # --- L7 ---
    sf = tr.get("series_feasibility", {})
    if sf:
        A(f"[L7] series={sf.get('n_series','-')} len_ge5={sf.get('n_series_length_ge_5','-')} "
          f"pair_r3={sf.get('n_series_pairs_sharing_3plus_r_groups','-')} "
          f"pair_r5={sf.get('n_series_pairs_sharing_5plus_r_groups','-')}")

    # --- 非独立性 ---
    A("[INDEP] blocking nblocks icc neff")
    for name, e in ind.get("blockings", {}).items():
        A(f"{name} {e.get('n_blocks','-')} {_n(e.get('icc'))} {e.get('n_effective','-')}")
    s = ind.get("summary", {})
    if s:
        A(f"NEFF {s.get('n_effective_min')}-{s.get('n_effective_max')} / {s.get('n_compounds')}")

    # --- フラグメント統計（L2b の成否） ---
    cov = frg.get("fragment_context_coverage", {})
    if cov:
        A("[FRAG] L2b の前提: フラグメントは文脈を跨いで繰り返すか")
        A(f"distinct={frg.get('n_distinct_fragments','-')} "
          f"cov_med={cov.get('median','-')} cov_max={cov.get('max','-')}")
        A(f"in1={cov.get('n_in_1_context','-')} in2plus={cov.get('n_in_2plus','-')} "
          f"in5plus={cov.get('n_in_5plus','-')} in10plus={cov.get('n_in_10plus','-')}")
        lf = frg.get("lambda_fragment", {})
        if "lambda_frag" in lf:
            A(f"lambda_frag={_n(lf['lambda_frag'])} nfrag={lf.get('n_fragments','-')}")
        else:
            A(f"lambda_frag ERR {lf.get('error','')}")
        wv = frg.get("within_fragment_variation", {})
        if wv:
            A(f"within_sd med={_n(wv.get('median_sd'))} p90={_n(wv.get('p90_sd'))} "
              f"n={wv.get('n_fragments','-')}")
        sd = frg.get("series_depth", {})
        if sd:
            A(f"depth med={sd.get('median','-')} max={sd.get('max','-')} "
              f"ge5={sd.get('n_ge5','-')} ge10={sd.get('n_ge10','-')} ge20={sd.get('n_ge20','-')}")

    # --- 文脈カタログと翻訳可能性 ---
    if ctx:
        A("[CTX] 文脈カタログ")
        bp = ctx.get("by_provenance", {})
        A(f"total={ctx.get('n_contexts_total','-')} cluster={bp.get('cluster','-')} "
          f"quantile={bp.get('quantile','-')} scaffold={bp.get('scaffold','-')}")
        sz = ctx.get("size_distribution", {})
        if sz:
            A(f"size med={sz.get('median','-')} ge10={sz.get('n_ge10','-')} "
              f"ge30={sz.get('n_ge30','-')} ge100={sz.get('n_ge100','-')}")
        rd = ctx.get("redundancy", {})
        if rd:
            A(f"jaccard med={_n(rd.get('median'))} p99={_n(rd.get('p99'))} "
              f"ge09={rd.get('n_pairs_ge_0_9','-')} "
              f"dup_ctx={rd.get('n_contexts_with_a_near_duplicate_0_9','-')}")
        tr = ctx.get("translation", {})
        if "auc_median" in tr:
            A(f"translate auc_med={_n(tr['auc_median'])} p10={_n(tr.get('auc_p10'))} "
              f"ge070={_n(tr.get('fraction_auc_ge_0_70'))} "
              f"ge080={_n(tr.get('fraction_auc_ge_0_80'))} n={tr.get('n_contexts_evaluated','-')}")
        else:
            A(f"translate ERR {tr.get('error','')}")

    # --- 交絡 ---
    if cnf:
        g = cnf.get("global_confounder_r2", {})
        A("[CONF] 交絡の強さ")
        A(f"global_r2={_n(g.get('r2'))} all_tier1_r2={_n(cnf.get('all_tier1_r2'))}")
        ind_c = cnf.get("individual", {})
        A(" ".join(f"{k}={_n(v.get('pearson_r'))}" for k, v in ind_c.items()) or "-")
        w = cnf.get("within_scaffold_confounder_r2", {})
        if "median" in w:
            A(f"within_scaffold_r2 med={_n(w['median'])} p90={_n(w.get('p90'))} "
              f"n={w.get('n_scaffolds_evaluated','-')}")

    # --- ドライラン（最重要） ---
    lenses = dry.get("lenses", {})
    if lenses:
        A(f"[DRY] ドライラン perm={dry.get('n_permutations','-')} "
          f"ctx={dry.get('n_contexts','-')} series={dry.get('n_series','-')}")
        A("lens obs(3閾値) null_block(3閾値) enrich(3閾値)")
        for lens, rows in lenses.items():
            obs = "/".join(str(r["observed"]) for r in rows)
            nb = "/".join(str(r["null_block_mean"]) for r in rows)
            ng = "/".join(str(r["null_global_mean"]) for r in rows)
            en = "/".join(
                "-" if r["enrichment_vs_block_null"] is None
                else str(r["enrichment_vs_block_null"]) for r in rows
            )
            A(f"{lens} obs={obs} nb={nb} ng={ng} enr={en}")

    failed = [k for k, v in results.items() if isinstance(v, dict) and "error" in v]
    if failed:
        A(f"[FAILED] {','.join(failed)}")

    # 転記誤りの検出用。数値トークンだけから作るのでラベルの崩れには反応しない。
    A(f"[CK] {_checksum(L)}")
    A("=== END ===")
    return "\n".join(L)


def _checksum(lines: list[str]) -> str:
    """数値だけを拾ってハッシュする短いチェックサム。

    転記後に受け取り側が再計算し、一致しなければ転記誤りが判る。
    ラベルの表記揺れや空白の違いでは変化しない。
    """
    import hashlib
    import re

    tokens = re.findall(r"-?\d+(?:\.\d+)?(?:e[-+]?\d+)?", " ".join(lines), flags=re.I)
    payload = ",".join(tokens).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:6]
