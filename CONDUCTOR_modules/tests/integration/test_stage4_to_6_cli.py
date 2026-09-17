from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_ROOT = PROJECT_ROOT / "CONDUCTOR_modules"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config(tmp_path: Path, **statistics: int) -> Path:
    config = yaml.safe_load((MODULE_ROOT / "config" / "defaults.yaml").read_text(encoding="utf-8"))
    config["statistics"].update(statistics)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _request(
    tmp_path: Path,
    skill_name: str,
    phase: str,
    config: Path,
    inputs: list[tuple[str, Path]],
    operation: str,
) -> Path:
    value = {
        "schema_version": "0.2.1",
        "identity": {
            "project": "test",
            "run_id": "RUN-test",
            "phase_id": phase,
            "node_id": f"NODE-{skill_name}",
            "attempt_id": "ATT-1",
            "skill_name": skill_name,
        },
        "endpoint_id": "EP",
        "config_path": str(config.resolve()),
        "random_seed": 17,
        "inputs": [
            {"role": role, "path": str(path.resolve()), "sha256": _sha256(path)}
            for role, path in inputs
        ],
        "parameters": {"operation": operation},
        "resources": {"workers": 2, "memory_mb": 1024},
    }
    path = tmp_path / f"{skill_name}-request.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _run(skill: str, request: Path, output: Path, workers: int = 1) -> dict:
    runner = PROJECT_ROOT / ".claude" / "skills" / skill / "scripts" / "run.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "--request", str(request), "--output-dir", str(output), "--workers", str(workers)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    response = json.loads(lines[0])
    assert (output / response["manifest"]).is_file()
    return response


def test_fragment_and_context_cli_contracts(tmp_path) -> None:
    config = _config(tmp_path)
    compounds = tmp_path / "compounds.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "canonical_smiles": "CCCCc1ccccc1", "mol_parse_ok": True},
            {"compound_id": "B", "canonical_smiles": "CCCCCc1ccccc1", "mol_parse_ok": True},
            {"compound_id": "R1", "canonical_smiles": "CCCCc1ccccc1CCCC", "mol_parse_ok": True},
            {"compound_id": "R2", "canonical_smiles": "CCCCc1ncccc1CCCC", "mol_parse_ok": True},
        ]
    ).to_csv(compounds, index=False)
    endpoints = tmp_path / "endpoints.csv"
    pd.DataFrame(
        [
            {"compound_id": identifier, "endpoint_id": "EP", "oriented_value": float(index)}
            for index, identifier in enumerate(("A", "B", "R1", "R2"), start=1)
        ]
    ).to_csv(endpoints, index=False)
    fragment_request = _request(
        tmp_path,
        "cs-fragment-engine",
        "P03",
        config,
        [("compounds", compounds), ("endpoint_table", endpoints)],
        "build_database",
    )
    fragment_output = tmp_path / "fragment"
    response = _run("cs-fragment-engine", fragment_request, fragment_output, workers=2)
    assert response["status"] == "succeeded"
    assert (fragment_output / "mmp.sqlite").is_file()

    identifiers = [f"C{index:02d}" for index in range(12)]
    context_compounds = tmp_path / "context-compounds.csv"
    pd.DataFrame(
        {"compound_id": identifiers, "canonical_smiles": ["CCc1ccccc1", "CCCc1ccccc1"] * 6}
    ).to_csv(context_compounds, index=False)
    context_endpoints = tmp_path / "context-endpoints.csv"
    pd.DataFrame(
        {"compound_id": identifiers, "endpoint_id": ["EP"] * 12, "oriented_value": np.arange(12, dtype=float)}
    ).to_csv(context_endpoints, index=False)
    spaces = []
    values = np.column_stack((np.r_[np.zeros(6), np.ones(6) * 10], np.arange(12)))
    for identifier, tier in (("D001", 1), ("D002", 3)):
        payload = tmp_path / f"{identifier}.csv"
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "input_smiles": ["CC"] * 12,
                "mol_parse_ok": [True] * 12,
                "description_error": [""] * 12,
                "signal": values[:, 0],
                "noise": values[:, 1],
            }
        ).to_csv(payload, index=False)
        distance = np.sqrt(np.square(values[:, None, :] - values[None, :, :]).sum(axis=2)).astype(np.float32)
        matrix = tmp_path / f"{identifier}.npy"
        np.save(matrix, distance, allow_pickle=False)
        metadata = tmp_path / f"{identifier}-distance.json"
        metadata.write_text(json.dumps({"compound_ids": identifiers}), encoding="utf-8")
        spaces.append(
            {
                "space_id": identifier,
                "tier": tier,
                "structurality": "non_structural",
                "path": str(payload.resolve()),
                "distance_path": str(matrix.resolve()),
                "distance_metadata_path": str(metadata.resolve()),
            }
        )
    registry = tmp_path / "feature_spaces.json"
    registry.write_text(json.dumps({"schema_version": "0.2.1", "spaces": spaces}), encoding="utf-8")
    context_config = yaml.safe_load(config.read_text(encoding="utf-8"))
    context_config["contexts"]["cluster_counts"] = [2]
    context_config["contexts"]["quantiles"] = [0.5]
    context_config_path = tmp_path / "context-config.yaml"
    context_config_path.write_text(yaml.safe_dump(context_config, sort_keys=False), encoding="utf-8")
    context_request = _request(
        tmp_path,
        "cs-context-builder",
        "P02",
        context_config_path,
        [("compounds", context_compounds), ("endpoint_table", context_endpoints), ("feature_spaces", registry)],
        "build_contexts",
    )
    context_output = tmp_path / "context"
    response = _run("cs-context-builder", context_request, context_output)
    assert response["status"] == "succeeded"
    assert pd.read_csv(context_output / "context_catalog.csv")["context_id"].is_unique


