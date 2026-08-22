from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))
COMMON_COLUMNS = ["compound_id", "input_smiles", "mol_parse_ok", "description_error"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def find_workspace() -> Path:
    skill_candidates = [SKILL_DIR, *SKILL_DIR.parents]
    cwd_candidates = [Path.cwd(), *Path.cwd().parents]

    # The nearest Project containing this installed Skill is authoritative.
    # This also preserves standalone general-mode use without CONDUCTOR_modules.
    for candidate in skill_candidates:
        installed_skill = candidate / ".claude" / "skills" / SKILL_DIR.name
        if (installed_skill / "capability.json").is_file():
            return candidate

    # Fall back to the caller Project only for non-standard script placement.
    for candidate in cwd_candidates:
        if (candidate / ".claude" / "skills").is_dir() and (
            candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json"
        ).is_file():
            return candidate

    for candidate in cwd_candidates:
        if (candidate / ".claude" / "skills").is_dir():
            return candidate
    return Path.cwd()


def safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_json(value), ensure_ascii=False, indent=2), encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_hash(value: Any) -> str:
    payload = json.dumps(safe_json(value), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_json(instance: dict[str, Any], schema_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required in CONDUCTOR mode") from exc
    schema_path = SKILL_DIR / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=instance, schema=schema)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Run {CAPABILITY['skill_name']}.")
    algorithm = CAPABILITY["implementation"]["algorithm"]
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="CSV containing compound IDs and SMILES.")
    source.add_argument("--smiles", action="append", help="A SMILES value; repeat for multiple compounds.")
    parser.add_argument("--compound-id", action="append", help="ID paired by position with --smiles.")
    parser.add_argument("--id-column")
    parser.add_argument("--smiles-column")
    parser.add_argument("--output-dir")
    parser.add_argument("--format", choices=["csv", "parquet"], default="csv")
    parser.add_argument("--run-id")
    parser.add_argument("--round-id")
    parser.add_argument("--project")
    parser.add_argument("--node-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    if algorithm in {"morgan", "atom_pair", "topological_torsion", "rdkit_path", "rdkit_pattern", "rdkit_layered", "avalon", "gobbi_pharm2d"}:
        parser.add_argument("--n-bits", type=int, default=2048)
    if algorithm == "morgan":
        parser.add_argument("--radius", type=int, default=2)
        parser.add_argument("--encoding", choices=["bit", "count"], default="bit")
        parser.add_argument("--use-features", action="store_true")
        parser.add_argument("--include-chirality", action=argparse.BooleanOptionalAction, default=False)
    if algorithm in {"rdkit_3d", "usr_usrcat", "shape", "mordred_3d", "tblite_xtb"}:
        parser.add_argument("--num-confs", type=int, default=20)
        parser.add_argument("--random-seed", type=int, default=61453)
    if algorithm == "gobbi_pharm2d":
        parser.add_argument("--reduction", choices=["none", "svd"], default="none")
        parser.add_argument("--svd-dim", type=int, default=256)
        parser.add_argument("--random-seed", type=int, default=61453)
    if algorithm == "chemberta_embedding":
        parser.add_argument("--model-dir")
        parser.add_argument("--batch-size", type=int, default=32)
        parser.add_argument("--max-length", type=int, default=512)
        parser.add_argument("--cpu-threads", type=int, default=8)
    if algorithm == "tblite_xtb":
        parser.add_argument("--charge", type=float)
        parser.add_argument("--uhf", type=int)
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "round_id", "node_id", "attempt_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, --round-id, --node-id, and --attempt-id")
    elif args.project or args.round_id or args.node_id or args.attempt_id:
        parser.error("--project, --round-id, --node-id, and --attempt-id are valid only with --conductor")
    for name in ("n_bits", "num_confs", "svd_dim", "batch_size", "max_length", "cpu_threads"):
        if hasattr(args, name) and getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    if hasattr(args, "radius") and args.radius < 0:
        parser.error("--radius must be >= 0")
    return args


def _name_score(name: str, kind: str) -> int:
    normalized = "".join(ch for ch in name.lower() if ch.isalnum())
    candidates = {
        "id": ["compoundid", "moleculeid", "mol id", "id", "chemblid", "sampleid"],
        "smiles": ["canonicalsmiles", "isomericsmiles", "smiles", "structure"],
    }[kind]
    compact = ["".join(ch for ch in item if ch.isalnum()) for item in candidates]
    if normalized in compact:
        return 100 - compact.index(normalized)
    return max((40 for item in compact if item in normalized), default=0)


