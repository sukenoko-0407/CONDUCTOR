from __future__ import annotations

import json
from pathlib import Path

import pytest

from conductor_stat_core import load_resolved_config, stable_id, validate_instance


MODULE_ROOT = Path(__file__).resolve().parents[2]


def test_stable_id_is_key_order_independent() -> None:
    left = stable_id("PAIR", {"a": 1, "b": [2, 3]})
    right = stable_id("PAIR", {"b": [2, 3], "a": 1})
    assert left == right
    assert left.startswith("PAIR|")
    assert len(left.split("|", 1)[1]) == 16


def test_stable_id_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        stable_id("TEST", {"value": float("nan")})


def test_config_deep_merge_rejects_unknown_keys(tmp_path: Path) -> None:
    project = tmp_path / "project.yaml"
    project.write_text("contexts:\n  no_such_key: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown configuration key"):
        load_resolved_config(MODULE_ROOT / "config" / "defaults.yaml", project)


def test_config_deep_merge_preserves_defaults(tmp_path: Path) -> None:
    project = tmp_path / "project.yaml"
    project.write_text("contexts:\n  neighbor_k: 7\n", encoding="utf-8")
    config = load_resolved_config(MODULE_ROOT / "config" / "defaults.yaml", project)
    assert config["contexts"]["neighbor_k"] == 7
    assert config["statistics"]["final_permutations"] == 1000


def test_context_schema_accepts_complete_record() -> None:
    record = {
        "context_id": "CL|D001|k10|c1|0123456789abcdef",
        "context_type": "cluster",
        "axis_id": "cluster|D001|k10",
        "source_space_id": "D001",
        "source_tier": 1,
        "condition_depth": 1,
        "member_count": 10,
        "endpoint_valid_count": 8,
        "representative_context_id": None,
        "dedup_status": "representative",
        "translation_status": "native",
        "calibration_scope": True,
    }
    validate_instance(record, MODULE_ROOT / "schemas" / "context.schema.json")


def test_finding_schema_requires_entities() -> None:
    schema = MODULE_ROOT / "schemas" / "finding.schema.json"
    document = json.loads(schema.read_text(encoding="utf-8"))
    assert "entities" in document["required"]
    assert set(document["$defs"]["entities"]["required"]) == {
        "context_ids",
        "scaffold_ids",
        "transformation_ids",
        "fragment_ids",
        "compound_ids",
        "feature_ids",
    }


@pytest.mark.parametrize("schema_path", sorted((MODULE_ROOT / "schemas").glob("*.schema.json")))
def test_every_schema_is_valid(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_class = __import__("jsonschema").validators.validator_for(schema)
    validator_class.check_schema(schema)
