from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors

from conductor_context_builder import build_contexts
from conductor_deepdive import ArtifactRegistry, build_chemical_axes, run_deep_dive
from conductor_lens_l1b import run_l1b
from conductor_report import EvidenceRegistry, build_entity_components, validate_finding_tests
from conductor_runtime import prepare_phase1
from conductor_scoring import score_findings
from conductor_stat_core import file_sha256
from description_adapter import write_distance_artifact


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = MODULE_ROOT.parent


def test_phase1_through_phase6_small_fixture(tmp_path: Path) -> None:
    identifiers = [f"C{index:02d}" for index in range(12)]
    smiles = ["C" * (index + 2) for index in range(12)]
    dataset = tmp_path / "dataset.csv"
    pd.DataFrame(
        {
            "compound_id": identifiers,
            "smiles": smiles,
            "activity": [float(index) + (0.2 if index % 2 else 0.0) for index in range(12)],
        }
    ).to_csv(dataset, index=False)
    registry_path = tmp_path / "endpoint_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.2.1",
                "selected_endpoint_id": "EP",
                "endpoints": [
                    {
                        "endpoint_id": "EP", "role": "primary", "kind": "measured",
                        "source_column": "activity", "transform": "none", "higher_is_better": True,
                        "unit": "fixture", "dependencies": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Phase 1: canonical registry plus one real D001-shaped representation.
    phase1 = prepare_phase1(
        dataset_path=dataset,
        registry_path=registry_path,
        selected_endpoint_id="EP",
        output_directory=tmp_path / "phase1",
        schema_directory=MODULE_ROOT / "schemas",
    )
    descriptor_rows = []
    for compound_id, value in zip(identifiers, smiles, strict=True):
        molecule = Chem.MolFromSmiles(value)
        assert molecule is not None
        descriptor_rows.append(
            {
                "compound_id": compound_id, "input_smiles": value, "mol_parse_ok": True,
                "description_error": "", "rdkit2d__MolWt": Descriptors.MolWt(molecule),
                "rdkit2d__MolLogP": Crippen.MolLogP(molecule), "rdkit2d__TPSA": Descriptors.TPSA(molecule),
                "rdkit2d__HeavyAtomCount": Descriptors.HeavyAtomCount(molecule),
            }
        )
    payload = tmp_path / "D001.csv"
    pd.DataFrame(descriptor_rows).to_csv(payload, index=False)
    space = write_distance_artifact(
        payload,
        {"space_id": "D001", "capability_id": "D001", "skill_name": "cs-compute-description-rdkit-2d", "tier": 1, "structurality": "non_structural", "metric": "euclidean", "path": str(payload), "parameters": {}},
        tmp_path / "distance",
    )

    # Phase 2 and 3: contexts followed by a genuine Lens replay over those artifacts.
    contexts = build_contexts(
        phase1.compounds, phase1.endpoints, [space], "EP", cluster_counts=(2,),
        quantiles=(0.5,), min_endpoint_n=3, random_seed=13,
    )
    lens = run_l1b(
        phase1.compounds, phase1.endpoints, contexts.catalog, contexts.membership, [space], "EP",
        run_seed=13, neighbor_k=2, min_endpoint_n=3, lambda_min=-10.0,
        screen_permutations=9, final_permutations=19, screen_p_max=1.0,
        report_q_max=1.0, calibration_permutations=3,
    )
    assert lens.findings and not lens.score_observations.empty

    # Phase 4: lens-exact residualized scoring.
    confounders = pd.DataFrame(
        {
            "compound_id": identifiers,
            "mw": [row["rdkit2d__MolWt"] for row in descriptor_rows],
            "clogp": [row["rdkit2d__MolLogP"] for row in descriptor_rows],
            "tpsa": [row["rdkit2d__TPSA"] for row in descriptor_rows],
            "scaffold_id": [f"ACYCLIC:{value}" for value in smiles],
        }
    )
    scored = score_findings(
        lens.findings, lens.score_observations, phase1.endpoints, "EP", run_seed=13,
        confounders=confounders, bootstrap_iterations=20,
        statistical_strength_min=0.0, robustness_min=0.0, display_k=1,
    )
    assert scored.gate["reportable_count"] >= 1

    # Phase 5: deterministic DeepDive without an external provider.
    axes = build_chemical_axes(phase1.compounds, PROJECT_ROOT / ".claude/skills/cs-deepdive/resources/hammett_constants.tsv")
    deep = run_deep_dive(
        list(scored.findings), ArtifactRegistry(lens.score_observations, axes, pd.DataFrame(), contexts.membership, random_seed=13, min_group_n=3),
        lambda _finding, _allowed, tree: [{"template_id": "T05", "parameters": {"iterations": 20}}] if len(tree) == 1 else [],
        max_depth=1, max_tests_per_finding=1,
    )
    assert deep.updated_findings and all(item["state"]["deep_dive"] != "not_dived" for item in deep.updated_findings)

    # Phase 6: fail-closed evidence/test reconciliation and entity graph assembly.
    evidence_path = tmp_path / "l1b_evidence.csv"
    tests_path = tmp_path / "l1b_tests.csv"
    lens.evidence.to_csv(evidence_path, index=False)
    lens.tests.to_csv(tests_path, index=False)
    evidence_registry = EvidenceRegistry.load(
        tmp_path, [evidence_path, tests_path],
        {evidence_path.name: file_sha256(evidence_path), tests_path.name: file_sha256(tests_path)},
    )
    validate_finding_tests(deep.updated_findings, evidence_registry, set(identifiers))
    components = build_entity_components(deep.updated_findings)
    assert components and set(value for component in components for value in component)
