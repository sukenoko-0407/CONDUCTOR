from __future__ import annotations

import json
from pathlib import Path

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
