from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def _browser_executable(explicit: str | None) -> str | None:
    candidates = [
        explicit,
        os.environ.get("CONDUCTOR_BROWSER_EXECUTABLE"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    return next((value for value in candidates if value and Path(value).is_file()), None)


def audit(html_path: Path, executable: str | None = None) -> dict[str, object]:
    failures: list[str] = []
    checks: list[str] = []
    metrics: dict[str, object] = {"html_bytes": html_path.stat().st_size}
    if metrics["html_bytes"] > 10 * 1024 * 1024:
        failures.append("Target HTML exceeds the 10 MiB size target")
    with sync_playwright() as playwright:
        launch = {"headless": True}
        browser_path = _browser_executable(executable)
        if browser_path:
            launch["executable_path"] = browser_path
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        navigation_started = time.perf_counter()
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_selector('[data-template-id="A008-target-workspace"]')
        metrics["dom_ready_ms"] = round((time.perf_counter() - navigation_started) * 1000, 1)
        if metrics["dom_ready_ms"] > 2000:
            failures.append("Target HTML exceeded the 2 second DOM-ready target")
        viewport_metrics: list[dict[str, object]] = []
        for width, height in ((1280, 720), (1440, 900), (1600, 900), (1920, 1080)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(50)
            shell = page.locator(".shell").bounding_box()
            dimensions = page.evaluate(
                "({scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,"
                "scrollHeight:document.documentElement.scrollHeight,clientHeight:document.documentElement.clientHeight})"
            )
            viewport_metrics.append({
                "viewport": f"{width}x{height}", "shell_box": shell, "document": dimensions,
            })
            if not shell or shell["width"] > width + .5 or shell["height"] > height + .5:
                failures.append(f"PC-wide shell does not fit the {width}x{height} viewport")
            if dimensions["scrollWidth"] > dimensions["clientWidth"]:
                failures.append(f"document has horizontal overflow at {width}x{height}")
            if dimensions["scrollHeight"] > dimensions["clientHeight"]:
                failures.append(f"document has page-level vertical scroll at {width}x{height}")
        metrics["viewports"] = viewport_metrics
        page.set_viewport_size({"width": 1600, "height": 900})
        checks.append("required PC-wide viewports and overflow")

        layer_counts = page.evaluate(
            """() => [...document.querySelectorAll('.map-layer')].map(layer => ({
              cut:layer.dataset.mapCut,
              cores:layer.querySelectorAll('[data-kind="core"]').length,
              neighbors:layer.querySelectorAll('[data-kind="neighbor"]').length,
              neighborGroups:layer.querySelectorAll('[data-kind="neighbor-group"]').length,
              directCount:[...layer.querySelectorAll('[data-kind="core"]')].reduce((n,x)=>n+Number(x.dataset.directCount||0),0),
              representedCount:[...layer.querySelectorAll('[data-neighbor-count]')].reduce((n,x)=>n+Number(x.dataset.neighborCount||0),0)
            }))"""
        )
        metrics["map_layer_counts"] = layer_counts
        if any(item["cores"] > 5 or item["neighbors"] > 25 for item in layer_counts):
            failures.append("A cut-specific Map exceeds 5 Core x 5 explicit Neighbor")
        if any(item["directCount"] != item["representedCount"] for item in layer_counts):
            failures.append("A cut-specific Map does not account for every displayed-Core Neighbor")
        svg_bounds = page.evaluate(
            """() => {
              const svgs = [...document.querySelectorAll('svg[aria-label="MMP relationship map"]')];
              if (!svgs.length) return {missing:true, outside:[]};
              const outside = svgs.flatMap((svg, layerIndex) => {
                const view = svg.viewBox.baseVal;
                return [...svg.querySelectorAll('.node[data-kind]')].flatMap(node => {
                  const box = node.getBBox();
                  const tolerance = 0.5;
                  const escaped = box.x < view.x - tolerance || box.y < view.y - tolerance ||
                    box.x + box.width > view.x + view.width + tolerance ||
                    box.y + box.height > view.y + view.height + tolerance;
                  return escaped ? [{layerIndex, kind:node.dataset.kind, x:box.x, y:box.y,
                    width:box.width, height:box.height}] : [];
                });
              });
              const collisions = svgs.flatMap((svg, layerIndex) => {
                const cards = [...svg.querySelectorAll('.node[data-kind]')].map(node => {
                  const rect = node.querySelector('.node-box');
                  return {node, box:rect ? rect.getBBox() : node.getBBox()};
                });
                const overlaps = [];
                for (let i = 0; i < cards.length; i += 1) {
                  for (let j = i + 1; j < cards.length; j += 1) {
                    const a = cards[i], b = cards[j];
                    const width = Math.min(a.box.x + a.box.width, b.box.x + b.box.width) - Math.max(a.box.x, b.box.x);
                    const height = Math.min(a.box.y + a.box.height, b.box.y + b.box.height) - Math.max(a.box.y, b.box.y);
                    if (width > 0.5 && height > 0.5) overlaps.push({
                      layerIndex,
                      first:a.node.dataset.kind,
                      second:b.node.dataset.kind,
                      overlapWidth:width,
                      overlapHeight:height,
                    });
                  }
                }
                return overlaps;
              });
              const contentOverflow = svgs.flatMap((svg, layerIndex) =>
                [...svg.querySelectorAll('.node[data-kind="neighbor-group"]')].flatMap(node => {
                  const rect = node.querySelector('.node-box');
                  if (!rect) return [];
                  const card = rect.getBBox();
                  return [...node.querySelectorAll('text')].flatMap(label => {
                    const box = label.getBBox(), tolerance = 2;
                    const escaped = box.x < card.x - tolerance || box.y < card.y - tolerance ||
                      box.x + box.width > card.x + card.width + tolerance ||
                      box.y + box.height > card.y + card.height + tolerance;
                    return escaped ? [{layerIndex, text:label.textContent, box, card}] : [];
                  });
                })
              );
              return {missing:false, outside, collisions, contentOverflow};
            }"""
        )
        metrics["svg_node_bounds"] = svg_bounds
        if svg_bounds.get("missing"):
            failures.append("relationship map SVG is missing")
        elif svg_bounds.get("outside"):
            failures.append(f"Map cards escape the SVG viewBox: {svg_bounds['outside']}")
        if svg_bounds.get("collisions"):
            failures.append(f"Map cards overlap: {svg_bounds['collisions']}")
        if svg_bounds.get("contentOverflow"):
            failures.append(
                f"Map card text overflows its border: {svg_bounds['contentOverflow']}"
            )
        solid_edges = page.locator(
            'svg[aria-label="MMP relationship map"] .edge'
        ).evaluate_all(
            "edges => edges.filter(edge => getComputedStyle(edge).strokeDasharray === 'none').length"
        )
        metrics["solid_map_edge_count"] = solid_edges
        if solid_edges:
            failures.append(f"Relationship Map contains {solid_edges} solid edges")
        checks.append("bounded relationship map")

        legend_layout = page.evaluate(
            """() => {const canvas=document.querySelector('.map-canvas'),legend=document.querySelector('.map-legend');
            if(!canvas||!legend)return null;const a=canvas.getBoundingClientRect(),b=legend.getBoundingClientRect();
            return {canvasBottom:a.bottom,legendTop:b.top,overlap:Math.max(0,a.bottom-b.top)}}"""
        )
        metrics["legend_layout"] = legend_layout
        if not legend_layout or legend_layout["overlap"] > .5:
            failures.append("Map legend overlaps the Map canvas")
        checks.append("legend separated from Map nodes")

        visible_neighbors = page.locator('.map-layer.active [data-kind="neighbor"]')
        visible_cores = page.locator('.map-layer.active [data-kind="core"]')
        neighbor_count = visible_neighbors.count()
        core_count = visible_cores.count()
        if neighbor_count:
            interaction_ms = visible_neighbors.first.evaluate(
                "element => {const started=performance.now(); "
                "element.dispatchEvent(new MouseEvent('click',{bubbles:true})); "
                "return performance.now()-started}"
            )
            page.wait_for_selector(".workspace.panel-open")
            metrics["neighbor_detail_ms"] = round(float(interaction_ms), 1)
            if metrics["neighbor_detail_ms"] > 100:
                failures.append("Neighbor detail panel exceeded the 100 ms interaction target")
            page.wait_for_timeout(250)  # allow the intentional panel-width transition to finish
            panel = page.locator(".detail").bounding_box()
            metrics["detail_panel_box"] = panel
            if not panel or not 645 <= panel["width"] <= 925:
                failures.append("Neighbor detail panel is outside the approved wide range")
            if page.locator(".detail-body img").count() < 3:
                failures.append("Neighbor detail does not expose Core and fragment structures")
            if "ΔN2T" not in page.locator(".detail-body").inner_text():
                failures.append("Neighbor detail does not state ΔN2T")
            if page.locator(".detail-body .comparison .structure-card img").count() < 2:
                failures.append("Neighbor detail omits whole-compound structures")
            if page.locator("#detailClose").evaluate("element => element !== document.activeElement"):
                failures.append("Neighbor detail does not move focus to the close button")
            page.locator("#detailClose").click()
            checks.append("Neighbor click/detail/close")

        if core_count:
            visible_cores.first.click()
            page.wait_for_selector(".workspace.panel-open")
            if page.locator(".detail-body img").count() < 1:
                failures.append("Core detail has no structure")
            if page.locator(".detail-body .core-target-pair .core-frame").count() != 1:
                failures.append("Core detail does not show the green Core card")
            if page.locator(".detail-body .core-target-pair .target-frame").count() != 1:
                failures.append("Core detail does not show the navy Target card")
            if page.locator(".detail-body").inner_text().find("Direct MMP：全Neighbor") < 0:
                failures.append("Core detail does not expose every Direct Neighbor route")
            page.keyboard.press("Escape")
            if page.locator(".workspace.panel-open").count():
                failures.append("Escape did not close the Core detail panel")
            checks.append("Core click/detail/Escape")

        routed_core = page.locator(
            '.map-layer.active [data-kind="core"][data-related-count]:not([data-related-count="0"])'
        )
        if routed_core.count():
            routed_core.first.click()
            page.wait_for_timeout(200)
            similar = page.locator(".detail-body [data-open-related]")
            if similar.count():
                similar.first.click()
                if "Similar Coreで観測されたMMP" not in page.locator("#detailTitle").inner_text():
                    failures.append("Similar-Core route did not open its MMP map")
                evidence_route = page.locator(".detail-body [data-open-evidence]")
                if evidence_route.count():
                    evidence_route.first.click()
                    page.locator("#detailBack").click()
                    if "Similar Coreで観測されたMMP" not in page.locator("#detailTitle").inner_text():
                        failures.append("Back did not return from MMP to Similar-Core map")
                    page.locator("#detailBack").click()
                    if "MMP Portal" not in page.locator("#detailTitle").inner_text():
                        failures.append("Back did not return from Similar-Core map to Core portal")
                else:
                    failures.append("Similar-Core map exposes no individual MMP route")
            else:
                failures.append("Core with related-count has no Similar-Core route")
            page.locator("#detailClose").click()
            checks.append("Core/Similar-Core/MMP/Back navigation")

        cut_options = page.locator("#cutFilter option").all_text_contents()
        if "1-cut" in cut_options and "2-cut" in cut_options:
            for value in ("1", "2"):
                page.locator("#cutFilter").select_option(value)
                if not page.locator(f'.map-layer.active[data-map-cut="{value}"]').is_visible():
                    failures.append(f"{value}-cut Map switch did not activate the requested layer")
            page.locator("#cutFilter").select_option("all")
            checks.append("1-cut/2-cut Map switch")

        page.locator('[data-view="transformation"]').click()
        if not page.locator('[data-view-panel="transformation"]').is_visible():
            failures.append("Transformation tab did not switch to its view")
        for scope in ("all", "direct", "transferred"):
            page.locator(f'[data-transformation-scope="{scope}"]').click()
            if not page.locator('[data-view-panel="transformation"]').is_visible():
                failures.append(f"Transformation/{scope} subtab is not visible")
        page.locator('[data-transformation-scope="all"]').click()
        transformation_card = page.locator(
            '#transformationCards [data-transformation-family]'
        ).first
        if transformation_card.count():
            transformation_card.click()
            page.wait_for_selector(".workspace.panel-open")
            detail_text = page.locator(".detail-body").inner_text()
            if "Core横断の観測" not in detail_text:
                failures.append("Transformation detail lacks cross-Core observations")
            page.locator("#detailClose").click()
        checks.append("Transformation cross-Core/Direct/Transferred views")

        # The header filters are a report-wide data-view contract, not a Map-
        # only control.  Exercise the combination on every card/table view.
        page.locator("#cutFilter").select_option("1")
        page.locator("#qualityFilter").select_option("high")
        page.locator('[data-view="transformation"]').click()
        bad_transformation_cuts = page.locator(
            '#transformationCards [data-transformation-cut]:not([data-transformation-cut="1"])'
        ).count()
        if bad_transformation_cuts:
            failures.append("Global cut/quality filters were not applied to Transformation")
        page.locator('[data-view="direction"]').click()
        direction_ids = page.locator("#directionCards [data-insight]").evaluate_all(
            "cards => cards.map(card => card.dataset.insight)"
        )
        if direction_ids:
            invalid_direction = page.evaluate(
                """ids => {const p=JSON.parse(document.getElementById('mmpPayload').textContent);
                return ids.some(id=>{const r=p.evidence.find(x=>x.evidence_id===id);
                return !r || Number(r.cut_count)!==1 || r.target_evidence_quality!=='high';});}""",
                direction_ids,
            )
            if invalid_direction:
                failures.append("Global cut/quality filters were not applied to N2T Direction")
        page.locator('[data-view="core"]').click()
        core_ids = page.locator("#coreTypeCards [data-core-route]").evaluate_all(
            "cards => cards.map(card => card.dataset.coreRoute)"
        )
        if core_ids:
            invalid_core = page.evaluate(
                """ids => {const p=JSON.parse(document.getElementById('mmpPayload').textContent);
                return ids.some(id=>!p.evidence.some(r=>r.portal_core_id===id &&
                  Number(r.cut_count)===1 && r.target_evidence_quality==='high'));}""",
                core_ids,
            )
            if invalid_core:
                failures.append("Global cut/quality filters were not applied to Target Connection")
        page.locator('[data-view="cuts"]').click()
        page.locator('[data-cut-view="1"]').click()
        cut_core_ids = page.locator("#cutCards [data-core-route]").evaluate_all(
            "cards => cards.map(card => card.dataset.coreRoute)"
        )
        if cut_core_ids:
            invalid_cut_core = page.evaluate(
                """ids => {const p=JSON.parse(document.getElementById('mmpPayload').textContent);
                return ids.some(id=>!p.evidence.some(r=>r.portal_core_id===id &&
                  Number(r.cut_count)===1 && r.target_evidence_quality==='high'));}""",
                cut_core_ids,
            )
            if invalid_cut_core:
                failures.append("Global cut/quality filters were not applied to N-Cuts")
        page.locator('[data-view="data"]').click()
        bad_table_rows = page.locator("#evidenceRows tr").evaluate_all(
            "rows => rows.filter(row => row.cells[2]?.textContent.trim() !== '1-cut' || "
            "!row.cells[6]?.textContent.includes('High')).length"
        )
        if bad_table_rows:
            failures.append("Global cut/quality filters were not applied to Data Table")
        page.locator("#cutFilter").select_option("all")
        page.locator("#qualityFilter").select_option("all")
        checks.append("global cut/quality filters across data views")

        page.locator('[data-view="direction"]').click()
        if not page.locator('[data-view-panel="direction"]').is_visible():
            failures.append("N2T Direction tab did not switch to its view")
        for view, expected_sign in (("positive", 1), ("negative", -1)):
            page.locator(f'[data-direction="{view}"]').click()
            card = page.locator('#directionCards [data-insight]').first
            if card.count():
                evidence_id = card.get_attribute("data-insight")
                delta = page.evaluate(
                    """evidenceId => {const payload=JSON.parse(document.getElementById('mmpPayload').textContent);
                    const row=payload.evidence.find(item=>item.evidence_id===evidenceId);
                    return row ? row.target_oriented_delta : null}""",
                    evidence_id,
                )
                if delta is None or (
                    expected_sign > 0 and float(delta) < 0
                ) or (
                    expected_sign < 0 and float(delta) >= 0
                ):
                    failures.append(
                        f"{view} insight opens an Evidence row with the wrong ΔN2T sign"
                    )
                card.click()
                page.wait_for_selector(".workspace.panel-open")
                page.wait_for_timeout(200)
                page.locator("#detailClose").click()
        page.locator('[data-view="core"]').click()
        for core_type in ("direct", "transferred"):
            page.locator(f'[data-core-type="{core_type}"]').click()
            if not page.locator('[data-view-panel="core"]').is_visible():
                failures.append(f"Target Connection/{core_type} subtab is not visible")
        page.locator('[data-view="cuts"]').click()
        for cut in ("1", "2"):
            page.locator(f'[data-cut-view="{cut}"]').click()
            if not page.locator('[data-view-panel="cuts"]').is_visible():
                failures.append(f"N-Cuts/{cut} subtab is not visible")
        page.locator('[data-view="data"]').click()
        payload_count = page.locator("#evidenceRows tr").count()
        if payload_count < 1:
            failures.append("secondary detail table did not render evidence rows")
        directional_transferred = page.evaluate(
            """() => {const payload=JSON.parse(document.getElementById('mmpPayload').textContent);
            const row=payload.evidence.find(item=>item.connection_scope==='transferred' &&
              ['A','B'].includes(item.target_variable_side_fixed) && item.alignment_status==='core_aligned');
            return row ? row.evidence_id : null}"""
        )
        if directional_transferred:
            page.locator(
                f'tr[data-evidence-id="{directional_transferred}"]'
            ).click()
            detail_text = page.locator(".detail-body").inner_text()
            if "Observed Target-like side" not in detail_text or "Endpoint" not in detail_text:
                failures.append(
                    "Transferred detail lacks the Target-like orientation or Endpoint labels"
                )
            image_status = page.locator(".detail-body img").evaluate_all(
                "images => Object.fromEntries(images.map(image => [image.alt, "
                "image.complete && image.naturalWidth > 0]))"
            )
            required_images = (
                "Mapped Target Core", "Mapped Evidence Core",
                "Observed counterpart compound", "Observed Target-like compound",
                "Observed counterpart fragment", "Observed Target-like fragment",
            )
            missing_images = [
                label for label in required_images if not image_status.get(label, False)
            ]
            if missing_images:
                failures.append(
                    "Transferred detail images failed to load individually: "
                    + ", ".join(missing_images)
                )
            page.locator("#detailClose").click()
            checks.append("Target-like Transferred structures and Endpoints")
        nondirectional_transferred = page.evaluate(
            """() => {const payload=JSON.parse(document.getElementById('mmpPayload').textContent);
            const row=payload.evidence.find(item=>item.connection_scope==='transferred' &&
              ['both','neither'].includes(item.target_variable_side_fixed));
            return row ? row.evidence_id : null}"""
        )
        if nondirectional_transferred:
            page.locator(
                f'tr[data-evidence-id="{nondirectional_transferred}"]'
            ).evaluate("element => element.click()")
            image_status = page.locator(".detail-body img").evaluate_all(
                "images => Object.fromEntries(images.map(image => [image.alt, "
                "image.complete && image.naturalWidth > 0]))"
            )
            required_images = (
                "Mapped Target Core", "Mapped Evidence Core",
                "Observed counterpart compound", "Observed Target-like compound",
                "Observed counterpart fragment", "Observed Target-like fragment",
            )
            missing_images = [
                label for label in required_images if not image_status.get(label, False)
            ]
            if missing_images:
                failures.append(
                    "Non-directional Transferred detail images failed to load: "
                    + ", ".join(missing_images)
                )
            page.locator("#detailClose").click()
            checks.append("Non-directional Transferred structures")
        missing_transferred_core_images = page.evaluate(
            """() => {const payload=JSON.parse(document.getElementById('mmpPayload').textContent);
            return payload.evidence.filter(item => item.connection_scope==='transferred' &&
              (!item.target_core_image || !item.evidence_core_image)).map(item => item.evidence_id)}"""
        )
        if missing_transferred_core_images:
            failures.append(
                "Transferred details lack Core images: "
                + str(missing_transferred_core_images[:10])
            )
        checks.append("all Transferred Core images")
        checks.append("signed interpretation views and secondary data table")
        page.locator('[data-view="guide"]').click()
        guide_text = page.locator('[data-view-panel="guide"]').inner_text()
        for required in ("ΔN2T", "Evidence quality", "heavy atom 4", "Align ×"):
            if required not in guide_text:
                failures.append(f"Evidence Guide is missing: {required}")
        checks.append("fixed Evidence Guide")
        browser.close()
    return {
        "status": "passed" if not failures else "failed",
        "checks": checks,
        "failures": failures,
        "viewports": ["1280x720", "1440x900", "1600x900", "1920x1080"],
        "browser_executable": _browser_executable(executable) or "playwright-managed chromium",
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--browser-executable")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = audit(args.html, args.browser_executable)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
