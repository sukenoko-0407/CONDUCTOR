from __future__ import annotations

import ast
import hashlib
import json
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"
VERSION = "0.1.9"
OBSOLETE_CONDUCTOR_SKILLS = {
    "cs-analysis-activity-cliff", "cs-analysis-activity-distribution",
    "cs-analysis-cluster-overlap", "cs-analysis-cluster-structural-diversity",
    "cs-analysis-descriptor-activity-correlation", "cs-analysis-interpret-mmp",
    "cs-analysis-knn-activity-consistency", "cs-analysis-pairwise-structure-similarity",
    "cs-analysis-projection-pca", "cs-analysis-projection-umap", "cs-analysis-sali",
    "cs-compute-clustering-categorical", "cs-conductor-assessment-report",
    "cs-conductor-dispatch", "cs-conductor-node-review", "cs-conductor-result-concierge",
    "cs-conductor-run-audit", "cs-conductor-state-report",
}
BATCH_RUNNER_SKILLS = {
    "cs-analysis-cluster-profile", "cs-analysis-cluster-enrichment",
    "cs-analysis-series-descriptor-contrast", "cs-analysis-series-projection-panel",
    "cs-analysis-multidescription-feature-model", "cs-analysis-series-landscape",
    "cs-analysis-series-structural-signature", "cs-analysis-series-report",
    "cs-compute-clustering-meta-overlap",
}
CUSTOM_DESCRIPTION_RUNNERS = {
    "cs-compute-description-mordred-3d",
    "cs-compute-description-tblite-xtb",
    "cs-compute-description-chemberta-embedding",
}
CUSTOM_CLUSTERING_RUNNERS = {
    "cs-compute-clustering-structure-mcs",
    "cs-compute-clustering-meta-overlap",
}


