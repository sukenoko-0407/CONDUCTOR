from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
SPEC = importlib.util.spec_from_file_location("conductor_runtime_013", CONTROLLER)
RUNTIME = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNTIME)


class Runtime013Tests(unittest.TestCase):
    def command(self, *arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(CONTROLLER), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        if ok and completed.returncode:
            self.fail(completed.stderr or completed.stdout)
        if not ok and not completed.returncode:
            self.fail("Command unexpectedly succeeded")
        return completed

    def active_basic_round(self, base: Path) -> tuple[Path, str]:
        source = base / "input.csv"
        source.write_text("compound_id,smiles,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n", encoding="utf-8")
        run_root = base / "run"
        self.command("init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better", "--project", "test", "--parallel-limit", "2", "--run-id", "run-013", "--output-dir", str(run_root))
        prepared = json.loads(self.command("prepare-round", "--run-root", str(run_root), "--objective", "packet test", "--walltime-minutes", "60", "--parallel-limit", "2", "--approve-high-cost").stdout)
        control_key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
        self.command("authorize-round", "--run-root", str(run_root), "--control-key", control_key, "--request-file", prepared["request_file"], "--authorization-token", prepared["authorization_token"])
        resumed = json.loads(self.command("resume-round", "--run-root", str(run_root), "--control-key", control_key, "--owner-id", "main-session").stdout)
        lease = resumed["lease_token"]
        self.command("plan-basic", "--run-root", str(run_root), "--lease-token", lease)
        return run_root, lease

    def test_default_lease_and_executor_timeout_are_six_hours(self) -> None:
        parser = RUNTIME.build_parser()
        resumed = parser.parse_args([
            "resume-round", "--run-root", "run", "--control-key", "key", "--owner-id", "owner",
        ])
        heartbeat = parser.parse_args([
            "heartbeat", "--run-root", "run", "--lease-token", "lease",
        ])
        packet = parser.parse_args([
            "prepare-execution-packet", "--run-root", "run", "--lease-token", "lease",
        ])

        self.assertEqual(360, RUNTIME.DEFAULT_LEASE_MINUTES)
        self.assertEqual(360, RUNTIME.DEFAULT_EXECUTION_TIMEOUT_MINUTES)
        self.assertEqual(360, resumed.lease_minutes)
        self.assertEqual(360, heartbeat.lease_minutes)
        self.assertEqual(360, packet.timeout_minutes)

    def test_cpu_budget_defaults_to_eight_and_is_independent_of_parallel_limit(self) -> None:
        parser = RUNTIME.build_parser()
        initialized = parser.parse_args([
            "init", "--input", "input.csv", "--endpoint", "pIC50",
            "--higher-is-better", "--project", "test", "--parallel-limit", "3",
        ])
        self.assertEqual(8, initialized.available_cpu_cores)
        control = {"run": {"parallel_limit": 3, "available_cpu_cores": 8}}
        self.assertEqual(3, RUNTIME._execution_capacity(control))
        control["run"]["parallel_limit"] = 16
        self.assertEqual(8, RUNTIME._execution_capacity(control))

    def test_bundled_schema_references_resolve_offline(self) -> None:
        subject = {
            "scope_mode": "global",
            "cluster_ids": [],
            "clustering_input_kind": "none",
            "cluster_source_description_nodes": [],
            "analysis_description_nodes": ["N000001"],
            "clustering_nodes": [],
            "population_count": 2,
            "endpoint_valid_count": 2,
            "analyzed_count": 2,
            "excluded_count": 0,
            "compound_set_hash": "0" * 64,
        }
        created_at = "2026-08-20T00:00:00+00:00"
        card = {
            "schema_version": "1.0.0",
            "result_ref": "N000002@ATT0001",
            "node_id": "N000002",
            "capability_id": "A001",
            "round_id": "RND0001",
            "analysis_subject": subject,
            "endpoint": {"name": "pIC50"},
            "metric": None,
            "headline": "offline validation",
            "key_metrics": {},
            "validation_passed": True,
            "eligible_for_downstream": True,
            "quality_flags": [],
            "artifact_links": {},
            "created_at": created_at,
        }
        analysis_result = {
            "document_type": "analysis_result",
            "schema_version": "1.0.0",
            "node_id": "N000002",
            "capability_id": "A001",
            "analysis_subject": subject,
            "primary_payload": "analysis.csv",
            "report": "analysis.html",
            "result_cards": ["result_card.json"],
            "created_at": created_at,
        }
        interpretation = {
            "schema_version": "3.0.0",
            "run_id": "run-013",
            "round_id": "RND0001",
            "node_id": "N000003",
            "title": "Offline interpretation",
            "report_header": {
                "project": "test",
                "endpoint": "pIC50",
                "higher_is_better": True,
                "endpoint_unit": None,
                "endpoint_transform": None,
                "completion": "complete",
            },
            "executive_summary": "Summary",
            "coverage_summary": "Coverage",
            "insights": [],
            "result_catalog": [card],
            "review_manifest": {
                "schema_version": "1.0.0",
                "round_id": "RND0001",
                "detailed_result_refs": ["N000002@ATT0001"],
                "aggregate_result_refs": [],
                "unreviewed_results": [],
                "scope_counts": {"global": 1},
                "operator_counts": {"A001": 1},
                "description_counts": {"N000001": 1},
                "created_at": created_at,
            },
            "created_at": created_at,
        }

        RUNTIME._local_schema_registry.cache_clear()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("HTTP retrieval attempted")):
            RUNTIME.validate(analysis_result, "analysis_result.schema.json")
            RUNTIME.validate(card, "result_card.schema.json")
            RUNTIME.validate(interpretation, "interpretation.schema.json")
        from referencing.exceptions import NoSuchResource

        schemas, registry = RUNTIME._local_schema_registry()
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema",
            schemas["analysis_result.schema.json"]["$schema"],
        )
        with self.assertRaises(NoSuchResource):
            registry.get_or_retrieve("https://example.invalid/not-bundled.schema.json")

        interpretation_runner = (
            ROOT
            / ".claude"
            / "skills"
            / "cs-analysis-interpret-results"
            / "scripts"
            / "run.py"
        )
        interpretation_spec = importlib.util.spec_from_file_location(
            "conductor_interpretation_schema_review",
            interpretation_runner,
        )
        interpretation_module = importlib.util.module_from_spec(interpretation_spec)
        assert interpretation_spec and interpretation_spec.loader
        interpretation_spec.loader.exec_module(interpretation_module)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("HTTP retrieval attempted")):
            self.assertEqual(
                [],
                interpretation_module.validate_context_schemas(
                    {
                        "result_cards": [card],
                        "review_manifest": interpretation["review_manifest"],
                    }
                ),
            )
            invalid_card = {**card, "node_id": "invalid"}
            context_issues = interpretation_module.validate_context_schemas(
                {
                    "result_cards": [invalid_card],
                    "review_manifest": interpretation["review_manifest"],
                }
            )
            self.assertTrue(any("result_cards[1] schema error" in issue for issue in context_issues))

    def test_main_orchestrator_is_manual_skill_not_agent(self) -> None:
        skill = ROOT / ".claude" / "skills" / "cs-conductor-orchestrator" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertIn("disable-model-invocation: true", skill.read_text(encoding="utf-8"))
        orchestrator_manifest = tomllib.loads((skill.parent / "env" / "pixi.toml").read_text(encoding="utf-8"))
        self.assertEqual({"python"}, set(orchestrator_manifest["dependencies"]))
        self.assertIn("py_compile", orchestrator_manifest["tasks"]["smoke"])
        orchestrator_runner = (skill.parent / "scripts" / "run.py").read_text(encoding="utf-8")
        self.assertIn("cs-conductor-runtime", orchestrator_runner)
        self.assertNotIn('"runtime_controller.py"', orchestrator_runner)
        runtime_manifest = tomllib.loads((ROOT / ".claude" / "skills" / "cs-conductor-runtime" / "env" / "pixi.toml").read_text(encoding="utf-8"))
        for dependency in ("jsonschema", "referencing", "pandas", "pyarrow"):
            self.assertIn(dependency, runtime_manifest["dependencies"])
            self.assertIn(dependency, runtime_manifest["tasks"]["smoke"])
        self.assertEqual(">=4.21,<5", runtime_manifest["dependencies"]["jsonschema"])
        interpretation_root = ROOT / ".claude" / "skills" / "cs-analysis-interpret-results"
        interpretation_manifest = tomllib.loads((interpretation_root / "env" / "pixi.toml").read_text(encoding="utf-8"))
        self.assertEqual(">=4.21,<5", interpretation_manifest["dependencies"]["jsonschema"])
        self.assertIn("referencing", interpretation_manifest["dependencies"])
        self.assertIn("referencing", interpretation_manifest["tasks"]["smoke"])
        self.assertTrue((interpretation_root / "schemas" / "interpretation_review_manifest.schema.json").is_file())
        interpretation_skill = (interpretation_root / "SKILL.md").read_text(encoding="utf-8")
        interpretation_readme = (interpretation_root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("--overwrite", interpretation_skill)
        self.assertIn("--output-dir path/to/preview", interpretation_readme)
        self.assertFalse((ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").exists())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-executor.md").is_file())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-interpreter.md").is_file())

        executor = (ROOT / ".claude" / "agents" / "cs-conductor-executor.md").read_text(encoding="utf-8")
        frontmatter = executor.split("---", 2)[1]
        executor_tools = next(line for line in frontmatter.splitlines() if line.startswith("tools:"))
        self.assertNotIn("Agent", executor_tools)
        self.assertNotIn("Skill", executor_tools)
        for instruction in ("compatibility-only", "deterministic OS Worker", "A background-task identifier", "Never start another packet"):
            self.assertIn(instruction, executor)

    def test_compact_response_is_bounded_and_does_not_embed_control(self) -> None:
        control = {
            "revision": 7,
            "run": {"run_id": "run"},
            "active_round_id": "RND0002",
            "round_state": "ACTIVE",
            "required_action": {"code": "SCIENTIFIC_DECISION", "reason": "test"},
            "counts": {"succeeded": 5000},
            "closure": {"contract_satisfied": False, "interpretation_ready": False, "audit_ready": False, "outcome": "undetermined"},
            "pointers": {"working_set": "runtime/working_set.json"},
        }
        response = RUNTIME._compact_response(control, detail_pointer="runtime/logs")
        self.assertEqual("0.1.6", response["protocol_version"])
        self.assertNotIn("control", response)
        self.assertLessEqual(len(RUNTIME.canonical_bytes(response)), RUNTIME.MAX_COMPACT_RESPONSE_BYTES)

    def test_execution_packet_is_signed_action_scoped_and_becomes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root, lease = self.active_basic_round(Path(temporary))
            response = json.loads(self.command("prepare-execution-packet", "--run-root", str(run_root), "--lease-token", lease, "--timeout-minutes", "5").stdout)
            self.assertEqual("0.1.6", response["protocol_version"])
            self.assertNotIn("lease_token", response)
            packet_path = Path(response["packet_path"])
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertNotIn("lease_token", packet)
            self.assertTrue(packet["execution_contracts"])
            self.assertTrue(all(contract["command_argv"][0] == RUNTIME.RUNTIME_PYTHON_TOKEN for contract in packet["execution_contracts"]))
            for contract in packet["execution_contracts"]:
                scratch = Path(contract["scratch"])
                skill_output = Path(contract["skill_output"])
                self.assertEqual(scratch / "output", skill_output)
                self.assertEqual("--conductor-request", contract["command_argv"][2])
                self.assertEqual(str(Path(contract["request_path"]).resolve()), contract["command_argv"][3])
                self.assertFalse(skill_output.exists())
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            validated = RUNTIME._validate_execution_packet(run_root, control, packet_path)
            self.assertEqual(response["packet_id"], validated["packet_id"])

            self.command("heartbeat", "--run-root", str(run_root), "--lease-token", lease)
            changed = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            with self.assertRaises(PermissionError):
                RUNTIME._validate_execution_packet(run_root, changed, packet_path)

    @unittest.skip("Legacy Skill-specific CLI assertion; fixed Request command is covered by test_runtime_015.py")
    def test_skill_command_hash_is_independent_of_controller_python(self) -> None:
        capability = RUNTIME.catalog()["D001"]
        control = {"run": {"project": "test", "run_id": "run-013", "input": "input.csv", "smiles_column": "smiles"}}
        node = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": capability["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        snapshot = {"nodes": [node]}
        scratch = ROOT / "scratch" / "N000001" / "ATT0001"
        with mock.patch.object(RUNTIME.sys, "executable", "/orchestrator/env/python"):
            prepared = RUNTIME._skill_command(ROOT, control, snapshot, node, "ATT0001", scratch)
            prepared_resolved = RUNTIME._resolve_skill_command(prepared)
        with mock.patch.object(RUNTIME.sys, "executable", "/runtime/env/python"):
            executed = RUNTIME._skill_command(ROOT, control, snapshot, node, "ATT0001", scratch)
            executed_resolved = RUNTIME._resolve_skill_command(executed)

        self.assertEqual(RUNTIME.RUNTIME_PYTHON_TOKEN, prepared[0])
        self.assertEqual(str(scratch / "output"), prepared[prepared.index("--output-dir") + 1])
        self.assertEqual(prepared, executed)
        self.assertEqual(RUNTIME.value_hash(prepared), RUNTIME.value_hash(executed))
        self.assertEqual("/orchestrator/env/python", prepared_resolved[0])
        self.assertEqual("/runtime/env/python", executed_resolved[0])
        self.assertEqual(prepared_resolved[1:], executed_resolved[1:])
        with self.assertRaises(PermissionError):
            RUNTIME._resolve_skill_command(["/unexpected/python", *prepared[1:]])

    def test_direct_structure_skills_receive_resolved_smiles_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,Standardized_SMILES,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            run_root = base / "run"
            self.command(
                "init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "2", "--run-id", "smiles-column",
                "--output-dir", str(run_root),
            )
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            self.assertEqual("Standardized_SMILES", control["run"]["smiles_column"])
            description_capability = RUNTIME.catalog()["D001"]
            description_node = {
                "node_id": "N000100", "capability_id": "D001",
                "skill_name": description_capability["skill_name"], "assigned_round": "RND0001",
                "kind": "description", "input_nodes": [], "parameters": {},
            }
            description_command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [description_node]}, description_node, "ATT0001",
                base / "D001" / "ATT0001",
            )
            self.assertEqual(
                "Standardized_SMILES",
                json.loads(Path(description_command[3]).read_text(encoding="utf-8"))["columns"]["smiles"],
            )
            for capability_id in ("C001", "C002", "C003", "C004"):
                capability = RUNTIME.catalog()[capability_id]
                node = {
                    "node_id": f"N{int(capability_id[1:]):06d}", "capability_id": capability_id,
                    "skill_name": capability["skill_name"], "assigned_round": "RND0001",
                    "kind": "clustering", "input_nodes": [], "parameters": {"min_cluster_size": 5},
                }
                command = RUNTIME._skill_command(
                    ROOT, control, {"nodes": [node]}, node, "ATT0001", base / capability_id / "ATT0001",
                )
                request = json.loads(Path(command[3]).read_text(encoding="utf-8"))
                self.assertEqual("Standardized_SMILES", request["columns"]["smiles"])

            for capability_id in ("A006", "A009", "A013"):
                capability = RUNTIME.catalog()[capability_id]
                node = {
                    "node_id": f"N{100 + int(capability_id[1:]):06d}", "capability_id": capability_id,
                    "skill_name": capability["skill_name"], "assigned_round": "RND0001",
                    "kind": "analysis", "input_nodes": [], "parameters": {}, "scope": {"mode": "global"},
                }
                command = RUNTIME._skill_command(
                    ROOT, control, {"nodes": [node]}, node, "ATT0001", base / capability_id / "ATT0001",
                )
                request = json.loads(Path(command[3]).read_text(encoding="utf-8"))
                self.assertEqual("Standardized_SMILES", request["columns"]["smiles"])

            capability = RUNTIME.catalog()["A001"]
            nonstructure_node = {
                "node_id": "N000201", "capability_id": "A001", "skill_name": capability["skill_name"],
                "assigned_round": "RND0001", "kind": "analysis", "input_nodes": [],
                "parameters": {}, "scope": {"mode": "global"},
            }
            nonstructure_command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [nonstructure_node]}, nonstructure_node, "ATT0001",
                base / "A001" / "ATT0001",
            )
            request = json.loads(Path(nonstructure_command[3]).read_text(encoding="utf-8"))
            self.assertEqual("Standardized_SMILES", request["columns"]["smiles"])

    def test_runtime_passes_only_the_canonical_description_result_downstream(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        dataset = base / "input.csv"
        dataset.write_text("compound_id,smiles,pIC50\nC001,CCO,5\nC002,CCN,6\n", encoding="utf-8")
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": str(dataset),
                "id_column": "compound_id", "endpoint": "pIC50", "higher_is_better": True,
                "smiles_column": "smiles", "available_cpu_cores": 8, "parallel_limit": 2,
            }
        }
        description_capability = RUNTIME.catalog()["D001"]
        description = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": description_capability["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
            "output_ref": str(base / "description" / "N000001"),
        }
        description_output = Path(description["output_ref"])
        description_output.mkdir(parents=True)
        (description_output / "features.csv").write_text("compound_id,f1\nC001,1\nC002,2\n", encoding="utf-8")
        RUNTIME.write_json(
            description_output / "result.json",
            {
                "document_type": "description_result", "schema_version": "1.0.0", "node_id": "N000001", "capability_id": "D001",
                "payload": "features.csv", "row_count": 2, "feature_count": 1,
                "value_semantics": "dense_continuous", "natural_metric": "euclidean",
                "feature_columns": ["f1"], "quality_flags": [], "created_at": RUNTIME.utc_now(),
            },
        )
        for capability_id, kind in (("C005", "clustering"), ("A003", "analysis"), ("A004", "analysis")):
            capability = RUNTIME.catalog()[capability_id]
            node = {
                "node_id": f"N{int(capability_id[1:]) + 10:06d}", "capability_id": capability_id,
                "skill_name": capability["skill_name"], "assigned_round": "RND0001", "kind": kind,
                "input_nodes": [description["node_id"]], "parameters": {}, "scope": {"mode": "global"},
            }
            command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [description, node]}, node, "ATT0001",
                base / capability_id / "ATT0001",
            )
            request = json.loads(Path(command[3]).read_text(encoding="utf-8"))
            source = next(item for item in request["inputs"] if item["role"] == "description")
            self.assertEqual(str(Path(description["output_ref"]) / "result.json"), source["result_path"])

    def test_xtb_is_exclusive_and_uses_four_cores_per_compound(self) -> None:
        capabilities = RUNTIME.catalog()
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": "input.csv",
                "smiles_column": "smiles", "parallel_limit": 8, "available_cpu_cores": 10,
            }
        }
        regular = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": capabilities["D001"]["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        xtb = {
            "node_id": "N000019", "capability_id": "D019", "skill_name": capabilities["D019"]["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        runnable = {node["node_id"]: node for node in (regular, xtb)}
        self.assertEqual([xtb["node_id"]], RUNTIME._select_execution_nodes([xtb["node_id"], regular["node_id"]], runnable, control))
        self.assertEqual([regular["node_id"]], RUNTIME._select_execution_nodes([regular["node_id"], xtb["node_id"]], runnable, control))
        options = RUNTIME._request_resource_options(control, xtb, capabilities["D019"])
        self.assertEqual({"cores_per_compound": 4, "compound_workers": 2, "available_cpu_cores": 10}, options)
        self.assertEqual(10, RUNTIME._node_cpu_allocation(control, xtb))
        self.assertEqual(4, RUNTIME._native_thread_limit(control, xtb))

    def test_mcs_is_exclusive_and_bounded_to_eight_single_thread_workers(self) -> None:
        capabilities = RUNTIME.catalog()
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": "input.csv",
                "smiles_column": "smiles", "parallel_limit": 8, "available_cpu_cores": 64,
            }
        }
        regular = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": capabilities["D001"]["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        mcs = {
            "node_id": "N000102", "capability_id": "C002", "skill_name": capabilities["C002"]["skill_name"],
            "assigned_round": "RND0001", "kind": "clustering", "input_nodes": [], "parameters": {},
        }
        runnable = {node["node_id"]: node for node in (regular, mcs)}
        self.assertEqual([mcs["node_id"]], RUNTIME._select_execution_nodes([mcs["node_id"], regular["node_id"]], runnable, control))
        self.assertEqual(8, RUNTIME._node_cpu_allocation(control, mcs))
        self.assertEqual(1, RUNTIME._native_thread_limit(control, mcs))
        control["run"]["available_cpu_cores"] = 4
        self.assertEqual(4, RUNTIME._node_cpu_allocation(control, mcs))

    def test_mcs_skill_worker_count_obeys_node_budget_and_task_count(self) -> None:
        runner = ROOT / ".claude" / "skills" / "cs-compute-clustering-structure-mcs" / "scripts" / "run.py"
        spec = importlib.util.spec_from_file_location("mcs_parallel_dispatch_test", runner)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with mock.patch.dict(
            os.environ,
            {"CONDUCTOR_NODE_CPU_CORES": "64", "CONDUCTOR_AVAILABLE_CPU_CORES": "64"},
        ):
            self.assertEqual(8, module._mcs_worker_count(1000))
            self.assertEqual(3, module._mcs_worker_count(3))
        with mock.patch.dict(
            os.environ,
            {"CONDUCTOR_NODE_CPU_CORES": "4", "CONDUCTOR_AVAILABLE_CPU_CORES": "64"},
        ):
            self.assertEqual(4, module._mcs_worker_count(1000))
        self.assertEqual(0, module._mcs_worker_count(0))

    def test_mordred_3d_is_exclusive_and_bounded_to_eight_single_thread_workers(self) -> None:
        capabilities = RUNTIME.catalog()
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": "input.csv",
                "smiles_column": "smiles", "parallel_limit": 8, "available_cpu_cores": 64,
            }
        }
        regular = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": capabilities["D001"]["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        mordred = {
            "node_id": "N000016", "capability_id": "D016", "skill_name": capabilities["D016"]["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        runnable = {node["node_id"]: node for node in (regular, mordred)}
        self.assertEqual([mordred["node_id"]], RUNTIME._select_execution_nodes([mordred["node_id"], regular["node_id"]], runnable, control))
        self.assertEqual(8, RUNTIME._node_cpu_allocation(control, mordred))
        self.assertEqual(1, RUNTIME._native_thread_limit(control, mordred))
        options = RUNTIME._request_resource_options(control, mordred, capabilities["D016"])
        self.assertEqual({"compound_workers": 8, "available_cpu_cores": 8}, options)

    def test_mordred_3d_parallel_dispatch_preserves_input_order_and_cpu_metadata(self) -> None:
        runner = ROOT / ".claude" / "skills" / "cs-compute-description-mordred-3d" / "scripts" / "run.py"
        spec = importlib.util.spec_from_file_location("mordred_3d_parallel_dispatch_test", runner)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class ImmediateFuture:
            def __init__(self, value: object) -> None:
                self.value = value

            def result(self) -> object:
                return self.value

        class ImmediateExecutor:
            def __init__(self, max_workers: int, **_kwargs: object) -> None:
                self.max_workers = max_workers

            def __enter__(self) -> "ImmediateExecutor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def submit(self, function: object, *arguments: object) -> ImmediateFuture:
                return ImmediateFuture(function(*arguments))

        rows = [
            {"compound_id": "C1", "input_smiles": "CCO", "description_error": ""},
            {"compound_id": "C2", "input_smiles": "CCN", "description_error": ""},
        ]
        arguments = argparse.Namespace(compound_workers=2, available_cpu_cores=8, num_confs=1, random_seed=61453)
        fake_worker = lambda index, _smiles, _settings: (
            index, {"mordred__test": float(index)}, None, None, index + 10,
        )
        with mock.patch.object(module.os, "sched_getaffinity", return_value=set(range(64)), create=True), mock.patch.object(
            module, "_mordred_3d_worker", side_effect=fake_worker
        ), mock.patch.object(
            module, "ProcessPoolExecutor", ImmediateExecutor
        ), mock.patch.object(module, "as_completed", side_effect=lambda futures: reversed(list(futures))):
            calculated, errors, resources = module.compute_mordred_3d_parallel(rows, [object(), object()], arguments)
        self.assertEqual([], errors)
        self.assertEqual([0.0, 1.0], [row["mordred__test"] for row in calculated])
        self.assertEqual(2, resources["compound_workers"])
        self.assertEqual(1, resources["native_threads_per_worker"])
        self.assertEqual(2, resources["maximum_cpu_cores"])
        self.assertEqual(8, resources["declared_available_cpu_cores"])

    def test_xtb_compound_parallel_dispatch_preserves_rows_and_cpu_metadata(self) -> None:
        runner = ROOT / ".claude" / "skills" / "cs-compute-description-tblite-xtb" / "scripts" / "run.py"
        spec = importlib.util.spec_from_file_location("xtb_parallel_dispatch_test", runner)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class ImmediateFuture:
            def __init__(self, value: object) -> None:
                self.value = value

            def result(self) -> object:
                return self.value

        executor_options: dict[str, object] = {}

        class ImmediateExecutor:
            def __init__(self, max_workers: int, **kwargs: object) -> None:
                self.max_workers = max_workers
                self.kwargs = kwargs
                executor_options.update(kwargs)

            def __enter__(self) -> "ImmediateExecutor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def submit(self, function: object, *arguments: object) -> ImmediateFuture:
                return ImmediateFuture(function(*arguments))

        rows = [
            {"compound_id": "C1", "input_smiles": "CCO", "description_error": ""},
            {"compound_id": "C2", "input_smiles": "CCN", "description_error": ""},
        ]
        arguments = argparse.Namespace(
            compound_workers=2, cores_per_compound=4, num_confs=1,
            random_seed=61453, charge=None, uhf=None, available_cpu_cores=8,
        )
        fake_worker = lambda index, _smiles, _settings: (
            index, {"xtb__test": float(index)}, None, None,
            {"pid": index + 1, "affinity_cpu_ids": None, "affinity_cpu_count": None, "thread_environment": {}},
        )
        with mock.patch.object(module, "_linux_allowed_cpu_ids", return_value=None), mock.patch.object(
            module, "_xtb_worker", side_effect=fake_worker
        ), mock.patch.object(
            module, "ProcessPoolExecutor", ImmediateExecutor
        ), mock.patch.object(module, "as_completed", side_effect=lambda futures: list(futures)), mock.patch.dict(
            os.environ, {}, clear=False
        ):
            calculated, errors, resources = module.compute_xtb_parallel(rows, [object(), object()], arguments)
        self.assertEqual([], errors)
        self.assertEqual([0.0, 1.0], [row["xtb__test"] for row in calculated])
        self.assertEqual(2, resources["compound_workers"])
        self.assertEqual(4, resources["cores_per_compound"])
        self.assertEqual(8, resources["maximum_cpu_cores"])
        self.assertEqual(8, resources["declared_available_cpu_cores"])
        self.assertFalse(resources["cpu_affinity_enforced"])
        self.assertEqual("4,1", resources["thread_environment"]["OMP_NUM_THREADS"])
        self.assertEqual("1", resources["thread_environment"]["OPENBLAS_NUM_THREADS"])
        self.assertEqual("spawn", executor_options["mp_context"].get_start_method())
        self.assertIs(module._initialize_xtb_worker, executor_options["initializer"])

    def test_xtb_cpu_plan_uses_disjoint_linux_affinity_groups(self) -> None:
        runner = ROOT / ".claude" / "skills" / "cs-compute-description-tblite-xtb" / "scripts" / "run.py"
        spec = importlib.util.spec_from_file_location("xtb_cpu_plan_test", runner)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        arguments = argparse.Namespace(compound_workers=2, cores_per_compound=4, available_cpu_cores=10)
        with mock.patch.object(module, "_linux_allowed_cpu_ids", return_value=list(range(12))):
            plan = module._xtb_cpu_plan(20, arguments)
        self.assertEqual([[0, 1, 2, 3], [4, 5, 6, 7]], plan["affinity_groups"])
        self.assertEqual(list(range(10)), plan["selected_cpu_ids"])
        self.assertEqual(8, plan["maximum_cpu_cores"])
        with mock.patch.object(module, "_linux_allowed_cpu_ids", return_value=list(range(8))):
            with self.assertRaisesRegex(RuntimeError, "cpuset allowance"):
                module._xtb_cpu_plan(20, arguments)

    @unittest.skip("Legacy Skill-specific CLI assertion; Request adapter coverage is in test_runtime_015.py")
    def test_projection_cluster_overlay_uses_clustering_node_id_not_unsupported_representation_option(self) -> None:
        capabilities = RUNTIME.catalog()
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": "input.csv",
                "endpoint": "pIC50", "higher_is_better": True, "smiles_column": "smiles",
                "parallel_limit": 2, "available_cpu_cores": 8,
            }
        }
        clustering = {
            "node_id": "N000101", "capability_id": "C005", "skill_name": capabilities["C005"]["skill_name"],
            "assigned_round": "RND0001", "kind": "clustering", "input_nodes": [], "parameters": {},
        }
        for offset, capability_id in enumerate(("A003", "A004"), 2):
            global_projection = {
                "node_id": f"N00010{offset}", "capability_id": capability_id,
                "skill_name": capabilities[capability_id]["skill_name"],
                "assigned_round": "RND0001", "kind": "analysis", "input_nodes": [], "parameters": {},
            }
            overlay = {
                "node_id": f"N00011{offset}", "capability_id": capability_id,
                "skill_name": capabilities[capability_id]["skill_name"],
                "assigned_round": "RND0001", "kind": "analysis",
                "input_nodes": [clustering["node_id"], global_projection["node_id"]],
                "parameters": {"role": "cluster-overlay", "target_cluster": "CL000001"},
                "scope": {"mode": "single_cluster"},
            }
            with mock.patch.object(RUNTIME, "_primary_payload", side_effect=lambda node: Path(f"{node['node_id']}.csv")):
                command = RUNTIME._skill_command(
                    ROOT, control, {"nodes": [clustering, global_projection, overlay]}, overlay,
                    "ATT0001", ROOT / "scratch" / f"{capability_id}-overlay",
                )
            self.assertEqual(clustering["node_id"], command[command.index("--clustering-node-id") + 1])
            self.assertNotIn("--clustering-representation", command)

    def test_canonical_result_identity_and_artifact_paths_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "description" / "N000001"
            output.mkdir(parents=True)
            node = {
                "node_id": "N000001", "capability_id": "D001", "kind": "description",
                "output_ref": str(output),
            }
            payload = output / "features.csv"
            payload.write_text("compound_id,f1\nC001,1\n", encoding="utf-8")
            result = {
                "document_type": "description_result", "schema_version": "1.0.0",
                "node_id": "N000001", "capability_id": "D001", "payload": payload.name,
                "row_count": 1, "feature_count": 1, "value_semantics": "dense_continuous",
                "natural_metric": "euclidean", "feature_columns": ["f1"], "quality_flags": [],
                "created_at": RUNTIME.utc_now(),
            }
            RUNTIME.write_json(output / "result.json", result)
            self.assertEqual(payload, RUNTIME._primary_payload(node))
            result["capability_id"] = "D002"
            RUNTIME.write_json(output / "result.json", result)
            with self.assertRaises(Exception):
                RUNTIME._canonical_result(node)
            with self.assertRaises(ValueError):
                RUNTIME._skill_artifact_path(root, "../escaped.json")

    def test_init_requires_explicit_smiles_column_only_when_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,parent_smiles,product_smiles,pIC50\nCMP1,CCO,CCN,5.1\n",
                encoding="utf-8",
            )
            failed = self.command(
                "init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "1", "--run-id", "ambiguous",
                "--output-dir", str(base / "failed-run"), ok=False,
            )
            self.assertIn("Ambiguous SMILES columns", failed.stderr)
            run_root = base / "explicit-run"
            self.command(
                "init", "--input", str(source), "--smiles-column", "product_smiles",
                "--endpoint", "pIC50", "--higher-is-better", "--project", "test",
                "--parallel-limit", "1", "--run-id", "explicit", "--output-dir", str(run_root),
            )
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            self.assertEqual("product_smiles", control["run"]["smiles_column"])

    @unittest.skip("0.1.6 does not support legacy Run metadata")
    def test_legacy_run_without_smiles_metadata_uses_deterministic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,source_SMILES_text,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            control = {"run": {"project": "test", "run_id": "legacy", "input": str(source)}}
            capability = RUNTIME.catalog()["C001"]
            node = {
                "node_id": "N000001", "capability_id": "C001", "skill_name": capability["skill_name"],
                "assigned_round": "RND0001", "kind": "clustering", "input_nodes": [],
                "parameters": {"min_cluster_size": 5},
            }
            command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [node]}, node, "ATT0001", base / "scratch" / "ATT0001",
            )
            option = command.index("--smiles-column")
            self.assertEqual("source_SMILES_text", command[option + 1])

    def test_legacy_run_can_record_explicit_smiles_column_when_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,molecule_text,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            run_root = base / "run"
            self.command(
                "init", "--input", str(source), "--smiles-column", "molecule_text",
                "--endpoint", "pIC50", "--higher-is-better", "--project", "test",
                "--parallel-limit", "1", "--run-id", "legacy-explicit", "--output-dir", str(run_root),
            )
            control_path = run_root / "conductor_control.json"
            legacy_control = json.loads(control_path.read_text(encoding="utf-8"))
            legacy_control["run"].pop("smiles_column")
            RUNTIME.write_json(control_path, legacy_control)
            prepared = json.loads(self.command(
                "prepare-round", "--run-root", str(run_root), "--objective", "legacy resume",
                "--walltime-minutes", "60", "--parallel-limit", "1", "--approve-high-cost",
            ).stdout)
            control_key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
            self.command(
                "authorize-round", "--run-root", str(run_root), "--control-key", control_key,
                "--request-file", prepared["request_file"],
                "--authorization-token", prepared["authorization_token"],
            )
            resumed = json.loads(self.command(
                "resume-round", "--run-root", str(run_root), "--control-key", control_key,
                "--owner-id", "legacy-main", "--smiles-column", "molecule_text",
            ).stdout)
            self.assertTrue(resumed["lease_acquired"])
            control = json.loads(control_path.read_text(encoding="utf-8"))
            self.assertEqual("molecule_text", control["run"]["smiles_column"])

    def test_runtime_management_files_do_not_dirty_skill_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / "ATT0001"
            scratch.mkdir()
            skill_output = RUNTIME._skill_output_dir(scratch)
            logical = [RUNTIME.RUNTIME_PYTHON_TOKEN, "empty-output-check"]
            script = (
                "from pathlib import Path; import sys; "
                "output=Path(sys.argv[1]); "
                "assert not output.exists(), 'skill output was pre-created'; "
                "output.mkdir(); (output/'ok.txt').write_text('ok', encoding='utf-8')"
            )
            outcome = RUNTIME._run_one(
                [sys.executable, "-c", script, str(skill_output)],
                scratch / "run.log",
                scratch / "process.json",
                30,
                RUNTIME.value_hash(logical),
            )

            self.assertEqual(0, outcome["returncode"])
            self.assertTrue((scratch / "tmp").is_dir())
            self.assertTrue((scratch / "process.json").is_file())
            self.assertEqual("ok", (skill_output / "ok.txt").read_text(encoding="utf-8"))
            process = json.loads((scratch / "process.json").read_text(encoding="utf-8"))
            self.assertEqual(RUNTIME.value_hash(logical), process["command_hash"])
            self.assertEqual(sys.executable, process["runtime_python"])

    def test_runtime_separates_node_cpu_budget_from_native_thread_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / "ATT0001"
            log = scratch / "run.log"
            script = (
                "import json,os; print(json.dumps({"
                "'node':os.environ['CONDUCTOR_NODE_CPU_CORES'],"
                "'available':os.environ['CONDUCTOR_AVAILABLE_CPU_CORES'],"
                "'native':os.environ['CONDUCTOR_NATIVE_THREAD_LIMIT'],"
                "'omp':os.environ['OMP_NUM_THREADS']}))"
            )
            outcome = RUNTIME._run_one(
                [sys.executable, "-c", script], log, scratch / "process.json", 30,
                "contract-hash", cpu_cores=8, available_cpu_cores=8, native_thread_limit=4,
            )
            self.assertEqual(0, outcome["returncode"])
            self.assertEqual(
                {"node": "8", "available": "8", "native": "4", "omp": "4"},
                json.loads(log.read_text(encoding="utf-8")),
            )

    @unittest.skip("Adaptive recovery scratch was removed in 0.1.6")
    def test_only_empty_or_recovery_scratch_can_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / "ATT0001"
            scratch.mkdir()
            RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=False)
            recovery = scratch / "recovery"
            recovery.mkdir()
            RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=True)
            with self.assertRaises(FileExistsError):
                RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=False)
            (scratch / "process.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=True)

    def test_invalid_execution_contract_does_not_create_attempt_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root, lease = self.active_basic_round(Path(temporary))
            response = json.loads(self.command(
                "prepare-execution-packet", "--run-root", str(run_root),
                "--lease-token", lease, "--timeout-minutes", "5",
            ).stdout)
            packet = json.loads(Path(response["packet_path"]).read_text(encoding="utf-8"))
            scratch_paths = [Path(contract["scratch"]) for contract in packet["execution_contracts"]]
            original = RUNTIME._skill_command

            def changed_command(*arguments: object, **keywords: object) -> list[str]:
                command = original(*arguments, **keywords)
                return [*command, "--unexpected-contract-change"]

            arguments = argparse.Namespace(
                run_root=str(run_root), packet=response["packet_path"],
            )
            with mock.patch.object(RUNTIME, "_skill_command", side_effect=changed_command):
                with self.assertRaises(PermissionError):
                    RUNTIME.cmd_execute_packet(arguments)
            for path in scratch_paths:
                self.assertTrue(path.is_dir())
                self.assertEqual({"execution_request.json"}, {item.name for item in path.iterdir()})

    @unittest.skip("Legacy 200/50 planner was replaced by one 100-Node exploration in 0.1.6")
    def test_analysis_planning_is_batched_and_capped_per_round(self) -> None:
        maximum, batch_size = RUNTIME._analysis_planning_limits()
        self.assertEqual(200, maximum)
        self.assertEqual(50, batch_size)
        self.assertEqual(100, RUNTIME._initial_global_analysis_limit())
        control = {"active_round_id": "RND0001", "run": {"run_root": str(ROOT / ".test-run")}}
        snapshot = {
            "counters": {"node": 0, "cluster": 0, "insight": 0},
            "nodes": [],
            "rounds": {"RND0001": {"reused_node_ids": []}},
            "plans": {"RND0001": {}},
        }
        specs = [
            {
                "capability_id": "A001",
                "input_nodes": [],
                "scope": {"mode": "single_cluster", "cluster_ids": [f"C{index:06d}"]},
                "parameters": {"target_cluster": f"C{index:06d}"},
            }
            for index in range(1, 251)
        ]

        expected_deferred = [200, 150, 100, 50]
        for expected in expected_deferred:
            planned, deferred = RUNTIME._materialize_analysis_specs(snapshot, control, specs, "initial_local")
            self.assertEqual(50, len(planned))
            self.assertEqual(expected, deferred)
        planned, deferred = RUNTIME._materialize_analysis_specs(snapshot, control, specs, "initial_local")
        self.assertEqual([], planned)
        self.assertEqual(50, deferred)
        self.assertEqual(200, RUNTIME._round_analysis_work_count(snapshot, "RND0001"))

        for node in snapshot["nodes"]:
            node["status"] = "succeeded"
            node["result_quality"] = {"eligible_for_downstream": True}
        control["active_round_id"] = "RND0002"
        snapshot["rounds"]["RND0002"] = {"reused_node_ids": []}
        snapshot["plans"]["RND0002"] = {}
        planned, deferred = RUNTIME._materialize_analysis_specs(snapshot, control, specs, "initial_local")
        self.assertEqual(50, len(planned))
        self.assertEqual(0, deferred)
        self.assertEqual(50, RUNTIME._round_analysis_work_count(snapshot, "RND0002"))

    @unittest.skip("Legacy Initial Global phase was replaced by the unified explorer in 0.1.6")
    def test_initial_global_reserves_capacity_for_local_analysis(self) -> None:
        control = {"active_round_id": "RND0001", "run": {"run_root": str(ROOT / ".test-run")}}
        snapshot = {
            "counters": {"node": 0, "cluster": 0, "insight": 0},
            "nodes": [],
            "rounds": {"RND0001": {"reused_node_ids": []}},
            "plans": {"RND0001": {}},
        }
        specs = [
            {
                "capability_id": capability_id,
                "input_nodes": [],
                "scope": {"mode": "global"},
                "parameters": {"serial": serial},
            }
            for serial in range(100)
            for capability_id in ("A001", "A002", "A003")
        ]
        ordered = RUNTIME._balanced_analysis_specs(snapshot, specs, "initial_global")
        self.assertEqual({"A001", "A002", "A003"}, {item["capability_id"] for item in ordered[:3]})

        planned, deferred = RUNTIME._materialize_analysis_specs(
            snapshot, control, specs, "initial_global", wave_limit=100,
        )
        self.assertEqual((50, 250), (len(planned), deferred))
        planned, deferred = RUNTIME._materialize_analysis_specs(
            snapshot, control, specs, "initial_global", wave_limit=100,
        )
        self.assertEqual((50, 200), (len(planned), deferred))
        planned, deferred = RUNTIME._materialize_analysis_specs(
            snapshot, control, specs, "initial_global", wave_limit=100,
        )
        self.assertEqual((0, 200), (len(planned), deferred))
        self.assertEqual(100, RUNTIME._round_analysis_work_count(snapshot, "RND0001"))

    @unittest.skip("Legacy Initial Global/Local phases were replaced by the unified explorer in 0.1.6")
    def test_initial_exploration_covers_global_and_local_within_two_hundred_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            (root / "runtime").mkdir(parents=True)
            RUNTIME.write_json(root / "conductor_control.json", {"run": {"row_count": 1000}})
            control = {"active_round_id": "RND0001", "run": {"run_root": str(root)}}
            snapshot = {
                "counters": {"node": 0, "cluster": 0, "insight": 0},
                "nodes": [],
                "rounds": {"RND0001": {"reused_node_ids": [], "finish_reason": None, "runtime_version": "0.1.4"}},
                "plans": {"RND0001": {"basic_compute": False, "initial_global": False, "initial_local": False}},
            }
            RUNTIME._plan_basic(control, snapshot)
            cluster_rows = []
            for node in snapshot["nodes"]:
                node["status"] = "succeeded"
                node["result_quality"] = {"eligible_for_downstream": True}
                if node["kind"] == "clustering":
                    cluster_rows.append({
                        "cluster_id": f"C{len(cluster_rows) + 1:06d}",
                        "source_node_id": node["node_id"],
                        "compound_count": 20,
                        "structural_cohesion": 0.8,
                        "status": "active",
                    })
            (root / "runtime" / "cluster_registry.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in cluster_rows), encoding="utf-8",
            )

            for _ in range(2):
                planned = RUNTIME._plan_initial_global(control, snapshot)
                self.assertEqual(50, len(planned))
                for node in snapshot["nodes"]:
                    if node["node_id"] in planned:
                        node["status"] = "succeeded"
                        node["result_quality"] = {"eligible_for_downstream": True}
            global_capabilities = {
                node["capability_id"] for node in snapshot["nodes"] if node.get("wave") == "initial_global"
            }
            self.assertEqual(
                set(RUNTIME.profile()["initial_exploration"]["global_operator_capabilities"]),
                global_capabilities,
            )
            self.assertTrue(snapshot["plans"]["RND0001"]["initial_global"])

            for _ in range(2):
                planned = RUNTIME._plan_initial_local(root, control, snapshot)
                self.assertEqual(50, len(planned))
                for node in snapshot["nodes"]:
                    if node["node_id"] in planned:
                        node["status"] = "succeeded"
                        node["result_quality"] = {"eligible_for_downstream": True}
            local_capabilities = {
                node["capability_id"] for node in snapshot["nodes"] if node.get("wave") == "initial_local"
            }
            self.assertTrue(
                set(RUNTIME.profile()["initial_exploration"]["local_operator_capabilities"])
                <= local_capabilities
            )
            self.assertEqual(200, RUNTIME._round_analysis_work_count(snapshot, "RND0001"))
            self.assertTrue(snapshot["plans"]["RND0001"]["initial_local"])
            self.assertEqual(
                "analysis_node_budget_exhausted",
                snapshot["rounds"]["RND0001"]["finish_reason"],
            )

    def test_analysis_node_limit_is_a_runtime_finalization_reason(self) -> None:
        round_id = "RND0001"
        snapshot = {
            "nodes": [
                {"kind": "analysis", "created_in_round": round_id, "assigned_round": round_id}
                for _ in range(200)
            ],
            "rounds": {round_id: {}},
        }
        control = {"active_round_id": round_id}
        allowed, reason = RUNTIME._finalize_allowed(Path("."), control, snapshot)
        self.assertTrue(allowed)
        self.assertEqual("analysis_node_budget_exhausted", reason)

    def test_interpretation_retry_exhaustion_is_a_human_stop(self) -> None:
        control = {
            "active_round_id": "RND0001",
            "round_state": "FINALIZING",
            "blocker": {"code": "INTERPRETATION_RETRY_EXHAUSTED", "node_id": "N000001"},
            "lease": {},
            "closure": {"interpretation_ready": False, "audit_ready": False},
        }
        snapshot = {"nodes": [], "rounds": {"RND0001": {"state": "FINALIZING"}}, "plans": {}}
        action = RUNTIME._required_action(Path("."), control, snapshot)
        self.assertEqual("INTERPRETATION_BLOCKED", action["code"])

    @unittest.skip("Adaptive command recovery was removed in 0.1.6")
    def test_adaptive_recovery_rejects_scientific_parameter_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "runtime" / "scratch" / "RND0001" / "N000001" / "ATT0002"
            recovery = scratch / "recovery"
            recovery.mkdir(parents=True)
            prior = root / "runtime" / "scratch" / "RND0001" / "N000001" / "ATT0001" / "failure_packet.json"
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps({"recoverable": True, "classification": "argument_contract_mismatch"}), encoding="utf-8")
            base = [RUNTIME.RUNTIME_PYTHON_TOKEN, "skill-launch.py", "--node-id", "N000001", "--metric", "euclidean", "--input", "old.csv"]
            changed = [RUNTIME.RUNTIME_PYTHON_TOKEN, "skill-launch.py", "--node-id", "N000001", "--metric", "manhattan", "--input", "old.csv"]
            command_path = recovery / "command.json"
            command_path.write_text(json.dumps({"node_id": "N000001", "command_argv": changed}), encoding="utf-8")
            manifest = {
                "schema_version": "1.0.0", "node_id": "N000001", "attempt_id": "ATT0002",
                "node_signature": "a" * 64, "failure_classification": "argument_contract_mismatch",
                "reason": "test", "changed_contract_fields": ["option_alias"],
                "scientific_invariants_unchanged": True, "command_hash": RUNTIME.value_hash(changed),
                "temporary_file_hashes": {}, "created_at": RUNTIME.utc_now(),
            }
            manifest_path = recovery / "recovery_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            packet = {"execution_contracts": [{
                "node_id": "N000001", "attempt_id": "ATT0002", "node_signature": "a" * 64,
                "scratch": str(scratch), "command_argv": base,
                "prior_failure_pointer": str(prior.relative_to(root)),
            }]}
            with self.assertRaises(PermissionError):
                RUNTIME._load_recovery_override(root, packet, str(command_path), str(manifest_path))


if __name__ == "__main__":
    unittest.main()
