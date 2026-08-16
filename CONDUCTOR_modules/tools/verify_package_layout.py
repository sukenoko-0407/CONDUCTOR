from __future__ import annotations

import json
import sys
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent


def main() -> int:
    errors: list[str] = []
    required = [
        "VERSION", "catalog/catalog.json", "catalog/included_skills.json", "catalog/analysis_profile.json",
        "docs/README.md", "docs/CONDUCTOR_overview.md", "docs/CONDUCTOR_policy.md",
        "docs/CONDUCTOR_interpretation_policy.md", "docs/CONDUCTOR_design_spec.md",
        "docs/CONDUCTOR_output_contract.md", "docs/CONDUCTOR_identifier_reference.md",
        "docs/CONDUCTOR_skill_catalog.md", "schemas/capability.schema.json", "schemas/state.schema.json",
        "schemas/execution_event.schema.json", "schemas/operator_summary.schema.json",
        "schemas/interpretation.schema.json", "schemas/analysis_profile.schema.json",
        "tools/templates/state_manager.py", "tools/migrate_description_010_to_011.py", "pyproject.toml", "uv.lock",
    ]
    for relative in required:
        if not (MODULE_ROOT / relative).is_file(): errors.append(f"missing module file: CONDUCTOR_modules/{relative}")
    version = (MODULE_ROOT / "VERSION").read_text(encoding="utf-8").strip() if (MODULE_ROOT / "VERSION").is_file() else None
    if version != "0.1.1": errors.append(f"unexpected package version: {version}")

    for name in ("cs-conductor-orchestrator.md", "cs-conductor-interpreter.md", "cs-conductor-description-migrator.md"):
        if not (PROJECT_ROOT / ".claude" / "agents" / name).is_file(): errors.append(f"missing Agent: {name}")

    obsolete_paths=[
        PROJECT_ROOT/".claude"/"agents"/"cs-conductor-v430-migrator.md",
        PROJECT_ROOT/".claude"/"skills"/"cs-conductor-migrate-v430-run",
        MODULE_ROOT/"schemas"/"evidence.schema.json",
        MODULE_ROOT/"schemas"/"evidence_digest.schema.json",
        MODULE_ROOT/"schemas"/"interpretation_id_reservation.schema.json",
        MODULE_ROOT/"tools"/"render_explanation_docs.py",
    ]
    for path in obsolete_paths:
        if path.exists(): errors.append(f"obsolete 0.1.1 path remains: {path.relative_to(PROJECT_ROOT)}")
    legacy_schema_names={"evidence.schema.json","evidence_digest.schema.json","interpretation_id_reservation.schema.json"}
    skill_root=PROJECT_ROOT/".claude"/"skills"
    for path in skill_root.rglob("*.json") if skill_root.is_dir() else []:
        if path.name in legacy_schema_names and "env" not in path.parts: errors.append(f"obsolete Skill schema remains: {path.relative_to(PROJECT_ROOT)}")

    selection_path=MODULE_ROOT/"catalog"/"included_skills.json";catalog_path=MODULE_ROOT/"catalog"/"catalog.json"
    if selection_path.is_file() and catalog_path.is_file():
        selection=json.loads(selection_path.read_text(encoding="utf-8"));catalog=json.loads(catalog_path.read_text(encoding="utf-8"))
        names=[*selection.get("included_skills",[]),*selection.get("support_skills",[])]
        allowlisted=set(selection.get("included_skills",[]));catalog_names={item.get("skill_name") for item in catalog.get("capabilities",[])}
        if len(names)!=len(set(names)): errors.append("Skill selection contains duplicates")
        if allowlisted!=catalog_names: errors.append("Catalog does not match included_skills")
        if catalog.get("conductor_version")!="0.1.1": errors.append("Catalog version mismatch")
        for name in names:
            root=PROJECT_ROOT/".claude"/"skills"/name
            for relative in ("SKILL.md","README.md","capability.json","scripts/launch.py","env/pixi.toml"):
                if not (root/relative).is_file(): errors.append(f"{name}: missing {relative}")
            if not (root/"capability.json").is_file(): continue
            capability=json.loads((root/"capability.json").read_text(encoding="utf-8"))
            if capability.get("skill_name")!=name: errors.append(f"{name}: capability skill_name mismatch")
            if capability.get("version")!="0.1.1": errors.append(f"{name}: capability version mismatch")
            stage=capability.get("stage")
            if stage in {"description","clustering","analysis","interpretation"}:
                if not (root/"schemas"/"execution_event.schema.json").is_file(): errors.append(f"{name}: execution event schema missing")
                run_text=(root/"scripts"/"run.py").read_text(encoding="utf-8")
                skill_text=(root/"SKILL.md").read_text(encoding="utf-8")
                if "--round-id" not in run_text: errors.append(f"{name}: CONDUCTOR CLI does not expose --round-id")
                if "--round-id RND0001" not in skill_text: errors.append(f"{name}: SKILL.md lacks a complete Round-scoped example")
            if stage=="analysis":
                for relative in ("schemas/operator_summary.schema.json","scripts/operator_report.py"):
                    if not (root/relative).is_file() and capability.get("capability_id") not in {"A003","A004","A005"}: errors.append(f"{name}: missing {relative}")
                text=run_text
                for token in ("operator_summary.json","operator_report.html","--round-id","--attempt-id"):
                    if token not in text: errors.append(f"{name}: Operator contract missing {token}")

    profile_path=MODULE_ROOT/"catalog"/"analysis_profile.json"
    if profile_path.is_file():
        profile=json.loads(profile_path.read_text(encoding="utf-8"))
        if profile.get("profile_id")!="comprehensive-multiround-beta": errors.append("unexpected analysis profile")
        if profile.get("modeling",{}).get("fixed_description_panel") != ["D001","D002","D006","D013","D016","D019"]: errors.append("A005 fixed panel mismatch")
        initial=profile.get("initial_exploration",{})
        if initial.get("projection_overlay_capabilities") != ["A003","A004"]: errors.append("projection overlay profile mismatch")
        if set(initial.get("global_operator_capabilities",[])) != {f"A{i:03d}" for i in range(1,14)}: errors.append("initial Global exploration must contain every Operator")
        if profile.get("modeling",{}).get("minimum_local_samples") != 30: errors.append("A005 minimum Local sample count mismatch")

    if catalog_path.is_file():
        by_id={item.get("capability_id"):item for item in json.loads(catalog_path.read_text(encoding="utf-8")).get("capabilities",[])}
        a005=by_id.get("A005",{})
        if a005.get("cost",{}).get("human_approval_required") is not False: errors.append("A005 must be preauthorized in initial exploration")
        mcs=by_id.get("C002",{}).get("default_parameters",{})
        if mcs.get("max_pairs") != 1000 or int(mcs.get("max_core_clusters",0)) < 300: errors.append("MCS exploration limit mismatch")

    public_roots=[PROJECT_ROOT/".claude"/"agents",PROJECT_ROOT/".claude"/"skills",MODULE_ROOT/"catalog",MODULE_ROOT/"docs",MODULE_ROOT/"schemas"]
    forbidden=("CONDUCTOR_v4","interpret-evidence","pretrained-embedding")
    for root in public_roots:
        for path in root.rglob("*") if root.exists() else []:
            if path.is_file() and path.suffix.lower() in {".md",".json"}:
                if "env" in path.parts or "refactoring_plan" in path.name: continue
                text=path.read_text(encoding="utf-8",errors="ignore")
                for token in forbidden:
                    if token in text and "v430" not in str(path): errors.append(f"obsolete public token {token}: {path.relative_to(PROJECT_ROOT)}")

    if errors:
        for error in errors: print(f"ERROR: {error}",file=sys.stderr)
        return 1
    print("CONDUCTOR 0.1.1 package layout is valid")
    return 0


if __name__ == "__main__": raise SystemExit(main())
