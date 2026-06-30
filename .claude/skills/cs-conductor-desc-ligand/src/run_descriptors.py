from __future__ import annotations

import argparse
import json
import sys
import traceback as tb
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .column_infer import infer_columns
from .desc_2d import calc_rdkit_2d_descriptors, calc_rdkit_fragment_counts
from .desc_3d import calc_rdkit_3d_descriptors, calc_shape_basic, calc_usr_usrcat, get_3d_mol
from .fp_keys import calc_atom_pair_fp, calc_maccs_keys, calc_topological_torsion_fp
from .fp_morgan import calc_morgan_fingerprint
from .io_utils import ensure_output_dir, read_input_csv, write_descriptor_csv, write_error_report, write_run_metadata
from .mol_utils import prepare_molecule_table, require_rdkit

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import rdkit
except ImportError:  # pragma: no cover
    rdkit = None


DEFAULT_2D_SETS = [f"L{i:02d}" for i in range(1, 12)]
THREED_SETS = ["L14", "L15", "L16"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_config() -> dict[str, Any]:
    sets = {
        "L01": {"name": "rdkit_0d_1d_2d", "enabled_by_default": True, "output": "L01_rdkit_0d_1d_2d.csv", "requires_3d": False},
        "L02": {"name": "ecfp4_bit", "enabled_by_default": True, "output": "L02_ecfp4_bit.csv", "requires_3d": False, "params": {"radius": 2, "n_bits": 2048, "use_features": False, "vector_type": "bit"}},
        "L03": {"name": "ecfp4_count", "enabled_by_default": True, "output": "L03_ecfp4_count.csv", "requires_3d": False, "params": {"radius": 2, "n_bits": 2048, "use_features": False, "vector_type": "count"}},
        "L04": {"name": "ecfp6_bit", "enabled_by_default": True, "output": "L04_ecfp6_bit.csv", "requires_3d": False, "params": {"radius": 3, "n_bits": 2048, "use_features": False, "vector_type": "bit"}},
        "L05": {"name": "ecfp6_count", "enabled_by_default": True, "output": "L05_ecfp6_count.csv", "requires_3d": False, "params": {"radius": 3, "n_bits": 2048, "use_features": False, "vector_type": "count"}},
        "L06": {"name": "fcfp4_bit", "enabled_by_default": True, "output": "L06_fcfp4_bit.csv", "requires_3d": False, "params": {"radius": 2, "n_bits": 2048, "use_features": True, "vector_type": "bit"}},
        "L07": {"name": "fcfp4_count", "enabled_by_default": True, "output": "L07_fcfp4_count.csv", "requires_3d": False, "params": {"radius": 2, "n_bits": 2048, "use_features": True, "vector_type": "count"}},
        "L08": {"name": "maccs_keys", "enabled_by_default": True, "output": "L08_maccs_keys.csv", "requires_3d": False},
        "L09": {"name": "atom_pair", "enabled_by_default": True, "output": "L09_atom_pair.csv", "requires_3d": False, "params": {"n_bits": 2048, "vector_type": "count"}},
        "L10": {"name": "topological_torsion", "enabled_by_default": True, "output": "L10_topological_torsion.csv", "requires_3d": False, "params": {"n_bits": 2048, "vector_type": "count"}},
        "L11": {"name": "rdkit_fragment_counts", "enabled_by_default": True, "output": "L11_rdkit_fragment_counts.csv", "requires_3d": False},
        "L14": {"name": "rdkit_3d_descriptors", "enabled_by_default": False, "output": "L14_rdkit_3d_descriptors.csv", "requires_3d": True},
        "L15": {"name": "usr_usrcat", "enabled_by_default": False, "output": "L15_usr_usrcat.csv", "requires_3d": True},
        "L16": {"name": "shape_basic", "enabled_by_default": False, "output": "L16_shape_basic.csv", "requires_3d": True},
    }
    return {"global": {"n_bits_default": 2048, "include_invalid_rows": True}, "sets": sets}


def load_config(path: str | None) -> dict[str, Any]:
    if path and Path(path).exists() and yaml is not None:
        with Path(path).open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    if path and Path(path).exists() and yaml is None:
        return _default_config()
    return _default_config()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate RDKit ligand descriptor CSV files.")
    parser.add_argument("--input", required=True, help="Input CSV containing compound IDs and SMILES.")
    parser.add_argument("--output-dir", default=None, help="Directory for output CSV files. Defaults to descriptions/<input_csv_stem>.")
    parser.add_argument("--config", default="config/descriptor_sets.yaml", help="Descriptor set YAML config.")
    parser.add_argument("--id-col", default=None, help="Explicit compound ID column.")
    parser.add_argument("--smiles-col", default=None, help="Explicit SMILES column.")
    parser.add_argument("--sets", default=None, help="Comma-separated descriptor set IDs, e.g. L01,L02.")
    parser.add_argument("--enable-3d", action="store_true", help="Allow L14-L16 3D descriptor sets.")
    parser.add_argument("--dry-run", action="store_true", help="Show inferred columns and planned outputs without writing descriptors.")
    parser.add_argument("--n-bits", type=int, default=None, help="Override fingerprint bit length where applicable.")
    parser.add_argument("--include-invalid-rows", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing descriptor CSV files.")
    return parser.parse_args(argv)


def select_sets(config: dict[str, Any], requested: str | None, enable_3d: bool) -> list[str]:
    available = config["sets"]
    if requested:
        selected = [item.strip().upper() for item in requested.split(",") if item.strip()]
    else:
        selected = [set_id for set_id, spec in available.items() if spec.get("enabled_by_default")]
        if enable_3d:
            selected.extend([set_id for set_id in THREED_SETS if set_id in available])

    unknown = [set_id for set_id in selected if set_id not in available]
    if unknown:
        raise ValueError(f"Unknown descriptor set IDs: {','.join(unknown)}")

    blocked = [set_id for set_id in selected if available[set_id].get("requires_3d") and not enable_3d]
    if blocked:
        raise ValueError(f"3D descriptor sets require --enable-3d: {','.join(blocked)}")
    return selected


def _prefix_for_set(set_id: str) -> str:
    return {
        "L02": "ecfp4_bit",
        "L03": "ecfp4_cnt",
        "L04": "ecfp6_bit",
        "L05": "ecfp6_cnt",
        "L06": "fcfp4_bit",
        "L07": "fcfp4_cnt",
    }[set_id]


def _calculator_for_set(set_id: str, spec: dict[str, Any]) -> Callable:
    params = dict(spec.get("params") or {})

    if set_id in {"L02", "L03", "L04", "L05", "L06", "L07"}:
        prefix = _prefix_for_set(set_id)
        return lambda mol: calc_morgan_fingerprint(mol, prefix=prefix, **params)
    if set_id == "L01":
        return calc_rdkit_2d_descriptors
    if set_id == "L08":
        return calc_maccs_keys
    if set_id == "L09":
        return lambda mol: calc_atom_pair_fp(mol, **params)
    if set_id == "L10":
        return lambda mol: calc_topological_torsion_fp(mol, **params)
    if set_id == "L11":
        return calc_rdkit_fragment_counts
    if set_id == "L14":
        return lambda mol: calc_rdkit_3d_descriptors(get_3d_mol(mol))
    if set_id == "L15":
        return lambda mol: calc_usr_usrcat(get_3d_mol(mol))
    if set_id == "L16":
        return lambda mol: calc_shape_basic(get_3d_mol(mol))
    raise ValueError(f"No calculator implemented for {set_id}")


def _base_record(row: pd.Series, descriptor_error: str = "") -> dict[str, Any]:
    return {
        "compound_id": row["compound_id"],
        "canonical_smiles": row["canonical_smiles"],
        "mol_parse_ok": bool(row["mol_parse_ok"]),
        "descriptor_error": descriptor_error,
    }


def compute_set(mol_table: pd.DataFrame, set_id: str, spec: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    calculator = _calculator_for_set(set_id, spec)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for _, mol_row in mol_table.iterrows():
        if not bool(mol_row["mol_parse_ok"]):
            message = str(mol_row["mol_error"])
            rows.append(_base_record(mol_row, message))
            errors.append(
                {
                    "compound_id": mol_row["compound_id"],
                    "input_smiles": mol_row["input_smiles"],
                    "canonical_smiles": mol_row["canonical_smiles"],
                    "descriptor_set": set_id,
                    "error_type": "mol_parse_error",
                    "error_message": message,
                    "traceback": "",
                }
            )
            continue
        try:
            features = calculator(mol_row["mol"])
            rows.append({**_base_record(mol_row), **features})
        except Exception as exc:
            error_type = "conformer_error" if spec.get("requires_3d") else "descriptor_error"
            rows.append(_base_record(mol_row, str(exc)))
            errors.append(
                {
                    "compound_id": mol_row["compound_id"],
                    "input_smiles": mol_row["input_smiles"],
                    "canonical_smiles": mol_row["canonical_smiles"],
                    "descriptor_set": set_id,
                    "error_type": error_type,
                    "error_message": str(exc),
                    "traceback": tb.format_exc(),
                }
            )
    df = pd.DataFrame(rows)
    common = ["compound_id", "canonical_smiles", "mol_parse_ok", "descriptor_error"]
    feature_cols = sorted([col for col in df.columns if col not in common])
    return df[common + feature_cols], errors


def _validate_columns(df: pd.DataFrame, id_col: str | None, smiles_col: str | None) -> None:
    if smiles_col is None:
        raise ValueError("SMILES column could not be inferred. Specify --smiles-col.")
    missing = [col for col in [id_col, smiles_col] if col and col not in df.columns]
    if missing:
        raise ValueError(f"Specified column(s) not found in input CSV: {', '.join(missing)}")


def _dry_run_report(
    df: pd.DataFrame,
    mol_table: pd.DataFrame | None,
    id_col: str | None,
    smiles_col: str,
    selected_sets: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    valid_count = int(mol_table["mol_parse_ok"].sum()) if mol_table is not None else None
    invalid_count = int((~mol_table["mol_parse_ok"]).sum()) if mol_table is not None else None
    return {
        "id_col": id_col,
        "smiles_col": smiles_col,
        "n_rows": int(len(df)),
        "valid_smiles": valid_count,
        "invalid_smiles": invalid_count,
        "descriptor_sets": selected_sets,
        "planned_outputs": [config["sets"][set_id]["output"] for set_id in selected_sets],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output_dir is None:
        args.output_dir = str(repo_root() / "descriptions" / Path(args.input).stem)
    config = load_config(args.config)
    df = read_input_csv(args.input)
    inferred = infer_columns(df)
    id_col = args.id_col or config.get("global", {}).get("id_column") or inferred["id_col"]
    smiles_col = args.smiles_col or config.get("global", {}).get("smiles_column") or inferred["smiles_col"]
    _validate_columns(df, id_col, smiles_col)

    selected_sets = select_sets(config, args.sets, args.enable_3d)
    if args.n_bits:
        for set_id in selected_sets:
            params = config["sets"][set_id].setdefault("params", {})
            if "n_bits" in params:
                params["n_bits"] = args.n_bits

    require_rdkit()
    mol_table = prepare_molecule_table(df, id_col, smiles_col)

    if args.dry_run:
        print(json.dumps(_dry_run_report(df, mol_table, id_col, smiles_col, selected_sets, config), indent=2, ensure_ascii=False))
        return 0

    ensure_output_dir(args.output_dir)
    all_errors: list[dict[str, Any]] = []
    outputs: dict[str, str] = {}
    failed_by_set: dict[str, int] = {}

    for set_id in selected_sets:
        spec = config["sets"][set_id]
        output_path = Path(args.output_dir, spec["output"])
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(f"Output exists; use --overwrite to replace it: {output_path}")
        descriptor_df, errors = compute_set(mol_table, set_id, spec)
        if not args.include_invalid_rows:
            descriptor_df = descriptor_df[descriptor_df["mol_parse_ok"]].copy()
        write_descriptor_csv(descriptor_df, str(output_path))
        all_errors.extend(errors)
        outputs[set_id] = spec["output"]
        failed_by_set[set_id] = len(errors)

    write_error_report(all_errors, args.output_dir)
    duplicate_ids = int(mol_table["compound_id"].duplicated().sum())
    metadata = {
        "input": args.input,
        "output_dir": args.output_dir,
        "rdkit_version": getattr(rdkit, "__version__", "unknown") if rdkit else "unavailable",
        "id_col": id_col,
        "smiles_col": smiles_col,
        "n_rows": int(len(mol_table)),
        "n_valid_mols": int(mol_table["mol_parse_ok"].sum()),
        "n_invalid_mols": int((~mol_table["mol_parse_ok"]).sum()),
        "n_duplicate_compound_ids": duplicate_ids,
        "descriptor_sets": selected_sets,
        "outputs": outputs,
        "errors": failed_by_set,
        "column_inference": inferred,
        "argv": sys.argv[1:] if argv is None else argv,
    }
    write_run_metadata(metadata, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
