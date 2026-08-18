from __future__ import annotations

import json
import sys
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
VERSION = "0.1.3"


def main() -> int:
    errors: list[str] = []
    required = [
        "VERSION", "catalog/catalog.json", "catalog/included_skills.json", "catalog/analysis_profile.json",
        "docs/README.md", "docs/CONDUCTOR_overview.md", "docs/CONDUCTOR_policy.md",
        "docs/CONDUCTOR_interpretation_policy.md", "docs/CONDUCTOR_design_spec.md",
        "docs/CONDUCTOR_output_contract.md", "docs/CONDUCTOR_identifier_reference.md",
        "docs/CONDUCTOR_skill_catalog.md", "schemas/capability.schema.json",
        "schemas/conductor_control.schema.json", "schemas/runtime_event.schema.json",
        "schemas/node_record.schema.json", "schemas/round_contract.schema.json",
        "schemas/round_outcome.schema.json", "schemas/analysis_subject.schema.json",
        "schemas/result_card.schema.json", "schemas/working_set.schema.json",
        "schemas/interpretation.schema.json", "tools/runtime_controller.py",
        "schemas/execution_packet.schema.json", "schemas/failure_packet.schema.json",
        "schemas/compact_runtime_response.schema.json", "schemas/recovery_manifest.schema.json",
        "tools/templates/state_manager.py", "pyproject.toml", "uv.lock",
    ]
    for relative in required:
        if not (MODULE_ROOT / relative).is_file():
            errors.append(f"missing module file: CONDUCTOR_modules/{relative}")
    version = (MODULE_ROOT / "VERSION").read_text(encoding="utf-8").strip() if (MODULE_ROOT / "VERSION").is_file() else None
    if version != VERSION:
        errors.append(f"unexpected package version: {version}")

    for name in ("cs-conductor-executor.md", "cs-conductor-interpreter.md"):
        if not (PROJECT_ROOT / ".claude" / "agents" / name).is_file():
            errors.append(f"missing Agent: {name}")
    if (PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").exists():
        errors.append("obsolete Orchestrator Agent remains; 0.1.3 uses an inline Main Agent Skill")
    if (PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-description-migrator.md").exists():
        errors.append("obsolete migration Agent remains")

    obsolete = [
        MODULE_ROOT / "schemas" / "state.schema.json",
        MODULE_ROOT / "tools" / "migrate_description_010_to_011.py",
        MODULE_ROOT / "docs" / "CONDUCTOR_0.1.0_to_0.1.1_description_migration.md",
    ]
    for path in obsolete:
        if path.exists():
            errors.append(f"obsolete path remains: {path.relative_to(PROJECT_ROOT)}")
    old_dispatch = PROJECT_ROOT / ".claude" / "skills" / "cs-conductor-dispatch"
    if any((old_dispatch / name).exists() for name in ("SKILL.md", "capability.json", "README.md")):
        errors.append("obsolete cs-conductor-dispatch Skill remains")

    selection_path = MODULE_ROOT / "catalog" / "included_skills.json"
    catalog_path = MODULE_ROOT / "catalog" / "catalog.json"
    if selection_path.is_file() and catalog_path.is_file():
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        included = selection.get("included_skills", [])
        support = selection.get("support_skills", [])
        all_names = [*included, *support]
        if len(all_names) != len(set(all_names)):
            errors.append("Skill selection contains duplicates")
        if set(included) != {item.get("skill_name") for item in catalog.get("capabilities", [])}:
            errors.append("Catalog does not match included_skills")
        if catalog.get("conductor_version") != VERSION:
            errors.append("Catalog version mismatch")
        capability_ids: list[str] = []
        for name in all_names:
            root = PROJECT_ROOT / ".claude" / "skills" / name
            for relative in ("SKILL.md", "README.md", "capability.json", "scripts/launch.py", "env/pixi.toml"):
                if not (root / relative).is_file():
                    errors.append(f"{name}: missing {relative}")
            if not (root / "capability.json").is_file():
                continue
            capability = json.loads((root / "capability.json").read_text(encoding="utf-8"))
            capability_ids.append(str(capability.get("capability_id")))
            if capability.get("skill_name") != name or capability.get("version") != VERSION:
                errors.append(f"{name}: metadata identity/version mismatch")
            stage = capability.get("stage")
            if stage in {"description", "clustering", "analysis"}:
                run_text = (root / "scripts" / "run.py").read_text(encoding="utf-8")
                skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
                for token in ("--conductor", "--round-id", "--node-id", "--attempt-id"):
                    if token not in run_text or token not in skill_text:
                        errors.append(f"{name}: incomplete CONDUCTOR execution contract ({token})")
            if stage == "interpretation":
                if (root / "schemas" / "state.schema.json").exists():
                    errors.append(f"{name}: obsolete State schema remains")
                for relative in ("schemas/result_card.schema.json", "schemas/analysis_subject.schema.json", "scripts/render.py"):
                    if not (root / relative).is_file():
                        errors.append(f"{name}: missing {relative}")
        if len(capability_ids) != len(set(capability_ids)):
            errors.append("Capability IDs are not unique across selected Skills")

    profile_path = MODULE_ROOT / "catalog" / "analysis_profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if set(profile.get("initial_exploration", {}).get("global_operator_capabilities", [])) != {f"A{i:03d}" for i in range(1, 14)}:
            errors.append("initial Global exploration must contain every Operator")
        if profile.get("modeling", {}).get("minimum_local_samples") != 30:
            errors.append("minimum Local model sample count mismatch")

    public_roots = [PROJECT_ROOT / ".claude" / "agents", MODULE_ROOT / "docs", MODULE_ROOT / "schemas"]
    for root in public_roots:
        for path in root.rglob("*") if root.exists() else []:
            if path.is_file() and path.suffix.lower() in {".md", ".json"} and "runtime_redesign" not in path.name:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in ("cs-conductor-description-migrator", "CL######", "ACT####", "orchestrator_brief.json"):
                    if token in text:
                        errors.append(f"obsolete public token {token}: {path.relative_to(PROJECT_ROOT)}")

    orchestrator = PROJECT_ROOT / ".claude" / "skills" / "cs-conductor-orchestrator" / "SKILL.md"
    if not orchestrator.is_file():
        errors.append("missing Main Agent Orchestrator Skill")
    elif "disable-model-invocation: true" not in orchestrator.read_text(encoding="utf-8"):
        errors.append("Main Agent Orchestrator Skill is not manual-only")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("CONDUCTOR 0.1.3 package layout is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