def infer_columns(df: pd.DataFrame, id_column: str | None, smiles_column: str | None) -> tuple[str | None, str]:
    if id_column and id_column not in df.columns:
        raise ValueError(f"ID column not found: {id_column}")
    if smiles_column and smiles_column not in df.columns:
        raise ValueError(f"SMILES column not found: {smiles_column}")
    if not smiles_column:
        ranked = sorted(df.columns, key=lambda c: _name_score(str(c), "smiles"), reverse=True)
        smiles_column = str(ranked[0]) if ranked and _name_score(str(ranked[0]), "smiles") > 0 else None
    if not smiles_column:
        try:
            from rdkit import Chem
            scores = []
            for column in df.columns:
                values = df[column].dropna().astype(str).head(50)
                valid = sum(Chem.MolFromSmiles(value) is not None for value in values)
                scores.append((valid / max(1, len(values)), str(column)))
            ratio, candidate = max(scores, default=(0.0, ""))
            if ratio >= 0.6:
                smiles_column = candidate
        except ImportError:
            pass
    if not smiles_column:
        raise ValueError("SMILES column could not be inferred; specify --smiles-column")
    if not id_column:
        ranked = sorted(df.columns, key=lambda c: _name_score(str(c), "id"), reverse=True)
        if ranked and _name_score(str(ranked[0]), "id") > 0 and str(ranked[0]) != smiles_column:
            id_column = str(ranked[0])
    return id_column, smiles_column


def load_records(args: argparse.Namespace) -> tuple[pd.DataFrame, str, str]:
    if args.input:
        input_path = Path(args.input)
        header = pd.read_csv(input_path, nrows=0)
        candidate_id = args.id_column
        if not candidate_id:
            ranked_ids = sorted(header.columns, key=lambda column: _name_score(str(column), "id"), reverse=True)
            candidate_id = str(ranked_ids[0]) if ranked_ids and _name_score(str(ranked_ids[0]), "id") > 0 else None
        df = pd.read_csv(input_path, dtype={candidate_id: "string"} if candidate_id else None)
        id_column, smiles_column = infer_columns(df, args.id_column, args.smiles_column)
        if id_column and df[id_column].isna().any():
            raise ValueError("Compound IDs must not be missing")
        ids = df[id_column].astype(str).str.strip() if id_column else pd.Series([f"CMPD_{i:06d}" for i in range(1, len(df) + 1)])
        source_name = input_path.stem
        input_hash = file_sha256(input_path)
        smiles = df[smiles_column]
    else:
        values = list(args.smiles or [])
        supplied_ids = list(args.compound_id or [])
        if supplied_ids and len(supplied_ids) != len(values):
            raise ValueError("The number of --compound-id values must match --smiles values")
        ids = pd.Series(supplied_ids or [f"CMPD_{i:06d}" for i in range(1, len(values) + 1)])
        smiles = pd.Series(values)
        source_name = "smiles"
        input_hash = object_hash({"compound_ids": ids.astype(str).tolist(), "smiles": values})
    if len(ids) == 0:
        raise ValueError("At least one compound is required")
    if ids.isna().any() or ids.astype(str).str.strip().eq("").any():
        raise ValueError("Compound IDs must not be missing")
    if ids.astype(str).duplicated().any():
        duplicates = ids.astype(str)[ids.astype(str).duplicated(keep=False)].unique().tolist()[:10]
        raise ValueError(f"Duplicate compound IDs: {duplicates}")
    return pd.DataFrame({"compound_id": ids.astype(str), "input_smiles": smiles}), source_name, input_hash


def output_dir(args: argparse.Namespace, source_name: str, run_id: str) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    root = find_workspace() / "results"
    skill = CAPABILITY["skill_name"]
    if args.conductor:
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "description" / skill / str(args.node_id).replace(":", "-") / "attempts" / str(args.attempt_id)
    return root / "description" / source_name / skill / run_id


def bit_values(fp: Any, prefix: str, n_bits: int | None = None) -> dict[str, int]:
    size = int(n_bits if n_bits is not None else fp.GetNumBits())
    on_bits = set(int(value) for value in fp.GetOnBits())
    return {f"{prefix}_{i:04d}": int(i in on_bits) for i in range(size)}