def test_l2b_cli_writes_one_stdout_object_and_checkpoint(tmp_path) -> None:
    config = _config(tmp_path, final_permutations=300)
    observations: list[dict] = []
    endpoints: list[dict] = []
    for index in range(12):
        target, other = f"T{index}", f"O{index}"
        observations.extend(
            [
                {
                    "row_id": f"RT{index}", "series_key": f"S{index}", "transform_class": "terminal_substitution",
                    "fragment_id": "FRAG|0000000000000001", "fragment_smiles": "[1*]N",
                    "compound_ids_json": json.dumps([target]), "n_compounds": 1, "endpoint_mean": 2 + index / 20,
                },
                {
                    "row_id": f"RO{index}", "series_key": f"S{index}", "transform_class": "terminal_substitution",
                    "fragment_id": f"FRAG|{index + 100:016x}", "fragment_smiles": "[1*]C",
                    "compound_ids_json": json.dumps([other]), "n_compounds": 1, "endpoint_mean": 0,
                },
            ]
        )
        endpoints.extend(
            [
                {"compound_id": target, "endpoint_id": "EP", "oriented_value": 2 + index / 20},
                {"compound_id": other, "endpoint_id": "EP", "oriented_value": 0.0},
            ]
        )
    observations_path = tmp_path / "observations.csv"
    pd.DataFrame(observations).to_csv(observations_path, index=False)
    endpoints_path = tmp_path / "l2-endpoints.csv"
    pd.DataFrame(endpoints).to_csv(endpoints_path, index=False)
    database = tmp_path / "mmp.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value_json TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES('complete','true')")
        connection.execute('CREATE TABLE pairs(pair_id TEXT PRIMARY KEY,"class" TEXT)')
        connection.execute("INSERT INTO pairs VALUES('P1','terminal_substitution')")
    contexts = tmp_path / "contexts.csv"
    pd.DataFrame([{"context_id": "SC|0000000000000001", "calibration_scope": True}]).to_csv(contexts, index=False)
    request = _request(
        tmp_path,
        "cs-lens-l2",
        "P03",
        config,
        [
            ("fragment_observations", observations_path),
            ("endpoint_table", endpoints_path),
            ("mmp_database", database),
            ("context_catalog", contexts),
        ],
        "l2b",
    )
    output = tmp_path / "l2"
    response = _run("cs-lens-l2", request, output)
    assert response["status"] == "succeeded"
    checkpoint = json.loads((output / "l2b_calibration.json").read_text(encoding="utf-8"))
    assert checkpoint["acceptance_gt_1_5"]
    assert checkpoint["series_count"] == 12
    assert len((output / "findings.jsonl").read_text(encoding="utf-8").splitlines()) == 1
