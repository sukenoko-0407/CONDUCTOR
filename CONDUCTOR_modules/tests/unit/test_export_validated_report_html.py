from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from conductor_stat_core import stable_id

from CONDUCTOR_modules.tools.export_validated_report_html import _visual_inputs


ROOT = Path(__file__).resolve().parents[3]
EXPORTER = ROOT / "CONDUCTOR_modules" / "tools" / "export_validated_report_html.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exporter_verifies_accepted_artifacts_and_does_not_overwrite(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "endpoint_id": "EP",
                "components": [],
                "finding_count": 0,
            }
        ),
        encoding="utf-8",
    )
    findings = tmp_path / "final_findings.jsonl"
    findings.write_text("", encoding="utf-8")
    validation = tmp_path / "citation_validation.json"
    validation.write_text(
        json.dumps({"status": "succeeded", "errors": [], "failure_fraction": 0.0}),
        encoding="utf-8",
    )
    artifacts = [
        ("report_json", report),
        ("final_findings", findings),
        ("citation_validation", validation),
    ]
    manifest = tmp_path / "artifact_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "producer": {
                    "run_id": "RUN|fixture",
                    "node_id": "P06-REPORT",
                    "attempt_id": "ATTEMPT|fixture",
                    "skill_name": "cs-report",
                },
                "created_at": "2026-09-21T00:00:00Z",
                "artifacts": [
                    {"role": role, "path": path.name, "sha256": _sha256(path)}
                    for role, path in artifacts
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "external" / "report.html"
    command = [
        sys.executable,
        str(EXPORTER),
        "--artifact-manifest",
        str(manifest),
        "--output",
        str(output),
    ]

    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(completed.stdout)["run_root_modified"] is False

    repeated = subprocess.run(command, text=True, capture_output=True, check=False)
    assert repeated.returncode != 0
    assert "Refusing to overwrite" in repeated.stderr


def test_exporter_can_render_one_requested_finding(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"status": "succeeded", "endpoint_id": "EP", "components": []}),
        encoding="utf-8",
    )
    finding = {
        "finding_id": "F000001",
        "lens": "L5",
        "claim": {
            "subject_type": "feature",
            "subject_id": "D001::signal",
            "condition_id": "CTX",
            "effect_direction": "mixed",
            "effect_size": 1.2,
            "effect_unit": "fisher_z_difference",
            "support_n": 30,
        },
        "tests": [
            {
                "test_id": "TEST|1",
                "method": "fisher_z",
                "statistic": 1.2,
                "p_value": 0.01,
                "q_value": 0.02,
            }
        ],
        "falsification": {"type": "fixture", "parameters": {}, "decision_rule": "fixture"},
        "triviality": {"raw_effect_size": 1.2, "adjusted_effect_size": 1.1, "verdict": "non_trivial"},
        "translation": {},
        "entities": {"feature_ids": ["D001::signal"], "context_ids": ["CTX"]},
        "citations": [{"citation_id": "CIT-1", "table_ref": "evidence.csv#row_id=E1"}],
        "scores": {"rank": 1, "composite": 0.8},
        "state": {"pipeline": "reportable", "deep_dive": "SURVIVED"},
    }
    findings = tmp_path / "final_findings.jsonl"
    findings.write_text(json.dumps(finding) + "\n", encoding="utf-8")
    validation = tmp_path / "citation_validation.json"
    validation.write_text(json.dumps({"status": "succeeded", "errors": []}), encoding="utf-8")
    evidence = tmp_path / "evidence.csv"
    evidence.write_text("row_id,feature_id,r_a,r_b,n_a,n_b\nE1,D001::signal,0.6,-0.5,20,30\n", encoding="utf-8")
    score_observations = tmp_path / "score_observations.csv"
    score_observations.write_text(
        "finding_key,feature_value,endpoint_value,context_role\n"
        "FND|fixture,-1,1,focal\nFND|fixture,1,2,focal\n"
        "FND|fixture,-1,2,complement\nFND|fixture,1,1,complement\n",
        encoding="utf-8",
    )
    finding["finding_key"] = "FND|fixture"
    findings.write_text(json.dumps(finding) + "\n", encoding="utf-8")
    compounds = tmp_path / "compounds.csv"
    compounds.write_text("compound_id,canonical_smiles\nC1,CC\n", encoding="utf-8")
    source_manifest = tmp_path / "source_manifest.json"
    source_manifest.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "artifacts": [
                    {
                        "role": "score_observations",
                        "path": score_observations.name,
                        "sha256": _sha256(score_observations),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifacts = [("report_json", report), ("final_findings", findings), ("citation_validation", validation)]
    manifest = tmp_path / "artifact_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "producer": {"run_id": "RUN|fixture", "skill_name": "cs-report"},
                "created_at": "2026-09-22T00:00:00Z",
                "input_artifacts": [
                    {"role": "evidence_table", "path": str(evidence), "sha256": _sha256(evidence)},
                    {"role": "compounds", "path": str(compounds), "sha256": _sha256(compounds)},
                    {"role": "artifact_manifest", "path": str(source_manifest), "sha256": _sha256(source_manifest)},
                ],
                "artifacts": [
                    {"role": role, "path": path.name, "sha256": _sha256(path)}
                    for role, path in artifacts
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "external" / "F000001.html"
    completed = subprocess.run(
        [
            sys.executable,
            str(EXPORTER),
            "--artifact-manifest",
            str(manifest),
            "--finding-id",
            "F000001",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = output.read_text(encoding="utf-8")
    assert "この知見が意味すること" in rendered
    assert "D001::signal" in rendered
    assert "相関方向反転の実測図" in rendered
    assert rendered.count("<circle") >= 4
    assert json.loads(completed.stdout)["finding_report_count"] == 1


def test_visual_inputs_resolve_l7_fragment_structures_from_verified_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "mmp.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE fragmentations('
            'fragmentation_id TEXT PRIMARY KEY, compound_id TEXT, "class" TEXT, '
            'constant_key TEXT, variable_smiles TEXT, cut_count INTEGER, '
            'attachment_mapping_json TEXT, mapping_status TEXT, status TEXT, '
            'exclusion_reason TEXT)'
        )
        connection.execute(
            "INSERT INTO fragmentations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "FG|1",
                "C1",
                "terminal_substitution",
                "[*:1]c1ccccc1",
                "[*:1]C",
                1,
                "{}",
                "mapped",
                "accepted",
                None,
            ),
        )
    manifest = {
        "input_artifacts": [
            {
                "role": "mmp_database",
                "path": str(database),
                "sha256": _sha256(database),
            }
        ]
    }

    _, _, fragments = _visual_inputs(manifest, tmp_path)

    fragment_id = stable_id(
        "FRAG",
        {
            "schema_version": "0.2.1",
            "class": "terminal_substitution",
            "variable_smiles": "[*:1]C",
        },
    )
    assert fragments == {fragment_id: "[*:1]C"}
