"""Shared deterministic Finding construction helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .ids import stable_id


ENTITY_KEYS = (
    "context_ids",
    "scaffold_ids",
    "transformation_ids",
    "fragment_ids",
    "compound_ids",
    "feature_ids",
)


def finding_key(
    *,
    lens: str,
    endpoint_id: str,
    subject_id: str,
    condition_id: str | None,
    effect_direction: str,
    questions: Iterable[str],
) -> str:
    return stable_id(
        "FND",
        {
            "schema_version": "0.2.1",
            "lens": lens,
            "endpoint_ids": [endpoint_id],
            "subject": subject_id,
            "condition": condition_id,
            "direction": effect_direction,
            "test_questions": sorted(set(str(value) for value in questions)),
        },
    )


def base_finding(
    *,
    lens: str,
    endpoint_id: str,
    subject_type: str,
    subject_id: str,
    condition_id: str | None,
    effect_direction: str,
    effect_size: float,
    effect_unit: str,
    support_n: int,
    tests: list[dict[str, Any]],
    falsification_type: str,
    falsification_parameters: dict[str, Any],
    falsification_rule: str,
    entities: dict[str, Iterable[str]] | None = None,
    citations: list[dict[str, str]] | None = None,
    translation_status: str = "not_required",
    labels: Iterable[str] = (),
) -> dict[str, Any]:
    if support_n < 1:
        raise ValueError("A Finding requires support_n >= 1")
    direction = str(effect_direction)
    questions = [str(item["question"]) for item in tests]
    key = finding_key(
        lens=lens,
        endpoint_id=endpoint_id,
        subject_id=subject_id,
        condition_id=condition_id,
        effect_direction=direction,
        questions=questions,
    )
    normalized_entities = {
        name: sorted(set(str(value) for value in (entities or {}).get(name, ())))
        for name in ENTITY_KEYS
    }
    return {
        "finding_id": "",
        "finding_key": key,
        "lens": lens,
        "endpoint_ids": [endpoint_id],
        "claim": {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "condition_id": condition_id,
            "condition_depth": 1,
            "effect_direction": direction,
            "effect_size": float(effect_size),
            "effect_unit": effect_unit,
            "support_n": int(support_n),
        },
        "tests": deepcopy(tests),
        "falsification": {
            "type": falsification_type,
            "parameters": deepcopy(falsification_parameters),
            "decision_rule": falsification_rule,
        },
        "triviality": {
            "confounders_tested": [],
            "raw_effect_size": float(effect_size),
            "adjusted_effect_size": float(effect_size),
            "verdict": "not_assessed",
        },
        "translation": {"status": translation_status},
        "entities": normalized_entities,
        "citations": deepcopy(citations or []),
        "scores": {
            "statistical_strength": None,
            "robustness": None,
            "non_triviality": None,
            "actionability": None,
            "frontier_relevance": None,
            "composite": None,
            "rank": None,
        },
        "state": {"pipeline": "candidate", "deep_dive": "not_dived"},
        "labels": sorted(set(str(value) for value in labels)),
        "merged_into": None,
        "narrative": None,
    }


def assign_finding_ids(findings: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    result = sorted((deepcopy(item) for item in findings), key=lambda item: item["finding_key"])
    keys = [item["finding_key"] for item in result]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate finding_key values")
    for index, item in enumerate(result, start=1):
        item["finding_id"] = f"F{index:06d}"
    return tuple(result)
