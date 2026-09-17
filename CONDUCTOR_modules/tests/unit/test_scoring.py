from __future__ import annotations

import pandas as pd

from conductor_scoring import score_findings
from conductor_stat_core import base_finding, stable_id


def _finding(lens: str, subject: str, effect: float, context: str) -> dict:
    test_id = stable_id("TEST", {"lens": lens, "subject": subject})
    return base_finding(
        lens=lens,
        endpoint_id="EP",
        subject_type="feature",
        subject_id=subject,
        condition_id=context,
        effect_direction="positive" if effect > 0 else "flat",
        effect_size=effect,
        effect_unit="oriented_endpoint",
        support_n=4,
        tests=[{"test_id": test_id, "question": "q", "method": "fixture", "statistic": effect, "p_value": 0.01, "q_value": 0.01, "null_iterations": 100}],
        falsification_type="fixture",
        falsification_parameters={},
        falsification_rule="fixture",
        entities={"context_ids": [context], "compound_ids": ["C1", "C2"], "feature_ids": ["F"]},
    )


def test_scoring_applies_fixed_gate_and_retains_duplicate_loser() -> None:
    findings = [_finding("L5", "A", 1.0, "CTX"), _finding("L1b", "B", 0.8, "CTX")]
    observations = []
    for finding in findings:
        for index in range(8):
            observations.append({"finding_key": finding["finding_key"], "row_id": f"R{index}", "block_id": f"S{index // 2}", "effect": finding["claim"]["effect_size"], "compound_id": f"C{index}", "endpoint_value": float(index), "actionability_level": "exact"})
    result = score_findings(
        findings,
        pd.DataFrame(observations),
        pd.DataFrame({"endpoint_id": ["EP"] * 20, "oriented_value": range(20)}),
        "EP",
        run_seed=3,
        bootstrap_iterations=50,
        display_k=1,
    )
    assert result.gate["status"] == "succeeded"
    states = {item["state"]["pipeline"] for item in result.findings}
    assert states == {"reportable", "merged"}
    loser = next(item for item in result.findings if item["state"]["pipeline"] == "merged")
    assert loser["merged_into"] is not None
    assert all(0.0 <= float(value) <= 1.0 for value in result.scores["composite"])


def test_zero_raw_effect_has_zero_non_triviality() -> None:
    finding = _finding("L5", "ZERO", 0.0, "CTX0")
    observations = pd.DataFrame([{"finding_key": finding["finding_key"], "row_id": "R", "block_id": "B", "effect": 0.0, "compound_id": "C", "endpoint_value": 1.0, "actionability_level": "descriptive"}])
    result = score_findings([finding], observations, pd.DataFrame({"endpoint_id": ["EP", "EP"], "oriented_value": [0.0, 2.0]}), "EP", run_seed=1, bootstrap_iterations=10, display_k=1)
    assert result.findings[0]["scores"]["non_triviality"] == 0.0


def test_l5_adjusted_effect_is_recomputed_from_residualized_endpoint() -> None:
    finding = _finding("L5", "CONFOUNDED", 1.0, "A|B")
    observations = []
    endpoint_rows = []
    confounder_rows = []
    for index in range(8):
        compound_id = f"C{index}"
        endpoint_rows.append({"compound_id": compound_id, "endpoint_id": "EP", "oriented_value": float(index)})
        confounder_rows.append({"compound_id": compound_id, "mw": float(index), "clogp": 0.0, "tpsa": 0.0, "scaffold_id": "S"})
        observations.append({
            "finding_key": finding["finding_key"], "row_id": f"R{index}", "block_id": f"B{index}",
            "effect": 1.0, "compound_id": compound_id, "endpoint_value": float(index),
            "context_role": "a" if index < 4 else "b", "feature_value": float(index % 4),
            "actionability_level": "direction_only",
        })
    result = score_findings(
        [finding], pd.DataFrame(observations), pd.DataFrame(endpoint_rows), "EP", run_seed=7,
        confounders=pd.DataFrame(confounder_rows), bootstrap_iterations=10, display_k=1,
    )
    scored = result.findings[0]
    assert abs(scored["triviality"]["adjusted_effect_size"]) < 1e-10
    assert scored["scores"]["non_triviality"] == 0.0
    assert scored["triviality"]["confounders_tested"] == ["MW", "cLogP", "TPSA", "scaffold_class"]
