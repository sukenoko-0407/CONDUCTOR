from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from mmp_outputs import render_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-render an existing A014 result without changing scientific artifacts")
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.result_dir).resolve()
    result = json.loads((root / "mmp_result.json").read_text(encoding="utf-8"))
    role = result["role"]
    table_names = {
        "global-build": ["transform_summary.csv", "core_summary.csv", "transform_core_summary.csv"],
        "local-screen": ["mmp_local_screening.csv"],
        "local-detail": ["mmp_local_detail_pairs.csv", "mmp_global_vs_local.csv"],
    }[role]
    cards = [json.loads(line) for line in (root / "mmp_reference_cards.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    tables = [(name.removesuffix(".csv").replace("_", " "), pd.read_csv(root / name)) for name in table_names if (root / name).is_file()]
    report = render_report(
        role=role, scope_label=result.get("cluster_id") or result["scope"], endpoint=result.get("endpoint", "unknown"),
        higher_is_better=bool(result.get("higher_is_better", True)), core_policy=result["core_policy"],
        counts=result["counts"], cards=cards, tables=tables,
        artifact_names=sorted(result.get("artifacts", {}).values()),
        limitations=["再描画では科学計算結果を変更していません。"],
    )
    destination = Path(args.output).resolve() if args.output else root / "operator_report.html"
    destination.write_text(report, encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
