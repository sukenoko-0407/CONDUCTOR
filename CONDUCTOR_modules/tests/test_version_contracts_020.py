from __future__ import annotations

import ast
import json
import re
import tomllib
import unittest
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"
SCHEMAS = MODULES / "schemas"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def const(schema: dict[str, Any], property_name: str) -> Any:
    return schema.get("properties", {}).get(property_name, {}).get("const")


def refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                yield item
            else:
                yield from refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from refs(item)


class VersionContracts020(unittest.TestCase):
    def test_package_runtime_and_protocol_versions_are_aligned(self) -> None:
        package_version = (MODULES / "VERSION").read_text(encoding="utf-8").strip()
        project = tomllib.loads((MODULES / "pyproject.toml").read_text(encoding="utf-8"))
        tree = ast.parse((MODULES / "tools" / "runtime_controller.py").read_text(encoding="utf-8"))
        assignments: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = node.value.value
        self.assertEqual("0.2.0", package_version)
        self.assertEqual(package_version, project["project"]["version"])
        self.assertEqual(package_version, assignments["VERSION"])
        self.assertEqual(package_version, assignments["PROTOCOL_VERSION"])
        self.assertEqual(package_version, const(load_json(SCHEMAS / "conductor_control.schema.json"), "conductor_version"))
        for name in (
            "compact_runtime_response.schema.json",
            "execution_packet.schema.json",
            "runtime_worker_status.schema.json",
            "failure_packet.schema.json",
        ):
            self.assertEqual(package_version, const(load_json(SCHEMAS / name), "protocol_version"), name)

    def test_skill_manifest_producers_and_runtime_consumer_use_same_conductor_version(self) -> None:
        package_version = (MODULES / "VERSION").read_text(encoding="utf-8").strip()
        schemas = sorted(SKILLS.glob("*/schemas/artifact_manifest.schema.json"))
        self.assertGreater(len(schemas), 40)
        for path in schemas:
            schema = load_json(path)
            self.assertEqual("2.0.0", const(schema, "schema_version"), str(path))
            self.assertEqual(package_version, const(schema, "conductor_version"), str(path))
            run_path = path.parents[1] / "scripts" / "run.py"
            if run_path.is_file():
                literals = set(re.findall(r'"conductor_version"\s*:\s*"([^"]+)"', run_path.read_text(encoding="utf-8")))
                self.assertEqual({package_version}, literals, str(run_path))
        canonical = load_json(SCHEMAS / "artifact_manifest.schema.json")
        self.assertEqual(package_version, const(canonical, "conductor_version"))

    def test_execution_request_producer_and_every_skill_adapter_use_schema_1(self) -> None:
        request_version = const(load_json(SCHEMAS / "execution_request.schema.json"), "schema_version")
        self.assertEqual("1.0.0", request_version)
        adapters = sorted(SKILLS.glob("*/scripts/conductor_request_adapter.py"))
        self.assertGreater(len(adapters), 40)
        pattern = re.compile(r'^REQUEST_SCHEMA_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
        for path in adapters:
            match = pattern.search(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(match, str(path))
            self.assertEqual(request_version, match.group(1), str(path))

    def test_stage_result_and_interpretation_schema_copies_match_consumers(self) -> None:
        strict_copies = {
            "description_result.schema.json": sorted(SKILLS.glob("*/schemas/description_result.schema.json")),
            "result_card.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "result_card.schema.json",
                SKILLS / "cs-analysis-interpret-mmp" / "schemas" / "result_card.schema.json",
            ],
            "analysis_subject.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "analysis_subject.schema.json",
                SKILLS / "cs-analysis-interpret-mmp" / "schemas" / "analysis_subject.schema.json",
            ],
            "interpretation.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "interpretation.schema.json",
            ],
            "interpretation_review_manifest.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "interpretation_review_manifest.schema.json",
            ],
            "review_bundle.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "review_bundle.schema.json",
            ],
            "operator_interpretation_profile.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "operator_interpretation_profile.schema.json",
            ],
            "result_assessment.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "result_assessment.schema.json",
            ],
            "screening_batch.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "screening_batch.schema.json",
            ],
            "screening_draft.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "screening_draft.schema.json",
            ],
            "working_set.schema.json": [
                SKILLS / "cs-analysis-interpret-results" / "schemas" / "working_set.schema.json",
            ],
        }
        for name, copies in strict_copies.items():
            canonical = load_json(SCHEMAS / name)
            self.assertTrue(copies, name)
            for path in copies:
                self.assertTrue(path.is_file(), str(path))
                self.assertEqual(canonical, load_json(path), str(path))
        self.assertEqual("1.0.0", const(load_json(SCHEMAS / "description_result.schema.json"), "schema_version"))
        self.assertEqual("2.0.0", const(load_json(SCHEMAS / "result_card.schema.json"), "schema_version"))

    def test_catalog_schema_copies_match(self) -> None:
        for name in ("capability.schema.json", "analysis_profile.schema.json"):
            self.assertEqual(
                load_json(SCHEMAS / name),
                load_json(SKILLS / "cs-conductor-runtime" / "schemas" / name),
                name,
            )
        capabilities = sorted(SKILLS.glob("*/capability.json"))
        self.assertGreater(len(capabilities), 45)
        for path in capabilities:
            self.assertEqual("2.0.0", load_json(path).get("schema_version"), str(path))

    def test_event_and_operator_summary_versions_match_runtime_consumers(self) -> None:
        expected_event = const(load_json(SCHEMAS / "execution_event.schema.json"), "schema_version")
        expected_summary = const(load_json(SCHEMAS / "operator_summary.schema.json"), "schema_version")
        self.assertEqual("2.0.0", expected_event)
        self.assertEqual("1.0.0", expected_summary)
        for path in SKILLS.glob("*/schemas/execution_event.schema.json"):
            self.assertEqual(expected_event, const(load_json(path), "schema_version"), str(path))
        for path in SKILLS.glob("*/schemas/operator_summary.schema.json"):
            self.assertEqual(expected_summary, const(load_json(path), "schema_version"), str(path))

    def test_every_relative_schema_reference_resolves_locally(self) -> None:
        schema_paths = list(SCHEMAS.glob("*.schema.json"))
        for directory in SKILLS.glob("*/schemas"):
            schema_paths.extend(directory.glob("*.schema.json"))
        for path in schema_paths:
            for reference in refs(load_json(path)):
                if reference.startswith("#") or "://" in reference:
                    continue
                target = path.parent / reference.split("#", 1)[0]
                self.assertTrue(target.is_file(), f"{path}: unresolved $ref {reference}")

    def test_mmp_specialized_schema_names_match_their_ids(self) -> None:
        directory = SKILLS / "cs-analysis-interpret-mmp" / "schemas"
        for name in (
            "mmp_interpretation_candidate.schema.json",
            "mmp_interpretation_analysis_subject.schema.json",
        ):
            schema = load_json(directory / name)
            self.assertTrue(str(schema["$id"]).endswith("/" + name), name)


if __name__ == "__main__":
    unittest.main()
