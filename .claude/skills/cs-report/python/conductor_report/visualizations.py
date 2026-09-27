"""Lens-specific, self-contained SVG visualizations for human reports."""

from __future__ import annotations

import html
import json
import math
import re
from typing import Any, Iterable


COLORS = {
    "accent": "#0f5f73",
    "accent2": "#d97706",
    "positive": "#16744a",
    "negative": "#b42318",
    "neutral": "#667085",
    "grid": "#d8e0e6",
    "paper": "#ffffff",
    "wash": "#f4f7f9",
}


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _extent(values: Iterable[float], *, include_zero: bool = False) -> tuple[float, float]:
    material = list(values)
    if include_zero:
        material.append(0.0)
    if not material:
        return 0.0, 1.0
    low, high = min(material), max(material)
    if low == high:
        padding = max(abs(low) * 0.1, 0.5)
        return low - padding, high + padding
    padding = (high - low) * 0.08
    return low - padding, high + padding


def _map(value: float, low: float, high: float, start: float, end: float) -> float:
    return (start + end) / 2 if high == low else start + (value - low) / (high - low) * (end - start)


def molecule_svg(
    smiles: str,
    *,
    width: int = 300,
    height: int = 210,
    highlight_smarts: str | None = None,
) -> str:
    """Draw an actual molecule/fragment. Missing RDKit is a hard reporting error."""

    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
    except ImportError as exc:  # pragma: no cover - deployment contract
        raise RuntimeError(
            "RDKit is required for chemical structure figures; run the exporter in the "
            "locked cs-report Pixi environment"
        ) from exc
    molecule = Chem.MolFromSmiles(str(smiles))
    if molecule is None:
        raise ValueError(f"Cannot render invalid SMILES as a 2D structure: {smiles!r}")
    rdMolDraw2D.PrepareMolForDrawing(molecule)
    highlight_atoms: list[int] = []
    if highlight_smarts:
        query = Chem.MolFromSmarts(str(highlight_smarts))
        if query is not None:
            match = molecule.GetSubstructMatch(query)
            highlight_atoms = list(match)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.drawOptions().clearBackground = False
    drawer.drawOptions().padding = 0.08
    drawer.DrawMolecule(molecule, highlightAtoms=highlight_atoms)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    svg = re.sub(r"<\?xml[^>]*>\s*", "", svg)
    svg = re.sub(r"xmlns=['\"]http://www\.w3\.org/2000/svg['\"]\s*", "", svg)
    svg = re.sub(r"xmlns:rdkit=['\"]http://www\.rdkit\.org/xml['\"]\s*", "", svg)
    svg = re.sub(r"xmlns:xlink=['\"]http://www\.w3\.org/1999/xlink['\"]\s*", "", svg)
    svg = svg.replace(
        "<svg ", '<svg role="img" aria-label="2D chemical structure" ', 1
    )
    return svg.strip()


def _molecule_panel(
    smiles: str,
    label: str,
    *,
    compact: bool = False,
    highlight_smarts: str | None = None,
) -> str:
    width, height = ((210, 150) if compact else (300, 210))
    return (
        '<figure class="molecule-panel">'
        f'{molecule_svg(smiles, width=width, height=height, highlight_smarts=highlight_smarts)}'
        f'<figcaption><strong>{_escape(label)}</strong><code>{_escape(smiles)}</code></figcaption>'
        '</figure>'
    )


def _structure_sequence(panels: list[str], arrows: list[str] | None = None) -> str:
    pieces: list[str] = []
    for index, panel in enumerate(panels):
        pieces.append(panel)
        if index < len(panels) - 1:
            label = (arrows or [])[index] if arrows and index < len(arrows) else "→"
            pieces.append(f'<div class="chem-arrow" aria-label="transformation">{_escape(label)}</div>')
    return f'<div class="structure-sequence">{"".join(pieces)}</div>'


