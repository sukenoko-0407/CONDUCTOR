"""Run the Stage 4/6 checkpoint on an explicitly supplied calibration CSV."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from rdkit import Chem

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for package in ("cs-stat-core", "cs-fragment-engine", "cs-lens-l2"):
    path = PROJECT_ROOT / ".claude" / "skills" / package / "python"
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from conductor_fragment_engine import build_fragment_database  # noqa: E402
from conductor_lens_l2 import run_l2b  # noqa: E402
from conductor_stat_core import atomic_write_json  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--id-column", required=True)
    parser.add_argument("--smiles-column", required=True)
    parser.add_argument("--endpoint-column", required=True)
    parser.add_argument("--endpoint-id", default="EP_PRIMARY")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--screen-permutations", type=int, default=100)
    parser.add_argument("--final-permutations", type=int, default=1000)
    parser.add_argument("--context-catalog")
    return parser.parse_args()


def _phase1(source: pd.DataFrame, id_column: str, smiles_column: str, endpoint_column: str, endpoint_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if source[id_column].astype("string").isna().any() or source[id_column].astype(str).duplicated().any():
        raise ValueError("Calibration data requires non-null unique compound IDs")
    compounds: list[dict[str, object]] = []
    for compound_id, smiles in zip(source[id_column].astype(str), source[smiles_column], strict=True):
        molecule = Chem.MolFromSmiles(str(smiles))
        compounds.append(
            {
                "compound_id": compound_id,
                "input_smiles": str(smiles),
                "canonical_smiles": Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True) if molecule else str(smiles),
                "mol_parse_ok": molecule is not None,
            }
        )
    endpoints = pd.DataFrame(
        {
            "compound_id": source[id_column].astype(str),
            "endpoint_id": endpoint_id,
            "raw_value": pd.to_numeric(source[endpoint_column], errors="coerce"),
            "value": pd.to_numeric(source[endpoint_column], errors="coerce"),
            "oriented_value": pd.to_numeric(source[endpoint_column], errors="coerce"),
        }
    )
    endpoints["is_measured"] = endpoints["oriented_value"].notna()
    return pd.DataFrame(compounds), endpoints


def main() -> int:
    args = _arguments()
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Calibration output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(Path(args.input).resolve(), dtype={args.id_column: "string"})
    required = {args.id_column, args.smiles_column, args.endpoint_column}
    if required - set(source.columns):
        raise ValueError(f"Calibration input is missing columns: {sorted(required - set(source.columns))}")
    compounds, endpoints = _phase1(source, args.id_column, args.smiles_column, args.endpoint_column, args.endpoint_id)
    phase1 = output / "phase1"
    phase1.mkdir()
    compounds.to_csv(phase1 / "compounds.csv", index=False, lineterminator="\n")
    endpoints.to_csv(phase1 / "endpoints.csv", index=False, lineterminator="\n")
    phase3 = output / "phase3"
    fragment = build_fragment_database(
        compounds,
        endpoints,
        args.endpoint_id,
        phase3,
        similar_core_workers=max(1, args.workers),
    )
    l2b = run_l2b(
        fragment.observations,
        endpoints,
        args.endpoint_id,
        run_seed=args.seed,
        screen_permutations=args.screen_permutations,
        final_permutations=args.final_permutations,
        calibration_permutations=min(20, args.screen_permutations),
    )
    l2b.evidence.to_csv(phase3 / "l2b_evidence.csv", index=False, lineterminator="\n")
    l2b.tests.to_csv(phase3 / "l2b_tests.csv", index=False, lineterminator="\n")
    with (phase3 / "findings.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for finding in l2b.findings:
            handle.write(json.dumps(finding, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    context_count = None
    calibration_scope_count = None
    if args.context_catalog:
        contexts = pd.read_csv(Path(args.context_catalog).resolve())
        context_count = len(contexts)
        calibration_scope_count = int(contexts.get("calibration_scope", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    checkpoint = {
        "schema_version": "0.2.1",
        "input_path": str(Path(args.input).resolve()),
        "compound_count": len(compounds),
        "valid_structure_count": int(compounds["mol_parse_ok"].sum()),
        "fragment": fragment.metrics,
        "l2b": l2b.metrics,
        "calibration": l2b.calibration,
        "context_count": context_count,
        "calibration_scope_context_count": calibration_scope_count,
        "is_reference_calibration_shape": len(compounds) == 961,
    }
    atomic_write_json(output / "stage6_checkpoint.json", checkpoint)
    print(json.dumps({"status": "succeeded", "checkpoint": str(output / "stage6_checkpoint.json")}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
