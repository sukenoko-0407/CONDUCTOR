"""Offline JSONL command provider with bounded logical-call retries."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .contracts import validate_instance


class LogicalCallFailure(RuntimeError):
    def __init__(self, message: str, *, attempts: int, errors: list[str]):
        super().__init__(message)
        self.attempts = attempts
        self.errors = tuple(errors)


def call_local_jsonl(
    command: str,
    request: dict[str, Any],
    *,
    timeout_seconds: int,
    schema_retries: int,
    response_schema: Path,
) -> tuple[dict[str, Any], int]:
    if not command or not str(command).strip():
        raise ValueError("llm.command is required for this phase")
    if timeout_seconds <= 0 or schema_retries < 0:
        raise ValueError("Invalid Local LLM timeout or retry count")
    argv = shlex.split(str(command), posix=os.name != "nt")
    if os.name == "nt":
        # shlex's non-POSIX mode preserves wrapping quotes, while subprocess
        # expects an argv sequence without those delimiters.
        argv = [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"} else item
            for item in argv
        ]
    if not argv:
        raise ValueError("llm.command resolved to an empty command")
    errors: list[str] = []
    for attempt in range(1, schema_retries + 2):
        try:
            completed = subprocess.run(
                argv,
                input=json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"provider exit {completed.returncode}: {completed.stderr.strip()[:500]}")
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if len(lines) != 1:
                raise ValueError(f"provider must emit exactly one JSON object, received {len(lines)} lines")
            response = json.loads(lines[0])
            validate_instance(response, response_schema)
            if response["request_id"] != request["request_id"]:
                raise ValueError("Local LLM response request_id mismatch")
            if completed.stderr:
                # Successful providers may emit immutable model/prompt metadata.
                # Preserve it in the enclosing Skill attempt log instead of
                # silently discarding the provider's stderr.
                print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
            return response, attempt
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
    raise LogicalCallFailure("Local LLM logical call failed after retries", attempts=schema_retries + 1, errors=errors)