def _scatter_svg(
    rows: list[dict[str, Any]],
    *,
    x_field: str,
    y_field: str,
    x_label: str,
    y_label: str,
    group_field: str | None = None,
    group_labels: dict[str, str] | None = None,
    diagonal: bool = False,
    regression: bool = False,
    tooltip_field: str | None = None,
    title: str,
) -> str:
    points = []
    for row in rows:
        x_value, y_value = _finite(row.get(x_field)), _finite(row.get(y_field))
        if x_value is not None and y_value is not None:
            group = str(row.get(group_field, "all")) if group_field else "all"
            tooltip = str(row.get(tooltip_field, group)) if tooltip_field else group
            points.append((x_value, y_value, group, tooltip))
    if not points:
        return '<p class="visual-missing">散布図に必要な有限観測値がありません。</p>'
    width, height = 720, 390
    left, right, top, bottom = 76, 28, 36, 62
    x_low, x_high = _extent(value[0] for value in points)
    y_low, y_high = _extent(value[1] for value in points)
    if diagonal:
        common_low, common_high = min(x_low, y_low), max(x_high, y_high)
        x_low = y_low = common_low
        x_high = y_high = common_high
    plot_right, plot_bottom = width - right, height - bottom
    elements = [
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{COLORS["paper"]}"/>',
        f'<text x="{left}" y="22" class="chart-title">{_escape(title)}</text>',
    ]
    for step in range(6):
        fraction = step / 5
        x = left + fraction * (plot_right - left)
        y = top + fraction * (plot_bottom - top)
        x_value = x_low + fraction * (x_high - x_low)
        y_value = y_high - fraction * (y_high - y_low)
        elements.extend(
            [
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{plot_bottom}" stroke="{COLORS["grid"]}"/>',
                f'<line x1="{left}" y1="{y:.1f}" x2="{plot_right}" y2="{y:.1f}" stroke="{COLORS["grid"]}"/>',
                f'<text x="{x:.1f}" y="{plot_bottom + 20}" text-anchor="middle" class="tick">{x_value:.3g}</text>',
                f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" class="tick">{y_value:.3g}</text>',
            ]
        )
    if diagonal:
        elements.append(
            f'<line x1="{left}" y1="{plot_bottom}" x2="{plot_right}" y2="{top}" stroke="{COLORS["neutral"]}" stroke-dasharray="6 5" stroke-width="2"/>'
        )
    groups = sorted({point[2] for point in points})
    palette = [COLORS["accent"], COLORS["accent2"], COLORS["positive"], COLORS["negative"]]
    colors = {group: palette[index % len(palette)] for index, group in enumerate(groups)}
    if regression:
        for group in groups:
            selected = [(x, y) for x, y, value, _ in points if value == group]
            if len(selected) < 2:
                continue
            mean_x = sum(value[0] for value in selected) / len(selected)
            mean_y = sum(value[1] for value in selected) / len(selected)
            denominator = sum((value[0] - mean_x) ** 2 for value in selected)
            if denominator == 0:
                continue
            slope = sum((x - mean_x) * (y - mean_y) for x, y in selected) / denominator
            intercept = mean_y - slope * mean_x
            y_start, y_end = intercept + slope * x_low, intercept + slope * x_high
            elements.append(
                f'<line x1="{left}" y1="{_map(y_start, y_low, y_high, plot_bottom, top):.1f}" x2="{plot_right}" y2="{_map(y_end, y_low, y_high, plot_bottom, top):.1f}" stroke="{colors[group]}" stroke-width="3" opacity=".8"/>'
            )
    for x_value, y_value, group, tooltip in points:
        elements.append(
            f'<circle cx="{_map(x_value, x_low, x_high, left, plot_right):.1f}" cy="{_map(y_value, y_low, y_high, plot_bottom, top):.1f}" r="4.3" fill="{colors[group]}" fill-opacity=".72"><title>{_escape(tooltip)}: ({x_value:.6g}, {y_value:.6g})</title></circle>'
        )
    elements.extend(
        [
            f'<text x="{(left + plot_right) / 2:.1f}" y="{height - 12}" text-anchor="middle" class="axis-label">{_escape(x_label)}</text>',
            f'<text x="18" y="{(top + plot_bottom) / 2:.1f}" text-anchor="middle" transform="rotate(-90 18 {(top + plot_bottom) / 2:.1f})" class="axis-label">{_escape(y_label)}</text>',
        ]
    )
    legend = "".join(
        f'<span><i style="background:{colors[group]}"></i>{_escape((group_labels or {}).get(group, group))}</span>'
        for group in groups
    )
    return (
        '<figure class="data-figure">'
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'
        f'<figcaption class="chart-legend">{legend}</figcaption></figure>'
    )


