from __future__ import annotations

import json
from pathlib import Path

import pytest

from conductor_runtime import PipelineCoordinator, PipelinePlan, RuntimeStateStore
from conductor_runtime.dag import NodePlan, _stall_threshold_seconds
from work_contract import WorkEstimate


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


def test_runtime_resolves_declared_dependency_manifest(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: '0.2.1'\n", encoding="utf-8")
    upstream_request = tmp_path / "upstream.json"
    downstream_request = tmp_path / "downstream.json"
    base = {
        "schema_version": "0.2.1",
        "endpoint_id": "EP",
        "config_path": str(config),
        "random_seed": 1,
        "parameters": {"operation": "fixture"},
        "resources": {"workers": 1, "memory_mb": 128},
    }
    upstream_request.write_text(json.dumps({
        **base,
        "identity": {"project": "P", "run_id": "RUN", "phase_id": "P01", "node_id": "A", "attempt_id": "TEMPLATE", "skill_name": "cs-stat-core"},
        "inputs": [],
    }), encoding="utf-8")
    downstream_request.write_text(json.dumps({
        **base,
        "identity": {"project": "P", "run_id": "RUN", "phase_id": "P02", "node_id": "B", "attempt_id": "TEMPLATE", "skill_name": "cs-stat-core"},
        "inputs": [{"role": "artifact_manifest", "path": "manifest://A", "sha256": "a" * 64, "producer_manifest": None}],
    }), encoding="utf-8")
    upstream_launch = tmp_path / "upstream.py"
    upstream_launch.write_text(
        "import argparse,json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output-dir');p.add_argument('--workers');a=p.parse_args()\n"
        "o=Path(a.output_dir);o.mkdir(parents=True);(o/'artifact_manifest.json').write_text(json.dumps({'status':'succeeded','artifacts':[]}))\n",
        encoding="utf-8",
    )
    downstream_launch = tmp_path / "downstream.py"
    downstream_launch.write_text(
        "import argparse,json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output-dir');p.add_argument('--workers');a=p.parse_args()\n"
        "r=json.load(open(a.request));m=Path(r['inputs'][0]['path']);assert m.name=='artifact_manifest.json';assert r['inputs'][0]['producer_manifest']==str(m)\n"
        "o=Path(a.output_dir);o.mkdir(parents=True);(o/'artifact_manifest.json').write_text(json.dumps({'status':'succeeded','artifacts':[]}))\n",
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "run_id": "RUN", "code_version": "0.2.1", "nodes": [
            {"node_id": "A", "phase_id": "P01", "skill_name": "cs-stat-core", "dependencies": [], "request_template": str(upstream_request), "launch_path": str(upstream_launch), "output_directory": str(tmp_path / "A")},
            {"node_id": "B", "phase_id": "P02", "skill_name": "cs-stat-core", "dependencies": ["A"], "request_template": str(downstream_request), "launch_path": str(downstream_launch), "output_directory": str(tmp_path / "B")},
        ],
    }), encoding="utf-8")
    coordinator = PipelineCoordinator(
        PipelinePlan.load(plan_path),
        RuntimeStateStore(tmp_path / "run" / "runtime.sqlite"),
        tmp_path / "run",
        Path(__file__).resolve().parents[2] / "schemas",
    )
    assert coordinator.run(workers=1)["status"] == "succeeded"


