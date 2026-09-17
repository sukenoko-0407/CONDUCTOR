from __future__ import annotations

import sys

import pytest

from conductor_stat_core import LogicalCallFailure, call_local_jsonl


def _request() -> dict:
    return {
        "schema_version": "0.2.1",
        "request_id": "LLMREQ_fixture",
        "task": "select_deep_dive",
        "finding_ids": ["F000001"],
        "allowed_templates": ["T05"],
        "evidence": [],
        "output_schema": {"type": "object"},
    }


def test_local_llm_retries_schema_failure_then_succeeds(tmp_path, project_root) -> None:
    script = tmp_path / "fixture provider.py"
    state = tmp_path / "attempt.txt"
    script.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "state = pathlib.Path(sys.argv[1])\n"
        "attempt = int(state.read_text() or '0') if state.exists() else 0\n"
        "state.write_text(str(attempt + 1))\n"
        "if attempt == 0:\n"
        "    print('{}')\n"
        "else:\n"
        "    print(json.dumps({'schema_version':'0.2.1','request_id':request['request_id'],'selections':[],'narrative':None,'citations':[]}))\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}" "{state}"'
    response, attempts = call_local_jsonl(
        command,
        _request(),
        timeout_seconds=5,
        schema_retries=1,
        response_schema=project_root / "CONDUCTOR_modules" / "schemas" / "llm_response.schema.json",
    )
    assert attempts == 2
    assert response["request_id"] == "LLMREQ_fixture"


def test_local_llm_reports_all_failed_attempts(tmp_path, project_root) -> None:
    script = tmp_path / "invalid_provider.py"
    script.write_text("print('{}')\n", encoding="utf-8")
    with pytest.raises(LogicalCallFailure) as captured:
        call_local_jsonl(
            f'"{sys.executable}" "{script}"',
            _request(),
            timeout_seconds=5,
            schema_retries=2,
            response_schema=project_root / "CONDUCTOR_modules" / "schemas" / "llm_response.schema.json",
        )
    assert captured.value.attempts == 3
    assert len(captured.value.errors) == 3
