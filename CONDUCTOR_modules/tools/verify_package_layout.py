from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
VERSION = "0.2.0"
# Skill implementation versions are independent from the Run artifact
# contract.  Older scientific kernels remain supported, but all newly emitted
# CONDUCTOR artifacts must declare VERSION.
SUPPORTED_COMPONENT_VERSIONS = {"0.1.6", "0.1.7", VERSION}
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
        "schemas/result_card.schema.json", "schemas/operator_interpretation_profile.schema.json",
        "schemas/review_bundle.schema.json", "schemas/working_set.schema.json",
        "schemas/result_assessment.schema.json", "schemas/screening_batch.schema.json",
        "schemas/screening_draft.schema.json", "schemas/screening_summary.schema.json",
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

    def schema(relative: str) -> dict:
        return json.loads((MODULE_ROOT / "schemas" / relative).read_text(encoding="utf-8"))

    protocol_schemas = (
        "compact_runtime_response.schema.json",
        "execution_packet.schema.json",
        "runtime_worker_status.schema.json",
        "failure_packet.schema.json",
    )
    for name in protocol_schemas:
        path = MODULE_ROOT / "schemas" / name
        if path.is_file() and schema(name).get("properties", {}).get("protocol_version", {}).get("const") != VERSION:
            errors.append(f"Protocol version mismatch: schemas/{name}")
    control_path = MODULE_ROOT / "schemas" / "conductor_control.schema.json"
    if control_path.is_file() and schema("conductor_control.schema.json").get("properties", {}).get("conductor_version", {}).get("const") != VERSION:
        errors.append("Control schema CONDUCTOR version mismatch")

    mirror_contracts = {
        ".claude/skills/cs-conductor-runtime/schemas/capability.schema.json": "capability.schema.json",
        ".claude/skills/cs-conductor-runtime/schemas/analysis_profile.schema.json": "analysis_profile.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/result_card.schema.json": "result_card.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/analysis_subject.schema.json": "analysis_subject.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/interpretation.schema.json": "interpretation.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/interpretation_review_manifest.schema.json": "interpretation_review_manifest.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/review_bundle.schema.json": "review_bundle.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/result_assessment.schema.json": "result_assessment.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/screening_batch.schema.json": "screening_batch.schema.json",
        ".claude/skills/cs-analysis-interpret-results/schemas/screening_draft.schema.json": "screening_draft.schema.json",
        ".claude/skills/cs-analysis-interpret-mmp/schemas/result_card.schema.json": "result_card.schema.json",
        ".claude/skills/cs-analysis-interpret-mmp/schemas/analysis_subject.schema.json": "analysis_subject.schema.json",
    }
    for relative, canonical_name in mirror_contracts.items():
        path = PROJECT_ROOT / relative
        canonical = MODULE_ROOT / "schemas" / canonical_name
        if path.is_file() and canonical.is_file() and json.loads(path.read_text(encoding="utf-8")) != json.loads(canonical.read_text(encoding="utf-8")):
            errors.append(f"Schema mirror mismatch: {relative} != CONDUCTOR_modules/schemas/{canonical_name}")

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
            if stage == "analysis" and not isinstance(capability.get("interpretation_profile"), dict):
                errors.append(f"{name}: analysis capability lacks an Interpretation Profile")
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
                else:
                    adapter_text = (root / "scripts" / "conductor_request_adapter.py").read_text(encoding="utf-8")
                    if 'REQUEST_SCHEMA_VERSION = "1.0.0"' not in adapter_text:
                        errors.append(f"{name}: Execution Request schema version mismatch")
                artifact_schema_path = root / "schemas" / "artifact_manifest.schema.json"
                if not artifact_schema_path.is_file():
                    errors.append(f"{name}: missing Artifact Manifest schema")
                else:
                    artifact_schema = json.loads(artifact_schema_path.read_text(encoding="utf-8"))
                    artifact_properties = artifact_schema.get("properties", {})
                    if artifact_properties.get("schema_version", {}).get("const") != "2.0.0" or artifact_properties.get("conductor_version", {}).get("const") != VERSION:
                        errors.append(f"{name}: Artifact Manifest producer/consumer version mismatch")
                if "--conductor-request" not in launcher_text:
                    errors.append(f"{name}: launcher has no common Execution Request entry")
                for token in (".bootstrap.lock", ".environment-ready", '"--locked"', "owner.json", "environment_fingerprint", "manifest.read_bytes()"):
                    if token not in launcher_text:
                        errors.append(f"{name}: launcher lacks concurrent Pixi bootstrap guard ({token})")
                for token in ("--conductor", "--round-id", "--node-id", "--attempt-id"):
                    if token not in run_text:
                        errors.append(f"{name}: scientific kernel lacks internal CONDUCTOR context ({token})")
                if f'"conductor_version": "{VERSION}"' not in run_text and f'"conductor_version":"{VERSION}"' not in run_text:
                    errors.append(f"{name}: CONDUCTOR artifact manifest version is not {VERSION}")
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
                required_interpretation_files = ["schemas/result_card.schema.json", "schemas/analysis_subject.schema.json", "scripts/render.py"]
                if capability.get("capability_id") == "I001":
                    required_interpretation_files.extend(["schemas/review_bundle.schema.json", "schemas/operator_interpretation_profile.schema.json"])
                for relative in required_interpretation_files:
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
        if profile.get("runtime_planning", {}).get("max_new_analysis_nodes_per_round") != 500:
            errors.append("Round Analysis safety limit must be 500")
        if profile.get("runtime_planning", {}).get("analysis_activation_batch_size") != 25:
            errors.append("Analysis activation batch size must be 25")
        if profile.get("runtime_planning", {}).get("screening_batch_size") != 4:
            errors.append("Result Screening batch size must be 4")
        if profile.get("runtime_planning", {}).get("max_interpretation_result_cards") != 50:
            errors.append("Interpretation Result Card limit must be 50")
        mmp = profile.get("matched_molecular_pairs", {})
        if mmp.get("standard_flow") != "global_only" or mmp.get("manual_interpretation_skill") != "cs-analysis-interpret-mmp":
            errors.append("Standard A014 flow must be Global-only with explicit read-only I002 interpretation")
        if "A014" in exploration.get("local_operator_capabilities", []):
            errors.append("A014 must not be part of standard Local exploration")
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
    print("CONDUCTOR 0.2.0 package layout is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