def count_values(fp: Any, prefix: str, n_bits: int) -> dict[str, int]:
    values = fp.GetNonzeroElements()
    return {f"{prefix}_{i:04d}": int(values.get(i, 0)) for i in range(n_bits)}


def mol3d(mol: Any, args: argparse.Namespace) -> Any:
    from rdkit import Chem
    from rdkit.Chem import AllChem
    result = Chem.AddHs(Chem.Mol(mol))
    params = AllChem.ETKDGv3()
    params.randomSeed = int(args.random_seed)
    params.numThreads = 1
    conformer_ids = list(AllChem.EmbedMultipleConfs(result, numConfs=max(1, args.num_confs), params=params))
    if not conformer_ids:
        raise RuntimeError("RDKit conformer generation failed")
    energies: list[tuple[float, int]] = []
    for conf_id in conformer_ids:
        try:
            if AllChem.MMFFHasAllMoleculeParams(result):
                props = AllChem.MMFFGetMoleculeProperties(result, mmffVariant="MMFF94s")
                force = AllChem.MMFFGetMoleculeForceField(result, props, confId=conf_id)
            else:
                force = AllChem.UFFGetMoleculeForceField(result, confId=conf_id)
            force.Minimize(maxIts=200)
            energies.append((float(force.CalcEnergy()), int(conf_id)))
        except Exception:
            energies.append((float("inf"), int(conf_id)))
    best_id = min(energies)[1]
    selected = Chem.Mol(result)
    keep = Chem.Conformer(result.GetConformer(best_id))
    selected.RemoveAllConformers()
    selected.AddConformer(keep, assignId=True)
    return selected


def compute_one(mol: Any, args: argparse.Namespace) -> dict[str, Any]:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Descriptors3D, MACCSkeys, rdFingerprintGenerator, rdMolDescriptors
    algorithm = CAPABILITY["implementation"]["algorithm"]
    if algorithm == "rdkit_2d":
        return {f"rdkit2d__{name}": float(func(mol)) for name, func in Descriptors._descList}
    if algorithm == "morgan":
        kwargs = {
            "radius": args.radius,
            "fpSize": args.n_bits,
            "includeChirality": args.include_chirality,
        }
        if args.use_features:
            kwargs["atomInvariantsGenerator"] = rdFingerprintGenerator.GetMorganFeatureAtomInvGen()
        generator = rdFingerprintGenerator.GetMorganGenerator(**kwargs)
        prefix = "chiral_morgan" if args.include_chirality else "morgan"
        if args.encoding == "count":
            return count_values(generator.GetCountFingerprint(mol), f"{prefix}_count", args.n_bits)
        return bit_values(generator.GetFingerprint(mol), f"{prefix}_bit", args.n_bits)
    if algorithm == "maccs":
        return bit_values(MACCSkeys.GenMACCSKeys(mol), "maccs")
    if algorithm == "atom_pair":
        fp = rdFingerprintGenerator.GetAtomPairGenerator(fpSize=args.n_bits).GetCountFingerprint(mol)
        return count_values(fp, "atom_pair", args.n_bits)
    if algorithm == "topological_torsion":
        fp = rdFingerprintGenerator.GetTopologicalTorsionGenerator(fpSize=args.n_bits).GetCountFingerprint(mol)
        return count_values(fp, "topological_torsion", args.n_bits)
    if algorithm == "rdkit_fragment":
        return {f"fragment__{name}": float(func(mol)) for name, func in Descriptors._descList if name.startswith("fr_")}
    if algorithm == "rdkit_path":
        return bit_values(Chem.RDKFingerprint(mol, fpSize=args.n_bits), "rdkit_path", args.n_bits)
    if algorithm == "rdkit_pattern":
        return bit_values(Chem.PatternFingerprint(mol, fpSize=args.n_bits), "rdkit_pattern", args.n_bits)
    if algorithm == "rdkit_layered":
        return bit_values(Chem.LayeredFingerprint(mol, fpSize=args.n_bits), "rdkit_layered", args.n_bits)
    if algorithm == "avalon":
        from rdkit.Avalon import pyAvalonTools
        return bit_values(pyAvalonTools.GetAvalonFP(mol, nBits=args.n_bits), "avalon", args.n_bits)
    if algorithm in {"rdkit_3d", "usr_usrcat", "shape", "mordred_3d", "tblite_xtb"}:
        prepared = mol3d(mol, args)
        if algorithm == "rdkit_3d":
            names = ["Asphericity", "Eccentricity", "InertialShapeFactor", "NPR1", "NPR2", "PMI1", "PMI2", "PMI3", "PBF", "RadiusOfGyration", "SpherocityIndex"]
            return {f"rdkit3d__{name}": float(getattr(Descriptors3D, name)(prepared)) for name in names}
        if algorithm == "usr_usrcat":
            values = {f"usr__{i:02d}": float(v) for i, v in enumerate(rdMolDescriptors.GetUSR(prepared))}
            values.update({f"usrcat__{i:02d}": float(v) for i, v in enumerate(rdMolDescriptors.GetUSRCAT(prepared))})
            return values
        if algorithm == "shape":
            funcs = {"PMI1": rdMolDescriptors.CalcPMI1, "PMI2": rdMolDescriptors.CalcPMI2, "PMI3": rdMolDescriptors.CalcPMI3, "NPR1": rdMolDescriptors.CalcNPR1, "NPR2": rdMolDescriptors.CalcNPR2, "RadiusOfGyration": rdMolDescriptors.CalcRadiusOfGyration, "Asphericity": rdMolDescriptors.CalcAsphericity, "Eccentricity": rdMolDescriptors.CalcEccentricity, "InertialShapeFactor": rdMolDescriptors.CalcInertialShapeFactor, "SpherocityIndex": rdMolDescriptors.CalcSpherocityIndex}
            return {f"shape__{name}": float(func(prepared)) for name, func in funcs.items()}
        if algorithm == "mordred_3d":
            return mordred_values(prepared, ignore_3d=False)
        return tblite_values(prepared, args)
    if algorithm == "mordred_2d":
        return mordred_values(mol, ignore_3d=True)
    if algorithm == "gobbi_pharm2d":
        from rdkit.Chem.Pharm2D import Generate, Gobbi_Pharm2D
        fp = Generate.Gen2DFingerprint(mol, Gobbi_Pharm2D.factory)
        folded = set(int(hashlib.blake2b(str(int(bit)).encode("ascii"), digest_size=8).hexdigest(), 16) % args.n_bits for bit in fp.GetOnBits())
        return {f"pharm2d__{i:04d}": int(i in folded) for i in range(args.n_bits)}
    raise ValueError(f"Unsupported row-wise description algorithm: {algorithm}")


