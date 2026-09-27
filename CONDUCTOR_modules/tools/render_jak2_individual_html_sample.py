#!/usr/bin/env python3
"""Build a self-contained JAK2 MMP report sample from existing validation assets.

This is deliberately a presentation sample, not a CONDUCTOR 0.2.1 accepted
Finding.  Every compound, structure, endpoint value, and transformation shown
on the page is read from the checked-in 0.1.10 JAK2 report-validation output.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PYTHON = REPO_ROOT / ".claude" / "skills" / "cs-report" / "python"
sys.path.insert(0, str(REPORT_PYTHON))

from conductor_report.visualizations import molecule_svg  # noqa: E402


DEFAULT_SOURCE = (
    REPO_ROOT
    / "results"
    / "CONDUCTOR"
    / "report_validation"
    / "RV_CHEMBLE_JAK2_0110"
    / "operators"
    / "A008"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "CONDUCTOR_modules"
    / "docs"
    / "report_examples"
    / "CONDUCTOR_0.2.1_JAK2_MMP_individual_report_sample.html"
)
TARGET_ID = "CHEMBL3699558"
ANALYSIS_UNIT_ID = "C000003"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(value: Any, digits: int = 3) -> str:
    number = float(value)
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _molecule_panel(
    smiles: str,
    title: str,
    subtitle: str,
    *,
    highlight_smarts: str | None = None,
    featured: bool = False,
) -> str:
    svg = molecule_svg(
        smiles,
        width=420 if featured else 300,
        height=270 if featured else 205,
        highlight_smarts=highlight_smarts,
    )
    featured_class = " featured" if featured else ""
    return (
        f'<figure class="molecule{featured_class}">{svg}'
        f'<figcaption><strong>{_esc(title)}</strong><span>{_esc(subtitle)}</span>'
        f'<code>{_esc(smiles)}</code></figcaption></figure>'
    )


def _endpoint_chart(target: dict[str, str], pairs: list[dict[str, str]]) -> str:
    rows = [(TARGET_ID, float(target["target_endpoint"]), "target")]
    rows.extend(
        (row["neighbor_compound_id"], float(row["neighbor_endpoint"]), "neighbor")
        for row in pairs
    )
    rows.sort(key=lambda item: (-item[1], item[0]))
    low = min(value for _, value, _ in rows) - 0.2
    high = max(value for _, value, _ in rows) + 0.2
    width, height = 820, 92 + 64 * len(rows)
    left, right, top = 190, 42, 65
    plot_width = width - left - right

    def x(value: float) -> float:
        return left + (value - low) / (high - low) * plot_width

    elements = [
        f'<rect width="{width}" height="{height}" rx="14" fill="#fff"/>',
        '<text x="24" y="30" class="chart-title">実測JAK2 pIC50の比較</text>',
    ]
    for step in range(6):
        value = low + (high - low) * step / 5
        xpos = x(value)
        elements.append(
            f'<line x1="{xpos:.1f}" y1="{top-20}" x2="{xpos:.1f}" y2="{height-35}" stroke="#dbe4e8"/>'
            f'<text x="{xpos:.1f}" y="{height-13}" text-anchor="middle" class="tick">{value:.2f}</text>'
        )
    for index, (compound_id, value, kind) in enumerate(rows):
        ypos = top + index * 64
        color = "#075f73" if kind == "target" else "#d97706"
        elements.append(
            f'<text x="{left-14}" y="{ypos+5}" text-anchor="end" class="label">{_esc(compound_id)}</text>'
            f'<line x1="{x(low):.1f}" y1="{ypos}" x2="{x(value):.1f}" y2="{ypos}" stroke="{color}" stroke-width="12" stroke-linecap="round"/>'
            f'<circle cx="{x(value):.1f}" cy="{ypos}" r="9" fill="{color}"/>'
            f'<text x="{x(value)+16:.1f}" y="{ypos+5}" class="value">{value:.2f}</text>'
        )
    return (
        '<figure class="data-figure">'
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="JAK2 pIC50 comparison">'
        f'{"".join(elements)}</svg>'
        '<figcaption>青は注目化合物、橙は同一コアを持つ実測MMP近傍です。値は元の検証資産に記録されたpIC50です。</figcaption>'
        '</figure>'
    )


def _delta_chart(pairs: list[dict[str, str]]) -> str:
    rows = sorted(
        (
            row["neighbor_compound_id"],
            float(row["favorable_delta_toward_target"]),
        )
        for row in pairs
    )
    maximum = max(value for _, value in rows) * 1.12
    width, height = 820, 90 + 65 * len(rows)
    left, right, top = 190, 55, 65
    plot_width = width - left - right

    def x(value: float) -> float:
        return left + value / maximum * plot_width

    elements = [
        f'<rect width="{width}" height="{height}" rx="14" fill="#fff"/>',
        '<text x="24" y="30" class="chart-title">注目化合物側への活性差</text>',
    ]
    for step in range(6):
        value = maximum * step / 5
        xpos = x(value)
        elements.append(
            f'<line x1="{xpos:.1f}" y1="{top-20}" x2="{xpos:.1f}" y2="{height-35}" stroke="#dbe4e8"/>'
            f'<text x="{xpos:.1f}" y="{height-13}" text-anchor="middle" class="tick">{value:.2f}</text>'
        )
    for index, (compound_id, value) in enumerate(rows):
        ypos = top + index * 65
        elements.append(
            f'<text x="{left-14}" y="{ypos+5}" text-anchor="end" class="label">vs {_esc(compound_id)}</text>'
            f'<rect x="{left}" y="{ypos-12}" width="{max(2.0, x(value)-left):.1f}" height="24" rx="12" fill="#16744a"/>'
            f'<text x="{x(value)+12:.1f}" y="{ypos+5}" class="value">+{value:.2f}</text>'
        )
    return (
        '<figure class="data-figure">'
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="pIC50 deltas toward target">'
        f'{"".join(elements)}</svg>'
        '<figcaption>差は target pIC50 − neighbor pIC50。正値はCHEMBL3699558側が高活性であることを表します。</figcaption>'
        '</figure>'
    )


def _pair_card(target: dict[str, str], row: dict[str, str]) -> str:
    delta = float(row["favorable_delta_toward_target"])
    target_panel = _molecule_panel(
        row["target_smiles"],
        TARGET_ID,
        f'pIC50 {float(row["target_endpoint"]):.2f}',
        highlight_smarts=row["variable_target"],
    )
    neighbor_panel = _molecule_panel(
        row["neighbor_smiles"],
        row["neighbor_compound_id"],
        f'pIC50 {float(row["neighbor_endpoint"]):.2f}',
        highlight_smarts=row["variable_neighbor"],
    )
    target_fragment = _molecule_panel(
        row["variable_target"], "注目側置換基", "赤いハイライト部分"
    )
    neighbor_fragment = _molecule_panel(
        row["variable_neighbor"], "近傍側置換基", "赤いハイライト部分"
    )
    return f"""
