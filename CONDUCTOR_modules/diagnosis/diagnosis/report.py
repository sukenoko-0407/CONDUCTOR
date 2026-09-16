"""診断結果を Markdown レポートへ整形する。

重要: レポートには構造・SMILES・compound ID を一切含めない。集計統計のみ。
      社内データのまま外部へ共有できることを設計要件とする。
"""

from __future__ import annotations

from typing import Any


def _f(v: Any, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "はい" if v else "いいえ"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_f(x) for x in r) + " |")
    out.append("")
    return out


def render(results: dict[str, Any], meta: dict[str, Any]) -> str:
    L: list[str] = []
    A = L.append

    A("# CONDUCTOR 0.2.1 診断レポート")
    A("")
    A("計測専用。Finding は出さない。設計判断に必要な数値のみを返す。")
    A("")
    A("**本レポートには構造・SMILES・compound ID を含まない（集計統計のみ）。**")
    A("")
    A(f"- 実行日時: {meta.get('timestamp')}")
    A(f"- 記述子セット: {meta.get('descriptor_set')}")
    A(f"- 並列プロセス数: {meta.get('n_jobs')}")
    A(f"- 所要時間: {meta.get('elapsed_sec')} 秒")
    A("")

    # ---------------- Stage 0/1 ----------------
    A("## 1. 入力と Endpoint")
    A("")
    issues = results.get("input", {})
    if issues:
        A("### 入力の健全性")
        A("")
        L.extend(_table(["項目", "件数"], [[k, v] for k, v in issues.items()]))

    ep = results.get("endpoints", {})
    if ep:
        A("### Endpoint 分布")
        A("")
        rows = []
        for eid, d in ep.get("distributions", {}).items():
            rows.append([
                eid, d.get("role"), d.get("n_valid"), d.get("coverage_fraction"),
                d.get("median"), d.get("iqr"), d.get("range"), d.get("std"),
            ])
        L.extend(_table(
            ["Endpoint", "role", "有効N", "被覆率", "中央値", "IQR", "範囲", "SD"], rows))

        A("### 評価系カラム間の重なり")
        A("")
        A("**重なりが乏しい組は統合できない**（オフセットを推定できないため）。")
        A("")
        rows = []
        for o in ep.get("overlap", []):
            rows.append([
                o["endpoint_a"], o["endpoint_b"], o["n_a_only"], o["n_b_only"],
                o["n_both"], o.get("pearson_r_on_overlap"), o["verdict"],
            ])
        L.extend(_table(["A", "B", "A のみ", "B のみ", "両方", "重なり上の r", "判定"], rows))

        A("### 欠測パターンと選択バイアス")
        A("")
        A("ある Endpoint が測定された群と未測定群で、他 Endpoint の分布が違うかを検定する。")
        A("**系統的な欠測は範囲制限を生み、0.1.x の FF 選抜と同じ罠になる。**")
        A("")
        rows = []
        for b in ep.get("selection_bias", []):
            rows.append([
                b["measured_endpoint"], b["compared_on"],
                b["n_measured_group"], b["n_unmeasured_group"],
                b["median_measured"], b["median_unmeasured"],
                b["median_difference"], f"{b['mannwhitney_p']:.2e}",
                "系統的" if b["systematic"] else "—",
            ])
        L.extend(_table(
            ["測定有無の基準", "比較対象", "測定群N", "未測定群N",
             "測定群 中央値", "未測定群 中央値", "差", "p", "判定"], rows))

    # ---------------- Stage 2 ----------------
    div = results.get("diversity", {})
    if div:
        A("## 2. 構造多様性")
        A("")
        rs = div.get("ring_systems", {})
        A("### 環系（L2 環系置換の成立余地）")
        A("")
        L.extend(_table(["項目", "値"], [
            ["異なる環系の種類数", rs.get("distinct_ring_systems")],
            ["1分子あたり平均環系数", rs.get("mean_ring_systems_per_molecule")],
            ["1回しか出現しない環系", rs.get("n_ring_systems_occurring_once")],
            ["5回以上出現する環系", rs.get("n_ring_systems_occurring_5plus")],
        ]))
        A("> 5回以上出現する環系が少ないと、環系置換ペアは成立しにくい。")
        A("")

        ms = div.get("murcko_scaffolds", {})
        A("### Murcko 骨格（L7 の成立余地）")
        A("")
        L.extend(_table(["項目", "値"], [
            ["異なる骨格数", ms.get("distinct_scaffolds")],
            ["最大骨格の化合物数", ms.get("largest_scaffold_size")],
            ["化合物1個だけの骨格", ms.get("n_scaffolds_with_1_compound")],
            ["5化合物以上の骨格", ms.get("n_scaffolds_with_5plus")],
            ["10化合物以上の骨格", ms.get("n_scaffolds_with_10plus")],
            ["上位10骨格が占める割合", ms.get("fraction_in_top10_scaffolds")],
        ]))

        tn = div.get("tanimoto", {})
        A("### Tanimoto 分布（Cliff 距離下限 B-17 の材料）")
        A("")
        L.extend(_table(["項目", "値"], [
            ["全ペア数", tn.get("n_pairs")],
            ["中央値", tn.get("median")],
            ["p90", tn.get("p90")],
            ["p99", tn.get("p99")],
            ["0.75 以上のペア数", tn.get("n_pairs_ge_0_75")],
            ["0.90 以上のペア数", tn.get("n_pairs_ge_0_90")],
        ]))

    # ---------------- Stage 3 ----------------
    noise = results.get("noise", {})
    tr = results.get("transforms", {})
    if noise or tr:
        A("## 3. 測定ノイズ床の推定（B-0）")
        A("")
        A("**ここが決まると B-13（許容性の分散閾値）と B-14（分散縮小の閾値）が連動して決まる。**")
        A("")
        m = noise.get("methods", {})
        d1 = m.get("duplicate_structures", {})
        A(f"### 手法1: 同一構造・別 ID（{d1.get('n_duplicate_structure_groups', 0)} 組）")
        A("")
        rows = []
        for k, v in d1.items():
            if isinstance(v, dict) and "n_pairs" in v:
                rows.append([k, v.get("n_pairs"), v.get("median_abs_diff"), v.get("estimated_sd")])
        L.extend(_table(["Endpoint", "ペア数", "中央値 |Δ|", "推定SD"], rows) if rows
                 else ["（該当なし）", ""])

        d2 = m.get("near_identical_pairs", {})
        A(f"### 手法2: Tanimoto ≥ 0.95 の近接ペア（{d2.get('n_near_identical_pairs', 0)} 組）")
        A("")
        A("真の構造差も含むため上限寄り。**下側分位をノイズ床の目安として読む。**")
        A("")
        rows = []
        for k, v in d2.items():
            if isinstance(v, dict) and "n_pairs" in v:
                rows.append([k, v.get("n_pairs"), v.get("p10_abs_diff"),
                             v.get("p25_abs_diff"), v.get("median_abs_diff")])
        L.extend(_table(["Endpoint", "ペア数", "p10 |Δ|", "p25 |Δ|", "中央値 |Δ|"], rows))

        n3 = tr.get("noise_floor_method3_mmp_neutral", {})
        if n3.get("n_pairs"):
            A("### 手法3: MMP pair の Δ 分布")
            A("")
            L.extend(_table(["項目", "値"], [
                ["ペア数", n3.get("n_pairs")],
                ["全ペアの SD", n3.get("sd_all_pairs")],
                ["中央50%の SD", n3.get("sd_inner_50pct")],
                ["|Δ| p10", n3.get("abs_delta_p10")],
                ["|Δ| p25", n3.get("abs_delta_p25")],
            ]))
            A("> 0.1.x の `mmp_neutral_tolerance = 0.1` がこの分布に対して妥当かを判断する。")
            A("")

    # ---------------- Stage 4 ----------------
    ls = results.get("landscape", {})
    if ls and "error" not in ls:
        A("## 4. 局所平坦性 λ と L1a / L1b（B-1, B-2, B-18）")
        A("")
        A(f"主 Endpoint: `{ls.get('primary_endpoint')}` / 全体分散: {_f(ls.get('global_variance'))}")
        A("")
        A("λ が高い = 近傍が互いの活性を予測できる（平坦）。低い = Cliff 的。")
        A("")
        A("### 空間ごとの λ 分布（近傍サイズ別）")
        A("")
        rows = []
        for sid, e in ls.get("spaces", {}).items():
            if "error" in e:
                rows.append([sid, "—", "—", "計算失敗", "", "", ""])
                continue
            for k, s in e.get("lambda_by_k", {}).items():
                rows.append([
                    sid, e.get("structurality"), k, s.get("median"),
                    s.get("p90"), s.get("fraction_above_0_5"), s.get("fraction_above_0_7"),
                ])
        L.extend(_table(
            ["空間", "構造性", "k", "λ 中央値", "λ p90", "λ>0.5 の割合", "λ>0.7 の割合"], rows))

        A("### L1a / L1b の成立性")
        A("")
        A("**L1a** = 空間 × クラスタリングの**すべての**クラスタで平坦（= 最小クラスタ λ が高い）")
        A("**L1b** = **一部**クラスタのみ平坦（= 最大クラスタ λ が高い）")
        A("")
        rows = []
        for key, e in ls.get("l1a_l1b", {}).items():
            rows.append([
                e["space"], e["n_clusters_requested"], e["n_clusters_evaluable"],
                e["cluster_size_median"],
                e.get("l1a_min_cluster_lambda"), e.get("l1b_max_cluster_lambda"),
                e.get("n_clusters_above_0_5"), e.get("n_clusters_above_0_7"),
            ])
        L.extend(_table(
            ["空間", "クラスタ数", "評価可能", "サイズ中央値",
             "最小クラスタλ (L1a)", "最大クラスタλ (L1b)", "λ>0.5 個数", "λ>0.7 個数"], rows))
        A("> 最小クラスタ λ が高い行があれば L1a が実在する。全行で低ければ **L1b 一本に絞る**判断になる。")
        A("")

    # ---------------- Stage 5 ----------------
    if tr:
        A("## 5. 変換3クラス（L2 の実行可能性）")
        A("")
        A(f"_{tr.get('note')}_")
        A("")
        rows = []
        for cls, e in tr.get("transformation_classes", {}).items():
            rows.append([
                cls, e.get("n_constant_keys"), e.get("n_pairs"),
                e.get("n_pairs_with_both_endpoints"),
                e.get("n_distinct_transformations"),
                e.get("n_transformations_with_3plus_pairs"),
                e.get("n_transformations_with_10plus_pairs"),
            ])
        L.extend(_table(
            ["変換クラス", "constant key 数", "pair 数", "両端 Endpoint 有",
             "異なる変換数", "3ペア以上の変換", "10ペア以上の変換"], rows))
        A("> **環系置換の pair 数がここで決まる。** 少なければ L7 の比重を上げる判断になる。")
        A("")

        cr = tr.get("core_similarity_relaxation", {})
        if "n_pairs_exact_core" in cr:
            A("### Core 類似度を緩めたときの伸び（6b・近似）")
            A("")
            rows = [["厳密一致", cr.get("n_pairs_exact_core")]]
            for t, v in cr.get("n_additional_pairs_at_core_tanimoto", {}).items():
                rows.append([f"Tanimoto ≥ {t} まで緩和（追加分）", v])
            L.extend(_table(["条件", "pair 数"], rows))

        ce = tr.get("cliff_extraction", {})
        if ce.get("grid"):
            A("### Cliff からの変換抽出率（6c）")
            A("")
            A("**抽出できない Cliff は構造が離れすぎており L2 の材料にならない。**")
            A("")
            rows = [[r["tanimoto_min"], r["delta_min_in_global_iqr"], r["n_cliff_pairs"],
                     r["n_with_extractable_transformation"], r["extraction_rate"]]
                    for r in ce["grid"]]
            L.extend(_table(
                ["Tanimoto 下限", "Δ 下限 (×IQR)", "Cliff 数", "変換抽出可", "抽出率"], rows))
            A("> 抽出率が低いなら Cliff 起点経路の設計を見直す必要がある。")
            A("")

        sf = tr.get("series_feasibility", {})
        if sf:
            A("## 6. L7 系列の成立性")
            A("")
            L.extend(_table(["項目", "値"], [
                ["系列数（R 基2個以上）", sf.get("n_series")],
                ["系列長 中央値", sf.get("series_length_median")],
                ["系列長 最大", sf.get("series_length_max")],
                ["長さ3以上の系列", sf.get("n_series_length_ge_3")],
                ["長さ5以上の系列", sf.get("n_series_length_ge_5")],
                ["長さ8以上の系列", sf.get("n_series_length_ge_8")],
                ["共通 R 基3個以上の系列ペア", sf.get("n_series_pairs_sharing_3plus_r_groups")],
                ["共通 R 基5個以上の系列ペア", sf.get("n_series_pairs_sharing_5plus_r_groups")],
            ]))
            A("> 共通 R 基を持つ系列ペアが十分にあれば L7 が成立する（C-13 の m を決める材料）。")
            A("")

    # ---------------- Stage 7 ----------------
    ind = results.get("independence", {})
    if ind:
        A("## 7. データの非独立性（F-1）")
        A("")
        A(ind.get("note", ""))
        A("")
        rows = []
        for name, e in ind.get("blockings", {}).items():
            rows.append([
                name, e.get("n_blocks"), e.get("mean_block_size"),
                e.get("max_block_size"), e.get("icc"),
                e.get("design_effect"), e.get("n_effective"),
            ])
        L.extend(_table(
            ["ブロック定義", "ブロック数", "平均サイズ", "最大サイズ",
             "級内相関 ICC", "design effect", "実効N"], rows))
        s = ind.get("summary", {})
        if s:
            A(f"> 化合物数 {s.get('n_compounds')} に対し、実効標本サイズは "
              f"**{s.get('n_effective_min')} 〜 {s.get('n_effective_max')}**。"
              f"最悪ケースで **{s.get('shrinkage_worst_case')} 倍**に縮む。")
            A("")
            A("> これが小さいほど、独立性を仮定した検定は偽陽性を出しやすい。"
              "ブロック構造を保った並べ替え検定が必要になる。")
            A("")

    A("---")
    A("")
    A("## このレポートの使い方")
    A("")
    A("このファイル（`diagnosis_report.md`）をそのまま設計担当へ渡してください。")
    A("構造・compound ID は含まれていません。全数値は `diagnosis_report.json` にもあります。")
    A("")
    return "\n".join(x for x in L if x is not None)
