#!/usr/bin/env python3
"""Render approval-grade HTML mocks for every CONDUCTOR Finding pattern.

Chemical structures are JAK2 compounds already present in this repository.
Statistical values, contexts, scores, deep-dive outcomes, and virtual candidates
are deterministic presentation mocks.  The generated pages use the production
HTML renderer so that reviewers see the actual intended final layout.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PYTHON = REPO_ROOT / ".claude" / "skills" / "cs-report" / "python"
sys.path.insert(0, str(REPORT_PYTHON))

from conductor_report.html_report import render_finding_html, render_html_report  # noqa: E402


DEFAULT_JAK = REPO_ROOT / "chemble_jak2_download_01.csv"
DEFAULT_MMP = (
    REPO_ROOT
    / "results"
    / "CONDUCTOR"
    / "report_validation"
    / "RV_CHEMBLE_JAK2_0110"
    / "operators"
    / "A008"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "CONDUCTOR_modules"
    / "docs"
    / "report_examples"
    / "JAK2_all_lens_final_mock"
)

RUN_ID = "RUN-JAK2-FINAL-REPORT-MOCK"
ENDPOINT_ID = "JAK2_pIC50"
CREATED_AT = "2026-09-22T12:00:00+09:00"
MOCK_BANNER = (
    '<aside class="callout"><strong>承認用フルモック：</strong>'
    "化学構造はリポジトリ内のJAK2素材を使用しています。p/q値、効果量、文脈、スコア、"
    "deep dive結果、未観測候補は最終表示を確認するための決定論的な創作値です。"
    "科学的結論として引用してはいけません。</aside>"
)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _inject_mock_banner(page: str) -> str:
    return page.replace("<body><main>", f"<body><main>{MOCK_BANNER}", 1)


def _test_rows(prefix: str, p: float, q: float, method: str, statistic: float) -> list[dict[str, Any]]:
    return [
        {
            "test_id": f"TEST-{prefix}-PRIMARY",
            "question": "主要効果は帰無分布から区別できるか",
            "method": method,
            "statistic": statistic,
            "p_value": p,
            "q_value": q,
            "null_iterations": 1000,
            "multiplicity_family": f"FAMILY-{prefix}",
        },
        {
            "test_id": f"TEST-{prefix}-SENSITIVITY",
            "question": "感度解析でも方向と有意性が保たれるか",
            "method": f"{method} sensitivity",
            "statistic": statistic * 0.91,
            "p_value": min(1.0, p * 1.7),
            "q_value": min(1.0, q * 1.45),
            "null_iterations": 1000,
            "multiplicity_family": f"FAMILY-{prefix}",
        },
    ]


def _finding(
    *,
    number: int,
    lens: str,
    subject_type: str,
    subject_id: str,
    condition_id: str | None,
    direction: str,
    effect: float,
    effect_unit: str,
    support_n: int,
    p: float,
    q: float,
    statistic: float,
    method: str,
    evidence_ref: str,
    entities: dict[str, Any],
    deep_dive: str,
    narrative: str,
    rank: int,
    score: float,
    falsification_type: str,
    falsification_rule: str,
    falsification_parameters: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    identifier = f"F-JAK-MOCK-{number:03d}"
    citation_id = f"CIT-JAK-MOCK-{number:03d}"
    return {
        "schema_version": "0.2.1",
        "finding_id": identifier,
        "finding_key": f"FND|JAK2|MOCK|{number:03d}",
        "lens": lens,
        "endpoint_id": ENDPOINT_ID,
        "claim": {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "condition_id": condition_id,
            "effect_direction": direction,
            "effect_size": effect,
            "effect_unit": effect_unit,
            "support_n": support_n,
        },
        "tests": _test_rows(identifier, p, q, method, statistic),
        "falsification": {
            "type": falsification_type,
            "parameters": falsification_parameters,
            "decision_rule": falsification_rule,
        },
        "entities": entities,
        "citations": [{"citation_id": citation_id, "table_ref": evidence_ref}],
        "triviality": {
            "raw_effect_size": effect,
            "adjusted_effect_size": effect * 0.86,
            "confounders_tested": ["MW", "cLogP", "TPSA"],
            "verdict": "non_trivial",
        },
        "translation": {
            "priority": "high" if rank <= 3 else "medium",
            "actionability": "direct" if lens in {"L2a", "L4", "L7"} else "design_review",
            "suggested_action": action,
        },
        "scores": {
            "rank": rank,
            "statistical_strength": min(0.99, score + 0.03),
            "robustness": max(0.0, score - 0.04),
            "non_triviality": max(0.0, score - 0.08),
            "actionability": max(0.0, score - 0.02),
            "frontier_relevance": max(0.0, score - 0.06),
            "composite": score,
        },
        "state": {"pipeline": "reportable", "deep_dive": deep_dive},
        "narrative": narrative.replace("[[CIT]]", f"[[{citation_id}]]"),
    }


def _base_material(jak_path: Path, mmp_dir: Path) -> tuple[list[dict[str, str]], dict[str, str], list[dict[str, str]]]:
    compounds = _csv(jak_path)
    smiles = {row["ID"]: row["SMILES"] for row in compounds}
    mmp_rows = [
        row
        for row in _csv(mmp_dir / "mmp_target_pairs.csv")
        if row["analysis_unit_id"] == "C000003" and row["target_compound_id"] == "CHEMBL3699558"
    ]
    unique_mmp = {row["mmp_id"]: row for row in mmp_rows}
    mmp_rows = sorted(unique_mmp.values(), key=lambda row: row["mmp_id"])
    for row in mmp_rows:
        smiles[row["target_compound_id"]] = row["target_smiles"]
        smiles[row["neighbor_compound_id"]] = row["neighbor_smiles"]
    return compounds, smiles, mmp_rows


def _build_mock(jak_path: Path, mmp_dir: Path) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, str],
    dict[str, str],
]:
    rows, compound_smiles, mmp_rows = _base_material(jak_path, mmp_dir)
    by_id = {row["ID"]: row for row in rows}
    evidence: dict[str, dict[str, Any]] = {}
    observations: dict[str, list[dict[str, Any]]] = {}
    fragment_smiles = {
        "R-F": "[*:1]F",
        "R-Cl": "[*:1]Cl",
        "R-CF3": "[*:1]C(F)(F)F",
        "R-SO2CF3": "[*:1]S(=O)(=O)C(F)(F)F",
    }
    findings: list[dict[str, Any]] = []

    # L1b: local SAR flatness / local neighborhood.
    ref = "mock_l1b_evidence.csv#row_id=E-L1B-001"
    l1_ids = [row["ID"] for row in rows[:12]]
    evidence[ref] = {
        "row_id": "E-L1B-001",
        "space_id": "D012::Morgan_2048_Tanimoto",
        "context_id": "CTX::aminopyrazole-cyclohexyl-series",
        "endpoint_n": 42,
        "neighbor_k": 5,
        "lambda": 0.731,
        "global_variance": 0.684,
    }
    finding = _finding(
        number=1, lens="L1b", subject_type="feature_space", subject_id="D012::Morgan_2048_Tanimoto",
        condition_id="CTX::aminopyrazole-cyclohexyl-series", direction="flat", effect=0.731,
        effect_unit="local_flatness_lambda", support_n=42, p=0.00042, q=0.0031, statistic=4.18,
        method="context-preserving permutation", evidence_ref=ref,
        entities={"compound_ids": l1_ids, "context_ids": ["CTX::aminopyrazole-cyclohexyl-series"], "feature_ids": ["D012::Morgan_2048_Tanimoto"]},
        deep_dive="SURVIVED", narrative="同一系列内では、近傍化合物のEndpointを用いた局所予測が全体平均より安定しました。分子量等の調整後も局所性は維持されました。[[CIT]]",
        rank=4, score=0.81, falsification_type="neighbor_stability",
        falsification_rule="近傍kと特徴空間を変更したとき、lambdaが事前設定下限を下回れば反証とする。",
        falsification_parameters={"neighbor_k": [3, 5, 8], "spaces": ["D012", "D014"]},
        action="局所近傍を優先して同系列内の次化合物を設計し、系列外への一般化は別途検証する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {
            "compound_id": cid,
            "endpoint_value": float(by_id[cid]["pIC50"]),
            "effect": 0.88 - index * 0.045,
            "neighbor_order_compound_ids_json": json.dumps([value for value in l1_ids if value != cid][:3]),
        }
        for index, cid in enumerate(l1_ids)
    ]

    # L2a: context-dependent MMP transformation.
    acid_pair = next(row for row in mmp_rows if row["neighbor_compound_id"] == "CHEMBL3699554")
    ref = "mock_l2a_evidence.csv#row_id=E-L2A-001"
    inside_effects = [2.04, 1.76, 1.54, 1.31, 1.12, 1.02, 0.94, 0.88]
    outside_effects = [-0.18, -0.12, -0.07, -0.04, 0.0, 0.02, 0.05, 0.08, 0.11, 0.15, 0.19, 0.24]
    evidence[ref] = {
        "row_id": "E-L2A-001", "transform_class": "amide_vs_carboxylate",
        "variable_from": acid_pair["variable_neighbor"], "variable_to": acid_pair["variable_target"],
        "n_in": len(inside_effects), "n_out": len(outside_effects), "median_in": 1.215,
        "median_out": 0.035, "median_shift": 1.18, "variance_ratio": 3.42,
    }
    finding = _finding(
        number=2, lens="L2a", subject_type="transformation", subject_id="TRF::CO2H-to-CONHCH2CF3",
        condition_id="CTX::tert-alkyl-aminopyrazole", direction="positive", effect=1.18,
        effect_unit="oriented_endpoint_shift", support_n=20, p=0.00008, q=0.0012, statistic=4.91,
        method="stratified permutation of MMP effects", evidence_ref=ref,
        entities={"compound_ids": [acid_pair["neighbor_compound_id"], acid_pair["target_compound_id"]], "context_ids": ["CTX::tert-alkyl-aminopyrazole"], "transformation_ids": ["TRF::CO2H-to-CONHCH2CF3"]},
        deep_dive="SURVIVED", narrative="カルボン酸からトリフルオロエチルアミドへの置換は対象文脈内で大きい正方向シフトを示し、文脈外では効果がほぼ消失しました。[[CIT]]",
        rank=1, score=0.94, falsification_type="context_swap",
        falsification_rule="文脈ラベルを保持した再標本化で中央値差の符号が維持されなければ反証とする。",
        falsification_parameters={"iterations": 5000, "minimum_pairs_per_group": 8},
        action="対象系列で酸／アミド対を追加合成し、文脈外系列を負の対照として同一assayで測定する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"comparison_group": "inside", "effect": value, **({"pair_from_compound_id": acid_pair["neighbor_compound_id"], "pair_to_compound_id": acid_pair["target_compound_id"]} if index == 0 else {})}
        for index, value in enumerate(inside_effects)
    ] + [{"comparison_group": "outside", "effect": value} for value in outside_effects]

    # L2b-A: consistent fragment contribution.
    fragment = "c1ccc(S(=O)(=O)C(F)(F)F)cc1"
    l2b_ids = ["CHEMBL3647725", "CHEMBL3647726", "CHEMBL3647730", "CHEMBL3647736"]
    ref = "mock_l2b_evidence.csv#row_id=E-L2B-001"
    evidence[ref] = {"row_id": "E-L2B-001", "fragment_smiles": fragment, "transform_class": "aryl-SO2CF3", "series_count": 5, "residual_mean": 0.46, "residual_sd": 0.12, "residual_variance": 0.0144}
    finding = _finding(
        number=3, lens="L2b", subject_type="fragment", subject_id="FRAG::aryl-SO2CF3",
        condition_id="across_series", direction="positive", effect=0.46, effect_unit="oriented_endpoint_residual",
        support_n=47, p=0.00031, q=0.0048, statistic=3.72, method="series-adjusted residual meta-analysis", evidence_ref=ref,
        entities={"compound_ids": l2b_ids, "fragment_ids": ["FRAG::aryl-SO2CF3"], "context_ids": [f"SERIES-{value}" for value in "ABCDE"]},
        deep_dive="WEAKENED", narrative="系列効果を除いた後もフラグメントの正方向寄与は残りましたが、leave-one-series-out解析で効果量は小さくなりました。[[CIT]]",
        rank=3, score=0.86, falsification_type="leave_one_series_out",
        falsification_rule="いずれか一系列の除外で統合効果の符号が反転した場合は反証とする。",
        falsification_parameters={"minimum_series": 4}, action="独立系列で同フラグメントを持つ対照化合物を追加し、系列調整後寄与を再確認する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"context_id": f"SERIES-{letter}", "effect": value}
        for letter, value in zip("ABCDE", [0.31, 0.42, 0.47, 0.53, 0.57], strict=True)
    ]

    # L2b-B: heterogeneous fragment contribution.
    ref = "mock_l2b_evidence.csv#row_id=E-L2B-002"
    hetero_fragment = "c1ccc(Cl)cc1"
    hetero_ids = ["CHEMBL3647783", "CHEMBL3647794", "CHEMBL3647795", "CHEMBL3647797"]
    evidence[ref] = {"row_id": "E-L2B-002", "fragment_smiles": hetero_fragment, "transform_class": "aryl-Cl", "series_count": 6, "residual_mean": 0.08, "residual_sd": 0.74, "residual_variance": 0.548}
    finding = _finding(
        number=4, lens="L2b", subject_type="fragment", subject_id="FRAG::aryl-Cl",
        condition_id="across_series", direction="mixed", effect=0.548, effect_unit="oriented_endpoint_variance",
        support_n=61, p=0.0014, q=0.012, statistic=3.19, method="series residual heterogeneity test", evidence_ref=ref,
        entities={"compound_ids": hetero_ids, "fragment_ids": ["FRAG::aryl-Cl"], "context_ids": [f"SERIES-{value}" for value in "ABCDEF"]},
        deep_dive="SURVIVED", narrative="平均寄与は小さい一方、系列ごとの寄与は正負に分かれました。系列を入れ替える深掘りでも不均一性は維持されました。[[CIT]]",
        rank=6, score=0.75, falsification_type="heterogeneity_collapse",
        falsification_rule="系列別残差分散が事前設定した背景分散以下になれば反証とする。",
        falsification_parameters={"background_variance": 0.18}, action="aryl-Clを一律に最適化指針とせず、系列別に対照MMPを置いて寄与方向を確認する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"context_id": f"SERIES-{letter}", "effect": value}
        for letter, value in zip("ABCDEF", [-0.88, -0.46, -0.12, 0.35, 0.61, 0.97], strict=True)
    ]

    # L4: virtual frontier candidate.
    ref = "mock_l4_evidence.csv#row_id=E-L4-001"
    candidate_smiles = by_id["CHEMBL3647738"]["SMILES"]
    l4_sources = ["CHEMBL3647725", "CHEMBL3647736", "CHEMBL3647739"]
    evidence[ref] = {"row_id": "E-L4-001", "candidate_smiles": candidate_smiles, "space_count": 4, "neighbor_k": 12, "lower_confidence_limit": 7.45, "density_gap": 0.63, "region_score": 0.86, "conservative_p_value": 0.012}
    finding = _finding(
        number=5, lens="L4", subject_type="virtual_candidate", subject_id="VIRTUAL-JAK2-001",
        condition_id="reachable_in_one_transformation", direction="positive", effect=0.86, effect_unit="region_score",
        support_n=36, p=0.012, q=0.031, statistic=2.51, method="multi-space frontier permutation", evidence_ref=ref,
        entities={"compound_ids": l4_sources, "candidate_ids": ["VIRTUAL-JAK2-001"], "feature_ids": ["D012", "D013", "D014", "D019"]},
        deep_dive="INCONCLUSIVE", narrative="候補は複数特徴空間で高活性近傍に接していますが、外挿領域にあるため追加検証は結論不能でした。[[CIT]]",
        rank=5, score=0.78, falsification_type="nearest_neighbor_counterexample",
        falsification_rule="いずれかの必須空間で低活性の近接反例が閾値以内に存在すれば候補を棄却する。",
        falsification_parameters={"spaces": 4, "neighbor_k": 12, "minimum_lcl": 7.2}, action="合成前に3D整合性と物性制約を確認し、最小の類縁体セットで予測領域を実測する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"block_id": space, "compound_id": cid, "endpoint_value": float(by_id[cid]["pIC50"])}
        for space in ["D012", "D013", "D014", "D019"]
        for cid in l4_sources
    ]

    # L5: correlation sign reversal across a context axis.
    ref = "mock_l5_evidence.csv#row_id=E-L5-001"
    l5_ids = [row["ID"] for row in rows[:28]]
    evidence[ref] = {"row_id": "E-L5-001", "axis_id": "AXIS::aryl-SO2CF3", "context_a": "present", "feature_id": "D001::MolLogP", "r_a": 0.72, "r_b": -0.61, "global_r": 0.08, "n_a": 14, "n_b": 14, "fisher_z_difference": 4.07}
    finding = _finding(
        number=6, lens="L5", subject_type="feature_context_interaction", subject_id="D001::MolLogP|AXIS::aryl-SO2CF3",
        condition_id="AXIS::aryl-SO2CF3|present", direction="mixed", effect=1.33, effect_unit="correlation_difference",
        support_n=28, p=0.00019, q=0.0029, statistic=4.07, method="Fisher z difference with permutation", evidence_ref=ref,
        entities={"compound_ids": l5_ids, "context_ids": ["AXIS::aryl-SO2CF3|present", "AXIS::aryl-SO2CF3|complement"], "feature_ids": ["D001::MolLogP"]},
        deep_dive="SURVIVED", narrative="MolLogPとJAK2 pIC50の関係は対象文脈で正、同軸補集合で負となり、全体相関では相殺されました。[[CIT]]",
        rank=2, score=0.91, falsification_type="axis_stratified_bootstrap",
        falsification_rule="両群の相関差のbootstrap区間が0をまたぐ、または符号反転が消失すれば反証とする。",
        falsification_parameters={"iterations": 5000, "minimum_n_per_group": 12}, action="全体QSARの単一係数を用いず、aryl-SO2CF3文脈で分けた物性最適化方針を比較する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = []
    for index, cid in enumerate(l5_ids):
        endpoint = float(by_id[cid]["pIC50"])
        focal = index < 14
        observations[finding["finding_key"]].append(
            {"compound_id": cid, "feature_value": (endpoint - 7.5) + (index % 3) * 0.08 if focal else -(endpoint - 7.5) + (index % 3) * 0.08, "endpoint_value": endpoint, "context_role": "focal" if focal else "complement"}
        )

    # L7-A: SAR rank reversal between two series.
    ref = "mock_l7_evidence.csv#row_id=E-L7-001"
    core_a = "[*:1]c1ccc(Nc2nn([C@H]3CCCC[C@@H]3C#N)cc2C(N)=O)cc1"
    core_b = "[*:1]c1ccc(Nc2ncc(C(N)=O)n2[C@H]2CCCC[C@@H]2C#N)cc1"
    evidence[ref] = {"row_id": "E-L7-001", "series_a": "SERIES-A::aminopyrazole", "series_b": "SERIES-B::aminopyrimidine", "constant_a": core_a, "constant_b": core_b, "common_r_count": 4, "spearman_rho": -0.82, "mean_difference": 0.18}
    l7_pairs = [("R-F", 8.7, 7.4, "CHEMBL3639983", "CHEMBL3640018"), ("R-Cl", 8.2, 7.9, "CHEMBL3647783", "CHEMBL3647794"), ("R-CF3", 7.6, 8.3, "CHEMBL3647761", "CHEMBL3647762"), ("R-SO2CF3", 7.2, 8.8, "CHEMBL3647725", "CHEMBL3647736")]
    finding = _finding(
        number=7, lens="L7", subject_type="series_pair", subject_id="SERIES-A::aminopyrazole|SERIES-B::aminopyrimidine",
        condition_id="matched_common_R_groups", direction="mixed", effect=-0.82, effect_unit="spearman_rho",
        support_n=4, p=0.0061, q=0.024, statistic=-0.82, method="exact Spearman permutation", evidence_ref=ref,
        entities={"compound_ids": [item for row in l7_pairs for item in row[3:]], "series_ids": ["SERIES-A::aminopyrazole", "SERIES-B::aminopyrimidine"], "fragment_ids": [row[0] for row in l7_pairs]},
        deep_dive="SURVIVED", narrative="共通R基をそろえると両系列の活性順位は逆転し、片方の系列で有利な置換基が他方では不利でした。[[CIT]]",
        rank=7, score=0.72, falsification_type="common_R_leave_one_out",
        falsification_rule="共通R基を1つずつ除外した順位相関の過半数が負でなくなれば反証とする。",
        falsification_parameters={"minimum_common_r": 4}, action="系列間で置換基順位をそのまま移植せず、両coreに同じR基を導入した対応ペアを追加測定する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"target_id": fragment_id, "effect": value_b - value_a, "endpoint_left_value": value_a, "endpoint_value": value_b, "compound_ids_a_json": json.dumps([cid_a]), "compound_ids_b_json": json.dumps([cid_b])}
        for fragment_id, value_a, value_b, cid_a, cid_b in l7_pairs
    ]

    # L7-B: series main-effect shift with preserved rank.
    ref = "mock_l7_evidence.csv#row_id=E-L7-002"
    evidence[ref] = {"row_id": "E-L7-002", "series_a": "SERIES-C::neutral-linker", "series_b": "SERIES-D::basic-linker", "constant_a": core_a, "constant_b": core_b, "common_r_count": 4, "spearman_rho": 0.91, "mean_difference": 0.74}
    l7_shift = [("R-F", 7.1, 7.8, "CHEMBL3647743", "CHEMBL3647744"), ("R-Cl", 7.4, 8.1, "CHEMBL3647788", "CHEMBL3647795"), ("R-CF3", 7.7, 8.5, "CHEMBL3647777", "CHEMBL3647801"), ("R-SO2CF3", 8.0, 8.8, "CHEMBL3647730", "CHEMBL3647738")]
    finding = _finding(
        number=8, lens="L7", subject_type="series_pair", subject_id="SERIES-C::neutral-linker|SERIES-D::basic-linker",
        condition_id="matched_common_R_groups", direction="positive", effect=0.74, effect_unit="oriented_endpoint_mean_difference",
        support_n=4, p=0.0038, q=0.019, statistic=4.22, method="paired common-R permutation", evidence_ref=ref,
        entities={"compound_ids": [item for row in l7_shift for item in row[3:]], "series_ids": ["SERIES-C::neutral-linker", "SERIES-D::basic-linker"], "fragment_ids": [row[0] for row in l7_shift]},
        deep_dive="WEAKENED", narrative="置換基順位は系列間でおおむね保持されましたが、basic-linker系列は共通R基全体で高いEndpoint水準を示しました。[[CIT]]",
        rank=8, score=0.69, falsification_type="paired_series_shift",
        falsification_rule="対応R基差の中央値が事前設定最小差を下回る、または符号が不安定なら反証とする。",
        falsification_parameters={"minimum_shift": 0.5, "minimum_common_r": 4}, action="順位の移植可能性と系列主効果を分離し、core変更による基礎活性上昇を対応ペアで再確認する。",
    )
    findings.append(finding)
    observations[finding["finding_key"]] = [
        {"target_id": fragment_id, "effect": value_b - value_a, "endpoint_left_value": value_a, "endpoint_value": value_b, "compound_ids_a_json": json.dumps([cid_a]), "compound_ids_b_json": json.dumps([cid_b])}
        for fragment_id, value_a, value_b, cid_a, cid_b in l7_shift
    ]

    return findings, evidence, observations, compound_smiles, fragment_smiles


def _filename(finding: dict[str, Any]) -> str:
    variants = {
        "F-JAK-MOCK-001": "F001_L1b_local_SAR.html",
        "F-JAK-MOCK-002": "F002_L2a_context_MMP.html",
        "F-JAK-MOCK-003": "F003_L2b_consistent_fragment.html",
        "F-JAK-MOCK-004": "F004_L2b_heterogeneous_fragment.html",
        "F-JAK-MOCK-005": "F005_L4_frontier_candidate.html",
        "F-JAK-MOCK-006": "F006_L5_correlation_reversal.html",
        "F-JAK-MOCK-007": "F007_L7_rank_reversal.html",
        "F-JAK-MOCK-008": "F008_L7_series_shift.html",
    }
    return variants[str(finding["finding_id"])]


def generate(jak_path: Path, mmp_dir: Path, output_dir: Path) -> None:
    findings, evidence, observations, compounds, fragments = _build_mock(jak_path, mmp_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_dir = output_dir / "findings"
    detail_dir.mkdir(parents=True, exist_ok=True)
    validation = {"status": "succeeded", "errors": [], "failure_fraction": 0.0}
    report_paths: dict[str, str] = {}
    components: list[dict[str, Any]] = []
    for finding in findings:
        filename = _filename(finding)
        report_paths[finding["finding_id"]] = f"findings/{filename}"
        page = render_finding_html(
            finding, validation, run_id=RUN_ID, endpoint_id=ENDPOINT_ID,
            created_at=CREATED_AT, evidence_by_ref=evidence,
            observations_by_finding=observations, compound_smiles=compounds,
            fragment_smiles=fragments, overview_href="../index.html",
        )
        (detail_dir / filename).write_text(_inject_mock_banner(page), encoding="utf-8")
        citation = finding["citations"][0]
        components.append(
            {
                "component_id": f"COMPONENT-{finding['finding_id']}",
                "finding_ids": [finding["finding_id"]],
                "narrative": finding["narrative"],
                "citations": [citation["citation_id"]],
                "citation_refs": [citation],
            }
        )
    report = {
        "schema_version": "0.2.1", "status": "succeeded", "endpoint_id": ENDPOINT_ID,
        "display_k": len(findings), "components": components,
        "lens_telemetry": [
            {"lens": lens, "engine": "approval_mock", "cost_model_version": "display-only", "unit_count": 1000 * (index + 1), "estimated_seconds": 10.0 + index, "actual_wall_seconds": 8.0 + index, "estimate_actual_ratio": (10.0 + index) / (8.0 + index), "observed_units_per_second": 125.0 + index * 10, "evaluation": "mock"}
            for index, lens in enumerate(["L1b", "L2a", "L2b", "L4", "L5", "L7"])
        ],
    }
    index_page = render_html_report(
        report, findings, validation, run_id=RUN_ID, created_at=CREATED_AT,
        evidence_by_ref=evidence, observations_by_finding=observations,
        compound_smiles=compounds, fragment_smiles=fragments,
        finding_report_paths=report_paths,
    )
    (output_dir / "index.html").write_text(_inject_mock_banner(index_page), encoding="utf-8")
    mock_data = {
        "notice": "Approval mock only. Statistical values and analysis outcomes are fictional.",
        "run_id": RUN_ID, "endpoint_id": ENDPOINT_ID, "findings": findings,
        "evidence_by_ref": evidence, "observations_by_finding": observations,
        "compound_smiles": compounds, "fragment_smiles": fragments,
    }
    (output_dir / "mock_report_data.json").write_text(
        json.dumps(mock_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jak-csv", type=Path, default=DEFAULT_JAK)
    parser.add_argument("--mmp-dir", type=Path, default=DEFAULT_MMP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.jak_csv.resolve(), args.mmp_dir.resolve(), args.output_dir.resolve())
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
