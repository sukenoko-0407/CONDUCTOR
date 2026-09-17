from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROVIDER = ROOT / "CONDUCTOR_modules" / "local_llm_provider" / "provider.py"


class _Handler(BaseHTTPRequestHandler):
    payloads: list[dict] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.payloads.append(payload)
        request = json.loads(payload["messages"][1]["content"].split("入力JSON:\n", 1)[1])
        response = {
            "schema_version": "0.2.1",
            "request_id": request["request_id"],
            "selections": [],
            "narrative": None,
            "citations": [],
        }
        body = json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalProviderContractTest(unittest.TestCase):
    def test_three_tasks_against_openai_compatible_fixture(self) -> None:
        _Handler.payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config_path = Path(directory) / "provider_config.json"
                config_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "0.2.1",
                            "provider_version": "0.2.1.2",
                            "backend": "vllm",
                            "backend_version": "fixture-build",
                            "endpoint": f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                            "approved_host": "127.0.0.1",
                            "allow_plaintext_http": False,
                            "authentication": "none",
                            "api_key_env": None,
                            "health_endpoint": None,
                            "model": "fixture-model",
                            "model_revision": "fixture-revision",
                            "quantization": "fixture",
                            "prompt_version": "0.2.1",
                            "temperature": 0.7,
                            "top_p": 0.8,
                            "top_k": 20,
                            "min_p": 0.0,
                            "seed": 20260916,
                            "max_tokens": 128,
                            "request_timeout_seconds": 5,
                            "enable_thinking": False,
                        }
                    ),
                    encoding="utf-8",
                )
                for index, task in enumerate(
                    ("select_deep_dive", "summarize_deep_dive", "compose_component_narrative"), start=1
                ):
                    request = {
                        "schema_version": "0.2.1",
                        "request_id": f"LLMREQ-FIXTURE-{index}",
                        "task": task,
                        "finding_ids": ["F000001"],
                        "allowed_templates": ["T05"] if task == "select_deep_dive" else [],
                        "evidence": [],
                        "output_schema": {"type": "object"},
                    }
                    completed = subprocess.run(
                        [sys.executable, str(PROVIDER), "--config", str(config_path)],
                        input=json.dumps(request, ensure_ascii=False) + "\n",
                        text=True,
                        encoding="utf-8",
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    output_lines = [line for line in completed.stdout.splitlines() if line]
                    self.assertEqual(len(output_lines), 1)
                    self.assertEqual(json.loads(output_lines[0])["request_id"], request["request_id"])
                    metadata = json.loads(completed.stderr)
                    self.assertEqual(metadata["model"], "fixture-model")
            self.assertEqual(len(_Handler.payloads), 3)
            for payload in _Handler.payloads:
                self.assertEqual(payload["temperature"], 0.7)
                self.assertEqual(payload["top_p"], 0.8)
                self.assertEqual(payload["top_k"], 20)
                self.assertEqual(payload["min_p"], 0.0)
                self.assertEqual(payload["seed"], 20260916)
                self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
                self.assertEqual(payload["response_format"]["type"], "json_schema")
                generation_schema = payload["response_format"]["json_schema"]["schema"]
                self.assertNotIn("uniqueItems", generation_schema["properties"]["citations"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
