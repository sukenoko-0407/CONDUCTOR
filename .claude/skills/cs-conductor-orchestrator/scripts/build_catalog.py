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
    approval_policy = value.get("approval_policy", "standard")
    high_cost = value["cost"].get("class") in {"high", "very_high"}
    approval_required = bool(value["cost"].get("human_approval_required"))
    if approval_policy == "preauthorized_initial":
        if not high_cost or approval_required or not value.get("default_wide_shallow"):
            raise ValueError(
                f"{expected_name}: preauthorized_initial requires a high-cost, "
                "approval-free default_wide_shallow capability"
            )
    elif high_cost and not approval_required:
        raise ValueError(f"{expected_name}: high-cost capability must require human approval unless explicitly preauthorized")
    if value["stage"] != "grouping":
        return
    kind = value.get("grouping_kind")
    algorithm = value.get("implementation", {}).get("algorithm", "")
    contracts = value.get("input_contract") or []
    dependencies = value.get("dependencies") or []
    if kind == "direct_structure":
        if algorithm not in {"structure_murcko", "structure_mcs", "structure_brics", "structure_recap"}:
            raise ValueError(f"{expected_name}: direct_structure must use an explicit structure rule, decomposition, or MCS algorithm")
        if contracts != ["smiles_csv_or_inline_smiles"] or dependencies:
            raise ValueError(f"{expected_name}: direct_structure must consume SMILES directly and have no Description dependency")
    elif kind == "description_vector":
        if not algorithm.startswith("vector_"):
            raise ValueError(f"{expected_name}: description_vector must use a vector_* implementation")
        if contracts != ["description_vector_csv"] or dependencies != ["description"]:
            raise ValueError(f"{expected_name}: description_vector must consume one Description vector artifact")
    elif kind not in {"categorical", "meta"}:
        raise ValueError(f"{expected_name}: grouping_kind is missing or unsupported")


def render_markdown(catalog: dict[str, Any]) -> str:
    lines = ["# CONDUCTOR v4 Skill Catalog", "", "> この文書は`catalog/catalog.json`から生成される。収載対象は人間管理の`catalog/included_skills.json`で指定する。", "", f"Generated: `{catalog['generated_at']}`", ""]
    for stage in ["description", "grouping", "analysis", "interpretation", "orchestration"]:
        entries = [entry for entry in catalog["capabilities"] if entry["stage"] == stage]
        if not entries:
            continue
        lines.extend([f"## {stage.title()}", "", "| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Wide axis | Wide sources | Cost | Status | Human approval |", "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for entry in entries:
            variants = ", ".join(item["id"] for item in entry.get("variants") or []) or "-"
            if entry.get("default_variant"):
                variants += f" (default: {entry['default_variant']})"
            axis = entry.get("wide_shallow_axis") or "-"
            sources = "; ".join(f"{role}: {', '.join(values)}" for role, values in (entry.get("wide_shallow_sources") or {}).items()) or "-"
            grouping_kind = entry.get("grouping_kind") or "-"
            input_contract = ", ".join(entry.get("input_contract") or []) or "-"
            lines.append(f"| {entry['capability_id']} | `{entry['skill_name']}` | {entry['display_name']} | {variants} | {entry['family']} | {grouping_kind} | {input_contract} | {axis} | {sources} | {entry['cost']['class']} | {entry['applicability']['status']} | {entry['cost']['human_approval_required']} |")
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
    by_id = {item["capability_id"]: item for item in capabilities}
    for capability in capabilities:
        if not capability.get("default_wide_shallow"):
            continue
        if not capability.get("wide_shallow_axis"):
            raise ValueError(f"{capability['capability_id']}: default wide-shallow capability requires wide_shallow_axis")
        sources = capability.get("wide_shallow_sources") or {}
        parameter_overrides = capability.get("wide_shallow_parameter_overrides") or {}
        for dependency_stage in (stage for stage in capability.get("dependencies") or [] if stage != "evidence"):
            if dependency_stage not in sources:
                raise ValueError(f"{capability['capability_id']}: default wide-shallow dependency {dependency_stage} requires explicit wide_shallow_sources")
            for source_id in sources[dependency_stage]:
                if source_id == "*":
                    continue
                source = by_id.get(source_id)
                if source is None:
                    raise ValueError(f"{capability['capability_id']}: unknown wide-shallow source {source_id}")
                if source["stage"] != dependency_stage:
                    raise ValueError(f"{capability['capability_id']}: source {source_id} is not stage {dependency_stage}")
                if not source.get("default_wide_shallow"):
                    raise ValueError(f"{capability['capability_id']}: source {source_id} is not in the default wide-shallow plan")
        for dependency_stage, source_overrides in parameter_overrides.items():
            if dependency_stage not in (capability.get("dependencies") or []):
                raise ValueError(f"{capability['capability_id']}: parameter override stage {dependency_stage} is not a dependency")
            allowed_sources = sources.get(dependency_stage) or []
            for source_id in source_overrides:
                source = by_id.get(source_id)
                if source is None or source["stage"] != dependency_stage:
                    raise ValueError(f"{capability['capability_id']}: invalid parameter override source {source_id}")
                if "*" not in allowed_sources and source_id not in allowed_sources:
                    raise ValueError(f"{capability['capability_id']}: parameter override source {source_id} is not declared in wide_shallow_sources")
    catalog = {"schema_version": "1.0.0", "conductor_version": "4.0.0", "selection_managed_by": "human", "selection_path": "catalog/included_skills.json", "generated_at": utc_now(), "capabilities": capabilities}
    return catalog, render_markdown(catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the human-curated CONDUCTOR v4 Catalog.")
    parser.add_argument("--check", action="store_true", help="Validate metadata and selection without writing.")
    args = parser.parse_args()
    workspace = find_workspace()
    catalog, markdown = build(workspace)
    if args.check:
        catalog_path = workspace / "catalog" / "catalog.json"
        markdown_path = workspace / "docs" / "CONDUCTOR_v4_skill_catalog.md"
        if not catalog_path.exists() or not markdown_path.exists():
            raise FileNotFoundError("Generated Catalog artifacts are missing")
        existing = json.loads(catalog_path.read_text(encoding="utf-8"))
        comparable_existing = {key: value for key, value in existing.items() if key != "generated_at"}
        comparable_generated = {key: value for key, value in catalog.items() if key != "generated_at"}
        if comparable_existing != comparable_generated:
            raise ValueError("catalog/catalog.json is stale; rebuild the Catalog")
        catalog["generated_at"] = existing["generated_at"]
        if markdown_path.read_text(encoding="utf-8") != render_markdown(catalog):
            raise ValueError("docs/CONDUCTOR_v4_skill_catalog.md is stale; rebuild the Catalog")
    else:
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