def _grouped_strip_svg(
    groups: list[tuple[str, list[float]]], *, title: str, value_label: str
) -> str:
    material = [(label, [value for value in values if math.isfinite(value)]) for label, values in groups]
    all_values = [value for _, values in material for value in values]
    if not all_values:
        return '<p class="visual-missing">分布図に必要な有限観測値がありません。</p>'
    width, row_height = 720, 92
    height = 70 + row_height * len(material)
    left, right = 130, 35
    low, high = _extent(all_values, include_zero=True)
    plot_right = width - right
    elements = [f'<rect width="{width}" height="{height}" rx="10" fill="{COLORS["paper"]}"/>', f'<text x="{left}" y="25" class="chart-title">{_escape(title)}</text>']
    zero = _map(0.0, low, high, left, plot_right)
    elements.append(f'<line x1="{zero:.1f}" y1="42" x2="{zero:.1f}" y2="{height - 38}" stroke="{COLORS["neutral"]}" stroke-dasharray="5 4"/>')
    for index, (label, values) in enumerate(material):
        y = 68 + index * row_height
        elements.append(f'<text x="{left - 12}" y="{y + 5}" text-anchor="end" class="axis-label">{_escape(label)}</text>')
        elements.append(f'<line x1="{left}" y1="{y}" x2="{plot_right}" y2="{y}" stroke="{COLORS["grid"]}"/>')
        for point_index, value in enumerate(values):
            jitter = ((point_index % 7) - 3) * 3.0
            elements.append(f'<circle cx="{_map(value, low, high, left, plot_right):.1f}" cy="{y + jitter:.1f}" r="4" fill="{COLORS["accent"]}" fill-opacity=".66"><title>{value:.6g}</title></circle>')
        if values:
            ordered = sorted(values)
            median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered)//2-1] + ordered[len(ordered)//2]) / 2
            median_x = _map(median, low, high, left, plot_right)
            elements.append(f'<path d="M {median_x:.1f} {y-20} V {y+20}" stroke="{COLORS["negative"]}" stroke-width="4"><title>median {median:.6g}</title></path>')
    elements.append(f'<text x="{(left + plot_right) / 2:.1f}" y="{height - 10}" text-anchor="middle" class="axis-label">{_escape(value_label)}</text>')
    return f'<figure class="data-figure"><svg class="chart" viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg><figcaption>各点は解析に使用した最小観測単位、赤線は中央値、破線は0です。</figcaption></figure>'


def _representative_molecules(
    compound_ids: list[str],
    compound_smiles: dict[str, str],
    *,
    highlight_smarts: str | None = None,
    limit: int = 4,
) -> str:
    panels = []
    for compound_id in compound_ids:
        smiles = compound_smiles.get(compound_id)
        if not smiles:
            continue
        panels.append(
            _molecule_panel(
                smiles,
                compound_id,
                compact=True,
                highlight_smarts=highlight_smarts,
            )
        )
        if len(panels) >= limit:
            break
    return f'<div class="molecule-grid">{"".join(panels)}</div>' if panels else ""


