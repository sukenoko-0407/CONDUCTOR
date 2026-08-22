from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
VERSION = "0.1.6"
SUPPORTED_COMPONENT_VERSIONS = {VERSION}
COMMON_SCIENTIFIC_OPTIONS = {
    "--conductor", "--project", "--run-id", "--round-id", "--node-id",
    "--attempt-id", "--output-dir", "--input",
}
ADAPTER_REQUIRED_OPTIONS = {
    "description": {"--id-column", "--smiles-column"},
    "structure_clustering": {"--id-column", "--smiles-column"},
    "categorical_clustering": {"--id-column", "--columns"},
    "vector_clustering": {"--id-column", "--description-result", "--input-representation"},
    "meta_clustering": {"--id-column"},
    "standard_operator": {"--id-column", "--property-column", "--higher-is-better", "--description", "--description-node-id", "--membership", "--clustering-node-id", "--scope-mode"},
    "projection_operator": {"--id-column", "--property-column", "--higher-is-better", "--description", "--description-result", "--membership", "--clustering-node-id"},
    "multidescription_operator": {"--id-column", "--property-column", "--higher-is-better", "--description", "--description-node-id", "--membership", "--clustering-node-id"},
    "mmp_operator": {"--id-column", "--smiles-column", "--endpoint-column", "--higher-is-better", "--mmp-database", "--cluster-membership"},
}


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
        "schemas/runtime_worker_status.schema.json",
        "schemas/compact_runtime_response.schema.json", "schemas/execution_request.schema.json",
        "tools/templates/conductor_request_adapter.py", "tools/templates/launch.py",
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
        errors.append("obsolete Orchestrator Agent remains; the Main Agent uses an inline Orchestrator Skill")
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
            if capability.get("skill_name") != name or capability.get("version") not in SUPPORTED_COMPONENT_VERSIONS:
                errors.append(f"{name}: metadata identity/version mismatch")
            stage = capability.get("stage")
            if stage in {"description", "clustering", "analysis"}:
                run_text = (root / "scripts" / "run.py").read_text(encoding="utf-8")
                skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
                launcher_text = (root / "scripts" / "launch.py").read_text(encoding="utf-8")
                if not isinstance(capability.get("conductor_request"), dict):
                    errors.append(f"{name}: missing conductor_request capability contract")
                    adapter_name = None
                else:
                    adapter_name = capability["conductor_request"].get("adapter")
                if not (root / "scripts" / "conductor_request_adapter.py").is_file():
                    errors.append(f"{name}: missing common Execution Request adapter")
                if "--conductor-request" not in launcher_text:
                    errors.append(f"{name}: launcher has no common Execution Request entry")
                for token in (".bootstrap.lock", ".environment-ready", '"--locked"', "owner.json", "environment_fingerprint", "manifest.read_bytes()"):
                    if token not in launcher_text:
                        errors.append(f"{name}: launcher lacks concurrent Pixi bootstrap guard ({token})")
                for token in ("--conductor", "--round-id", "--node-id", "--attempt-id"):
                    if token not in run_text:
                        errors.append(f"{name}: scientific kernel lacks internal CONDUCTOR context ({token})")
                expected_options = COMMON_SCIENTIFIC_OPTIONS | ADAPTER_REQUIRED_OPTIONS.get(str(adapter_name), set())
                for option in sorted(expected_options):
                    if option not in run_text:
                        errors.append(f"{name}: {adapter_name} adapter may emit unsupported CLI option {option}")
                for parameter, value in (capability.get("default_parameters") or {}).items():
                    if parameter in {"role", "target_cluster", "comparison_cluster"} or value is False or value is None:
                        continue
                    option = "--" + str(parameter).replace("_", "-")
                    if option not in run_text:
                        errors.append(f"{name}: default parameter has no matching CLI option ({option})")
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
        exploration = profile.get("exploration", {})
        expected_operators = {f"A{i:03d}" for i in range(1, 15)}
        if set(exploration.get("global_operator_capabilities", [])) != expected_operators:
            errors.append("Global exploration must contain every Operator")
        if profile.get("runtime_planning", {}).get("max_new_analysis_nodes_per_round") != 100:
            errors.append("Round Analysis limit must be 100")
        if exploration.get("scope_sequence") != ["global", "global", "local"]:
            errors.append("Global-first exploration sequence mismatch")
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

    orchestrator_root = PROJECT_ROOT / ".claude" / "skills" / "cs-conductor-orchestrator"
    orchestrator = orchestrator_root / "SKILL.md"
    if not orchestrator.is_file():
        errors.append("missing Main Agent Orchestrator Skill")
    elif "disable-model-invocation: true" not in orchestrator.read_text(encoding="utf-8"):
        errors.append("Main Agent Orchestrator Skill is not manual-only")
    orchestrator_manifest = orchestrator_root / "env" / "pixi.toml"
    if not orchestrator_manifest.is_file():
        errors.append("missing Main Agent Orchestrator Pixi manifest")
    else:
        try:
            manifest = tomllib.loads(orchestrator_manifest.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid Main Agent Orchestrator Pixi manifest: {exc}")
        else:
            dependencies = manifest.get("dependencies", {})
            if set(dependencies) != {"python"}:
                errors.append("Orchestrator Pixi environment must remain a Python-only Runtime launcher")
            smoke = manifest.get("tasks", {}).get("smoke", "")
            if "py_compile" not in smoke:
                errors.append("Orchestrator smoke task must compile its thin launcher")
    orchestrator_runner = orchestrator_root / "scripts" / "run.py"
    if orchestrator_runner.is_file():
        runner_text = orchestrator_runner.read_text(encoding="utf-8")
        if "cs-conductor-runtime" not in runner_text or '"runtime_controller.py"' in runner_text:
            errors.append("Orchestrator must delegate every control command through the Runtime launcher")

    runtime_root = PROJECT_ROOT / ".claude" / "skills" / "cs-conductor-runtime"
    runtime_manifest = runtime_root / "env" / "pixi.toml"
    if not runtime_manifest.is_file():
        errors.append("missing CONDUCTOR Runtime Pixi manifest")
    else:
        try:
            manifest = tomllib.loads(runtime_manifest.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid CONDUCTOR Runtime Pixi manifest: {exc}")
        else:
            dependencies = manifest.get("dependencies", {})
            for dependency in ("jsonschema", "referencing", "pandas", "pyarrow"):
                if dependency not in dependencies:
                    errors.append(f"missing CONDUCTOR Runtime dependency: {dependency}")
                if dependency not in manifest.get("tasks", {}).get("smoke", ""):
                    errors.append(f"Runtime smoke task does not import: {dependency}")

    executor = PROJECT_ROOT / ".claude" / "agents" / "cs-conductor-executor.md"
    if executor.is_file():
        executor_text = executor.read_text(encoding="utf-8")
        for token in ("compatibility-only", "deterministic OS Worker", "A background-task identifier", "Never start another packet", "<CONDUCTOR_RUNTIME_PYTHON>"):
            if token not in executor_text:
                errors.append(f"Executor contract is missing: {token}")
        frontmatter = executor_text.split("---", 2)[1]
        tools_line = next((line for line in frontmatter.splitlines() if line.startswith("tools:")), "")
        if "Agent" in tools_line or "Skill" in tools_line:
            errors.append("Executor must not have Agent or Skill tools")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("CONDUCTOR 0.1.6 package layout is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
