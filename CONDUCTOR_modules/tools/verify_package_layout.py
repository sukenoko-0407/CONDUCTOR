from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify() -> list[str]:
    errors: list[str] = []
    included_path = MODULE_ROOT / "catalog" / "included_skills.json"
    catalog_path = MODULE_ROOT / "catalog" / "catalog.json"
    for path in (included_path, catalog_path):
        if not path.is_file():
            errors.append(f"missing catalog file: {path}")
    if errors:
        return errors
    included = _read(included_path)
    catalog = _read(catalog_path)
    if included.get("schema_version") != "0.2.1" or catalog.get("schema_version") != "0.2.1":
        errors.append("catalog schema_version must be 0.2.1")
    descriptions = list(included.get("description_skills", []))
    pipeline = list(included.get("pipeline_skills", []))
    if len(descriptions) != 18 or len(set(descriptions)) != 18:
        errors.append("included_skills must contain exactly 18 unique Description Skills")
    filesystem_descriptions = sorted(path.name for path in (PROJECT_ROOT / ".claude" / "skills").glob("cs-compute-description-*") if path.is_dir())
    if sorted(descriptions) != filesystem_descriptions:
        errors.append("Description catalog and filesystem differ")
    selected = descriptions + pipeline
    if len(selected) != len(set(selected)):
        errors.append("included_skills contains duplicate skill names")
    catalog_rows = catalog.get("capabilities", [])
    catalog_names = [row.get("skill_name") for row in catalog_rows]
    if sorted(catalog_names) != sorted(selected):
        errors.append("catalog.json and included_skills.json differ")
    capability_ids: set[str] = set()
    for name in selected:
        skill = PROJECT_ROOT / ".claude" / "skills" / name
        required = [skill / "SKILL.md", skill / "capability.json", skill / "env" / "pixi.toml", skill / "env" / "pixi.lock", skill / "scripts" / "launch.py", skill / "scripts" / "run.py"]
        for path in required:
            if not path.is_file():
                errors.append(f"missing Skill file: {path.relative_to(PROJECT_ROOT)}")
        capability_path = skill / "capability.json"
        if capability_path.is_file():
            capability = _read(capability_path)
            identifier = str(capability.get("capability_id", ""))
            if capability.get("skill_name") != name:
                errors.append(f"capability skill_name mismatch: {name}")
            if identifier in capability_ids:
                errors.append(f"duplicate capability_id: {identifier}")
            capability_ids.add(identifier)
    description_ids = {
        str(_read(PROJECT_ROOT / ".claude" / "skills" / name / "capability.json").get("capability_id"))
        for name in descriptions
    }
    expected_ids = {f"D{number:03d}" for number in range(1, 17)} | {"D019", "D020"}
    if description_ids != expected_ids:
        errors.append("Description IDs must be D001-D016, D019, and D020")
    for schema in (
        "artifact_manifest.schema.json", "context.schema.json", "deep_dive_node.schema.json",
        "endpoint_registry.schema.json", "execution_event.schema.json", "execution_request.schema.json",
        "finding.schema.json", "llm_request.schema.json", "llm_response.schema.json",
        "mpo_contract.schema.json", "runtime_state.schema.json",
    ):
        if not (MODULE_ROOT / "schemas" / schema).is_file():
            errors.append(f"missing schema: {schema}")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    included = _read(MODULE_ROOT / "catalog" / "included_skills.json")
    print(json.dumps({"status": "succeeded", "description_skills": len(included["description_skills"]), "pipeline_skills": len(included["pipeline_skills"])}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
