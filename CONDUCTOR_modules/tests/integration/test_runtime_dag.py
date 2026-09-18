from __future__ import annotations

import json
from pathlib import Path

import pytest

from conductor_runtime import PipelineCoordinator, PipelinePlan, RuntimeStateStore


def test_runtime_dag_executes_once_and_resumes_succeeded_node(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: '0.2.1'\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema_version": "0.2.1",
        "identity": {"project": "P", "run_id": "RUN", "phase_id": "P01", "node_id": "N", "attempt_id": "TEMPLATE", "skill_name": "cs-stat-core"},
        "endpoint_id": "EP", "config_path": str(config), "random_seed": 1, "inputs": [],
        "parameters": {"operation": "fixture"}, "resources": {"workers": 0, "memory_mb": 128},
    }), encoding="utf-8")
    launch = tmp_path / "worker.py"
    launch.write_text(
        "import argparse,json\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output-dir');p.add_argument('--workers');a=p.parse_args()\n"
        "o=Path(a.output_dir);o.mkdir(parents=True);(o/'artifact_manifest.json').write_text(json.dumps({'status':'succeeded','artifacts':[]}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "node-output"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"run_id": "RUN", "code_version": "0.2.1", "nodes": [{"node_id": "N", "phase_id": "P01", "skill_name": "cs-stat-core", "dependencies": [], "request_template": str(request), "launch_path": str(launch), "output_directory": str(output)}]}), encoding="utf-8")
    plan = PipelinePlan.load(plan_path)
    store = RuntimeStateStore(tmp_path / "run" / "runtime.sqlite")
    coordinator = PipelineCoordinator(plan, store, tmp_path / "run", Path(__file__).resolve().parents[2] / "schemas")
    first = coordinator.run()
    second = coordinator.run()
    assert first["status"] == second["status"] == "succeeded"
    assert len(list((tmp_path / "run" / "attempts" / "N").iterdir())) == 1


def test_ready_nodes_wait_for_dependencies(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "state.sqlite")
    for node_id in ("A", "B"):
        store.register_node(node_id=node_id, run_id="RUN", phase_id="P01", skill_name="cs-runtime", input_hashes=[], config_hash="a" * 64, code_version="0.2.1")
    store.register_dependencies("B", ["A"])
    assert [row["node_id"] for row in store.ready_nodes("RUN")] == ["A"]
    leased = store.lease("A")
    base = {"node_id": "A", "attempt_id": leased["attempt_id"], "lease_token": leased["lease_token"], "occurred_at": "2026-09-17T00:00:00Z", "payload": {}}
    assert store.apply_event({**base, "event_id": "E1", "event_type": "started"})
    assert store.apply_event({**base, "event_id": "E2", "event_type": "succeeded"})
    assert [row["node_id"] for row in store.ready_nodes("RUN")] == ["B"]


def test_runtime_injects_explicit_cpu_upper_bound(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: '0.2.1'\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema_version": "0.2.1",
        "identity": {"project": "P", "run_id": "RUN", "phase_id": "P01", "node_id": "CPU", "attempt_id": "TEMPLATE", "skill_name": "cs-stat-core"},
        "endpoint_id": "EP", "config_path": str(config), "random_seed": 1,
        "inputs": [], "parameters": {"operation": "fixture"},
        "resources": {"workers": 7, "memory_mb": 128},
    }), encoding="utf-8")
    launch = tmp_path / "worker.py"
    launch.write_text(
        "import argparse,json,os\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output-dir');p.add_argument('--workers');a=p.parse_args()\n"
        "r=json.load(open(a.request));o=Path(a.output_dir);o.mkdir(parents=True);(o/'cpu.txt').write_text(os.environ['CONDUCTOR_AVAILABLE_CPU_CORES']+'|'+os.environ['CONDUCTOR_NODE_CPU_CORES']+'|'+a.workers+'|'+str(r['resources']['workers']))\n"
        "(o/'artifact_manifest.json').write_text(json.dumps({'status':'succeeded','artifacts':[]}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "node-output"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "run_id": "RUN", "code_version": "0.2.1",
        "nodes": [{"node_id": "CPU", "phase_id": "P01", "skill_name": "cs-stat-core", "dependencies": [], "request_template": str(request), "launch_path": str(launch), "output_directory": str(output)}],
    }), encoding="utf-8")
    coordinator = PipelineCoordinator(
        PipelinePlan.load(plan_path), RuntimeStateStore(tmp_path / "run" / "runtime.sqlite"),
        tmp_path / "run", Path(__file__).resolve().parents[2] / "schemas",
    )
    assert coordinator.run(workers=7)["status"] == "succeeded"
    attempt_output = next(output.iterdir())
    assert (attempt_output / "cpu.txt").read_text(encoding="utf-8") == "7|7|7|7"


def test_pipeline_rejects_noncanonical_description_node(tmp_path: Path) -> None:
    request = tmp_path / "description-request.json"
    request.write_text(
        json.dumps({"parameters": {"operation": "descriptions"}}),
        encoding="utf-8",
    )
    launch = tmp_path / "ad-hoc-description-node.py"
    launch.write_text("raise SystemExit(0)\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({
            "run_id": "RUN",
            "code_version": "0.2.1",
            "nodes": [{
                "node_id": "P01-DESCRIPTIONS",
                "phase_id": "P01",
                "skill_name": "cs-runtime",
                "dependencies": [],
                "request_template": str(request),
                "launch_path": str(launch),
                "output_directory": str(tmp_path / "output"),
            }],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tracked canonical"):
        PipelinePlan.load(plan)