def normalized_source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def main() -> int:
    errors: list[str] = []
    if (MODULES / "VERSION").read_text(encoding="utf-8").strip() != VERSION: errors.append("VERSION is not 0.1.9")
    selection = json.loads((MODULES / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
    names = [name for key in ("description_skills","clustering_skills","analysis_skills","interpretation_skills","support_skills") for name in selection.get(key, [])]
    if len(names) != len(set(names)): errors.append("included Skill names are not unique")
    physical_names = sorted(path.name for path in SKILLS.iterdir() if path.is_dir())
    extra_names = sorted(set(physical_names) & OBSOLETE_CONDUCTOR_SKILLS)
    missing_names = sorted(set(names) - set(physical_names))
    if extra_names: errors.append(f"known obsolete CONDUCTOR Skill directories remain: {extra_names}")
    if missing_names: errors.append(f"selected Skill directories are missing: {missing_names}")
    catalog = json.loads((MODULES / "catalog" / "catalog.json").read_text(encoding="utf-8"))
    catalog_names = [str(item.get("skill_name")) for item in catalog.get("capabilities", [])]
    if catalog.get("conductor_version") != VERSION:
        errors.append("catalog version mismatch")
    if set(catalog_names) != set(names) or len(catalog_names) != len(names):
        errors.append("catalog capabilities do not exactly match included_skills.json")
    profile_path = MODULES / "catalog" / "analysis_profile.json"
    selection_path = MODULES / "catalog" / "included_skills.json"
    if catalog.get("profile_hash") != hashlib.sha256(profile_path.read_bytes()).hexdigest():
        errors.append("catalog profile_hash is stale")
    if catalog.get("selection_hash") != hashlib.sha256(selection_path.read_bytes()).hexdigest():
        errors.append("catalog selection_hash is stale")
    ids=[]
    for name in names:
        directory=SKILLS/name
        required=("SKILL.md","README.md","capability.json") if name=="cs-analysis-interpret-results" else ("SKILL.md","README.md","capability.json","env/pixi.toml","scripts/launch.py")
        for relative in required:
            if not (directory/relative).is_file(): errors.append(f"{name}: missing {relative}")
        manifest = directory / "env" / "pixi.toml"
        if manifest.is_file():
            try: tomllib.loads(manifest.read_text(encoding="utf-8-sig"))
            except Exception as exc: errors.append(f"{name}: invalid env/pixi.toml: {exc}")
        cap_path=directory/"capability.json"
        if cap_path.is_file():
            try:
                cap=json.loads(cap_path.read_text(encoding="utf-8")); ids.append(cap["capability_id"])
                if cap.get("skill_name")!=name: errors.append(f"{name}: skill_name mismatch")
                if cap.get("version")!=VERSION: errors.append(f"{name}: product version mismatch")
                request_contract = cap.get("conductor_request")
                if cap.get("stage") not in {"interpretation", "orchestration"}:
                    if not isinstance(request_contract, dict) or not request_contract.get("adapter"):
                        errors.append(f"{name}: missing conductor_request adapter")
                    elif not isinstance(request_contract.get("required_input_roles"), list):
                        errors.append(f"{name}: required_input_roles must be an array")
            except Exception as exc: errors.append(f"{name}: invalid capability.json: {exc}")
        for script in (directory/"scripts").glob("*.py") if (directory/"scripts").is_dir() else []:
            source = script.read_text(encoding="utf-8-sig")
            try: ast.parse(source,filename=str(script))
            except Exception as exc: errors.append(f"{script.relative_to(ROOT)}: {exc}")
            if "jsonschema.validate" in source and (
                'schema.pop("$schema", None)' not in source
                or 'schema.pop("$id", None)' not in source
            ):
                errors.append(
                    f"{script.relative_to(ROOT)}: JSON Schema validation is not offline-safe"
                )
    if len(ids)!=len(set(ids)): errors.append("Capability IDs are not unique")
    runtime_wrapper = SKILLS / "cs-conductor-runtime" / "scripts" / "state_manager.py"
    if runtime_wrapper.is_file():
        wrapper_source = runtime_wrapper.read_text(encoding="utf-8-sig")
        required_wrapper_tokens = (
            'candidate / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"',
            'runpy.run_path(str(controller), run_name="__main__")',
        )
        for token in required_wrapper_tokens:
            if token not in wrapper_source:
                errors.append(f"Runtime state_manager.py does not delegate to the canonical controller: missing {token}")
    else:
        errors.append("cs-conductor-runtime: missing scripts/state_manager.py")
    adapter_template = (MODULES / "tools" / "templates" / "conductor_request_adapter.py").read_bytes()
    for name in names:
        adapter = SKILLS / name / "scripts" / "conductor_request_adapter.py"
        if adapter.is_file() and adapter.read_bytes() != adapter_template:
            errors.append(f"{name}: conductor_request_adapter.py differs from the canonical template")
    common_launcher_names = [
        name for key in ("description_skills", "clustering_skills", "analysis_skills")
        for name in selection.get(key, [])
    ]
    common_launcher = (SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "launch.py").read_bytes()
    for name in common_launcher_names:
        launcher = SKILLS / name / "scripts" / "launch.py"
        if launcher.read_bytes() != common_launcher:
            errors.append(f"{name}: launch.py differs from the canonical common launcher")
    on_demand_launcher = (
        SKILLS / "cs-conductor-on-demand-analysis" / "scripts" / "launch.py"
    ).read_text(encoding="utf-8-sig")
    for token in ("def ensure_environment(", 'mutex = env_dir / ".bootstrap.lock"', "for _ in range(3600):"):
        if token not in on_demand_launcher:
            errors.append(f"cs-conductor-on-demand-analysis: bootstrap concurrency guard is missing {token}")
    common_description_runner = normalized_source(
        SKILLS / "cs-compute-description-rdkit-2d" / "scripts" / "run.py"
    )
    for name in selection.get("description_skills", []):
        if name not in CUSTOM_DESCRIPTION_RUNNERS:
            runner = SKILLS / name / "scripts" / "run.py"
            if normalized_source(runner) != common_description_runner:
                errors.append(f"{name}: run.py differs from the canonical common Description runner")
    common_clustering_runner = normalized_source(
        SKILLS / "cs-compute-clustering-structure-murcko" / "scripts" / "run.py"
    )
    for name in selection.get("clustering_skills", []):
        if name not in CUSTOM_CLUSTERING_RUNNERS:
            runner = SKILLS / name / "scripts" / "run.py"
            if normalized_source(runner) != common_clustering_runner:
                errors.append(f"{name}: run.py differs from the canonical common Clustering runner")
    for shared_name in ("batch_skill_common.py", "series_batch_runner.py"):
        shared_template = (MODULES / "tools" / "templates" / shared_name).read_bytes()
        for name in names:
            shared_copy = SKILLS / name / "scripts" / shared_name
            if shared_copy.is_file() and shared_copy.read_bytes() != shared_template:
                errors.append(f"{name}: {shared_name} differs from the canonical template")
    batch_runner_template = (MODULES / "tools" / "templates" / "series_batch_runner.py").read_bytes()
    for name in BATCH_RUNNER_SKILLS:
        runner = SKILLS / name / "scripts" / "run.py"
        if runner.read_bytes() != batch_runner_template:
            errors.append(f"{name}: run.py differs from the canonical batch runner")
    for template_name in (
        "standard_summary_template.html", "series_detail_template.html",
    ):
        canonical_template = MODULES / "tools" / "templates" / template_name
        installed_template = (
            SKILLS / "cs-analysis-series-report" / "templates" / template_name
        )
        if not installed_template.is_file():
            errors.append(
                f"cs-analysis-series-report: missing templates/{template_name}"
            )
        elif installed_template.read_bytes() != canonical_template.read_bytes():
            errors.append(
                f"cs-analysis-series-report: templates/{template_name} "
                "differs from the canonical template"
            )
    standard_template_source = (
        MODULES / "tools" / "templates" / "standard_summary_template.html"
    ).read_text(encoding="utf-8")
    at_a_glance_token = 'data-report-section="at-a-glance"'
    endpoint_token = 'data-report-section="endpoint-overview"'
    if at_a_glance_token not in standard_template_source:
        errors.append("A009 template is missing the at-a-glance section")
    elif (
        endpoint_token not in standard_template_source
        or standard_template_source.index(at_a_glance_token)
        > standard_template_source.index(endpoint_token)
    ):
        errors.append("A009 at-a-glance section must precede Endpoint overview")
    mmp_source = (SKILLS / "cs-analysis-matched-molecular-pairs" / "scripts" / "run.py").read_text(encoding="utf-8")
    for obsolete_role in ("global-build", "local-screen", "local-detail"):
        if obsolete_role in mmp_source:
            errors.append(f"MMP implementation retains obsolete role: {obsolete_role}")
    mmp_template_contract = {
        "mmp_target_report_template.html": (
            'data-report-section="structures"',
            'data-report-section="basic-information"',
            'data-report-section="mmp-details"',
            'data-report-section="visual-transformations"',
            'data-report-section="full-data"',
            'Target full SMILES',
        ),
        "mmp_overview_report_template.html": (
            'data-report-section="scope"',
            'data-report-section="targets"',
            'data-report-section="full-data"',
        ),
    }
    for template_name, required_tokens in mmp_template_contract.items():
        template_path = (
            SKILLS / "cs-analysis-matched-molecular-pairs"
            / "templates" / template_name
        )
        if not template_path.is_file():
            errors.append(
                "cs-analysis-matched-molecular-pairs: missing "
                f"templates/{template_name}"
            )
            continue
        template_source = template_path.read_text(encoding="utf-8")
        for token in required_tokens:
            if token not in template_source:
                errors.append(
                    "cs-analysis-matched-molecular-pairs: "
                    f"templates/{template_name} is missing {token}"
                )
    for token in (
        "select_minimal_transform_rows(",
        "orient_report_rows_target_to(",
        "render_transformation_gallery(",
    ):
        if token not in mmp_source:
            errors.append(f"MMP report implementation is missing {token}")
    profile=json.loads((MODULES/"catalog"/"analysis_profile.json").read_text(encoding="utf-8"))
    if profile.get("conductor_version")!=VERSION: errors.append("analysis_profile version mismatch")
    if profile.get("basic_compute",{}).get("min_cluster_size")!=5: errors.append("min_cluster_size must be 5")
    if profile.get("basic_compute",{}).get("min_ff_evaluate")!=10: errors.append("min_ff_evaluate must default to 10")
    if profile.get("standard_analysis",{}).get("capabilities")!=["A003","A004","A005","A006","A007","A008","A009"]: errors.append("standard capability order mismatch")
    if profile.get("standard_analysis",{}).get("mmp_type_i_top_k")!=1: errors.append("standard MMP Type-I must use Top 1")
    obsolete=("cs-conductor-executor.md",)
    for name in obsolete:
        if (ROOT/".claude"/"agents"/name).exists(): errors.append(f"obsolete Agent remains: {name}")
    if errors:
        print("\n".join(f"ERROR: {value}" for value in errors),file=sys.stderr); return 1
    print(json.dumps({"status":"ok","version":VERSION,"skill_count":len(names),"capability_count":len(ids)},ensure_ascii=False)); return 0


if __name__=="__main__": raise SystemExit(main())
