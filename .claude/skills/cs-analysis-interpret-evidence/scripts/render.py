from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


RUN_PATH = Path(__file__).resolve().with_name("run.py")
SPEC = importlib.util.spec_from_file_location("interpretation_runtime", RUN_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load interpretation runtime: {RUN_PATH}")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate interpretation JSON and regenerate Markdown/HTML.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--markdown")
    parser.add_argument("--html")
    parser.add_argument("--exploration-plan", help="Optional exploration_plan.json to validate with the dedicated schema.")
    args = parser.parse_args()
    source = Path(args.input)
    value = json.loads(source.read_text(encoding="utf-8"))
    RUNTIME.validate(value, "interpretation.schema.json")
    if args.exploration_plan:
        plan = json.loads(Path(args.exploration_plan).read_text(encoding="utf-8"))
        RUNTIME.validate(plan, "interpretation_exploration_plan.schema.json")
    markdown_path = Path(args.markdown) if args.markdown else source.with_suffix(".md")
    html_path = Path(args.html) if args.html else source.with_suffix(".html")
    markdown_path.write_text(RUNTIME.markdown_report(value), encoding="utf-8")
    html_path.write_text(RUNTIME.html_report(value), encoding="utf-8")
    print(markdown_path)
    print(html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
