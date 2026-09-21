from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from conductor_report import CitationError, EvidenceRegistry, build_entity_components, render_html_report, validate_component_narrative, validate_component_response, validate_finding_tests
from conductor_stat_core import base_finding, file_sha256, stable_id


def _finding(identifier: str, compound_ids: list[str], context: str = "CTX") -> dict:
    test_id = stable_id("TEST", {"id": identifier})
    finding = base_finding(
        lens="L5", endpoint_id="EP", subject_type="feature", subject_id=identifier,
        condition_id=context, effect_direction="positive", effect_size=1.0,
        effect_unit="unit", support_n=3,
        tests=[{"test_id": test_id, "question": "q", "method": "fixture", "statistic": 1.0, "p_value": 0.01, "q_value": 0.02, "null_iterations": 100}],
        falsification_type="fixture", falsification_parameters={}, falsification_rule="fixture",
        entities={"compound_ids": compound_ids, "context_ids": [context]},
        citations=[{"citation_id": f"CIT-{identifier}", "table_ref": f"evidence.csv#row_id=E-{identifier}"}],
    )
    finding["finding_id"] = identifier
    finding["state"]["pipeline"] = "reportable"
    return finding


def _registry(tmp_path: Path, findings: list[dict]) -> EvidenceRegistry:
    evidence = tmp_path / "evidence.csv"
    pd.DataFrame([{"row_id": f"E-{item['finding_id']}", "effect": 1.0, "n": 3} for item in findings]).to_csv(evidence, index=False)
    tests = tmp_path / "tests.csv"
    pd.DataFrame([{"row_id": f"T-{item['finding_id']}", "test_id": item["tests"][0]["test_id"], "statistic": 1.0, "p_value": 0.01, "q_value": 0.02} for item in findings]).to_csv(tests, index=False)
    return EvidenceRegistry.load(tmp_path, [evidence, tests], {"evidence.csv": file_sha256(evidence), "tests.csv": file_sha256(tests)})


def test_entity_graph_uses_typed_shared_entities(tmp_path) -> None:
    first = _finding("F000001", ["C1", "C2"])
    second = _finding("F000002", ["C2", "C3"])
    third = _finding("F000003", ["C9"], "OTHER")
    assert build_entity_components([first, second, third]) == [["F000001", "F000002"], ["F000003"]]


def test_citation_numeric_tolerance_and_test_reconciliation(tmp_path) -> None:
    finding = _finding("F000001", ["C1"])
    registry = _registry(tmp_path, [finding])
    validate_finding_tests([finding], registry, {"C1"})
    warnings = validate_component_narrative("N1", "Effect 1.009 [[CIT-F000001]]", ["CIT-F000001"], {"CIT-F000001": "evidence.csv#row_id=E-F000001"}, registry)
    assert warnings == []
    with pytest.raises(CitationError, match="numeric token"):
        validate_component_narrative("N1", "Effect 2.0 [[CIT-F000001]]", ["CIT-F000001"], {"CIT-F000001": "evidence.csv#row_id=E-F000001"}, registry)


def test_compose_response_rejects_uncited_structural_number(tmp_path) -> None:
    finding = _finding("F000001", ["C1"])
    registry = _registry(tmp_path, [finding])
    available = {"CIT-F000001": "evidence.csv#row_id=E-F000001"}
    with pytest.raises(CitationError, match="structural numeric expression"):
        validate_component_response(
            "N1",
            {
                "selections": [],
                "narrative": "この1連結成分は関連を示す。[[CIT-F000001]]",
                "citations": ["CIT-F000001"],
            },
            available,
            registry,
        )


def test_compose_response_accepts_fail_closed_null(tmp_path) -> None:
    finding = _finding("F000001", ["C1"])
    registry = _registry(tmp_path, [finding])
    assert validate_component_response(
        "N1",
        {"selections": [], "narrative": None, "citations": []},
        {"CIT-F000001": "evidence.csv#row_id=E-F000001"},
        registry,
    ) == []


def test_evidence_registry_rejects_hash_mismatch(tmp_path) -> None:
    table = tmp_path / "evidence.csv"
    pd.DataFrame([{"row_id": "R1", "value": 1}]).to_csv(table, index=False)
    with pytest.raises(CitationError, match="hash mismatch"):
        EvidenceRegistry.load(tmp_path, [table], {"evidence.csv": "0" * 64})


def test_evidence_registry_accepts_zero_row_lens_table(tmp_path) -> None:
    table = tmp_path / "l4_evidence.csv"
    table.write_text("\n", encoding="utf-8")
    registry = EvidenceRegistry.load(
        tmp_path,
        [table],
        {table.name: file_sha256(table)},
    )
    assert registry.tables[table.name].empty
    assert registry.tables[table.name].columns.tolist() == ["row_id"]


def test_pair_ids_require_the_run_pair_registry(tmp_path) -> None:
    finding = _finding("F000001", ["C1"])
    evidence = tmp_path / "evidence.csv"
    pd.DataFrame([{"row_id": "E-F000001", "pair_id": "PAIR|known", "effect": 1.0}]).to_csv(evidence, index=False)
    tests = tmp_path / "tests.csv"
    pd.DataFrame([{"row_id": "T-F000001", "test_id": finding["tests"][0]["test_id"], "statistic": 1.0, "p_value": 0.01, "q_value": 0.02}]).to_csv(tests, index=False)
    registry = EvidenceRegistry.load(tmp_path, [evidence, tests], {"evidence.csv": file_sha256(evidence), "tests.csv": file_sha256(tests)})
    with pytest.raises(CitationError, match="no mmp_database"):
        validate_finding_tests([finding], registry, {"C1"})
    validate_finding_tests([finding], registry, {"C1"}, {"PAIR|known"})


def test_html_report_is_self_contained_and_escapes_artifact_values() -> None:
    finding = _finding("F000001", ["C1"])
    finding["claim"]["subject_id"] = "<script>alert('x')</script>"
    finding["scores"] = {"rank": 1, "composite": 0.75}
    report = {
        "status": "succeeded",
        "endpoint_id": "EP<&>",
        "components": [
            {
                "component_id": "COMPONENT|fixture",
                "finding_ids": ["F000001"],
                "narrative": "関連を示す。[[CIT-F000001]]",
                "citations": ["CIT-F000001"],
                "citation_refs": [
                    {
                        "citation_id": "CIT-F000001",
                        "table_ref": "evidence.csv#row_id=E-F000001",
                    }
                ],
            }
        ],
    }
    rendered = render_html_report(
        report,
        [finding],
        {"status": "succeeded", "errors": [], "failure_fraction": 0.0},
        run_id="RUN|fixture",
        created_at="2026-09-21T00:00:00Z",
    )

    assert "<!doctype html>" in rendered
    assert "<script" not in rendered
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in rendered
    assert "https://" not in rendered and "http://" not in rendered
    assert 'href="#citation-1"' in rendered
