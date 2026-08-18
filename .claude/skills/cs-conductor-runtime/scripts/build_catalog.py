from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]


def find_workspace() -> Path:
    for candidate in [SKILL_DIR, *SKILL_DIR.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / ".claude" / "skills").is_dir() and (candidate / "CONDUCTOR_modules" / "catalog").is_dir():
            return candidate
    raise RuntimeError("CONDUCTOR project root could not be located")


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
        if not high_cost or approval_required:
            raise ValueError(
                f"{expected_name}: preauthorized_initial requires a high-cost, approval-free capability"
            )
    elif high_cost and not approval_required:
        raise ValueError(f"{expected_name}: high-cost capability must require human approval unless explicitly preauthorized")
    if value["stage"] != "clustering":
        return
    kind = value.get("clustering_kind")
    algorithm = value.get("implementation", {}).get("algorithm", "")
    contracts = value.get("input_contract") or []
    dependencies = value.get("dependencies") or []
    if kind == "direct_structure":
        if algorithm not in {"structure_murcko", "structure_mcs", "structure_brics", "structure_recap"}:
            raise ValueError(f"{expected_name}: direct_structure must use an explicit structure rule, decomposition, or MCS algorithm")
        if contracts != ["compound_id_smiles_csv"] or dependencies:
            raise ValueError(f"{expected_name}: direct_structure must consume a compound-ID/SMILES CSV and have no Description dependency")
    elif kind == "description_vector":
        if not algorithm.startswith("vector_"):
            raise ValueError(f"{expected_name}: description_vector must use a vector_* implementation")
        if contracts != ["description_vector_csv"] or dependencies != ["description"]:
            raise ValueError(f"{expected_name}: description_vector must consume one Description vector artifact")
    elif kind not in {"categorical", "meta"}:
        raise ValueError(f"{expected_name}: clustering_kind is missing or unsupported")


def render_markdown(catalog: dict[str, Any]) -> str:
    lines = ["# CONDUCTOR Skill Catalog", "", "> この文書は`CONDUCTOR_modules/catalog/catalog.json`から生成される。収載対象は人間管理の`CONDUCTOR_modules/catalog/included_skills.json`、解析profileは`CONDUCTOR_modules/catalog/analysis_profile.json`で指定する。", "", f"Profile: `{catalog['profile_id']}`", f"Generated: `{catalog['generated_at']}`", ""]
    for stage in ["description", "clustering", "analysis", "interpretation", "orchestration"]:
        entries = [entry for entry in catalog["capabilities"] if entry["stage"] == stage]
        if not entries:
            continue
        lines.extend([f"## {stage.title()}", "", "| ID | Skill | Capability | Variants | Family | Clustering kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |", "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for entry in entries:
            variants = ", ".join(item["id"] for item in entry.get("variants") or []) or "-"
            if entry.get("default_variant"):
                variants += f" (default: {entry['default_variant']})"
            semantics = entry.get("value_semantics") or "-"
            metric = entry.get("natural_metric") or "-"
            clustering_kind = entry.get("clustering_kind") or "-"
            input_contract = ", ".join(entry.get("input_contract") or []) or "-"
            lines.append(f"| {entry['capability_id']} | `{entry['skill_name']}` | {entry['display_name']} | {variants} | {entry['family']} | {clustering_kind} | {input_contract} | {semantics} | {metric} | {entry['cost']['class']} | {entry['applicability']['status']} | {entry['cost']['human_approval_required']} |")
        lines.append("")
    return "\n".join(lines)


def build(workspace: Path) -> tuple[dict[str, Any], str]:
    modules = workspace / "CONDUCTOR_modules"
    selection_path = modules / "catalog" / "included_skills.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    names = selection.get("included_skills") or []
    if len(names) != len(set(names)):
        raise ValueError("included_skills contains duplicates")
    profile_path = modules / "catalog" / "analysis_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required to validate the analysis profile") from exc
    jsonschema.validate(profile, json.loads((modules / "schemas" / "analysis_profile.schema.json").read_text(encoding="utf-8")))
    capabilities = []
    for name in names:
        path = workspace / ".claude" / "skills" / name / "capability.json"
        if not path.exists():
            raise FileNotFoundError(f"Allowlisted Skill metadata not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        validate_capability(value, name)
        value = dict(value)
        capabilities.append(value)
    capabilities.sort(key=lambda item: item["capability_id"])
    ids = [item["capability_id"] for item in capabilities]
    if len(ids) != len(set(ids)):
        raise ValueError("Capability IDs must be unique")
    known = set(ids)
    referenced = set()
    for key in ["description_capabilities", "direct_structure_clustering", "vector_clustering_capabilities", "vector_clustering_representations", "conditional_clustering", "high_cost_bundle"]:
        referenced.update(profile["basic_compute"].get(key) or [])
    for key in ["description_master_panel", "global_operator_capabilities", "local_operator_capabilities"]:
        referenced.update(profile["initial_exploration"][key])
    referenced.update(profile["additional_exploration"]["operator_capabilities"])
    referenced.update(profile["modeling"]["fixed_description_panel"])
    unknown = sorted(referenced - known)
    if unknown:
        raise ValueError(f"Analysis profile references unknown capabilities: {unknown}")
    catalog = {"schema_version": "2.0.0", "conductor_version": "0.1.3", "profile_id": profile["profile_id"], "profile_path": "CONDUCTOR_modules/catalog/analysis_profile.json", "profile_hash": hashlib.sha256(profile_path.read_bytes()).hexdigest(), "selection_managed_by": "human", "selection_path": "CONDUCTOR_modules/catalog/included_skills.json", "generated_at": utc_now(), "capabilities": capabilities}
    return catalog, render_markdown(catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the human-curated CONDUCTOR Catalog.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Validate metadata and selection without writing (default).")
    mode.add_argument("--write", action="store_true", help="Explicit maintenance mode: regenerate the packaged Catalog and Markdown.")
    args = parser.parse_args()
    workspace = find_workspace()
    modules = workspace / "CONDUCTOR_modules"
    catalog, markdown = build(workspace)
    if not args.write:
        catalog_path = modules / "catalog" / "catalog.json"
        markdown_path = modules / "docs" / "CONDUCTOR_skill_catalog.md"
        if not catalog_path.exists() or not markdown_path.exists():
            raise FileNotFoundError("Generated Catalog artifacts are missing")
        existing = json.loads(catalog_path.read_text(encoding="utf-8"))
        comparable_existing = {key: value for key, value in existing.items() if key != "generated_at"}
        comparable_generated = {key: value for key, value in catalog.items() if key != "generated_at"}
        if comparable_existing != comparable_generated:
            raise ValueError("CONDUCTOR_modules/catalog/catalog.json is stale; rebuild the Catalog")
        catalog["generated_at"] = existing["generated_at"]
        if markdown_path.read_text(encoding="utf-8") != render_markdown(catalog):
            raise ValueError("CONDUCTOR_modules/docs/CONDUCTOR_skill_catalog.md is stale; rebuild the Catalog")
    else:
        (modules / "catalog" / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (modules / "docs" / "CONDUCTOR_skill_catalog.md").write_text(markdown, encoding="utf-8")
    print(f"Validated {len(catalog['capabilities'])} allowlisted capabilities")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
