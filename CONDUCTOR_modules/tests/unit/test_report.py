from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from conductor_report import CitationError, EvidenceRegistry, build_entity_components, render_finding_html, render_html_report, validate_component_narrative, validate_component_response, validate_finding_tests
from conductor_report.visualizations import render_lens_visual
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
        evidence_by_ref={
            "evidence.csv#row_id=E-F000001": {
                "row_id": "E-F000001",
                "feature_id": "D001::signal",
                "r_a": 0.6,
                "r_b": -0.5,
            }
        },
        observations_by_finding={
            finding["finding_key"]: [
                {"feature_value": -1.0, "endpoint_value": 1.0, "context_role": "focal", "compound_id": "C1"},
                {"feature_value": 1.0, "endpoint_value": 2.0, "context_role": "focal", "compound_id": "C2"},
            ]
        },
        finding_report_paths={"F000001": "finding_reports/F000001.html"},
    )

    assert "<!doctype html>" in rendered
    assert "<script" not in rendered
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in rendered
    assert "https://" not in rendered and "http://" not in rendered
    assert 'href="#citation-1"' in rendered
    assert "重要な知見" in rendered
    assert "詳しい個別レポート" in rendered
    assert "監査用付録：全Finding一覧" in rendered


def test_overview_explains_top_ten_and_lists_titles_for_ranks_eleven_to_twenty() -> None:
    findings = []
    report_paths = {}
    evidence_by_ref = {}
    observations_by_finding = {}
    for rank in range(1, 21):
        finding = _finding(f"F{rank:06d}", [f"C{rank}"])
        finding["claim"]["subject_id"] = f"SUBJECT-{rank:02d}"
        finding["scores"] = {"rank": rank, "composite": 1.0 - rank / 100.0}
        findings.append(finding)
        report_paths[finding["finding_id"]] = f"finding_reports/{finding['finding_id']}.html"
        evidence_by_ref[f"evidence.csv#row_id=E-{finding['finding_id']}"] = {
            "row_id": f"E-{finding['finding_id']}",
            "feature_id": f"SUBJECT-{rank:02d}",
            "r_a": 0.6,
            "r_b": -0.5,
        }
        observations_by_finding[finding["finding_key"]] = [
            {"feature_value": -1.0, "endpoint_value": 1.0, "context_role": "focal"},
            {"feature_value": 1.0, "endpoint_value": 2.0, "context_role": "focal"},
            {"feature_value": -1.0, "endpoint_value": 2.0, "context_role": "complement"},
            {"feature_value": 1.0, "endpoint_value": 1.0, "context_role": "complement"},
        ]

    rendered = render_html_report(
        {
            "status": "succeeded",
            "endpoint_id": "EP",
            "components": [],
            "finding_page_k": 20,
            "overview_detail_k": 10,
        },
        findings,
        {"status": "succeeded", "errors": [], "failure_fraction": 0.0},
        run_id="RUN|fixture",
        created_at="2026-09-29T00:00:00Z",
        evidence_by_ref=evidence_by_ref,
        observations_by_finding=observations_by_finding,
        finding_report_paths=report_paths,
    )

    assert rendered.count('class="insight"') == 10
    assert rendered.count('class="title-only"') == 10
    assert "重要な知見：1～10位" in rendered
    assert "11～20位" in rendered
    assert 'href="finding_reports/F000011.html"' in rendered
    assert 'href="finding_reports/F000020.html"' in rendered
    assert "個別レポート</span><strong>20</strong>" in rendered


def test_individual_finding_report_explains_claim_and_evidence() -> None:
    finding = _finding("F000001", ["C1"])
    finding["scores"] = {
        "rank": 1,
        "statistical_strength": 0.9,
        "robustness": 0.8,
        "non_triviality": 0.7,
        "actionability": 0.6,
        "frontier_relevance": 0.5,
        "composite": 0.21,
    }
    rendered = render_finding_html(
        finding,
        {"status": "succeeded", "errors": []},
        run_id="RUN|fixture",
        endpoint_id="EP",
        created_at="2026-09-22T00:00:00Z",
        evidence_by_ref={
            "evidence.csv#row_id=E-F000001": {
                "row_id": "E-F000001",
                "feature_id": "D001::signal",
                "r_a": "0.6",
                "r_b": "-0.5",
                "n_a": "20",
                "n_b": "30",
            }
        },
        observations_by_finding={
            finding["finding_key"]: [
                {"feature_value": -1.0, "endpoint_value": 1.0, "context_role": "focal", "compound_id": "C1"},
                {"feature_value": 1.0, "endpoint_value": 2.0, "context_role": "focal", "compound_id": "C2"},
            ]
        },
        overview_href="../report.html",
    )

    assert rendered.startswith("<!doctype html>")
    assert "この知見が意味すること" in rendered
    assert "統計的根拠" in rendered
    assert "反証条件" in rendered
    assert "D001::signal" in rendered
    assert "../report.html" in rendered