def _labeled_effect_svg(rows: list[dict[str, Any]], *, title: str) -> str:
    values = [
        (str(row.get("context_id") or row.get("block_id") or "series"), _finite(row.get("effect")))
        for row in rows
    ]
    values = [(label, value) for label, value in values if value is not None]
    if not values:
        raise ValueError("Lens visualization requires finite per-series effects")
    values = sorted(values, key=lambda item: (item[1], item[0]))
    if len(values) > 30:
        indices = sorted({round(index * (len(values) - 1) / 29) for index in range(30)})
        values = [values[index] for index in indices]
    width, row_height = 720, 25
    height = 72 + len(values) * row_height
    left, right = 210, 35
    low, high = _extent((value for _, value in values), include_zero=True)
    plot_right = width - right
    zero = _map(0.0, low, high, left, plot_right)
    elements = [
        f'<rect width="{width}" height="{height}" rx="10" fill="{COLORS["paper"]}"/>',
        f'<text x="{left}" y="25" class="chart-title">{_escape(title)}</text>',
        f'<line x1="{zero:.1f}" y1="42" x2="{zero:.1f}" y2="{height - 25}" stroke="{COLORS["neutral"]}" stroke-dasharray="5 4"/>',
    ]
    for index, (label, value) in enumerate(values):
        y = 55 + index * row_height
        x = _map(value, low, high, left, plot_right)
        color = COLORS["positive"] if value >= 0 else COLORS["negative"]
        elements.extend(
            [
                f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" class="tick">{_escape(label)}</text>',
                f'<line x1="{zero:.1f}" y1="{y}" x2="{x:.1f}" y2="{y}" stroke="{color}" stroke-width="3"/>',
                f'<circle cx="{x:.1f}" cy="{y}" r="5" fill="{color}"><title>{_escape(label)}: {value:.6g}</title></circle>',
            ]
        )
    return f'<figure class="data-figure"><svg class="chart" viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg><figcaption>系列数が多い場合は、効果量の範囲を保つ分位代表30系列を表示します。</figcaption></figure>'


def _l1b(
    finding: dict[str, Any],
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    compound_smiles: dict[str, str],
    compact: bool,
) -> str:
    chart = _scatter_svg(
        observations,
        x_field="endpoint_value",
        y_field="effect",
        x_label="Endpoint",
        y_label="局所予測誤差の改善量",
        tooltip_field="compound_id",
        title="文脈内化合物のEndpointと局所性",
    )
    if compact:
        return chart
    def effect_key(item: dict[str, Any]) -> tuple[float, str]:
        value = _finite(item.get("effect"))
        return (-math.inf if value is None else value, str(item.get("compound_id", "")))

    focal = max(observations, key=effect_key)
    focal_id = str(focal.get("compound_id", ""))
    neighbor_ids = _json_list(focal.get("neighbor_order_compound_ids_json"))[:3]
    if not focal_id or focal_id not in compound_smiles or not neighbor_ids:
        raise ValueError(
            "L1b visualization requires a focal compound and ordered local neighbors"
        )
    neighborhood = [
        _molecule_panel(
            compound_smiles[focal_id], f"注目化合物 {focal_id}", compact=True
        )
    ]
    for index, compound_id in enumerate(neighbor_ids, start=1):
        structure = compound_smiles.get(compound_id)
        if not structure:
            raise ValueError(f"L1b local neighbor structure is missing: {compound_id}")
        neighborhood.append(
            _molecule_panel(structure, f"近傍{index} {compound_id}", compact=True)
        )
    return (
        '<section class="lens-visual"><h2>局所SARの可視化</h2>'
        f'{chart}<h3>局所予測改善が最大の化合物と、その同一文脈内近傍</h3>'
        f'<div class="molecule-grid">{"".join(neighborhood)}</div>'
        '<p class="figure-note">近傍はL1bが解析時に固定した距離順です。'
        '図示のために再探索していません。</p></section>'
    )


def _l2a(
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    compound_smiles: dict[str, str],
    compact: bool,
) -> str:
    before, after = str(row.get("variable_from", "")), str(row.get("variable_to", ""))
    transformation = _structure_sequence(
        [_molecule_panel(before, "変換前", compact=compact), _molecule_panel(after, "変換後", compact=compact)],
        ["MMP変換 →"],
    )
    if compact:
        return transformation
    inside = [_finite(item.get("effect")) for item in observations if str(item.get("comparison_group")) == "inside"]
    outside = [_finite(item.get("effect")) for item in observations if str(item.get("comparison_group")) == "outside"]
    distribution = _grouped_strip_svg(
        [("対象文脈内", [value for value in inside if value is not None]), ("文脈外", [value for value in outside if value is not None])],
        title="同一MMP変換のEndpoint差分布",
        value_label="変換後 − 変換前（oriented Endpoint）",
    )
    pair_panels: list[str] = []
    for item in sorted(
        (value for value in observations if str(value.get("comparison_group")) == "inside"),
        key=lambda value: -abs(_finite(value.get("effect")) or 0.0),
    )[:3]:
        source_id, target_id = str(item.get("pair_from_compound_id", "")), str(item.get("pair_to_compound_id", ""))
        source, target = compound_smiles.get(source_id), compound_smiles.get(target_id)
        if source and target:
            pair_panels.append(
                '<article class="representative-pair">'
                + _structure_sequence(
                    [
                        _molecule_panel(source, source_id, compact=True, highlight_smarts=before),
                        _molecule_panel(target, target_id, compact=True, highlight_smarts=after),
                    ],
                    [f'Δ={_finite(item.get("effect")) or 0.0:.3g} →'],
                )
                + "</article>"
            )
    if not pair_panels:
        raise ValueError("L2a visualization requires at least one measured MMP pair")
    return f'<section class="lens-visual"><h2>MMP変換の構造と効果</h2>{transformation}{distribution}<h3>対象文脈内の代表的な実測MMPペア</h3>{"".join(pair_panels) or "<p class=\"visual-missing\">代表ペアを描画できませんでした。</p>"}</section>'