def mordred_values(mol: Any, ignore_3d: bool) -> dict[str, Any]:
    try:
        from mordred import Calculator, descriptors
    except ImportError:
        try:
            from mordredcommunity import Calculator, descriptors
        except ImportError as exc:
            raise RuntimeError("mordred or mordredcommunity is required") from exc
    calculator = Calculator(descriptors, ignore_3D=ignore_3d)
    result = calculator(mol)
    values: dict[str, Any] = {}
    casefold_counts: dict[str, int] = {}
    for descriptor, value in zip(calculator.descriptors, result):
        base_name = f"mordred__{descriptor}"
        casefolded = base_name.casefold()
        casefold_counts[casefolded] = casefold_counts.get(casefolded, 0) + 1
        output_name = base_name if casefold_counts[casefolded] == 1 else f"{base_name}__duplicate_{casefold_counts[casefolded]:02d}"
        try:
            number = float(value)
            values[output_name] = number if math.isfinite(number) else np.nan
        except Exception:
            values[output_name] = np.nan
    return values


def _result_array(result: Any, *names: str) -> np.ndarray | None:
    for name in names:
        try:
            value = result.get(name)
        except Exception:
            continue
        if value is not None:
            array = np.asarray(value, dtype=float)
            if array.size:
                return array
    return None


