"""CONDUCTOR 0.2.1 JSONL bridge for an approved vLLM server.

The runtime starts this program once per logical call. It accepts exactly one
JSON object on stdin and emits exactly one schema-valid JSON object on stdout.
Diagnostics and immutable provider metadata are written to stderr. The vLLM
server may run on another machine; this process never executes analysis tools.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.2.1"
PROVIDER_VERSION = "0.2.1.2"
TASKS = {"select_deep_dive", "summarize_deep_dive", "compose_component_narrative"}
TEMPLATES = {f"T{number:02d}" for number in range(1, 11)}
REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "task",
    "finding_ids",
    "allowed_templates",
    "evidence",
    "output_schema",
}
RESPONSE_KEYS = {"schema_version", "request_id", "selections", "narrative", "citations"}
CONFIG_KEYS = {
    "schema_version",
    "provider_version",
    "backend",
    "backend_version",
    "endpoint",
    "approved_host",
    "allow_plaintext_http",
    "authentication",
    "api_key_env",
    "health_endpoint",
    "model",
    "model_revision",
    "quantization",
    "prompt_version",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "seed",
    "max_tokens",
    "request_timeout_seconds",
    "enable_thinking",
}
FINDING_ID = re.compile(r"^F[0-9]{6}$")
CITATION_MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")
ENVIRONMENT_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProviderError(RuntimeError):
    """Raised for a provider contract or vLLM API failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ProviderError(f"vLLM redirect is forbidden (HTTP {code})")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError(f"{label} must be a JSON object")
    return value


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(f"{name} must be a non-empty string")
    return value


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_endpoint(
    value: Any,
    name: str,
    approved_host: str,
    allow_plaintext_http: bool,
    *,
    expected_suffix: str | None = None,
) -> str:
    endpoint = _nonempty_string(value, name)
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ProviderError(f"{name} must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError(f"{name} must not contain credentials, query, or fragment")
    host = parsed.hostname
    if host is None or host.lower() != approved_host.lower():
        raise ProviderError(f"{name} hostname must exactly match approved_host")
    if parsed.scheme == "http" and not _is_loopback_host(host) and not allow_plaintext_http:
        raise ProviderError(f"{name} must use https for a non-loopback host")
    if expected_suffix is not None and not parsed.path.rstrip("/").endswith(expected_suffix):
        raise ProviderError(f"{name} path must end with {expected_suffix}")
    return endpoint


def _validate_config(config: dict[str, Any], prompts: dict[str, Any]) -> None:
    missing = CONFIG_KEYS - set(config)
    extra = set(config) - CONFIG_KEYS
    if missing or extra:
        raise ProviderError(f"provider config keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    if config["schema_version"] != SCHEMA_VERSION:
        raise ProviderError("provider config schema_version must be 0.2.1")
    if config["provider_version"] != PROVIDER_VERSION:
        raise ProviderError(f"provider_version must be {PROVIDER_VERSION}")
    if config["backend"] != "vllm":
        raise ProviderError("backend must be vllm")
    for name in ("backend_version", "model", "model_revision", "quantization"):
        value = _nonempty_string(config[name], name)
        if value.startswith("REPLACE_WITH_"):
            raise ProviderError(f"{name} still contains an example placeholder")

    approved_host = _nonempty_string(config["approved_host"], "approved_host")
    if "://" in approved_host or "/" in approved_host or ":" in approved_host:
        raise ProviderError("approved_host must be a hostname or IP address without scheme, port, or path")
    if not isinstance(config["allow_plaintext_http"], bool):
        raise ProviderError("allow_plaintext_http must be boolean")
    _validate_endpoint(
        config["endpoint"],
        "endpoint",
        approved_host,
        config["allow_plaintext_http"],
        expected_suffix="/v1/chat/completions",
    )
    if config["health_endpoint"] is not None:
        _validate_endpoint(
            config["health_endpoint"],
            "health_endpoint",
            approved_host,
            config["allow_plaintext_http"],
        )

    if config["authentication"] not in {"none", "bearer_env"}:
        raise ProviderError("authentication must be none or bearer_env")
    if config["authentication"] == "none":
        if config["api_key_env"] is not None:
            raise ProviderError("api_key_env must be null when authentication is none")
    elif not isinstance(config["api_key_env"], str) or ENVIRONMENT_VARIABLE.fullmatch(config["api_key_env"]) is None:
        raise ProviderError("api_key_env must name an environment variable")

    if config["prompt_version"] != prompts.get("prompt_version"):
        raise ProviderError("provider config prompt_version does not match prompts.json")
    temperature = config["temperature"]
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0.0 < float(temperature) <= 2.0:
        raise ProviderError("temperature must be greater than 0 and at most 2")
    top_p = config["top_p"]
    if isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not 0.0 < float(top_p) <= 1.0:
        raise ProviderError("top_p must be greater than 0 and at most 1")
    top_k = config["top_k"]
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
        raise ProviderError("top_k must be a non-negative integer")
    min_p = config["min_p"]
    if isinstance(min_p, bool) or not isinstance(min_p, (int, float)) or not 0.0 <= float(min_p) <= 1.0:
        raise ProviderError("min_p must be between 0 and 1")
    if isinstance(config["seed"], bool) or not isinstance(config["seed"], int) or config["seed"] < 0:
        raise ProviderError("seed must be a non-negative integer")
    for name in ("max_tokens", "request_timeout_seconds"):
        if isinstance(config[name], bool) or not isinstance(config[name], int) or config[name] <= 0:
            raise ProviderError(f"{name} must be a positive integer")
    if config["enable_thinking"] is not False:
        raise ProviderError("enable_thinking must be false for the CONDUCTOR provider")


def _unique_strings(value: Any, name: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum or any(not isinstance(item, str) for item in value):
        raise ProviderError(f"{name} must be a string array with at least {minimum} item(s)")
    if len(value) != len(set(value)):
        raise ProviderError(f"{name} must contain unique values")
    return value


def _validate_request(request: dict[str, Any]) -> None:
    if set(request) != REQUEST_KEYS:
        raise ProviderError("request fields do not match llm_request.schema.json")
    if request["schema_version"] != SCHEMA_VERSION:
        raise ProviderError("request schema_version must be 0.2.1")
    _nonempty_string(request["request_id"], "request_id")
    if request["task"] not in TASKS:
        raise ProviderError("request task is unsupported")
    finding_ids = _unique_strings(request["finding_ids"], "finding_ids", minimum=1)
    if any(FINDING_ID.fullmatch(item) is None for item in finding_ids):
        raise ProviderError("finding_ids contains an invalid Finding ID")
    allowed = _unique_strings(request["allowed_templates"], "allowed_templates")
    if any(item not in TEMPLATES for item in allowed):
        raise ProviderError("allowed_templates contains an unsupported template")
    if not isinstance(request["evidence"], list) or any(not isinstance(item, dict) for item in request["evidence"]):
        raise ProviderError("evidence must be an array of objects")
    if not isinstance(request["output_schema"], dict):
        raise ProviderError("output_schema must be an object")


def _validate_parameters(template_id: str, parameters: dict[str, Any]) -> None:
    keys = set(parameters)
    if template_id == "T01":
        if keys != {"axis_id", "level"} or not isinstance(parameters["axis_id"], str):
            raise ProviderError("T01 parameters must contain axis_id and level")
    elif template_id == "T02":
        if keys != {"axis_id"} or not isinstance(parameters["axis_id"], str):
            raise ProviderError("T02 parameters must contain string axis_id")
    elif template_id in {"T03", "T04"}:
        name = "context_ids" if template_id == "T03" else "target_ids"
        if keys != {name}:
            raise ProviderError(f"{template_id} parameters must contain {name}")
        values = _unique_strings(parameters[name], name, minimum=1)
        if len(values) > 3:
            raise ProviderError(f"{name} may contain at most three values")
    elif template_id == "T05":
        if keys not in (set(), {"iterations"}):
            raise ProviderError("T05 parameters may only contain iterations")
        if "iterations" in parameters and (isinstance(parameters["iterations"], bool) or not isinstance(parameters["iterations"], int) or parameters["iterations"] <= 0):
            raise ProviderError("T05 iterations must be a positive integer")
    elif template_id == "T06":
        if keys != {"context_id", "transformation_id"} or any(not isinstance(parameters[name], str) for name in keys):
            raise ProviderError("T06 parameters must contain string context_id and transformation_id")
    elif template_id == "T07":
        if keys != {"confounders"}:
            raise ProviderError("T07 parameters must contain confounders")
        _unique_strings(parameters["confounders"], "confounders", minimum=1)
    elif template_id == "T08":
        if keys != {"unit_type"} or not isinstance(parameters["unit_type"], str):
            raise ProviderError("T08 parameters must contain string unit_type")
    elif template_id == "T09":
        if keys not in ({"sample_n"}, {"sample_n", "iterations"}):
            raise ProviderError("T09 parameters must contain sample_n and optional iterations")
        if any(isinstance(parameters[name], bool) or not isinstance(parameters[name], int) or parameters[name] <= 0 for name in keys):
            raise ProviderError("T09 sample_n and iterations must be positive integers")
    elif template_id == "T10":
        if keys != {"counterexample_rule"} or not isinstance(parameters["counterexample_rule"], str):
            raise ProviderError("T10 parameters must contain string counterexample_rule")


def _citation_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "citation_id" and isinstance(child, str):
                found.add(child)
            found.update(_citation_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_citation_ids(child))
    return found


def _validate_response(response: dict[str, Any], request: dict[str, Any]) -> None:
    if set(response) != RESPONSE_KEYS:
        raise ProviderError("response fields do not match llm_response.schema.json")
    if response["schema_version"] != SCHEMA_VERSION or response["request_id"] != request["request_id"]:
        raise ProviderError("response schema_version or request_id does not match the request")
    selections = response["selections"]
    if not isinstance(selections, list) or len(selections) > 3:
        raise ProviderError("selections must be an array with at most three items")
    seen: set[str] = set()
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != {"template_id", "parameters"}:
            raise ProviderError("each selection must contain only template_id and parameters")
        template_id = selection["template_id"]
        parameters = selection["parameters"]
        if template_id not in request["allowed_templates"] or not isinstance(parameters, dict):
            raise ProviderError("selection is not allowed by the request")
        _validate_parameters(template_id, parameters)
        signature = json.dumps(selection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if signature in seen:
            raise ProviderError("duplicate selection")
        seen.add(signature)
    narrative = response["narrative"]
    if narrative is not None and not isinstance(narrative, str):
        raise ProviderError("narrative must be a string or null")
    citations = _unique_strings(response["citations"], "citations")
    if request["task"] == "select_deep_dive":
        if narrative is not None or citations:
            raise ProviderError("select_deep_dive must return null narrative and no citations")
    elif selections:
        raise ProviderError("narrative tasks must return no selections")
    if narrative is None:
        if citations:
            raise ProviderError("null narrative must not include citations")
    else:
        markers = CITATION_MARKER.findall(narrative)
        ordered_markers = list(dict.fromkeys(markers))
        if ordered_markers != citations:
            raise ProviderError("narrative markers and citations must match in first-use order")
        if not set(citations).issubset(_citation_ids(request["evidence"])):
            raise ProviderError("response cites an ID absent from evidence")


def _read_one_request() -> dict[str, Any]:
    try:
        text = sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderError("stdin is not valid UTF-8") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ProviderError(f"stdin must contain exactly one non-empty JSON line; received {len(lines)}")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"stdin is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("stdin JSON must be an object")
    return value


def _headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config["authentication"] == "bearer_env":
        environment_name = config["api_key_env"]
        secret = os.environ.get(environment_name, "")
        if not secret:
            raise ProviderError(f"required API credential environment variable is not set: {environment_name}")
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _post_json(endpoint: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = response.read(16 * 1024 * 1024 + 1)
    except ProviderError:
        raise
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise ProviderError(f"vLLM HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"cannot reach approved vLLM endpoint: {exc}") from exc
    if len(body) > 16 * 1024 * 1024:
        raise ProviderError("vLLM response exceeds 16 MiB")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"vLLM returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("vLLM response must be a JSON object")
    return value


def _model_content(server_response: dict[str, Any]) -> dict[str, Any]:
    try:
        content = server_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("vLLM response has no choices[0].message.content") from exc
    if isinstance(content, dict):
        value = content
    elif isinstance(content, str):
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"model content is not a bare JSON object: {exc}") from exc
    else:
        raise ProviderError("vLLM message content must be a string or JSON object")
    if not isinstance(value, dict):
        raise ProviderError("model content must decode to a JSON object")
    return value


def _prompt_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _vllm_grammar_schema(response_schema: dict[str, Any]) -> dict[str, Any]:
    """Return an equivalent generation schema without xgrammar-unsupported hints.

    vLLM's xgrammar backend rejects uniqueItems. The provider enforces citation
    uniqueness again after generation, so removing this generation-time hint
    does not weaken the accepted response contract.
    """

    schema = json.loads(json.dumps(response_schema))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("uniqueItems", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


def _metadata(config: dict[str, Any], config_path: Path, prompts_path: Path) -> dict[str, Any]:
    return {
        "event": "conductor_local_llm_provider",
        "schema_version": SCHEMA_VERSION,
        "provider_version": PROVIDER_VERSION,
        "backend": config["backend"],
        "backend_version": config["backend_version"],
        "endpoint": config["endpoint"],
        "authentication": config["authentication"],
        "model": config["model"],
        "model_revision": config["model_revision"],
        "quantization": config["quantization"],
        "prompt_version": config["prompt_version"],
        "prompt_sha256": _prompt_hash(prompts_path),
        "provider_config_sha256": _prompt_hash(config_path),
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "top_k": config["top_k"],
        "min_p": config["min_p"],
        "seed": config["seed"],
        "enable_thinking": config["enable_thinking"],
    }


def _check_health(config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    _headers(config)
    if config["health_endpoint"] is None:
        return {**metadata, "health": "not_configured"}
    request = urllib.request.Request(config["health_endpoint"], headers=_headers(config), method="GET")
    try:
        with _opener().open(request, timeout=min(config["request_timeout_seconds"], 30)) as response:
            response.read(1024 * 1024)
    except ProviderError:
        raise
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"vLLM health check returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"vLLM health check failed: {exc}") from exc
    return {**metadata, "health": "ok"}


def execute(config_path: Path, prompts_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config = _load_object(config_path, "provider config")
    prompts = _load_object(prompts_path, "prompt manifest")
    _validate_config(config, prompts)
    request = _read_one_request()
    _validate_request(request)
    task_prompt = prompts.get("tasks", {}).get(request["task"])
    if not isinstance(task_prompt, str) or not task_prompt:
        raise ProviderError("prompt manifest has no prompt for the requested task")
    response_schema = _load_object(
        Path(__file__).resolve().parents[1] / "schemas" / "llm_response.schema.json",
        "response schema",
    )
    user_content = task_prompt + "\n\n入力JSON:\n" + json.dumps(
        request,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ],
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "top_k": config["top_k"],
        "min_p": config["min_p"],
        "seed": config["seed"],
        "max_tokens": config["max_tokens"],
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": config["enable_thinking"]},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "conductor_llm_response",
                "strict": True,
                "schema": _vllm_grammar_schema(response_schema),
            },
        },
    }
    server_response = _post_json(
        config["endpoint"],
        payload,
        _headers(config),
        config["request_timeout_seconds"],
    )
    response = _model_content(server_response)
    _validate_response(response, request)
    return response, _metadata(config, config_path, prompts_path)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 vLLM JSONL provider")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--prompts", type=Path, default=Path(__file__).with_name("prompts.json"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and query the configured health endpoint, if any",
    )
    args = parser.parse_args(argv)
    config_path = args.config.expanduser().resolve()
    prompts_path = args.prompts.expanduser().resolve()
    try:
        if args.check:
            config = _load_object(config_path, "provider config")
            prompts = _load_object(prompts_path, "prompt manifest")
            _validate_config(config, prompts)
            result = _check_health(config, _metadata(config, config_path, prompts_path))
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
            return 0
        response, metadata = execute(config_path, prompts_path)
        print(json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":")), file=sys.stderr)
        print(json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 0
    except ProviderError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"unexpected provider error: {exc}"},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