def _l2b(
    finding: dict[str, Any],
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    compound_smiles: dict[str, str],
    compact: bool,
) -> str:
    fragment = str(row.get("fragment_smiles", ""))
    structure = _molecule_panel(fragment, "評価フラグメント", compact=compact)
    if compact:
        return f'<div class="structure-sequence">{structure}</div>'
    strip = _labeled_effect_svg(observations, title="系列ごとの残差寄与")
    compound_ids = [str(value) for value in (finding.get("entities") or {}).get("compound_ids") or []]
    representatives = _representative_molecules(compound_ids, compound_smiles, highlight_smarts=fragment)
    if not representatives:
        raise ValueError("L2b visualization requires representative compound structures")
    return f'<section class="lens-visual"><h2>フラグメント寄与の構造的解釈</h2><div class="structure-sequence">{structure}</div>{strip}<h3>フラグメントを含む代表化合物</h3>{representatives}</section>'


def _l4(
    finding: dict[str, Any],
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    compound_smiles: dict[str, str],
    compact: bool,
) -> str:
    candidate = str(row.get("candidate_smiles", ""))
    candidate_panel = _molecule_panel(candidate, "未観測候補", compact=compact)
    if compact:
        return f'<div class="structure-sequence">{candidate_panel}</div>'
    sources = [str(value) for value in (finding.get("entities") or {}).get("compound_ids") or []]
    source_panels = []
    for compound_id in sources[:3]:
        smiles = compound_smiles.get(compound_id)
        if smiles:
            source_panels.append(
                _structure_sequence(
                    [_molecule_panel(smiles, compound_id, compact=True), _molecule_panel(candidate, "候補", compact=True)],
                    ["一段階変換 →"],
                )
            )
    if not source_panels:
        raise ValueError("L4 visualization requires at least one source compound structure")
    neighbor_chart = _grouped_strip_svg(
        [
            (str(space), [value for value in (_finite(item.get("endpoint_value")) for item in observations if str(item.get("block_id")) == space) if value is not None])
            for space in sorted({str(item.get("block_id", "space")) for item in observations})
        ],
        title="特徴空間ごとの近傍化合物Endpoint",
        value_label="oriented Endpoint",
    )
    return f'<section class="lens-visual"><h2>未探索候補の構造と到達経路</h2><div class="structure-sequence">{candidate_panel}</div><h3>既知化合物からの一段階到達例</h3>{"".join(source_panels) or "<p class=\"visual-missing\">source構造を描画できませんでした。</p>"}{neighbor_chart}</section>'


def _l5(observations: list[dict[str, Any]], compact: bool) -> str:
    chart = _scatter_svg(
        observations,
        x_field="feature_value",
        y_field="endpoint_value",
        x_label="特徴量",
        y_label="oriented Endpoint",
        group_field="context_role",
        group_labels={"focal": "対象文脈", "complement": "同軸補集合"},
        regression=True,
        tooltip_field="compound_id",
        title="文脈内外での特徴量–Endpoint相関",
    )
    return chart if compact else f'<section class="lens-visual"><h2>相関方向反転の実測図</h2>{chart}<p class="figure-note">実線は各群の最小二乗直線です。相関の符号と検定値はEvidenceおよび統計表を正とします。</p></section>'


