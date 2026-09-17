"""Single-writer DAG coordinator for CONDUCTOR 0.2.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conductor_stat_core import atomic_write_json, file_sha256, stable_id, validate_instance

from .state import RuntimeStateStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    def __init__(self, plan: PipelinePlan, state: RuntimeStateStore, run_directory: Path, schema_directory: Path):
        self.plan = plan
        self.state = state
        self.run_directory = run_directory.resolve()
        self.schema_directory = schema_directory.resolve()
        self.by_id = {node.node_id: node for node in plan.nodes}
        self.events = self.run_directory / "events"
        self.attempts = self.run_directory / "attempts"
        self.events.mkdir(parents=True, exist_ok=True)
        self.attempts.mkdir(parents=True, exist_ok=True)

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

    def _resolve_request(self, node: NodePlan, attempt: dict[str, Any], attempt_directory: Path) -> Path:
        request = json.loads(node.request_template.read_text(encoding="utf-8"))
        request["identity"].update({
            "run_id": self.plan.run_id, "phase_id": node.phase_id, "node_id": node.node_id,
            "attempt_id": attempt["attempt_id"], "skill_name": node.skill_name,
        })
        resolved = []
        for item in request.get("inputs", []):
            source = str(item["path"])
            if source.startswith("node://"):
                dependency_id, role = source.removeprefix("node://").split("/", 1)
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
            else:
                artifact_path = Path(source).resolve()
                resolved.append({**item, "path": str(artifact_path), "sha256": file_sha256(artifact_path)})
        request["inputs"] = resolved
        request_path = attempt_directory / "execution_request.json"
        atomic_write_json(request_path, request)
        validate_instance(request, self.schema_directory / "execution_request.schema.json")
        return request_path

    def _event(self, node: NodePlan, attempt: dict[str, Any], event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "schema_version": "0.2.1",
            "event_id": stable_id("EVENT", {"node": node.node_id, "attempt": attempt["attempt_id"], "type": event_type}),
            "run_id": self.plan.run_id, "node_id": node.node_id, "attempt_id": attempt["attempt_id"],
            "lease_token": attempt["lease_token"], "event_type": event_type, "occurred_at": _utc_now(), "payload": payload,
        }
        validate_instance(event, self.schema_directory / "execution_event.schema.json")
        event_filename = str(event["event_id"]).replace("|", "_").replace(":", "_") + ".json"
        atomic_write_json(self.events / event_filename, event)
        self.state.apply_event(event)
        return event

    def execute_node(self, node: NodePlan, *, lease_seconds: int = 3600, workers: int = 0) -> None:
        attempt = self.state.lease(node.node_id, seconds=lease_seconds)
        attempt_directory = self.attempts / node.node_id / attempt["attempt_id"]
        attempt_directory.mkdir(parents=True, exist_ok=False)
        self._event(node, attempt, "leased", {})
        self._event(node, attempt, "started", {})
        try:
            request_path = self._resolve_request(node, attempt, attempt_directory)
            output = node.output_directory / attempt["attempt_id"]
            completed = subprocess.run(
                [sys.executable, str(node.launch_path), "--request", str(request_path), "--output-dir", str(output), "--workers", str(workers)],
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            (attempt_directory / "stdout.txt").write_text(completed.stdout, encoding="utf-8", newline="\n")
            (attempt_directory / "stderr.txt").write_text(completed.stderr, encoding="utf-8", newline="\n")
            manifest_path = output / "artifact_manifest.json"
            if completed.returncode == 0 and manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                status = str(manifest["status"])
                if status in {"succeeded", "needs_design_review"}:
                    self._event(node, attempt, status, {"manifest_path": str(manifest_path), "returncode": completed.returncode})
                    return
            reason = f"worker exit {completed.returncode}; manifest_exists={manifest_path.is_file()}"
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
        return {
            "schema_version": "0.2.1", "run_id": self.plan.run_id, "status": status,
            "nodes": [{"node_id": row["node_id"], "phase_id": row["phase_id"], "skill_name": row["skill_name"], "state": row["state"], "attempt_id": row["attempt_id"], "manifest_path": row["manifest_path"]} for row in final],
        }
