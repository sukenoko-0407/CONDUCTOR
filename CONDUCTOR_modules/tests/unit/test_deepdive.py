from __future__ import annotations

import json

import numpy as np
import pandas as pd

from conductor_deepdive import ArtifactRegistry, build_chemical_axes, execute_template, judge_state, rerun_lens_effect, run_deep_dive
from conductor_stat_core import base_finding, stable_id


def _finding() -> dict:
    finding = base_finding(
        lens="L5", endpoint_id="EP", subject_type="feature", subject_id="F", condition_id="CTX",
        effect_direction="positive", effect_size=1.0, effect_unit="oriented_endpoint", support_n=12,
        tests=[{"test_id": stable_id("TEST", {"x": 1}), "question": "q", "method": "fixture", "statistic": 1.0, "p_value": 0.01, "q_value": 0.01, "null_iterations": 100}],
        falsification_type="fixture", falsification_parameters={}, falsification_rule="fixture",
    )
    finding["finding_id"] = "F000001"
    finding["state"]["pipeline"] = "reportable"
    return finding


def _registry(finding: dict) -> ArtifactRegistry:
    observations = pd.DataFrame([
        {"finding_key": finding["finding_key"], "row_id": f"R{i}", "compound_id": f"C{i}", "block_id": f"B{i//3}", "effect": 0.5 + i / 20, "context_id": "A", "target_id": "X" if i % 2 == 0 else "Y", "context_role":"a" if i<6 else "b", "feature_value":float(i%6), "endpoint_value":float(i if i<6 else 11-i), "mw": 300 + i, "clogp": i / 10, "tpsa": 50 + i}
        for i in range(12)
    ])
    axes = pd.DataFrame({"compound_id": [f"C{i}" for i in range(12)], "binary": ["yes"] * 6 + ["no"] * 6, "ordered": [i // 4 for i in range(12)], "mw":[300+i for i in range(12)], "clogp":[i/10 for i in range(12)], "tpsa":[50+i for i in range(12)]})
    candidates = pd.DataFrame([{"row_id": "G1", "context_id": "CTX", "transformation_id": "TR", "validation_status": "valid"}])
    return ArtifactRegistry(observations, axes, candidates, pd.DataFrame(), random_seed=4, min_group_n=3)


def test_all_ten_templates_have_executable_contracts() -> None:
    finding = _finding(); registry = _registry(finding)
    parameters = {
        "T01": {"axis_id": "binary", "level": "yes"},
        "T02": {"axis_id": "ordered"},
        "T03": {"context_ids": ["A"]},
        "T04": {"target_ids": ["X"]},
        "T05": {"iterations": 50},
        "T06": {"context_id": "CTX", "transformation_id": "TR"},
        "T07": {"confounders": ["mw", "clogp", "tpsa"]},
        "T08": {"unit_type": "observation"},
        "T09": {"sample_n": 6, "iterations": 50},
        "T10": {"counterexample_rule": "opposite sign"},
    }
    for template_id, payload in parameters.items():
        result = execute_template(template_id, finding, payload, registry)
        assert result["execution_status"] == "completed", template_id
        assert judge_state(template_id, result, 1.0) in {"SURVIVED", "WEAKENED", "REFUTED", "INCONCLUSIVE"}


def test_deep_dive_budget_and_deterministic_state_are_separate_from_selector() -> None:
    finding = _finding(); registry = _registry(finding)
    def selector(_finding, _allowed, tree):
        return [{"template_id": "T05", "parameters": {"iterations": 30}}] if len(tree) == 1 else []
    result = run_deep_dive([finding], registry, selector, max_tests_per_finding=2)
    assert len(result.nodes) == 2
    assert result.nodes[1]["state"] == "SURVIVED"
    assert result.updated_findings[0]["state"]["deep_dive"] == "SURVIVED"


def test_t01_chemical_axis_library_is_machine_generated(tmp_path) -> None:
    table = tmp_path / "hammett.tsv"
    table.write_text("version\tsubstituent\tsmarts\tsigma_meta\tsigma_para\tsource\tlicense\n0.2.1\tF\t[F]\t0.3\t0.1\ts\tfactual-data\n", encoding="utf-8")
    axes = build_chemical_axes(pd.DataFrame({"compound_id": ["C1"], "canonical_smiles": ["Fc1ccccc1"]}), table)
    required = {"scaffold_class", "substituent_heavy_atoms", "clogp", "tpsa", "hbd", "hba", "has_ring", "stereochemistry", "electronic_effect", "attachment_position"}
    assert required.issubset(axes.columns)
    assert axes.iloc[0]["hammett_version"] == "0.2.1"


def test_hammett_is_used_only_for_unique_meta_or_para_assignment(tmp_path) -> None:
    table = tmp_path / "hammett.tsv"
    table.write_text("version\tsubstituent\tsmarts\tsigma_meta\tsigma_para\tsource\tlicense\n0.2.1\tF\t[F]\t0.34\t0.06\tsource\tfactual-data\n", encoding="utf-8")
    axes = build_chemical_axes(
        pd.DataFrame({"compound_id": ["PARA", "MONO"], "canonical_smiles": ["CCc1ccc(F)cc1", "Fc1ccccc1"]}),
        table,
    ).set_index("compound_id")
    assert axes.loc["PARA", "electronic_effect_source"] == "hammett_para"
    assert axes.loc["PARA", "hammett_substituent"] == "F"
    assert axes.loc["PARA", "hammett_sigma"] == 0.06
    assert axes.loc["PARA", "electronic_effect"] == "EWG"
    assert axes.loc["MONO", "electronic_effect_source"] == "gasteiger_fallback"


def test_l2b_t07_replays_series_residuals_from_compound_endpoints() -> None:
    finding = base_finding(
        lens="L2b", endpoint_id="EP", subject_type="fragment", subject_id="F", condition_id=None,
        effect_direction="positive", effect_size=1.0, effect_unit="oriented_endpoint", support_n=3,
        tests=[{"test_id": stable_id("TEST", {"l2b": 1}), "question": "consistent_effect", "method": "fixture", "statistic": 1.0, "p_value": 0.01, "q_value": 0.01, "null_iterations": 10}],
        falsification_type="fixture", falsification_parameters={}, falsification_rule="fixture",
    )
    rows = []
    axes_rows = []
    for index in range(3):
        target, other = f"T{index}", f"O{index}"
        rows.append({
            "effect": 1.0, "compound_id": target,
            "subject_compound_ids_json": json.dumps([target]),
            "series_fragments_compound_ids_json": json.dumps([[target], [other]]),
            "series_fragments_endpoint_values_json": json.dumps([[2.0 + index], [float(index)]]),
        })
        axes_rows.extend([
            {"compound_id": target, "mw": 200.0 + index},
            {"compound_id": other, "mw": 100.0 + index},
        ])
    effect, p_value, metadata = rerun_lens_effect(
        finding, pd.DataFrame(rows), pd.DataFrame(axes_rows), ["mw"]
    )
    assert np.isfinite(effect) and 0.0 <= p_value <= 1.0
    assert metadata["replay_method"] == "L2b_minimum_unit"
