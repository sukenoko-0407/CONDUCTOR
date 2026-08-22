from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"
TEMPLATES = MODULES / "tools" / "templates"


def adapter_profile(capability: dict[str, object]) -> str:
    stage = str(capability["stage"])
    capability_id = str(capability["capability_id"])
    family = str(capability.get("family", ""))
    if stage == "description":
        return "description"
    if stage == "clustering":
        if str(capability.get("implementation", {}).get("algorithm", "")) == "categorical":
            return "categorical_clustering"
        if family == "description_vector":
            return "vector_clustering"
        if family == "meta":
            return "meta_clustering"
        return "structure_clustering"
    if capability_id in {"A003", "A004"}:
        return "projection_operator"
    if capability_id == "A005":
        return "multidescription_operator"
    if capability_id == "A014":
        return "mmp_operator"
    return "standard_operator"


def required_roles(profile: str) -> list[str]:
    return {
        "description": ["dataset"],
        "structure_clustering": ["dataset"],
        "categorical_clustering": ["dataset"],
        "vector_clustering": ["description"],
        "meta_clustering": ["cluster_membership_matrix"],
        "standard_operator": ["dataset"],
        "projection_operator": ["dataset"],
        "multidescription_operator": ["dataset", "description"],
        "mmp_operator": ["dataset_or_mmp_database"],
    }[profile]


def main() -> int:
    catalog = json.loads((MODULES / "catalog" / "catalog.json").read_text(encoding="utf-8"))
    common_launcher = TEMPLATES / "launch.py"
    adapter = TEMPLATES / "conductor_request_adapter.py"
    updated: list[str] = []
    for entry in catalog["capabilities"]:
        if entry.get("stage") not in {"description", "clustering", "analysis"}:
            continue
        skill_dir = SKILLS / entry["skill_name"]
        capability_path = skill_dir / "capability.json"
        capability = json.loads(capability_path.read_text(encoding="utf-8"))
        profile = adapter_profile(capability)
        capability["version"] = "0.1.5"
        capability["conductor_request"] = {
            "schema_version": "1.0.0",
            "adapter": profile,
            "required_input_roles": required_roles(profile),
            "unknown_parameters": "reject_by_skill_cli",
        }
        capability_path.write_text(json.dumps(capability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(adapter, skill_dir / "scripts" / "conductor_request_adapter.py")
        if entry["capability_id"] != "A014":
            shutil.copyfile(common_launcher, skill_dir / "scripts" / "launch.py")
        run_path = skill_dir / "scripts" / "run.py"
        if run_path.is_file():
            run_text = run_path.read_text(encoding="utf-8")
            run_text = re.sub(r'("conductor_version"\s*:\s*)"0\.1\.[34]"', r'\1"0.1.5"', run_text)
            run_path.write_text(run_text, encoding="utf-8")
        manifest_schema = skill_dir / "schemas" / "artifact_manifest.schema.json"
        if manifest_schema.is_file():
            schema = json.loads(manifest_schema.read_text(encoding="utf-8"))
            properties = schema.get("properties", {})
            properties["conductor_version"] = {"const": "0.1.5"}
            if isinstance(properties.get("skill_version"), dict) and "const" in properties["skill_version"]:
                properties["skill_version"] = {"const": "0.1.5"}
            manifest_schema.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated.append(f"{entry['capability_id']} {entry['skill_name']}")
    print("\n".join(updated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
