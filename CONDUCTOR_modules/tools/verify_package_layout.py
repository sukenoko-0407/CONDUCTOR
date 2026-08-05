from __future__ import annotations

import json
import sys
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    required_module_files = [
        "catalog/catalog.json",
        "catalog/included_skills.json",
        "docs/CONDUCTOR_v4_policy.md",
        "docs/CONDUCTOR_v4_design_spec.md",
        "docs/CONDUCTOR_v4_interpretation_policy.md",
        "docs/prompt/CONDUCTOR_analysis_request_prompt.md",
        "docs/prompt/CONDUCTOR_session_handoff_template.md",
        "schemas/capability.schema.json",
        "pyproject.toml",
        "uv.lock",
    ]
    for relative in required_module_files:
        if not (MODULE_ROOT / relative).is_file():
            errors.append(f"missing module file: CONDUCTOR_modules/{relative}")

    agents = [
        PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md",
        PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-interpreter.md",
    ]
    for path in agents:
        if not path.is_file():
            errors.append(f"missing Claude Code Agent: {path.relative_to(PROJECT_ROOT)}")

    selection_path = MODULE_ROOT / "catalog" / "included_skills.json"
    catalog_path = MODULE_ROOT / "catalog" / "catalog.json"
    if selection_path.is_file() and catalog_path.is_file():
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        names = selection.get("included_skills") or []
        catalog_names = [entry.get("skill_name") for entry in catalog.get("capabilities") or []]
        if len(names) != len(set(names)):
            errors.append("included_skills contains duplicates")
        if set(names) != set(catalog_names):
            errors.append("catalog capabilities do not match included_skills")
        if catalog.get("selection_path") != "CONDUCTOR_modules/catalog/included_skills.json":
            errors.append("catalog selection_path does not use the packaged location")

        for name in names:
            skill = PROJECT_ROOT / ".claude" / "skills" / name
            for relative in ["SKILL.md", "capability.json", "scripts/launch.py", "env/pixi.toml"]:
                if not (skill / relative).is_file():
                    errors.append(f"{name}: missing {relative}")
            runner = skill / "scripts" / "run.py"
            if runner.is_file():
                text = runner.read_text(encoding="utf-8")
                if "CONDUCTOR_modules\" / \"catalog\" / \"catalog.json" not in text:
                    errors.append(f"{name}: runner does not resolve the packaged Catalog")
                if "skill_candidates = [SKILL_DIR, *SKILL_DIR.parents]" not in text:
                    errors.append(f"{name}: runner does not prioritize its installed Project over the caller working directory")
                if "installed_skill = candidate / \".claude\" / \"skills\" / SKILL_DIR.name" not in text:
                    errors.append(f"{name}: runner does not support standalone general-mode installation")
            capability_path = skill / "capability.json"
            if capability_path.is_file():
                capability = json.loads(capability_path.read_text(encoding="utf-8"))
                if capability.get("skill_name") != name:
                    errors.append(f"{name}: capability skill_name mismatch")
                if capability.get("stage") in {"description", "grouping", "analysis"}:
                    if not (skill / "schemas" / "execution_event.schema.json").is_file():
                        errors.append(f"{name}: execution event schema is missing")

    legacy_roots = ["catalog", "docs", "schemas", "tests", "tools"]
    for name in legacy_roots:
        path = PROJECT_ROOT / name
        if path.is_dir() and any(item.is_file() for item in path.rglob("*")):
            errors.append(f"legacy CONDUCTOR files remain outside CONDUCTOR_modules/: {name}/")
        elif path.exists():
            warnings.append(f"empty legacy directory can be removed: {name}/")

    orchestrator_agent = PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md"
    if orchestrator_agent.is_file():
        text = orchestrator_agent.read_text(encoding="utf-8")
        for required in [
            "CONDUCTOR_modules/docs/CONDUCTOR_v4_policy.md",
            "CONDUCTOR_modules/catalog/catalog.json",
        ]:
            if required not in text:
                errors.append(f"Orchestrator Agent does not reference {required}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("CONDUCTOR package layout is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
