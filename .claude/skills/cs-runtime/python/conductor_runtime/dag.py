"""Single-writer DAG coordinator for CONDUCTOR 0.2.1."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conductor_stat_core import atomic_write_json, file_sha256, stable_id, validate_instance

from .state import RuntimeStateStore


PROJECT_ROOT = Path(__file__).resolve().parents[5]
TOOLS_DIRECTORY = PROJECT_ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIRECTORY))

from work_contract import WorkEstimate  # noqa: E402

CANONICAL_DESCRIPTION_NODE = (
    PROJECT_ROOT / "CONDUCTOR_modules" / "tools" / "description_node.py"
).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stall_threshold_seconds(
    observed_interval: float, settings: dict[str, float]
) -> float:
    return min(
        settings["stall_max_seconds"],
        max(
            settings["stall_min_seconds"],
            settings["stall_multiplier"] * observed_interval,
        ),
    )


@dataclass(frozen=True)
class NodePlan:
    node_id: str
    phase_id: str
    skill_name: str
    dependencies: tuple[str, ...]
    request_template: Path
    launch_path: Path
    output_directory: Path


@dataclass(frozen=True)
class PipelinePlan:
    run_id: str
    code_version: str
    nodes: tuple[NodePlan, ...]

    @classmethod
    def load(cls, path: Path) -> "PipelinePlan":
        payload = json.loads(path.resolve().read_text(encoding="utf-8"))
        required = {"run_id", "code_version", "nodes"}
        if required - set(payload):
            raise ValueError(f"Pipeline plan is missing fields: {sorted(required-set(payload))}")
        nodes: list[NodePlan] = []
        identifiers: set[str] = set()
        for raw in payload["nodes"]:
            node = NodePlan(
                str(raw["node_id"]), str(raw["phase_id"]), str(raw["skill_name"]),
                tuple(str(value) for value in raw.get("dependencies", [])),
                Path(raw["request_template"]).resolve(), Path(raw["launch_path"]).resolve(), Path(raw["output_directory"]).resolve(),
            )
            if node.node_id in identifiers:
                raise ValueError(f"Duplicate node_id: {node.node_id}")
            if not node.request_template.is_file() or not node.launch_path.is_file():
                raise FileNotFoundError(f"Node files are missing: {node.node_id}")
            request_template = json.loads(
                node.request_template.read_text(encoding="utf-8")
            )
            operation = (request_template.get("parameters") or {}).get("operation")
            if (
                operation == "descriptions"
                and node.launch_path != CANONICAL_DESCRIPTION_NODE
            ):
                raise ValueError(
                    "Phase 1 Description nodes must use the tracked canonical "
                    f"launch_path {CANONICAL_DESCRIPTION_NODE}: {node.node_id}"
                )
            identifiers.add(node.node_id)
            nodes.append(node)
        for node in nodes:
            unknown = set(node.dependencies) - identifiers
            if unknown:
                raise ValueError(f"Node {node.node_id} has unknown dependencies: {sorted(unknown)}")
        _assert_acyclic(nodes)
        return cls(str(payload["run_id"]), str(payload["code_version"]), tuple(sorted(nodes, key=lambda item: (item.phase_id, item.node_id))))


def _assert_acyclic(nodes: list[NodePlan]) -> None:
    dependencies = {node.node_id: set(node.dependencies) for node in nodes}
    remaining = set(dependencies)
    while remaining:
        ready = {node for node in remaining if not dependencies[node].intersection(remaining)}
        if not ready:
            raise ValueError(f"Pipeline plan contains a dependency cycle: {sorted(remaining)}")
        remaining -= ready


class PipelineCoordinator:
    LENS_SKILLS = {
        "cs-lens-l1b",
        "cs-lens-l2",
        "cs-lens-l4",
        "cs-lens-l5",
        "cs-lens-l7",
    }

    def __init__(self, plan: PipelinePlan, state: RuntimeStateStore, run_directory: Path, schema_directory: Path, config: dict[str, Any] | None = None):
        self.plan = plan
        self.state = state
        self.run_directory = run_directory.resolve()
        self.schema_directory = schema_directory.resolve()
        self.config = config or {}
        self.by_id = {node.node_id: node for node in plan.nodes}
        self.events = self.run_directory / "events"
        self.attempts = self.run_directory / "attempts"
        self.events.mkdir(parents=True, exist_ok=True)
        self.attempts.mkdir(parents=True, exist_ok=True)
        self._event_sequences: dict[tuple[str, str, str], int] = {}
        self._run_started_at = time.monotonic()
        self._admitted_estimated_seconds = 0.0

    def register(self) -> None:
        for node in self.plan.nodes:
            request = json.loads(node.request_template.read_text(encoding="utf-8"))
            input_hashes = []
            for item in request.get("inputs", []):
                digest = str(item.get("sha256", ""))
                if len(digest) != 64:
                    digest = hashlib.sha256(str(item.get("path", "")).encode()).hexdigest()
                input_hashes.append(digest)
            config_path = Path(request["config_path"]).resolve()
            self.state.register_node(
                node_id=node.node_id, run_id=self.plan.run_id, phase_id=node.phase_id,
                skill_name=node.skill_name, input_hashes=input_hashes,
                config_hash=file_sha256(config_path), code_version=self.plan.code_version,
            )
        for node in self.plan.nodes:
            self.state.register_dependencies(node.node_id, list(node.dependencies))

    def _resolve_request(
        self,
        node: NodePlan,
        attempt: dict[str, Any],
        attempt_directory: Path,
        available_cpu_cores: int,
    ) -> Path:
        request = json.loads(node.request_template.read_text(encoding="utf-8"))
        request["identity"].update({
            "run_id": self.plan.run_id, "phase_id": node.phase_id, "node_id": node.node_id,
            "attempt_id": attempt["attempt_id"], "skill_name": node.skill_name,
        })
        request["resources"]["workers"] = available_cpu_cores
        resolved = []
        for item in request.get("inputs", []):
            source = str(item["path"])
            if source.startswith("node://"):
                dependency_id, role = source.removeprefix("node://").split("/", 1)
                if dependency_id not in node.dependencies:
                    raise ValueError(
                        f"Artifact reference is not a declared dependency: {source}"
                    )
                parent = self.state.get_node(dependency_id)
                if parent["state"] != "succeeded" or not parent["manifest_path"]:
                    raise ValueError(f"Dependency artifact is unavailable: {source}")
                manifest_path = Path(parent["manifest_path"])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                matches = [artifact for artifact in manifest["artifacts"] if artifact["role"] == role]
                if len(matches) != 1:
                    raise ValueError(f"Dependency must expose one role {role}: {dependency_id}")
                artifact = matches[0]
                artifact_path = (manifest_path.parent / artifact["path"]).resolve()
                resolved.append({"role": item["role"], "path": str(artifact_path), "sha256": artifact["sha256"], "producer_manifest": str(manifest_path)})
            elif source.startswith("manifest://"):
                dependency_id = source.removeprefix("manifest://")
                if not dependency_id or "/" in dependency_id:
                    raise ValueError(f"Invalid manifest reference: {source}")
                if dependency_id not in node.dependencies:
                    raise ValueError(
                        f"Manifest reference is not a declared dependency: {source}"
                    )
                parent = self.state.get_node(dependency_id)
                if parent["state"] != "succeeded" or not parent["manifest_path"]:
                    raise ValueError(f"Dependency manifest is unavailable: {source}")
                manifest_path = Path(parent["manifest_path"]).resolve()
                if not manifest_path.is_file():
                    raise FileNotFoundError(
                        f"Dependency manifest path is missing: {manifest_path}"
                    )
                resolved.append({
                    "role": item["role"],
                    "path": str(manifest_path),
                    "sha256": file_sha256(manifest_path),
                    "producer_manifest": str(manifest_path),
                })
            else:
                artifact_path = Path(source).resolve()
                resolved.append({**item, "path": str(artifact_path), "sha256": file_sha256(artifact_path)})
        request["inputs"] = resolved
        request_path = attempt_directory / "execution_request.json"
        atomic_write_json(request_path, request)
        validate_instance(request, self.schema_directory / "execution_request.schema.json")
        return request_path

    def _event(self, node: NodePlan, attempt: dict[str, Any], event_type: str, payload: dict[str, Any], *, sequence: int | None = None) -> dict[str, Any]:
        sequence_key = (node.node_id, str(attempt["attempt_id"]), event_type)
        if sequence is None:
            sequence = self._event_sequences.get(sequence_key, 0)
            self._event_sequences[sequence_key] = sequence + 1
        event = {
            "schema_version": "0.2.1",
            "event_id": stable_id("EVENT", {"node": node.node_id, "attempt": attempt["attempt_id"], "type": event_type, "sequence": sequence}),
            "run_id": self.plan.run_id, "node_id": node.node_id, "attempt_id": attempt["attempt_id"],
            "lease_token": attempt["lease_token"], "event_type": event_type, "occurred_at": _utc_now(), "payload": payload,
        }
        validate_instance(event, self.schema_directory / "execution_event.schema.json")
        event_filename = str(event["event_id"]).replace("|", "_").replace(":", "_") + ".json"
        atomic_write_json(self.events / event_filename, event)
        self.state.apply_event(event)
        return event

    def _runtime_settings(self) -> tuple[dict[str, float], dict[str, float]]:
        runtime = self.config.get("runtime") or {}
        configured_budgets = runtime.get("budgets") or {}
        configured_progress = runtime.get("progress") or {}
        budgets = {
            "node_wall_seconds": float(configured_budgets.get("node_wall_seconds", 3600)),
            "run_wall_seconds": float(configured_budgets.get("run_wall_seconds", 21600)),
            "peak_memory_bytes": float(configured_budgets.get("peak_memory_bytes", 64 * 1024**3)),
            "family_size": float(configured_budgets.get("family_size", 500)),
        }
        progress = {
            "min_seconds": float(configured_progress.get("min_seconds", 5)),
            "min_fraction": float(configured_progress.get("min_fraction", 0.01)),
            "stall_multiplier": float(configured_progress.get("stall_multiplier", 20)),
            "stall_min_seconds": float(configured_progress.get("stall_min_seconds", 60)),
            "stall_max_seconds": float(configured_progress.get("stall_max_seconds", 600)),
        }
        if any(value <= 0 for value in budgets.values()):
            raise ValueError("Runtime budgets must be positive")
        if progress["min_seconds"] <= 0 or not 0 < progress["min_fraction"] <= 1:
            raise ValueError("Runtime progress settings are invalid")
        return budgets, progress

    @staticmethod
    def _progress_granularity(request: dict[str, Any]) -> str:
        operation = str((request.get("parameters") or {}).get("operation", ""))
        return "node" if operation in {"l2b", "l7"} else "loop"

    def _estimate_node_work(
        self,
        node: NodePlan,
        request_path: Path,
        attempt_directory: Path,
        output: Path,
        environment: dict[str, str],
        workers: int,
    ) -> WorkEstimate:
        command = [
            sys.executable,
            str(node.launch_path),
            "--request",
            str(request_path),
            "--output-dir",
            str(output),
            "--workers",
            str(workers),
            "--estimate-work",
        ]
        completed = subprocess.run(
            command,
            env=environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        (attempt_directory / "estimate_stdout.txt").write_text(
            completed.stdout, encoding="utf-8", newline="\n"
        )
        (attempt_directory / "estimate_stderr.txt").write_text(
            completed.stderr, encoding="utf-8", newline="\n"
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"work estimate exited {completed.returncode}: {completed.stderr[-2000:]}"
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ValueError(
                "--estimate-work must write exactly one non-empty JSON line to stdout"
            )
        payload = json.loads(lines[0])
        if not isinstance(payload, dict):
            raise ValueError("--estimate-work response must be a JSON object")
        estimate = WorkEstimate.from_dict(payload)
        atomic_write_json(attempt_directory / "work_estimate.json", estimate.to_dict())
        return estimate

    def _work_guard(
        self, node: NodePlan, estimate: WorkEstimate
    ) -> tuple[str | None, str]:
        budgets, _ = self._runtime_settings()
        family_gate = "exempt_parametric" if node.skill_name == "cs-lens-l4" else "applied"
        if family_gate == "applied" and estimate.family_size > budgets["family_size"]:
            return (
                f"family_size {estimate.family_size}>{int(budgets['family_size'])}",
                family_gate,
            )
        if estimate.peak_memory_bytes > budgets["peak_memory_bytes"]:
            return (
                f"peak_memory_bytes {estimate.peak_memory_bytes}>{int(budgets['peak_memory_bytes'])}",
                family_gate,
            )
        if estimate.estimated_seconds > budgets["node_wall_seconds"]:
            return (
                f"estimated_seconds {estimate.estimated_seconds:.6g}>{budgets['node_wall_seconds']:.6g}",
                family_gate,
            )
        elapsed_run_seconds = time.monotonic() - self._run_started_at
        projected_run_seconds = max(
            elapsed_run_seconds, self._admitted_estimated_seconds
        ) + estimate.estimated_seconds
        if projected_run_seconds > budgets["run_wall_seconds"]:
            return (
                f"projected_run_seconds {projected_run_seconds:.6g}>{budgets['run_wall_seconds']:.6g}",
                family_gate,
            )
        return None, family_gate

    def _write_guard_manifest(
        self,
        node: NodePlan,
        attempt: dict[str, Any],
        request: dict[str, Any],
        output: Path,
        estimate: WorkEstimate,
        reason: str,
        family_gate: str,
    ) -> Path:
        output.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": "0.2.1",
            "producer": {
                key: request["identity"][key]
                for key in ("run_id", "node_id", "attempt_id", "skill_name")
            },
            "status": "needs_design_review",
            "config_sha256": file_sha256(Path(request["config_path"])),
            "input_artifacts": [
                {"role": item["role"], "path": item["path"], "sha256": item["sha256"]}
                for item in request.get("inputs", [])
            ],
            "artifacts": [],
            "metrics": {
                "work_estimate": estimate.to_dict(),
                "family_gate": family_gate,
                "guard_decision": "needs_design_review",
            },
            "warnings": [f"R1 work guard stopped the node: {reason}"],
            "created_at": _utc_now(),
        }
        validate_instance(manifest, self.schema_directory / "artifact_manifest.schema.json")
        manifest_path = output / "artifact_manifest.json"
        atomic_write_json(manifest_path, manifest)
        return manifest_path

    @staticmethod
    def _drain_stream(stream: Any, destination: Any) -> None:
        try:
            for chunk in iter(lambda: stream.read(8192), ""):
                destination.write(chunk)
                destination.flush()
        finally:
            stream.close()

    def _run_monitored(
        self,
        node: NodePlan,
        attempt: dict[str, Any],
        command: list[str],
        environment: dict[str, str],
        attempt_directory: Path,
        progress_path: Path,
        granularity: str,
    ) -> tuple[int, float, bool]:
        _, settings = self._runtime_settings()
        stdout_file = (attempt_directory / "stdout.txt").open(
            "w", encoding="utf-8", newline="\n"
        )
        stderr_file = (attempt_directory / "stderr.txt").open(
            "w", encoding="utf-8", newline="\n"
        )
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            env=environment,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(
                target=self._drain_stream,
                args=(process.stdout, stdout_file),
                daemon=True,
            ),
            threading.Thread(
                target=self._drain_stream,
                args=(process.stderr, stderr_file),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        last_mtime_ns: int | None = None
        last_progress_at = started
        previous_progress_at: float | None = None
        observed_intervals: list[float] = []
        last_node_heartbeat = started
        stalled = False
        try:
            while process.poll() is None:
                now = time.monotonic()
                if granularity == "loop" and progress_path.is_file():
                    stat = progress_path.stat()
                    if last_mtime_ns != stat.st_mtime_ns:
                        progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
                        required = {"completed_units", "total_units", "elapsed_seconds"}
                        if set(progress_payload) != required:
                            raise ValueError("Invalid progress side-channel fields")
                        completed_units = int(progress_payload["completed_units"])
                        total_units = int(progress_payload["total_units"])
                        elapsed_seconds = float(progress_payload["elapsed_seconds"])
                        if completed_units < 0 or total_units < 0 or completed_units > total_units or elapsed_seconds < 0:
                            raise ValueError("Invalid progress side-channel values")
                        if previous_progress_at is not None:
                            observed_intervals.append(now - previous_progress_at)
                        previous_progress_at = now
                        last_progress_at = now
                        last_mtime_ns = stat.st_mtime_ns
                        payload = {
                            "progress_granularity": "loop",
                            **progress_payload,
                            "stalled": False,
                        }
                        self._event(node, attempt, "heartbeat", payload)
                        stalled = False
                elif granularity == "node" and now - last_node_heartbeat >= settings["min_seconds"]:
                    self._event(
                        node,
                        attempt,
                        "heartbeat",
                        {
                            "progress_granularity": "node",
                            "elapsed_seconds": now - started,
                            "process_alive": True,
                            "stalled": False,
                        },
                    )
                    last_node_heartbeat = now
                if granularity == "loop":
                    observed = (
                        sum(observed_intervals[-5:]) / len(observed_intervals[-5:])
                        if observed_intervals
                        else settings["min_seconds"]
                    )
                    stall_after = _stall_threshold_seconds(observed, settings)
                    if not stalled and now - last_progress_at > stall_after:
                        self._event(
                            node,
                            attempt,
                            "heartbeat",
                            {
                                "progress_granularity": "loop",
                                "elapsed_seconds": now - started,
                                "stalled": True,
                                "stall_threshold_seconds": stall_after,
                            },
                        )
                        stalled = True
                time.sleep(min(1.0, max(0.1, settings["min_seconds"] / 2)))
            returncode = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for thread in threads:
                thread.join(timeout=30)
            stdout_file.close()
            stderr_file.close()
        elapsed = time.monotonic() - started
        final_progress: dict[str, Any] = {}
        if granularity == "loop" and progress_path.is_file():
            candidate = json.loads(progress_path.read_text(encoding="utf-8"))
            if set(candidate) == {"completed_units", "total_units", "elapsed_seconds"}:
                completed_units = int(candidate["completed_units"])
                total_units = int(candidate["total_units"])
                if 0 <= completed_units <= total_units and float(candidate["elapsed_seconds"]) >= 0:
                    final_progress = candidate
                    if completed_units == total_units:
                        stalled = False
        self._event(
            node,
            attempt,
            "heartbeat",
            {
                "progress_granularity": granularity,
                "elapsed_seconds": elapsed,
                **final_progress,
                "process_alive": False,
                "stalled": stalled,
            },
        )
        return returncode, elapsed, stalled

    @staticmethod
    def _augment_manifest(
        manifest_path: Path,
        estimate: WorkEstimate,
        *,
        actual_seconds: float,
        family_gate: str,
        progress_granularity: str,
        stalled: bool,
    ) -> dict[str, Any]:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metrics = manifest.setdefault("metrics", {})
        metrics["work_estimate"] = estimate.to_dict()
        metrics["actual_wall_seconds"] = actual_seconds
        metrics["progress_granularity"] = progress_granularity
        metrics["family_gate"] = family_gate
        ratio = estimate.estimated_seconds / actual_seconds if actual_seconds > 0 else None
        metrics["estimate_actual_ratio"] = ratio
        warnings = manifest.setdefault("warnings", [])
        if ratio is not None and ratio >= 3:
            warnings.append(f"work estimate/actual ratio is {ratio:.3f} (>=3)")
        if stalled:
            warnings.append("Runtime observed a stalled progress interval; process was not killed")
        atomic_write_json(manifest_path, manifest)
        return manifest

    def execute_node(self, node: NodePlan, *, lease_seconds: int = 3600, workers: int = 0) -> None:
        attempt = self.state.lease(node.node_id, seconds=lease_seconds)
        attempt_directory = self.attempts / node.node_id / attempt["attempt_id"]
        attempt_directory.mkdir(parents=True, exist_ok=False)
        self._event(node, attempt, "leased", {})
        self._event(node, attempt, "started", {})
        try:
            if workers < 0:
                raise ValueError("workers must be >= 0")
            local_capacity = (
                len(os.sched_getaffinity(0))
                if hasattr(os, "sched_getaffinity")
                else (os.cpu_count() or 1)
            )
            if workers > local_capacity:
                raise ValueError(
                    f"Explicit workers={workers} exceed local CPU affinity={local_capacity}"
                )
            available_cpu_cores = (
                workers if workers > 0 else max(1, local_capacity - 1)
            )
            request_path = self._resolve_request(
                node, attempt, attempt_directory, available_cpu_cores
            )
            request = json.loads(request_path.read_text(encoding="utf-8"))
            output = node.output_directory / attempt["attempt_id"]
            environment = os.environ.copy()
            environment["CONDUCTOR_AVAILABLE_CPU_CORES"] = str(available_cpu_cores)
            environment["CONDUCTOR_NODE_CPU_CORES"] = str(available_cpu_cores)
            estimate: WorkEstimate | None = None
            family_gate = "not_applicable"
            if node.skill_name in self.LENS_SKILLS:
                estimate = self._estimate_node_work(
                    node,
                    request_path,
                    attempt_directory,
                    output,
                    environment,
                    available_cpu_cores,
                )
                self._event(
                    node,
                    attempt,
                    "heartbeat",
                    {"kind": "work_estimate", "work_estimate": estimate.to_dict()},
                )
                guard_reason, family_gate = self._work_guard(node, estimate)
                if guard_reason is not None:
                    manifest_path = self._write_guard_manifest(
                        node,
                        attempt,
                        request,
                        output,
                        estimate,
                        guard_reason,
                        family_gate,
                    )
                    self._event(
                        node,
                        attempt,
                        "needs_design_review",
                        {
                            "manifest_path": str(manifest_path),
                            "guard_reason": guard_reason,
                        },
                    )
                    return
            progress_path = attempt_directory / "progress.json"
            environment["CONDUCTOR_PROGRESS_PATH"] = str(progress_path)
            granularity = (
                self._progress_granularity(request)
                if node.skill_name in self.LENS_SKILLS
                else "node"
            )
            command = [
                sys.executable,
                str(node.launch_path),
                "--request",
                str(request_path),
                "--output-dir",
                str(output),
                "--workers",
                str(available_cpu_cores),
            ]
            returncode, actual_seconds, stalled = self._run_monitored(
                node,
                attempt,
                command,
                environment,
                attempt_directory,
                progress_path,
                granularity,
            )
            manifest_path = output / "artifact_manifest.json"
            if returncode == 0 and manifest_path.is_file():
                if estimate is not None:
                    manifest = self._augment_manifest(
                        manifest_path,
                        estimate,
                        actual_seconds=actual_seconds,
                        family_gate=family_gate,
                        progress_granularity=granularity,
                        stalled=stalled,
                    )
                else:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                status = str(manifest["status"])
                if status in {"succeeded", "needs_design_review"}:
                    if estimate is not None:
                        self._admitted_estimated_seconds += estimate.estimated_seconds
                    self._event(node, attempt, status, {"manifest_path": str(manifest_path), "returncode": returncode})
                    return
            reason = f"worker exit {returncode}; manifest_exists={manifest_path.is_file()}"
        except Exception as exc:
            reason = str(exc)
        prior = self.state.event_count(node.node_id, ("retryable",))
        self._event(node, attempt, "retryable" if prior < 1 else "failed", {"error": reason})

    def run(self, *, lease_seconds: int = 3600, workers: int = 0) -> dict[str, Any]:
        self.register()
        self.state.expire_leases()
        while True:
            nodes = self.state.list_nodes(self.plan.run_id)
            states = {node["node_id"]: node["state"] for node in nodes}
            if any(value == "failed" for value in states.values()): status = "failed"; break
            if any(value == "needs_design_review" for value in states.values()): status = "needs_design_review"; break
            if states and all(value == "succeeded" for value in states.values()): status = "succeeded"; break
            ready = self.state.ready_nodes(self.plan.run_id)
            if not ready: status = "failed"; break
            for row in ready:
                self.execute_node(self.by_id[row["node_id"]], lease_seconds=lease_seconds, workers=workers)
        final = self.state.list_nodes(self.plan.run_id)
        summary_nodes = []
        for row in final:
            heartbeat = self.state.latest_event_payload(row["node_id"], "heartbeat")
            latest_progress = None
            if heartbeat is not None and "progress_granularity" in heartbeat:
                latest_progress = heartbeat
            summary_nodes.append({
                "node_id": row["node_id"],
                "phase_id": row["phase_id"],
                "skill_name": row["skill_name"],
                "state": row["state"],
                "attempt_id": row["attempt_id"],
                "manifest_path": row["manifest_path"],
                "latest_progress": latest_progress,
                "stalled": bool((heartbeat or {}).get("stalled", False)),
            })
        return {
            "schema_version": "0.2.1", "run_id": self.plan.run_id, "status": status,
            "nodes": summary_nodes,
        }
