"""Narrow administrative recovery for one failed CONDUCTOR Runtime node."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PACKAGE = PROJECT_ROOT / ".claude" / "skills" / "cs-runtime" / "python"
if str(RUNTIME_PACKAGE) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PACKAGE))

from conductor_runtime import RuntimeStateStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or administratively requeue exactly one failed node"
    )
    parser.add_argument("--runtime-sqlite", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--expected-skill-name", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the requeue. Without this flag the command is read-only.",
    )
    args = parser.parse_args()
    runtime_path = Path(args.runtime_sqlite).resolve()
    if not runtime_path.is_file():
        raise FileNotFoundError(f"Runtime SQLite does not exist: {runtime_path}")
    store = RuntimeStateStore(runtime_path)
    node = store.get_node(args.node_id)
    if node["skill_name"] != args.expected_skill_name:
        raise ValueError(
            f"Expected skill {args.expected_skill_name!r}, found {node['skill_name']!r}"
        )
    if not args.apply:
        print(
            json.dumps(
                {"mode": "dry-run", "eligible": node["state"] == "failed", "node": node},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if node["state"] == "failed" else 3
    result = store.requeue_failed_node(
        args.node_id,
        expected_skill_name=args.expected_skill_name,
        operator=args.operator,
        reason=args.reason,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
