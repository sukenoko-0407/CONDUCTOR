from __future__ import annotations

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


def _smiles_values(mol_table: pd.DataFrame) -> list[str]:
    return [str(row["canonical_smiles"]) for _, row in mol_table.iterrows() if bool(row["mol_parse_ok"])]


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

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=trust_remote_code)
    model = AutoModel.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=trust_remote_code)
    model.to(device)
    model.eval()

    smiles = _smiles_values(mol_table)
    vectors: list[list[float]] = []
    with torch.no_grad():
        for start in range(0, len(smiles), batch_size):
            batch = smiles[start : start + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            output = model(**encoded)
            hidden = output.last_hidden_state
            if pooling == "cls":
                pooled = hidden[:, 0, :]
            elif pooling == "mean_last_hidden_state":
                mask = encoded["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            else:
                raise ValueError(f"Unsupported pooling: {pooling}")
            vectors.extend(pooled.detach().cpu().float().numpy().tolist())
    metadata = {
        "loader": "huggingface_transformers",
        "model_dir": str(model_dir),
        "pooling": pooling,
        "device": device,
        "max_length": max_length,
    }
    return vectors, metadata


def _unsupported_loader(spec: dict[str, Any]) -> None:
    loader = spec.get("loader") or (spec.get("params") or {}).get("loader") or "unknown"
    model_dir = spec.get("model_dir") or (spec.get("params") or {}).get("model_dir")
    if model_dir:
        _require_model_dir(spec)
    raise RuntimeError(
        f"Embedding loader '{loader}' is registered but does not yet have a runnable adapter. "
        "Add a model-specific adapter under src/embeddings before executing this set."
    )


def compute_pretrained_embedding_set(mol_table: pd.DataFrame, set_id: str, spec: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    loader = spec.get("loader") or (spec.get("params") or {}).get("loader") or ""
    loader = str(loader)
    vectors: list[list[float]]
    metadata: dict[str, Any]
    if loader in {"huggingface_transformers", "huggingface_transformers_trust_remote_code", "generic_torch_sequence"}:
        if loader == "huggingface_transformers_trust_remote_code":
            spec = {**spec, "trust_remote_code": True}
        vectors, metadata = _hf_embeddings(mol_table, spec)
    else:
        _unsupported_loader(spec)

    valid_positions = [idx for idx, row in mol_table.iterrows() if bool(row["mol_parse_ok"])]
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