def test_l2a_individual_report_contains_real_mmp_structures_and_effect_plot() -> None:
    finding = _finding("F000002", ["C1", "C2"])
    finding["lens"] = "L2a"
    finding["finding_key"] = "FND|0123456789abcdef"
    finding["claim"].update(
        {
            "subject_type": "transformation",
            "subject_id": "TR|fixture",
            "effect_direction": "positive",
            "effect_size": 1.1,
            "effect_unit": "oriented_endpoint_shift",
        }
    )
    finding["entities"]["transformation_ids"] = ["TR|fixture"]
    evidence_ref = "l2a_evidence.csv#row_id=E-F000002"
    finding["citations"] = [{"citation_id": "CIT-F000002", "table_ref": evidence_ref}]
    rendered = render_finding_html(
        finding,
        {"status": "succeeded", "errors": []},
        run_id="RUN|fixture",
        endpoint_id="EP",
        created_at="2026-09-22T00:00:00Z",
        evidence_by_ref={
            evidence_ref: {
                "row_id": "E-F000002",
                "variable_from": "[*:1]C",
                "variable_to": "[*:1]O",
                "n_in": 2,
                "n_out": 2,
                "median_in": 1.1,
                "median_out": 0.0,
                "median_shift": 1.1,
            }
        },
        observations_by_finding={
            finding["finding_key"]: [
                {
                    "comparison_group": "inside",
                    "effect": 1.0,
                    "pair_from_compound_id": "C1",
                    "pair_to_compound_id": "C2",
                },
                {"comparison_group": "inside", "effect": 1.2},
                {"comparison_group": "outside", "effect": -0.1},
                {"comparison_group": "outside", "effect": 0.1},
            ]
        },
        compound_smiles={"C1": "CC", "C2": "CO"},
    )

    assert "MMP変換の構造と効果" in rendered
    assert "代表的な実測MMPペア" in rendered
    assert rendered.count("<svg") >= 4
    assert "対象文脈内" in rendered and "文脈外" in rendered
    assert "http://" not in rendered and "<script" not in rendered


@pytest.mark.parametrize(
    ("lens", "evidence", "observations", "entities", "expected"),
    [
        (
            "L1b",
            {"space_id": "D001", "context_id": "CTX", "lambda": 0.8},
            [
                {"compound_id": "C1", "endpoint_value": 1.0, "effect": 0.5, "neighbor_order_compound_ids_json": '["C2","C3","C4"]'},
                {"compound_id": "C2", "endpoint_value": 2.0, "effect": 0.3, "neighbor_order_compound_ids_json": '["C1","C3","C4"]'},
            ],
            {"compound_ids": ["C1", "C2"]},
            "局所SARの可視化",
        ),
        (
            "L2b",
            {"fragment_smiles": "[*:1]C", "series_count": 2},
            [
                {"context_id": "SERIES-A", "effect": -0.2},
                {"context_id": "SERIES-B", "effect": 0.4},
            ],
            {"compound_ids": ["C1", "C2"]},
            "系列ごとの残差寄与",
        ),
        (
            "L4",
            {"candidate_smiles": "CO", "region_score": 0.7},
            [
                {"block_id": "D001", "compound_id": "C1", "endpoint_value": 1.0},
                {"block_id": "D001", "compound_id": "C2", "endpoint_value": 2.0},
            ],
            {"compound_ids": ["C1"]},
            "未探索候補の構造と到達経路",
        ),
        (
            "L5",
            {"feature_id": "D001::signal", "r_a": 0.8, "r_b": -0.7},
            [
                {"compound_id": "C1", "feature_value": -1.0, "endpoint_value": 1.0, "context_role": "focal"},
                {"compound_id": "C2", "feature_value": 1.0, "endpoint_value": 2.0, "context_role": "focal"},
                {"compound_id": "C3", "feature_value": -1.0, "endpoint_value": 2.0, "context_role": "complement"},
                {"compound_id": "C4", "feature_value": 1.0, "endpoint_value": 1.0, "context_role": "complement"},
            ],
            {},
            "相関方向反転の実測図",
        ),
        (
            "L7",
            {"constant_a": "[*:1]C", "constant_b": "[*:1]N", "spearman_rho": -0.8},
            [
                {"target_id": "FRAG-A", "effect": 1.0, "endpoint_left_value": 1.0, "endpoint_value": 2.0, "compound_ids_a_json": '["C1"]', "compound_ids_b_json": '["C2"]'},
                {"target_id": "FRAG-B", "effect": -1.0, "endpoint_left_value": 2.0, "endpoint_value": 1.0, "compound_ids_a_json": '["C3"]', "compound_ids_b_json": '["C4"]'},
            ],
            {},
            "系列coreとSAR移植性",
        ),
    ],
)
def test_each_lens_has_a_specific_data_visual(
    lens: str,
    evidence: dict,
    observations: list[dict],
    entities: dict,
    expected: str,
) -> None:
    rendered = render_lens_visual(
        {"lens": lens, "entities": entities},
        evidence,
        observations,
        {"C1": "CC", "C2": "CCC", "C3": "CO", "C4": "CN"},
        {"FRAG-A": "[*:1]C", "FRAG-B": "[*:1]O"},
    )
    assert expected in rendered
    assert "<svg" in rendered
    assert "http://" not in rendered and "<script" not in rendered
    if lens == "L1b":
        assert "同一文脈内近傍" in rendered
        assert rendered.count("2D chemical structure") == 4
    if lens == "L7":
        assert "共通R基（効果差の大きい代表例）" in rendered
        assert "同じR基を持つ代表実測化合物" in rendered
        assert rendered.count("2D chemical structure") >= 6


def test_l7_visual_fails_closed_when_common_r_group_structure_is_missing() -> None:
    with pytest.raises(ValueError, match="common R-group structure is missing"):
        render_lens_visual(
            {"lens": "L7", "entities": {}},
            {"constant_a": "[*:1]C", "constant_b": "[*:1]N"},
            [
                {
                    "target_id": "FRAG-A",
                    "effect": 1.0,
                    "endpoint_left_value": 1.0,
                    "endpoint_value": 2.0,
                    "compound_ids_a_json": '["C1"]',
                    "compound_ids_b_json": '["C2"]',
                }
            ],
            {"C1": "CC", "C2": "CN"},
            {},
        )
