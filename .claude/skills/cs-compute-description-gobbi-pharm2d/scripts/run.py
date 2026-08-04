from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
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
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / ".claude").exists() and (candidate / "catalog").exists():
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
    parser.add_argument("--project")
    parser.add_argument("--node-id")
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
    if algorithm == "pretrained_embedding":
        parser.add_argument("--model-dir")
        parser.add_argument("--adapter", help="Python file exposing embed_smiles(smiles, model_dir).")
        parser.add_argument("--device", default="cpu")
        parser.add_argument("--batch-size", type=int, default=32)
    if algorithm == "tblite_xtb":
        parser.add_argument("--charge", type=float)
        parser.add_argument("--uhf", type=int)
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "node_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, and --node-id")
    elif args.project or args.node_id:
        parser.error("--project and --node-id are valid only with --conductor")
    for name in ("n_bits", "num_confs", "svd_dim", "batch_size"):
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
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "description" / skill / str(args.node_id).replace(":", "-")
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
    calculator = Calculator("GFN2-xTB", numbers, positions, charge=charge, uhf=args.uhf)
    calculator.set("verbosity", 0)
    result = calculator.singlepoint()
    energy = float(result.get("energy"))
    values = {"tblite__energy_hartree": energy, "tblite__energy_ev": energy * 27.211386245988}
    charges = result.get("charges")
    if charges is not None:
        array = np.asarray(charges, dtype=float)
        values.update({"tblite__charge_min": float(array.min()), "tblite__charge_max": float(array.max()), "tblite__charge_mean": float(array.mean()), "tblite__charge_std": float(array.std())})
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
    if algorithm == "pretrained_embedding":
        smiles = [rows[position]["input_smiles"] for position in valid_positions]
        vectors = embed_smiles(smiles, args)
        if len(vectors) != len(valid_positions):
            raise RuntimeError("Embedding row count does not match valid molecule count")
        for position, vector in zip(valid_positions, vectors):
            rows[position].update({f"embedding__{i:04d}": float(value) for i, value in enumerate(vector)})
        return rows, {"model_dir": args.model_dir, "dimension": int(len(vectors[0]) if vectors else 0)}
    raise ValueError(f"Unsupported batch algorithm: {algorithm}")


def embed_smiles(smiles: list[str], args: argparse.Namespace) -> list[list[float]]:
    if args.adapter:
        path = Path(args.adapter)
        spec = importlib.util.spec_from_file_location("conductor_embedding_adapter", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load adapter: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "embed_smiles"):
            raise RuntimeError("Adapter must expose embed_smiles(smiles, model_dir)")
        result = module.embed_smiles(smiles, args.model_dir)
        return np.asarray(result, dtype=float).tolist()
    if not args.model_dir:
        raise ValueError("--model-dir or --adapter is required for pretrained embeddings")
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("torch and transformers are required") from exc
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(args.model_dir, local_files_only=True).to(args.device)
    model.eval()
    vectors: list[list[float]] = []
    for start in range(0, len(smiles), args.batch_size):
        batch = smiles[start : start + args.batch_size]
        encoded = tokenizer(batch, padding=True, truncation=True, return_tensors="pt").to(args.device)
        with torch.no_grad():
            output = model(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1)
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
    if algorithm == "morgan":
        metadata["representation_variant"] = "chiral" if args.include_chirality else "standard"
    elif algorithm == "gobbi_pharm2d":
        metadata["representation_variant"] = "svd" if args.reduction == "svd" else "folded"
    if (algorithm == "gobbi_pharm2d" and args.reduction == "svd") or algorithm == "pretrained_embedding":
        rows, batch_metadata = compute_batch(rows, mols, args)
        metadata.update(batch_metadata)
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
        "schema_version": "1.0.0", "conductor_version": "4.0.0", "run_id": run_id,
        "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"],
        "representation_id": CAPABILITY["representation_id"], "input": args.input or "inline_smiles", "input_hash": input_hash,
        "row_count": int(len(result)), "valid_molecule_count": int(result["mol_parse_ok"].sum()), "feature_count": len(features),
        "output": result_path.name, "format": args.format, "metadata": metadata, "warnings": warnings, "errors": errors, "created_at": utc_now()
    }
    if args.conductor:
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "description_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings, "errors": errors})
    if args.conductor:
        event = {
            "schema_version": "1.0.0", "project": args.project, "run_id": run_id, "node_id": args.node_id,
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
