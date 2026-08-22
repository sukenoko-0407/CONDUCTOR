from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_draft(context: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    allowed = set(context.get("allowed_result_refs") or [])
    if not str(draft.get("title") or "").strip():
        issues.append("title is required")
    if not str(draft.get("executive_summary") or "").strip():
        issues.append("executive_summary is required")
    if not str(draft.get("coverage_summary") or "").strip():
        issues.append("coverage_summary is required")
    for index, item in enumerate(draft.get("insights") or [], 1):
        prefix = f"insights[{index}]"
        if "scope" in item or "analysis_subject" in item or "insight_id" in item:
            issues.append(f"{prefix}: scope, analysis_subject, and formal insight_id are Runtime-owned")
        supporting = list(item.get("supporting_results") or [])
        comparisons = list(item.get("comparison_results") or [])
        counter = list(item.get("counter_results") or [])
        refs = set([*supporting, *comparisons, *counter])
        if not supporting:
            issues.append(f"{prefix}: supporting_results is required")
        if refs - allowed:
            issues.append(f"{prefix}: Result refs outside context: {sorted(refs-allowed)}")
        if item.get("claim_kind") in {"difference", "agreement", "contradiction"} and not comparisons:
            issues.append(f"{prefix}: comparison claim requires comparison_results")
        if not item.get("limitations"):
            issues.append(f"{prefix}: limitations is required")
        for key in ("title", "observation", "interpretation"):
            if not str(item.get(key) or "").strip():
                issues.append(f"{prefix}: {key} is required")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an ID-free CONDUCTOR 0.1.6 Interpretation draft.")
    parser.add_argument("--context", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    context = read_json(Path(args.context))
    draft = read_json(Path(args.draft))
    issues = validate_draft(context, draft)
    output = Path(args.output_dir)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    write_json(output / "validation.json", {"schema_version": "1.0.0", "status": "fail" if issues else "pass", "issues": issues})
    if issues:
        print(json.dumps({"status": "fail", "issues": issues}, ensure_ascii=False, indent=2))
        return 1
    shutil.copy2(args.draft, output / "validated_draft.json")
    lines = ["# Interpretation draft preview", "", draft["executive_summary"], ""]
    cards = []
    for index, item in enumerate(draft.get("insights") or [], 1):
        refs = ", ".join(item.get("supporting_results") or [])
        lines += [f"## Draft {index}: {item['title']}", "", f"- Claim: {item.get('claim_kind', 'single_scope_observation')}", f"- Supporting Results: {refs}", "", item["observation"], "", item["interpretation"], ""]
        cards.append(f"<article><h2>Draft {index}: {html.escape(item['title'])}</h2><p>{html.escape(item['observation'])}</p><p>{html.escape(item['interpretation'])}</p><small>{html.escape(refs)}</small></article>")
    (output / "preview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "preview.html").write_text(f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>body{{max-width:960px;margin:auto;font-family:system-ui;background:#f2f1ed;color:#29363a}}article{{background:#fff;padding:20px;margin:18px 0;border-left:6px solid #60777c}}</style></head><body><h1>{html.escape(draft['title'])}</h1><p>{html.escape(draft['executive_summary'])}</p>{''.join(cards)}</body></html>", encoding="utf-8")
    print(json.dumps({"status": "pass", "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