def _l7(
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    compound_smiles: dict[str, str],
    fragment_smiles: dict[str, str],
    compact: bool,
) -> str:
    chart = _scatter_svg(
        observations,
        x_field="endpoint_left_value",
        y_field="endpoint_value",
        x_label="系列A Endpoint",
        y_label="系列B Endpoint",
        diagonal=True,
        tooltip_field="target_id",
        title="共通置換基ごとの系列A–B対応",
    )
    if compact:
        return chart
    core_panels = []
    for key, label in (("constant_a", "系列A core"), ("constant_b", "系列B core")):
        smiles = str(row.get(key, ""))
        if smiles:
            core_panels.append(_molecule_panel(smiles, label, compact=True))
    cores = _structure_sequence(core_panels, ["比較 ↔"]) if core_panels else ""
    if len(core_panels) != 2:
        raise ValueError("L7 visualization requires both series core structures")
    ranked = sorted(
        observations,
        key=lambda item: (
            -abs(_finite(item.get("effect")) or 0.0),
            str(item.get("target_id", "")),
        ),
    )
    r_panels: list[str] = []
    for item in ranked[:4]:
        fragment_id = str(item.get("target_id", ""))
        structure = fragment_smiles.get(fragment_id)
        if not structure:
            raise ValueError(f"L7 common R-group structure is missing: {fragment_id}")
        r_panels.append(
            _molecule_panel(structure, f"共通R基 {fragment_id}", compact=True)
        )
    if not r_panels:
        raise ValueError("L7 visualization requires common R-group structures")
    representative = ranked[0]
    ids_a = _json_list(representative.get("compound_ids_a_json"))
    ids_b = _json_list(representative.get("compound_ids_b_json"))
    if not ids_a or not ids_b:
        raise ValueError(
            "L7 visualization requires representative compounds from both series"
        )
    compound_a, compound_b = compound_smiles.get(ids_a[0]), compound_smiles.get(ids_b[0])
    if not compound_a or not compound_b:
        raise ValueError("L7 representative compound structures are missing")
    measured_pair = _structure_sequence(
        [
            _molecule_panel(compound_a, f"系列A {ids_a[0]}", compact=True),
            _molecule_panel(compound_b, f"系列B {ids_b[0]}", compact=True),
        ],
        [f'同一R基・Δ {_finite(representative.get("effect")) or 0.0:.3g} →'],
    )
    return (
        '<section class="lens-visual"><h2>系列coreとSAR移植性</h2>'
        f'{cores}{chart}'
        '<p class="figure-note">破線は両系列でEndpointが等しい位置です。'
        '右上がりなら順位が保持され、右下がり傾向ならSAR順位反転を示します。</p>'
        f'<h3>系列間で比較した共通R基（効果差の大きい代表例）</h3>'
        f'<div class="molecule-grid">{"".join(r_panels)}</div>'
        f'<h3>同じR基を持つ代表実測化合物</h3>{measured_pair}</section>'
    )


def render_lens_visual(
    finding: dict[str, Any],
    evidence_row: dict[str, Any] | None,
    observations: list[dict[str, Any]] | None,
    compound_smiles: dict[str, str] | None,
    fragment_smiles: dict[str, str] | None = None,
    *,
    compact: bool = False,
) -> str:
    """Return the required Lens-specific visual or fail the reporting contract."""

    row = evidence_row or {}
    values = observations or []
    smiles = compound_smiles or {}
    fragments = fragment_smiles or {}
    lens = str(finding.get("lens", ""))
    if not row:
        raise ValueError(f"{lens} visualization requires its cited Evidence row")
    if not values:
        raise ValueError(f"{lens} visualization requires score_observations")
    if lens == "L1b":
        return _l1b(finding, row, values, smiles, compact)
    if lens == "L2a":
        return _l2a(row, values, smiles, compact)
    if lens == "L2b":
        return _l2b(finding, row, values, smiles, compact)
    if lens == "L4":
        return _l4(finding, row, values, smiles, compact)
    if lens == "L5":
        return _l5(values, compact)
    if lens == "L7":
        return _l7(row, values, smiles, fragments, compact)
    raise ValueError(f"Unsupported Lens visualization contract: {lens}")
