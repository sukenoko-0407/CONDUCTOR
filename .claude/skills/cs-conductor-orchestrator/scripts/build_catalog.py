from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]


def find_workspace() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / ".claude" / "skills").exists() and (candidate / "catalog").exists():
            return candidate
    raise RuntimeError("CONDUCTOR workspace could not be located")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_capability(value: dict[str, Any], expected_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required to validate the Catalog") from exc
    schema = json.loads((SKILL_DIR / "schemas" / "capability.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)
    if value["skill_name"] != expected_name:
        raise ValueError(f"{expected_name}: metadata skill_name mismatch")
    if value["cost"].get("class") in {"high", "very_high"} and not value["cost"].get("human_approval_required"):
        raise ValueError(f"{expected_name}: high-cost capability must require human approval")


def render_markdown(catalog: dict[str, Any]) -> str:
    lines = ["# CONDUCTOR v4 Skill Catalog", "", "> この文書は`catalog/catalog.json`から生成される。収載対象は人間管理の`catalog/included_skills.json`で指定する。", "", f"Generated: `{catalog['generated_at']}`", ""]
    for stage in ["description", "grouping", "analysis", "interpretation", "orchestration"]:
        entries = [entry for entry in catalog["capabilities"] if entry["stage"] == stage]
        if not entries:
            continue
        lines.extend([f"## {stage.title()}", "", "| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |", "|---|---|---|---|---|---|---|---|"])
        for entry in entries:
            variants = ", ".join(item["id"] for item in entry.get("variants") or []) or "-"
            if entry.get("default_variant"):
                variants += f" (default: {entry['default_variant']})"
            lines.append(f"| {entry['capability_id']} | `{entry['skill_name']}` | {entry['display_name']} | {variants} | {entry['family']} | {entry['cost']['class']} | {entry['applicability']['status']} | {entry['cost']['human_approval_required']} |")
        lines.append("")
    return "\n".join(lines)


def build(workspace: Path) -> tuple[dict[str, Any], str]:
    selection_path = workspace / "catalog" / "included_skills.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    names = selection.get("included_skills") or []
    if len(names) != len(set(names)):
        raise ValueError("included_skills contains duplicates")
    capabilities = []
    for name in names:
        path = workspace / ".claude" / "skills" / name / "capability.json"
        if not path.exists():
            raise FileNotFoundError(f"Allowlisted Skill metadata not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        validate_capability(value, name)
        capabilities.append(value)
    capabilities.sort(key=lambda item: item["capability_id"])
    ids = [item["capability_id"] for item in capabilities]
    if len(ids) != len(set(ids)):
        raise ValueError("Capability IDs must be unique")
    catalog = {"schema_version": "1.0.0", "conductor_version": "4.0.0", "selection_managed_by": "human", "selection_path": "catalog/included_skills.json", "generated_at": utc_now(), "capabilities": capabilities}
    return catalog, render_markdown(catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the human-curated CONDUCTOR v4 Catalog.")
    parser.add_argument("--check", action="store_true", help="Validate metadata and selection without writing.")
    args = parser.parse_args()
    workspace = find_workspace()
    catalog, markdown = build(workspace)
    if not args.check:
        (workspace / "catalog" / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (workspace / "docs" / "CONDUCTOR_v4_skill_catalog.md").write_text(markdown, encoding="utf-8")
    print(f"Validated {len(catalog['capabilities'])} allowlisted capabilities")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