def _stats(prefix: str, array: np.ndarray) -> dict[str, float]:
    values = np.asarray(array, dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if not values.size:
        return {}
    return {
        f"{prefix}_min": float(values.min()), f"{prefix}_max": float(values.max()),
        f"{prefix}_mean": float(values.mean()), f"{prefix}_std": float(values.std()),
    }


def tblite_values(prepared: Any, args: argparse.Namespace) -> dict[str, Any]:
    from rdkit import Chem
    try:
        from tblite.interface import Calculator
    except ImportError as exc:
        raise RuntimeError("tblite-python is required") from exc
    conformer = prepared.GetConformer()
    numbers = np.array([atom.GetAtomicNum() for atom in prepared.GetAtoms()], dtype=int)
    positions = np.array([list(conformer.GetAtomPosition(i)) for i in range(prepared.GetNumAtoms())], dtype=float) * 1.8897261246257702
    charge = float(Chem.GetFormalCharge(prepared) if args.charge is None else args.charge)
    uhf = 0 if args.uhf is None else int(args.uhf)
    calculator = Calculator("GFN2-xTB", numbers, positions, charge=charge, uhf=uhf)
    calculator.set("verbosity", 0)
    result = calculator.singlepoint()
    energy = float(result.get("energy"))
    values: dict[str, Any] = {
        "xtb__total_energy_hartree": energy,
        "xtb__energy_per_atom_hartree": energy / max(1, len(numbers)),
    }
    charges = _result_array(result, "charges")
    if charges is not None:
        values.update(_stats("xtb__mulliken_charge", charges))
        values["xtb__mulliken_charge_mean_abs"] = float(np.mean(np.abs(charges)))
        values["xtb__mulliken_charge_max_abs"] = float(np.max(np.abs(charges)))
    orbitals = _result_array(result, "orbital-energies", "orbital_energies")
    occupations = _result_array(result, "orbital-occupations", "orbital_occupations")
    if orbitals is not None and occupations is not None and orbitals.size == occupations.size:
        occupied = orbitals[occupations > 1e-8]
        virtual = orbitals[occupations <= 1e-8]
        if occupied.size:
            values["xtb__homo_energy_hartree"] = float(np.max(occupied))
        if virtual.size:
            values["xtb__lumo_energy_hartree"] = float(np.min(virtual))
        if occupied.size and virtual.size:
            values["xtb__homo_lumo_gap_hartree"] = float(np.min(virtual) - np.max(occupied))
    dipole = _result_array(result, "molecular-dipole", "dipole")
    if dipole is not None:
        values["xtb__dipole_magnitude_au"] = float(np.linalg.norm(dipole.reshape(-1)))
    quadrupole = _result_array(result, "molecular-quadrupole", "quadrupole")
    if quadrupole is not None:
        tensor = quadrupole.reshape(3, 3) if quadrupole.size == 9 else quadrupole
        if getattr(tensor, "shape", None) == (3, 3):
            tensor = tensor - np.eye(3) * np.trace(tensor) / 3.0
        values["xtb__quadrupole_traceless_frobenius_au"] = float(np.linalg.norm(tensor))
    atom_energies = _result_array(result, "atom-energies", "atom_energies")
    if atom_energies is not None:
        values.update(_stats("xtb__atom_energy_hartree", atom_energies))
    bond_orders = _result_array(result, "bond-orders", "bond_orders")
    if bond_orders is not None and bond_orders.ndim == 2:
        upper = bond_orders[np.triu_indices_from(bond_orders, k=1)]
        values["xtb__bond_order_sum"] = float(np.sum(upper))
        effective = upper[np.abs(upper) > 1e-3]
        if effective.size:
            values["xtb__bond_order_max"] = float(np.max(effective))
            values["xtb__bond_order_mean"] = float(np.mean(effective))
            values["xtb__bond_order_std"] = float(np.std(effective))
    return values


def compute_batch(rows: list[dict[str, Any]], mols: list[Any], args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    algorithm = CAPABILITY["implementation"]["algorithm"]
    valid_positions = [i for i, mol in enumerate(mols) if mol is not None]
    if algorithm == "gobbi_pharm2d" and args.reduction == "svd":
        if len(valid_positions) < 2:
            raise ValueError("At least two valid molecules are required")
        from rdkit.Chem.Pharm2D import Generate, Gobbi_Pharm2D
        from scipy import sparse
        from sklearn.decomposition import TruncatedSVD
        row_ids: list[int] = []
        col_ids: list[int] = []
        data: list[int] = []
        for matrix_row, position in enumerate(valid_positions):
            fp = Generate.Gen2DFingerprint(mols[position], Gobbi_Pharm2D.factory)
            for bit in fp.GetOnBits():
                row_ids.append(matrix_row); col_ids.append(int(bit)); data.append(1)
        raw_dim = int(Gobbi_Pharm2D.factory.GetSigSize())
        matrix = sparse.csr_matrix((data, (row_ids, col_ids)), shape=(len(valid_positions), raw_dim), dtype=float)
        dimension = min(args.svd_dim, len(valid_positions) - 1, raw_dim)
        reducer = TruncatedSVD(n_components=max(1, dimension), random_state=args.random_seed)
        transformed = reducer.fit_transform(matrix)
        for matrix_row, position in enumerate(valid_positions):
            rows[position].update({f"pharm2d_svd__{i:04d}": float(v) for i, v in enumerate(transformed[matrix_row])})
        return rows, {"raw_dimension": raw_dim, "actual_dimension": int(transformed.shape[1]), "explained_variance_ratio_sum": float(reducer.explained_variance_ratio_.sum())}
    if algorithm == "chemberta_embedding":
        smiles = [rows[position]["input_smiles"] for position in valid_positions]
        vectors = embed_smiles(smiles, args)
        if len(vectors) != len(valid_positions):
            raise RuntimeError("Embedding row count does not match valid molecule count")
        for position, vector in zip(valid_positions, vectors):
            rows[position].update({f"embedding__{i:04d}": float(value) for i, value in enumerate(vector)})
        return rows, {"model_dir": str(resolve_model_dir(args)), "dimension": int(len(vectors[0]) if vectors else 0), "pooling": "non_special_token_mean", "max_length": args.max_length, "batch_size": args.batch_size, "cpu_threads": args.cpu_threads, "device": "cpu"}
    raise ValueError(f"Unsupported batch algorithm: {algorithm}")


def resolve_model_dir(args: argparse.Namespace) -> Path:
    import os
    configured = args.model_dir or os.environ.get("CONDUCTOR_CHEMBERTA_MODEL_DIR")
    config_path = SKILL_DIR / "env" / "model_path.txt"
    if not configured and config_path.is_file():
        configured = config_path.read_text(encoding="utf-8").strip()
    if not configured:
        raise ValueError("ChemBERTa model path is required via --model-dir, CONDUCTOR_CHEMBERTA_MODEL_DIR, or env/model_path.txt")
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Local ChemBERTa model directory not found: {path}")
    return path


def model_signature(model_dir: Path) -> str:
    """Stable local-model identity without hashing multi-GB weight contents."""
    digest = hashlib.sha256()
    for path in sorted(p for p in model_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(model_dir).as_posix()
        stat = path.stat(); digest.update(f"{relative}\0{stat.st_size}\0".encode("utf-8"))
        if path.name in {"config.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.json"}:
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _enable_windows_extended_import_paths() -> None:
    """Avoid the legacy MAX_PATH boundary when Transformers scans model modules."""
    if os.name != "nt":
        return
    for index, entry in enumerate(sys.path):
        if not entry:
            continue
        resolved = os.path.abspath(entry)
        if "site-packages" in resolved.lower() and not resolved.startswith("\\\\?\\"):
            sys.path[index] = "\\\\?\\" + resolved


def embed_smiles(smiles: list[str], args: argparse.Namespace) -> list[list[float]]:
    _enable_windows_extended_import_paths()
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("torch and transformers are required") from exc
    model_dir = resolve_model_dir(args)
    torch.set_num_threads(args.cpu_threads)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(model_dir, local_files_only=True).cpu()
    model.eval()
    vectors: list[list[float]] = []
    for start in range(0, len(smiles), args.batch_size):
        batch = smiles[start : start + args.batch_size]
        encoded = tokenizer(batch, padding=True, truncation=True, max_length=args.max_length, return_special_tokens_mask=True, return_tensors="pt")
        special = encoded.pop("special_tokens_mask").bool()
        with torch.no_grad():
            output = model(**encoded).last_hidden_state
            mask = (encoded["attention_mask"].bool() & ~special).unsqueeze(-1)
            pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1)
        vectors.extend(pooled.detach().cpu().numpy().astype(float).tolist())
    return vectors


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    run_id = args.run_id or default_run_id()
    source, source_name, input_hash = load_records(args)
    outdir = output_dir(args, source_name, run_id)
    extension = "parquet" if args.format == "parquet" else "csv"
    if outdir.exists() and any(outdir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
        for name in [f"{CAPABILITY['output']['basename']}.csv", f"{CAPABILITY['output']['basename']}.parquet", "description_manifest.json", "warnings.json", "execution_event.json"]:
            (outdir / name).unlink(missing_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    result_path = outdir / f"{CAPABILITY['output']['basename']}.{extension}"
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError("RDKit is required") from exc
    rows: list[dict[str, Any]] = []
    mols: list[Any] = []
    warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    for record in source.to_dict(orient="records"):
        smiles = "" if pd.isna(record["input_smiles"]) else str(record["input_smiles"])
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        mols.append(mol)
        row = {"compound_id": str(record["compound_id"]), "input_smiles": smiles, "mol_parse_ok": mol is not None, "description_error": ""}
        if mol is None:
            row["description_error"] = "invalid_smiles"
            errors.append({"compound_id": row["compound_id"], "error_type": "invalid_smiles", "message": "RDKit could not parse input SMILES"})
        rows.append(row)
    algorithm = CAPABILITY["implementation"]["algorithm"]
    metadata: dict[str, Any] = {"algorithm": algorithm}
    value_semantics = CAPABILITY.get("value_semantics", "dense_continuous")
    natural_metric = CAPABILITY.get("natural_metric", "euclidean")
    metadata.update({"representation_family": CAPABILITY.get("family"), "value_semantics": value_semantics, "natural_metric": natural_metric})
    if algorithm == "morgan":
        metadata["representation_variant"] = "chiral" if args.include_chirality else "standard"
    elif algorithm == "gobbi_pharm2d":
        metadata["representation_variant"] = "svd" if args.reduction == "svd" else "folded"
        if args.reduction == "svd":
            value_semantics, natural_metric = "dense_embedding", "cosine"
            metadata.update({"value_semantics": value_semantics, "natural_metric": natural_metric})
    if (algorithm == "gobbi_pharm2d" and args.reduction == "svd") or algorithm == "chemberta_embedding":
        rows, batch_metadata = compute_batch(rows, mols, args)
        metadata.update(batch_metadata)
        if algorithm == "chemberta_embedding":
            metadata["model_signature"] = model_signature(resolve_model_dir(args))
    else:
        for index, mol in enumerate(mols):
            if mol is None:
                continue
            try:
                rows[index].update(compute_one(mol, args))
            except Exception as exc:
                rows[index]["description_error"] = str(exc)
                errors.append({"compound_id": rows[index]["compound_id"], "error_type": "description_error", "message": str(exc), "traceback": traceback.format_exc()})
    result = pd.DataFrame(rows)
    features = sorted(column for column in result.columns if column not in COMMON_COLUMNS)
    result = result[COMMON_COLUMNS + features]
    if args.format == "parquet":
        result.to_parquet(result_path, index=False)
    else:
        result.to_csv(result_path, index=False)
    if errors:
        warnings.append(f"{len(errors)} row-level errors were recorded")
    config = {key: value for key, value in vars(args).items() if key not in {"smiles", "compound_id"}}
    manifest = {
        "schema_version": "2.0.0", "conductor_version": "0.1.6", "artifact_stage": "description", "run_id": run_id,
        "node_id": args.node_id, "attempt_id": args.attempt_id,
        "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"],
        "representation_id": CAPABILITY["representation_id"], "input": args.input or "inline_smiles", "input_hash": input_hash,
        "value_semantics": value_semantics, "natural_metric": natural_metric, "feature_columns": features,
        "row_count": int(len(result)), "valid_molecule_count": int(result["mol_parse_ok"].sum()), "feature_count": len(features),
        "output": result_path.name, "format": args.format, "metadata": metadata, "warnings": warnings, "errors": errors, "created_at": utc_now()
    }
    if args.conductor:
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "description_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings, "errors": errors})
    if args.conductor:
        event = {
            "schema_version": "2.0.0", "project": args.project, "run_id": run_id, "round_id": args.round_id, "node_id": args.node_id, "attempt_id": args.attempt_id,
            "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded",
            "input_hash": input_hash, "config_hash": object_hash(config), "configuration": config,
            "artifacts": [{"type": "description", "path": result_path.name, "sha256": file_sha256(result_path)}, {"type": "manifest", "path": "description_manifest.json", "sha256": file_sha256(outdir / "description_manifest.json")}],
            "warnings": warnings, "started_at": started_at, "finished_at": utc_now()
        }
        validate_json(event, "execution_event.schema.json")
        write_json(outdir / "execution_event.json", event)
    print(result_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