<article class="pair-card">
  <div class="pair-heading"><div><span class="eyebrow">{_esc(row['transform_id'])}</span><h3>{_esc(row['neighbor_compound_id'])}との比較</h3></div><strong class="delta">Δ pIC50 +{delta:.2f}</strong></div>
  <div class="molecule-flow">{neighbor_panel}<div class="arrow"><span>置換</span><b>→</b></div>{target_panel}</div>
  <details><summary>変換部分だけを見る</summary><div class="molecule-flow fragments">{neighbor_fragment}<div class="arrow"><b>→</b></div>{target_fragment}</div><code class="smirks">{_esc(row['transform_smirks'])}</code></details>
  <p class="pair-note">共通コア重原子数 {_esc(row['core_heavy_atoms'])} ／ cut数 {_esc(row['cut_count'])} ／ transform support {_esc(row['transform_pair_support'])} ／ quality flag <code>{_esc(row['quality_flags'])}</code></p>
</article>"""


def build_html(source_dir: Path) -> str:
    pairs_all = _read_csv(source_dir / "mmp_target_pairs.csv")
    pairs = [
        row
        for row in pairs_all
        if row["analysis_unit_id"] == ANALYSIS_UNIT_ID
        and row["target_compound_id"] == TARGET_ID
    ]
    unique: dict[str, dict[str, str]] = {}
    for row in pairs:
        unique.setdefault(row["mmp_id"], row)
    pairs = sorted(unique.values(), key=lambda row: -float(row["favorable_delta_toward_target"]))
    if len(pairs) != 3:
        raise ValueError(f"Expected exactly three unique JAK2 MMP pairs, got {len(pairs)}")

    summaries = _read_csv(source_dir / "mmp_target_summary.csv")
    target = next(
        row
        for row in summaries
        if row["analysis_unit_id"] == ANALYSIS_UNIT_ID
        and row["target_compound_id"] == TARGET_ID
    )
    cores = _read_csv(source_dir / "mmp_target_core_summary.csv")
    core = next(
        row
        for row in cores
        if row["analysis_unit_id"] == ANALYSIS_UNIT_ID
        and row["target_compound_id"] == TARGET_ID
    )

    deltas = sorted(float(row["favorable_delta_toward_target"]) for row in pairs)
    median_delta = deltas[len(deltas) // 2]
    target_smiles = pairs[0]["target_smiles"]
    target_variable = pairs[0]["variable_target"]
    core_panel = _molecule_panel(
        core["exact_core_smiles"],
        f"共通コア {core['core_id']}",
        (
            f"{core['mmp_pair_count']} pairs / core heavy atoms "
            f"{pairs[0]['core_heavy_atoms']} / core MW {pairs[0]['core_molecular_weight']}"
        ),
        featured=True,
    )
    target_panel = _molecule_panel(
        target_smiles,
        TARGET_ID,
        f"JAK2 pIC50 {float(target['target_endpoint']):.2f}",
        highlight_smarts=target_variable,
        featured=True,
    )
    pair_cards = "".join(_pair_card(target, row) for row in pairs)
    endpoint_chart = _endpoint_chart(target, pairs)
    delta_chart = _delta_chart(pairs)
    source_rel = source_dir.relative_to(REPO_ROOT).as_posix()
    input_hash = pairs[0]["input_sha256"]
    parameter_hash = pairs[0]["parameter_hash"]
    engine_version = pairs[0]["engine_version"]

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JAK2 MMP 個別知見サンプル — CONDUCTOR</title>
<style>
:root{{--ink:#14212a;--muted:#596a74;--line:#d7e1e6;--paper:#fff;--wash:#eff4f5;--accent:#075f73;--accent2:#d97706;--ok:#166534;--warn:#8a4b08}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1220px;margin:auto;padding:34px}} header{{padding:28px 32px;background:linear-gradient(125deg,#063e4c,#08718a);color:#fff;border-radius:16px;box-shadow:0 8px 28px #16333b26}}
.kicker,.eyebrow{{font-size:.78rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}} header h1{{font-size:clamp(1.8rem,4vw,3rem);line-height:1.25;margin:.3rem 0}} header p{{max-width:900px;margin:.5rem 0;color:#e1f3f6}}
.notice{{margin:20px 0;padding:14px 18px;background:#fff8e8;border-left:5px solid #d59422;border-radius:8px}} h2{{margin-top:42px;padding-bottom:8px;border-bottom:2px solid var(--accent)}} h3{{line-height:1.35}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px;margin:20px 0}} .card,.panel,.pair-card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px}} .card span{{display:block;color:var(--muted);font-size:.85rem}} .card strong{{font-size:1.65rem}}
.hero-grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;align-items:stretch}} .molecule{{margin:0;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px;text-align:center}} .molecule svg{{display:block;max-width:100%;height:auto;margin:auto}} .molecule figcaption{{display:grid;gap:3px}} .molecule figcaption span{{color:var(--muted)}} .molecule code,.smirks{{font-size:.74rem;overflow-wrap:anywhere;color:var(--muted)}}
.chart{{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:12px;background:#fff}} .chart text{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--ink)}} .chart-title{{font-weight:800;font-size:17px}} .tick{{font-size:11px;fill:var(--muted)!important}} .label{{font-size:12px;font-weight:650}} .value{{font-size:13px;font-weight:800}} .data-figure{{margin:18px 0}} .data-figure figcaption{{color:var(--muted);font-size:.88rem}}
.pair-card{{margin:18px 0;border-left:5px solid var(--accent)}} .pair-heading{{display:flex;justify-content:space-between;gap:16px;align-items:start}} .pair-heading h3{{margin:.15rem 0}} .delta{{font-size:1.35rem;color:var(--ok);white-space:nowrap}} .molecule-flow{{display:grid;grid-template-columns:1fr 90px 1fr;gap:10px;align-items:center}} .arrow{{display:grid;place-items:center;color:var(--accent);text-align:center}} .arrow b{{font-size:2rem}} .fragments .molecule{{max-width:340px;margin:auto}} details{{margin-top:12px}} summary{{cursor:pointer;font-weight:750}} .pair-note{{color:var(--muted);font-size:.87rem}}
.interpretation{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel h3{{margin-top:0}} .positive{{border-top:5px solid var(--ok)}} .caution{{border-top:5px solid var(--accent2)}} table{{border-collapse:collapse;width:100%}} th,td{{border-bottom:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}} th{{background:#e7eef1;white-space:nowrap}} code{{overflow-wrap:anywhere}} .provenance{{font-size:.9rem}}
@media(max-width:800px){{main{{padding:18px}}.cards{{grid-template-columns:1fr 1fr}}.hero-grid,.interpretation{{grid-template-columns:1fr}}.molecule-flow{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg)}}}}
@media print{{body{{background:#fff}}main{{max-width:none;padding:0}}header{{box-shadow:none}}details{{display:block}}}}
</style></head>
<body><main>
<header><div class="kicker">CONDUCTOR · Individual insight report · JAK2 display sample</div>
<h1>同一コア上の側鎖置換とJAK2活性差を、構造と実測値で読む</h1>
<p>CHEMBL3699558を中心に、同一コアを共有する実測MMP 3組を1ページへ統合しました。化学構造、変換箇所、pIC50差、支持数の限界を同時に確認できます。</p></header>

<aside class="notice"><strong>表示品質確認用サンプルです。</strong> 元データはCONDUCTOR 0.1.10のJAK2 report-validation資産です。0.2.1の正式Finding、p/q値、deep dive、citation validationを捏造していません。このページ単独で統計的知見として受入れてはいけません。</aside>

<section class="cards">
 <div class="card"><span>注目化合物 pIC50</span><strong>{float(target['target_endpoint']):.2f}</strong></div>
 <div class="card"><span>実測MMPペア</span><strong>{len(pairs)}</strong></div>
 <div class="card"><span>注目側への中央値差</span><strong>+{median_delta:.2f}</strong></div>
 <div class="card"><span>独立core support / 変換</span><strong>1</strong></div>
</section>

<section><h2>まず構造を見る</h2><div class="hero-grid">{target_panel}{core_panel}</div><p>赤色ハイライトが比較対象の可変側鎖です。右は3ペアに共通する固定コアで、星印は置換点を示します。</p></section>

<section><h2>観測された活性差</h2>{endpoint_chart}{delta_chart}</section>

<section><h2>各MMPを個別に確認する</h2>{pair_cards}</section>

<section><h2>人間向けの読み取り</h2><div class="interpretation">
 <article class="panel positive"><h3>このデータが直接示すこと</h3><ul><li>CHEMBL3699558のpIC50は9.18でした。</li><li>同一コアを持つ3近傍はpIC50 8.52、8.00、7.14でした。</li><li>記録された3比較すべてでCHEMBL3699558側が高く、差は+0.66から+2.04でした。</li><li>比較対象はカルボン酸および立体の異なるトリフルオロメチルアルコール側鎖です。</li></ul></article>
 <article class="panel caution"><h3>このデータだけでは言えないこと</h3><ul><li>各変換は1ペア・1独立コアのみで、元資産にも<code>low_transform_support</code>が記録されています。</li><li>p値・q値、系列横断再現性、交絡調整、deep diveはこのサンプルにはありません。</li><li>側鎖が活性差の原因であることや作用機序は断定できません。</li><li>0.2.1で知見化するには、対応Lensの統計検定と反証手順を完走させる必要があります。</li></ul></article>
</div></section>

<section><h2>次に行う検証</h2><ol><li>同一変換を持つ別コア・別系列を追加し、方向と効果量の再現性を確認する。</li><li>測定条件とassay由来差を確認し、同一条件の実測値だけで比較する。</li><li>0.2.1のL2a/L2b候補として検定し、多重性補正・triviality・deep diveを通過した場合だけ正式Findingとする。</li></ol></section>

<section><h2>実測行</h2><div style="overflow:auto"><table><thead><tr><th>Neighbor</th><th>Target pIC50</th><th>Neighbor pIC50</th><th>Δ toward target</th><th>Target variable</th><th>Neighbor variable</th><th>Transform support</th><th>Flag</th></tr></thead><tbody>
{"".join(f'<tr><td>{_esc(row["neighbor_compound_id"])}</td><td>{float(row["target_endpoint"]):.2f}</td><td>{float(row["neighbor_endpoint"]):.2f}</td><td>+{float(row["favorable_delta_toward_target"]):.2f}</td><td><code>{_esc(row["variable_target"])}</code></td><td><code>{_esc(row["variable_neighbor"])}</code></td><td>{_esc(row["transform_pair_support"])}</td><td><code>{_esc(row["quality_flags"])}</code></td></tr>' for row in pairs)}
</tbody></table></div></section>

<section class="panel provenance"><h2>来歴と監査情報</h2><p>Source: <code>{_esc(source_rel)}</code></p><p>Analysis unit: <code>{ANALYSIS_UNIT_ID}</code> ／ target: <code>{TARGET_ID}</code> ／ engine: <code>{_esc(engine_version)}</code></p><p>input_sha256: <code>{_esc(input_hash)}</code><br>parameter_hash: <code>{_esc(parameter_hash)}</code></p><p>使用ファイル: <code>mmp_target_pairs.csv</code>, <code>mmp_target_summary.csv</code>, <code>mmp_target_core_summary.csv</code></p></section>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(source_dir), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