def test_runtime_work_guard_stops_lens_before_workload(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: '0.2.1'\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({
            "schema_version": "0.2.1",
            "identity": {
                "project": "P", "run_id": "RUN", "phase_id": "P03",
                "node_id": "L5", "attempt_id": "TEMPLATE", "skill_name": "cs-lens-l5",
            },
            "endpoint_id": "EP", "config_path": str(config), "random_seed": 1,
            "inputs": [], "parameters": {"operation": "l5"},
            "resources": {"workers": 1, "memory_mb": 128},
        }),
        encoding="utf-8",
    )
    launch = tmp_path / "lens.py"
    launch.write_text(
        "import argparse,json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--output-dir');p.add_argument('--workers');p.add_argument('--estimate-work',action='store_true');a=p.parse_args()\n"
        "if a.estimate_work: print(json.dumps({'unit_count':1,'family_size':501,'peak_memory_bytes':1,'estimated_seconds':1.0,'detail':{}}))\n"
        "else: Path(a.output_dir).mkdir(parents=True);(Path(a.output_dir)/'workload_started').write_text('yes')\n",
        encoding="utf-8",
    )
    output = tmp_path / "lens-output"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "run_id": "RUN", "code_version": "0.2.1",
            "nodes": [{
                "node_id": "L5", "phase_id": "P03", "skill_name": "cs-lens-l5",
                "dependencies": [], "request_template": str(request),
                "launch_path": str(launch), "output_directory": str(output),
            }],
        }),
        encoding="utf-8",
    )
    coordinator = PipelineCoordinator(
        PipelinePlan.load(plan_path),
        RuntimeStateStore(tmp_path / "run" / "runtime.sqlite"),
        tmp_path / "run",
        Path(__file__).resolve().parents[2] / "schemas",
        config={"runtime": {"budgets": {"family_size": 500}}},
    )
    summary = coordinator.run(workers=1)
    assert summary["status"] == "needs_design_review"
    attempt_output = next(output.iterdir())
    manifest = json.loads((attempt_output / "artifact_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metrics"]["family_gate"] == "applied"
    assert manifest["metrics"]["work_estimate"]["family_size"] == 501
    assert not (attempt_output / "workload_started").exists()


def test_runtime_work_guard_boundaries_and_l4_family_exemption(tmp_path: Path) -> None:
    plan = PipelinePlan("RUN", "0.2.1", ())
    coordinator = PipelineCoordinator(
        plan,
        RuntimeStateStore(tmp_path / "run" / "runtime.sqlite"),
        tmp_path / "run",
        Path(__file__).resolve().parents[2] / "schemas",
        config={
            "runtime": {
                "budgets": {
                    "family_size": 500,
                    "peak_memory_bytes": 100,
                    "node_wall_seconds": 10,
                    "run_wall_seconds": 100,
                }
            }
        },
    )
    l5 = NodePlan("L5", "P03", "cs-lens-l5", (), tmp_path, tmp_path, tmp_path)
    exact = WorkEstimate(1, 500, 100, 10.0, {})
    assert coordinator._work_guard(l5, exact) == (None, "applied")
    assert coordinator._work_guard(
        l5, WorkEstimate(1, 501, 100, 10.0, {})
    )[0].startswith("family_size")
    assert coordinator._work_guard(
        l5, WorkEstimate(1, 500, 101, 10.0, {})
    )[0].startswith("peak_memory_bytes")
    assert coordinator._work_guard(
        l5, WorkEstimate(1, 500, 100, 10.1, {})
    )[0].startswith("estimated_seconds")

    l4 = NodePlan("L4", "P03", "cs-lens-l4", (), tmp_path, tmp_path, tmp_path)
    assert coordinator._work_guard(
        l4, WorkEstimate(1, 10_000, 100, 10.0, {})
    ) == (None, "exempt_parametric")


def test_runtime_heartbeat_ids_repeat_safely_and_stall_threshold_is_clamped(
    tmp_path: Path,
) -> None:
    store = RuntimeStateStore(tmp_path / "run" / "runtime.sqlite")
    store.register_node(
        node_id="L5",
        run_id="RUN",
        phase_id="P03",
        skill_name="cs-lens-l5",
        input_hashes=[],
        config_hash="a" * 64,
        code_version="0.2.1",
    )
    attempt = store.lease("L5")
    node = NodePlan("L5", "P03", "cs-lens-l5", (), tmp_path, tmp_path, tmp_path)
    coordinator = PipelineCoordinator(
        PipelinePlan("RUN", "0.2.1", (node,)),
        store,
        tmp_path / "run",
        Path(__file__).resolve().parents[2] / "schemas",
    )
    first = coordinator._event(node, attempt, "heartbeat", {"stalled": True})
    second = coordinator._event(node, attempt, "heartbeat", {"stalled": False})
    assert first["event_id"] != second["event_id"]
    assert store.event_count("L5", ("heartbeat",)) == 2

    settings = {
        "stall_multiplier": 20.0,
        "stall_min_seconds": 60.0,
        "stall_max_seconds": 600.0,
    }
    assert _stall_threshold_seconds(1.0, settings) == 60.0
    assert _stall_threshold_seconds(100.0, settings) == 600.0
