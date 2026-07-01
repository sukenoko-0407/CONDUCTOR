from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import traceback as tb
from pathlib import Path
from typing import Any

import pandas as pd

from ..run_support import base_record


def _require_model_dir(spec: dict[str, Any]) -> Path:
    model_dir = spec.get("model_dir") or (spec.get("params") or {}).get("model_dir")
    if not model_dir:
        raise RuntimeError("pretrained embedding sets require a local model_dir in config/descriptor_sets.yaml.")
    path = Path(model_dir)
    if not path.exists():
        raise RuntimeError(f"Configured model_dir does not exist: {path}")
    return path


def _optional_model_dir(spec: dict[str, Any]) -> Path | None:
    model_dir = spec.get("model_dir") or (spec.get("params") or {}).get("model_dir")
    if not model_dir:
        return None
    path = Path(model_dir)
    if not path.exists():
        raise RuntimeError(f"Configured model_dir does not exist: {path}")
    return path


def _valid_positions(mol_table: pd.DataFrame) -> list[Any]:
    return [idx for idx, row in mol_table.iterrows() if bool(row["mol_parse_ok"])]


def _valid_records(mol_table: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, row in mol_table.iterrows():
        if not bool(row["mol_parse_ok"]):
            continue
        records.append(
            {
                "row_index": idx,
                "compound_id": row["compound_id"],
                "input_smiles": row["input_smiles"],
                "canonical_smiles": row["canonical_smiles"],
            }
        )
    return records


def _smiles_values(mol_table: pd.DataFrame) -> list[str]:
    return [str(row["canonical_smiles"]) for _, row in mol_table.iterrows() if bool(row["mol_parse_ok"])]


def _text_values(mol_table: pd.DataFrame, input_format: str) -> list[str]:
    smiles = _smiles_values(mol_table)
    normalized = input_format.strip().lower()
    if normalized in {"smiles", "canonical_smiles"}:
        return smiles
    if normalized == "selfies":
        try:
            import selfies as sf
        except ImportError as exc:
            raise RuntimeError("SELFIES input requires the selfies package.") from exc
        try:
            return [sf.encoder(value) for value in smiles]
        except Exception as exc:
            raise RuntimeError(f"Failed to convert canonical SMILES to SELFIES: {exc}") from exc
    raise ValueError(f"Unsupported pretrained embedding input_format: {input_format}")


def _pool_hf_output(output: Any, encoded: dict[str, Any], pooling: str) -> Any:
    if pooling == "pooler":
        pooler = getattr(output, "pooler_output", None)
        if pooler is None:
            raise ValueError("pooler pooling requested, but model output has no pooler_output.")
        return pooler

    hidden = getattr(output, "last_hidden_state", None)
    if hidden is None and isinstance(output, (tuple, list)) and output:
        hidden = output[0]
    if hidden is None:
        raise ValueError("Model output does not contain last_hidden_state.")

    if pooling == "cls":
        return hidden[:, 0, :]
    if pooling == "mean_last_hidden_state":
        mask = encoded["attention_mask"].unsqueeze(-1)
        return (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
    raise ValueError(f"Unsupported pooling: {pooling}")


def _hf_embeddings(mol_table: pd.DataFrame, spec: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
    model_dir = _require_model_dir(spec)
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("torch and transformers are required for Hugging Face pretrained embedding sets.") from exc

    params = dict(spec.get("params") or {})
    trust_remote_code = bool(params.get("trust_remote_code", spec.get("trust_remote_code", False)))
    pooling = str(params.get("pooling", spec.get("pooling", "mean_last_hidden_state")))
    batch_size = int(params.get("batch_size", 32))
    max_length = int(params.get("max_length", 256))
    device = str(params.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    input_format = str(params.get("input_format", "smiles"))

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=trust_remote_code)
    model = AutoModel.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=trust_remote_code)
    model.to(device)
    model.eval()

    texts = _text_values(mol_table, input_format)
    vectors: list[list[float]] = []
    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            output = model(**encoded)
            pooled = _pool_hf_output(output, encoded, pooling)
            vectors.extend(pooled.detach().cpu().float().numpy().tolist())
    metadata = {
        "loader": "huggingface_transformers",
        "model_dir": str(model_dir),
        "input_format": input_format,
        "pooling": pooling,
        "device": device,
        "max_length": max_length,
    }
    return vectors, metadata


def _feature_columns_from_dataframe(df: pd.DataFrame) -> list[str]:
    non_feature = {"compound_id", "canonical_smiles", "input_smiles", "mol_parse_ok", "descriptor_error"}
    return [col for col in df.columns if col not in non_feature and pd.api.types.is_numeric_dtype(df[col])]


def _coerce_vectors(result: Any, records: list[dict[str, Any]]) -> tuple[list[list[float]], dict[str, Any]]:
    metadata: dict[str, Any] = {}
    payload = result
    if isinstance(result, tuple) and len(result) == 2:
        payload, raw_metadata = result
        if isinstance(raw_metadata, dict):
            metadata.update(raw_metadata)
    if isinstance(payload, dict):
        if isinstance(payload.get("metadata"), dict):
            metadata.update(payload["metadata"])
        for key in ["vectors", "embeddings", "repr", "representations"]:
            if key in payload:
                payload = payload[key]
                break

    if isinstance(payload, pd.DataFrame):
        feature_cols = _feature_columns_from_dataframe(payload)
        if not feature_cols:
            raise RuntimeError("Embedding DataFrame output has no numeric feature columns.")
        if "compound_id" in payload.columns:
            ordered_ids = [record["compound_id"] for record in records]
            aligned = payload.set_index("compound_id").reindex(ordered_ids)
            if aligned[feature_cols].isna().all(axis=1).any():
                missing = aligned.index[aligned[feature_cols].isna().all(axis=1)].tolist()
                raise RuntimeError(f"Embedding DataFrame output is missing compound_id rows: {missing[:5]}")
            payload = aligned[feature_cols]
        else:
            if len(payload) != len(records):
                raise RuntimeError(f"Embedding DataFrame row count mismatch: {len(payload)} rows for {len(records)} molecules.")
            payload = payload[feature_cols]
        metadata.setdefault("feature_columns", feature_cols)
        return payload.astype(float).values.tolist(), metadata

    vectors: list[list[float]] = []
    try:
        for row in payload:
            vectors.append([float(value) for value in row])
    except TypeError as exc:
        raise RuntimeError("Embedding adapter output must be a 2D vector-like object, DataFrame, or dict with vectors.") from exc
    return vectors, metadata


def _resolve_custom_adapter_path(model_dir: Path, params: dict[str, Any]) -> Path:
    adapter_path = params.get("adapter_path")
    if adapter_path:
        path = Path(str(adapter_path))
        if not path.is_absolute():
            path = model_dir / path
        if not path.exists():
            raise RuntimeError(f"Configured adapter_path does not exist: {path}")
        return path

    for name in ["conductor_embedding_adapter.py", "adapter.py"]:
        path = model_dir / name
        if path.exists():
            return path
    raise RuntimeError(
        "local_custom pretrained embedding sets require conductor_embedding_adapter.py or adapter.py "
        "inside model_dir, or params.adapter_path."
    )


def _load_custom_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"conductor_embedding_adapter_{abs(hash(path))}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load custom embedding adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _custom_embeddings(mol_table: pd.DataFrame, spec: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
    model_dir = _require_model_dir(spec)
    params = dict(spec.get("params") or {})
    adapter_path = _resolve_custom_adapter_path(model_dir, params)
    module = _load_custom_module(adapter_path)
    records = _valid_records(mol_table)
    smiles = [str(record["canonical_smiles"]) for record in records]

    if hasattr(module, "embed_molecules"):
        result = module.embed_molecules(records, model_dir=str(model_dir), params=params)
    elif hasattr(module, "embed_smiles"):
        result = module.embed_smiles(smiles, model_dir=str(model_dir), params=params)
    else:
        raise RuntimeError("Custom embedding adapter must define embed_molecules(records, model_dir, params) or embed_smiles(smiles, model_dir, params).")

    vectors, metadata = _coerce_vectors(result, records)
    metadata.update({"loader": "local_custom", "model_dir": str(model_dir), "adapter_path": str(adapter_path)})
    return vectors, metadata


def _external_command_embeddings(mol_table: pd.DataFrame, spec: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
    params = dict(spec.get("params") or {})
    command = params.get("command")
    if not command:
        raise RuntimeError("external_command pretrained embedding sets require params.command.")
    model_dir = _optional_model_dir(spec)
    records = _valid_records(mol_table)
    with tempfile.TemporaryDirectory(prefix="conductor_embedding_") as temp_dir:
        work_dir = Path(temp_dir)
        input_csv = work_dir / "input_smiles.csv"
        output_csv = work_dir / "output_embeddings.csv"
        input_df = pd.DataFrame(records, columns=["row_index", "compound_id", "input_smiles", "canonical_smiles"])
        input_df[["compound_id", "canonical_smiles"]].to_csv(input_csv, index=False)
        mapping = {
            "input_csv": str(input_csv),
            "output_csv": str(output_csv),
            "model_dir": str(model_dir) if model_dir else "",
            "work_dir": str(work_dir),
        }
        if isinstance(command, list):
            run_command: str | list[str] = [str(part).format(**mapping) for part in command]
            shell = False
        else:
            run_command = str(command).format(**mapping)
            shell = True
        completed = subprocess.run(run_command, cwd=str(work_dir), capture_output=True, text=True, shell=shell)
        if completed.returncode != 0:
            raise RuntimeError(
                "external_command embedding failed with exit code "
                f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
        if not output_csv.exists():
            raise RuntimeError(f"external_command did not create expected output CSV: {output_csv}")
        output_df = pd.read_csv(output_csv)
    vectors, metadata = _coerce_vectors(output_df, records)
    metadata.update({"loader": "external_command", "model_dir": str(model_dir) if model_dir else "", "command": command})
    return vectors, metadata


def _unimol_embeddings(mol_table: pd.DataFrame, spec: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
    model_dir = _require_model_dir(spec)
    try:
        from unimol_tools import UniMolRepr
    except ImportError as exc:
        raise RuntimeError("Uni-Mol embeddings require the unimol_tools package.") from exc

    params = dict(spec.get("params") or {})
    init_kwargs: dict[str, Any] = {
        "data_type": params.get("data_type", "molecule"),
        "remove_hs": bool(params.get("remove_hs", False)),
        "use_cuda": bool(params.get("use_cuda", False)),
        "save_path": str(params.get("save_path") or model_dir),
    }
    for key in ["model_name", "model_size"]:
        if params.get(key) is not None:
            init_kwargs[key] = params[key]
    try:
        model = UniMolRepr(**init_kwargs)
    except TypeError:
        reduced = {key: value for key, value in init_kwargs.items() if key in {"data_type", "remove_hs", "use_cuda"}}
        model = UniMolRepr(**reduced)

    records = _valid_records(mol_table)
    smiles = [str(record["canonical_smiles"]) for record in records]
    result = model.get_repr(smiles, return_atomic_reprs=False)
    payload: Any = result
    if isinstance(result, dict):
        for key in ["cls_repr", "molecular_reprs", "molecule_repr", "repr", "representations"]:
            if key in result:
                payload = result[key]
                break
    vectors, metadata = _coerce_vectors(payload, records)
    metadata.update({"loader": "unimol_local", "model_dir": str(model_dir), "init_kwargs": init_kwargs})
    return vectors, metadata


def _find_mol2vec_model_file(model_dir: Path, params: dict[str, Any]) -> Path:
    model_file = params.get("model_file")
    if model_file:
        path = Path(str(model_file))
        if not path.is_absolute():
            path = model_dir / path
        if not path.exists():
            raise RuntimeError(f"Configured mol2vec model_file does not exist: {path}")
        return path
    for name in ["model.pkl", "mol2vec_model.pkl", "model.bin", "mol2vec.pkl", "model.word2vec"]:
        path = model_dir / name
        if path.exists():
            return path
    raise RuntimeError("mol2vec_local requires params.model_file or a known mol2vec model file inside model_dir.")


def _load_mol2vec_vectors(model_file: Path, binary: bool) -> Any:
    try:
        from gensim.models import KeyedVectors, Word2Vec
    except ImportError as exc:
        raise RuntimeError("mol2vec embeddings require gensim and mol2vec packages.") from exc

    load_errors: list[str] = []
    try:
        model = Word2Vec.load(str(model_file))
        return model.wv
    except Exception as exc:
        load_errors.append(f"Word2Vec.load: {exc}")
    try:
        return KeyedVectors.load(str(model_file))
    except Exception as exc:
        load_errors.append(f"KeyedVectors.load: {exc}")
    try:
        return KeyedVectors.load_word2vec_format(str(model_file), binary=binary)
    except Exception as exc:
        load_errors.append(f"load_word2vec_format: {exc}")
    raise RuntimeError(f"Failed to load mol2vec model file {model_file}: {'; '.join(load_errors)}")


def _mol2vec_embeddings(mol_table: pd.DataFrame, spec: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
    model_dir = _require_model_dir(spec)
    params = dict(spec.get("params") or {})
    model_file = _find_mol2vec_model_file(model_dir, params)
    try:
        from mol2vec.features import mol2alt_sentence
    except ImportError as exc:
        raise RuntimeError("mol2vec embeddings require the mol2vec package.") from exc

    wv = _load_mol2vec_vectors(model_file, bool(params.get("binary", False)))
    radius = int(params.get("radius", 1))
    dim = int(getattr(wv, "vector_size", 0))
    if dim <= 0:
        raise RuntimeError("Loaded mol2vec model does not expose vector_size.")

    vectors: list[list[float]] = []
    records = _valid_records(mol_table)
    valid_positions = _valid_positions(mol_table)
    for idx in valid_positions:
        mol = mol_table.loc[idx, "mol"]
        sentence = mol2alt_sentence(mol, radius)
        token_vectors = [wv[token] for token in sentence if token in wv]
        if token_vectors:
            summed = [0.0] * dim
            for vector in token_vectors:
                for pos, value in enumerate(vector):
                    summed[pos] += float(value)
            vectors.append([value / len(token_vectors) for value in summed])
        else:
            vectors.append([0.0] * dim)
    metadata = {"loader": "mol2vec_local", "model_dir": str(model_dir), "model_file": str(model_file), "radius": radius}
    return vectors, metadata


def compute_pretrained_embedding_set(mol_table: pd.DataFrame, set_id: str, spec: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    loader = spec.get("loader") or (spec.get("params") or {}).get("loader") or ""
    loader = str(loader)
    vectors: list[list[float]]
    metadata: dict[str, Any]
    if loader in {"huggingface_transformers", "huggingface_transformers_trust_remote_code", "generic_torch_sequence"}:
        if loader == "huggingface_transformers_trust_remote_code":
            spec = {**spec, "trust_remote_code": True}
        vectors, metadata = _hf_embeddings(mol_table, spec)
    elif loader == "local_custom":
        vectors, metadata = _custom_embeddings(mol_table, spec)
    elif loader == "external_command":
        vectors, metadata = _external_command_embeddings(mol_table, spec)
    elif loader == "unimol_local":
        vectors, metadata = _unimol_embeddings(mol_table, spec)
    elif loader == "mol2vec_local":
        vectors, metadata = _mol2vec_embeddings(mol_table, spec)
    else:
        model_dir = spec.get("model_dir") or (spec.get("params") or {}).get("model_dir")
        if model_dir:
            _require_model_dir(spec)
        raise RuntimeError(f"Unknown pretrained embedding loader: {loader}")

    valid_positions = _valid_positions(mol_table)
    if len(vectors) != len(valid_positions):
        raise RuntimeError(f"Embedding vector count mismatch for {set_id}: {len(vectors)} vectors for {len(valid_positions)} valid molecules.")
    dim = len(vectors[0]) if vectors else 0
    feature_cols = [f"embedding__dim_{i:04d}" for i in range(dim)]
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    vector_by_index = {idx: vectors[pos] for pos, idx in enumerate(valid_positions)}

    for idx, mol_row in mol_table.iterrows():
        if not bool(mol_row["mol_parse_ok"]):
            message = str(mol_row["mol_error"])
            rows.append(base_record(mol_row, message))
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
            vector = vector_by_index[idx]
            rows.append({**base_record(mol_row), **{col: float(value) for col, value in zip(feature_cols, vector)}})
        except Exception as exc:
            rows.append(base_record(mol_row, str(exc)))
            errors.append(
                {
                    "compound_id": mol_row["compound_id"],
                    "input_smiles": mol_row["input_smiles"],
                    "canonical_smiles": mol_row["canonical_smiles"],
                    "descriptor_set": set_id,
                    "error_type": "descriptor_error",
                    "error_message": str(exc),
                    "traceback": tb.format_exc(),
                }
            )
    df = pd.DataFrame(rows)
    common = ["compound_id", "canonical_smiles", "mol_parse_ok", "descriptor_error"]
    df.attrs["descriptor_metadata"] = {**metadata, "actual_dimension": dim, "set_id": set_id}
    return df[common + feature_cols], errors
