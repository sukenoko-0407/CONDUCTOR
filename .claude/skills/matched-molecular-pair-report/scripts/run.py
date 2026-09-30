from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _prepare_output(path: Path) -> Path:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise FileExistsError(f"Output directory must be new or empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _database_dataset(path: Path) -> tuple["pd.DataFrame", dict[str, Any]]:
    import pandas as pd
    if not path.is_file():
        raise FileNotFoundError(f"MMP database does not exist: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"MMP database integrity check failed: {integrity}")
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"metadata", "compounds", "pair_transformations", "fragmentations"}
        missing = sorted(required - tables)
        if missing:
            raise ValueError(f"Not a canonical MMP database; missing tables: {missing}")
        metadata = {
            key: json.loads(value)
            for key, value in connection.execute("SELECT key, value_json FROM metadata")
        }
        if metadata.get("schema_version") != "2.0.0" or not metadata.get("build_complete"):
            raise ValueError("Not a completed 0.1.11 canonical MMP database")
        compounds = pd.read_sql_query(
            "SELECT compound_id, smiles, endpoint FROM compounds ORDER BY compound_id",
            connection,
        )
    if compounds.empty:
        raise ValueError("MMP database has no compounds")
    compounds["compound_id"] = compounds["compound_id"].astype(str)
    return compounds, metadata


def _common_parameters(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "neutral_tolerance": 0.10,
        "cuts": 2,
        "radius_min": 0,
        "radius_max": 2,
        "max_compounds": 5000,
    }


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    input_path = _path(args.input)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input CSV does not exist: {input_path}")
    return {
        "dataset_path": str(input_path),
        "source_dataset_path": str(input_path),
        "columns": {
            "compound_id": args.id_column,
            "smiles": args.smiles_column,
            "endpoint": args.endpoint_column,
        },
        "higher_is_better": bool(args.higher_is_better),
        "workers": int(args.workers),
        "parameters": _common_parameters("database"),
    }


def _report_config(
    args: argparse.Namespace,
    database_path: Path,
    dataset_path: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    endpoint_column = str(metadata.get("endpoint_column", "endpoint"))
    parameters = _common_parameters("target")
    structural = metadata.get("structural_parameters") or {}
    radius = structural.get("radius") or [0, 2]
    parameters.update({
        "cut_smarts": str(metadata.get("cut_smarts", "default")),
        "cuts": int(metadata.get("num_cuts", 2)),
        "min_core_heavy_atoms": int(structural.get("min_core_heavy_atoms", 8)),
        "min_core_fraction": float(structural.get("min_core_fraction", 0.5)),
        "max_variable_heavy_atoms": int(structural.get("max_variable_heavy_atoms", 20)),
        "radius_min": int(radius[0]),
        "radius_max": int(radius[1]),
        "two_cut_thresholds": dict(structural.get("two_cut_thresholds") or {}),
        "neutral_tolerance": float(metadata.get("neutral_tolerance", 0.10)),
    })
    target_ids = list(dict.fromkeys(args.target_id))
    parameters["targets"] = [
        {
            "compound_id": target_id,
            "selection_sources": [
                {"source_type": "human_explicit", "source_id": "standalone_cli"}
            ],
        }
        for target_id in target_ids
    ]
    return {
        "dataset_path": str(dataset_path),
        "database_path": str(database_path),
        "columns": {
            "compound_id": "compound_id",
            "smiles": "smiles",
            "endpoint": endpoint_column,
        },
        "higher_is_better": bool(metadata.get("higher_is_better")),
        "workers": 1,
        "parameters": parameters,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone MMP database builder and 0.1.11 interactive target-report renderer. "
            "It does not require or invoke CONDUCTOR."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build a canonical MMP database from CSV")
    build.add_argument("--input", required=True, help="Input CSV")
    build.add_argument("--output-dir", required=True, help="New or empty output directory")
    build.add_argument("--id-column", required=True, help="Unique compound ID column")
    build.add_argument("--smiles-column", required=True, help="SMILES column")
    build.add_argument("--endpoint-column", required=True, help="Numeric endpoint column")
    direction = build.add_mutually_exclusive_group(required=True)
    direction.add_argument(
        "--higher-is-better", action="store_true",
        help="Larger endpoint values are favorable",
    )
    direction.add_argument(
        "--lower-is-better", action="store_true",
        help="Smaller endpoint values are favorable",
    )
    build.add_argument(
        "--workers", type=int, default=1,
        help="Requested fragmentation workers; the 0.1.11 engine caps this at 8",
    )

    report = subparsers.add_parser(
        "report", help="Render reports for compounds stored in an existing MMP database"
    )
    report.add_argument("--database", required=True, help="Existing mmp_database.sqlite")
    report.add_argument("--output-dir", required=True, help="New or empty output directory")
    report.add_argument(
        "--target-id", action="append", required=True,
        help="Compound ID to report; repeat for multiple targets",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        if args.workers < 1:
            raise ValueError("--workers must be at least 1")
        config = _build_config(args)
        from mmp_0111_runner import execute
        output = _prepare_output(_path(args.output_dir))
        return execute(config, output)

    database_path = _path(args.database)
    compounds, metadata = _database_dataset(database_path)
    known = set(compounds["compound_id"])
    unknown = sorted(set(args.target_id) - known)
    if unknown:
        raise ValueError(f"Target compound IDs are not present in the database: {unknown}")
    endpoint_column = str(metadata.get("endpoint_column", "endpoint"))
    dataset = compounds.rename(columns={"endpoint": endpoint_column})
    from mmp_0111_runner import execute
    output = _prepare_output(_path(args.output_dir))
    with tempfile.TemporaryDirectory(prefix="standalone-mmp-report-") as temporary:
        dataset_path = Path(temporary) / "database_compounds.csv"
        dataset.to_csv(dataset_path, index=False)
        config = _report_config(args, database_path, dataset_path, metadata)
        return execute(config, output)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
