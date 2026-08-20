from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors


DETAIL_COLUMNS = [
    "mmp_id", "compound_id_from", "compound_id_to", "smiles_from", "smiles_to",
    "endpoint_from", "endpoint_to", "endpoint_delta", "favorable_delta",
    "transform_id", "variable_from", "variable_to", "transform_smirks",
    "core_id", "exact_core_smiles", "core_heavy_atoms", "core_fraction_from",
    "core_fraction_to", "core_molecular_weight", "core_class", "eligibility_tier",
    "cut_count", "attachment_mapping", "native_rule_id", "endpoint_missing", "quality_flags",
    "environment_radius_0", "environment_radius_1", "environment_radius_2",
    "environment_radius_3", "environment_radius_4", "environment_radius_5",
    "environment_smarts_radius_0", "environment_smarts_radius_1", "environment_smarts_radius_2",
    "environment_smarts_radius_3", "environment_smarts_radius_4", "environment_smarts_radius_5",
    "environment_pseudosmiles_radius_0", "environment_pseudosmiles_radius_1", "environment_pseudosmiles_radius_2",
    "environment_pseudosmiles_radius_3", "environment_pseudosmiles_radius_4", "environment_pseudosmiles_radius_5",
]

CONTEXT_COLUMNS = [
    "context_id", "compound_id_from", "compound_id_to", "variable_from", "variable_to",
    "exact_core_smiles", "native_rule_id", "radius", "environment_smarts",
    "environment_pseudosmiles", "parent_smarts", "mmp_id",
]

SUMMARY_METRIC_COLUMNS = [
    "mmp_instance_count", "pair_count", "endpoint_pair_count", "independent_compound_count",
    "independent_core_count", "median_favorable_delta",
    "q1_favorable_delta", "q3_favorable_delta", "iqr_favorable_delta", "mad_favorable_delta",
    "direction_consistency", "core_weighted_median", "leave_one_core_out_sign_stability",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(prefix: str, *values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12].upper()}"


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def heavy_atoms(smiles: str) -> int:
    molecule = Chem.MolFromSmiles(str(smiles))
    if molecule is None:
        return 0
    return sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())


def load_input(
    input_path: Path,
    id_column: str,
    smiles_column: str,
    endpoint_column: str,
    max_compounds: int,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    frame = pd.read_csv(input_path)
    missing = [name for name in (id_column, smiles_column, endpoint_column) if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing required input columns: {missing}")
    selected = frame[[id_column, smiles_column, endpoint_column]].copy()
    selected.columns = ["compound_id", "smiles", "endpoint"]
    selected["compound_id"] = selected["compound_id"].astype(str).str.strip()
    selected["smiles"] = selected["smiles"].fillna("").astype(str).str.strip()
    if selected["compound_id"].eq("").any():
        raise ValueError("Empty compound ID is not allowed")
    duplicates = selected.loc[selected["compound_id"].duplicated(keep=False), "compound_id"].unique().tolist()
    if duplicates:
        raise ValueError(f"Duplicate compound IDs are not allowed: {duplicates[:10]}")
    if len(selected) > max_compounds:
        raise ValueError(f"Input contains {len(selected)} compounds; maximum is {max_compounds}")
    selected["endpoint"] = pd.to_numeric(selected["endpoint"], errors="coerce")
    selected["valid_smiles"] = selected["smiles"].map(lambda value: Chem.MolFromSmiles(value) is not None)
    selected["heavy_atoms"] = selected["smiles"].map(heavy_atoms)
    warnings: list[str] = []
    invalid = selected.loc[~selected["valid_smiles"], "compound_id"].tolist()
    if invalid:
        warnings.append(f"Invalid SMILES rows were retained in coverage but excluded from MMP generation: {len(invalid)}")
    valid = selected[selected["valid_smiles"]].copy()
    coverage = selected.assign(
        mmp_eligible=selected["valid_smiles"],
        endpoint_available=selected["endpoint"].notna(),
        exclusion_reason=np.where(selected["valid_smiles"], "", "invalid_smiles"),
    )
    return valid, coverage, warnings


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"mmpdb command failed ({completed.returncode}): {message[-4000:]}")


def build_native_database(
    valid: pd.DataFrame,
    work_dir: Path,
    *,
    jobs: int,
    num_cuts: int,
    min_core_heavy_atoms: int,
    extended_core_fraction: float,
    min_radius: int,
    max_radius: int,
    cut_smarts: str,
) -> tuple[Path, Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    smiles_file = work_dir / "input.smi"
    fragment_db = work_dir / "input.fragdb"
    native_db = work_dir / "mmpdb_native.sqlite"
    smiles_file.write_text(
        "".join(f"{row.smiles}\t{row.compound_id}\n" for row in valid.itertuples(index=False)),
        encoding="utf-8",
    )
    fragment_marker = work_dir / "fragment.complete.json"
    fragment_spec = {
        "input_sha256": sha256_file(smiles_file), "num_cuts": num_cuts,
        "min_core_heavy_atoms": min_core_heavy_atoms, "jobs": jobs, "cut_smarts": cut_smarts,
    }
    if not (fragment_db.is_file() and fragment_marker.is_file() and json.loads(fragment_marker.read_text(encoding="utf-8")) == fragment_spec):
        fragment_db.unlink(missing_ok=True)
        _run([
            sys.executable, "-m", "mmpdblib", "fragment", str(smiles_file),
            "--delimiter", "tab", "--salt-remover", "<none>", "--num-cuts", str(num_cuts),
            "--min-heavies-total-const-frag", str(min_core_heavy_atoms),
            "--max-heavies", "none", "--max-rotatable-bonds", "1000",
            "--cut-smarts", cut_smarts, "--num-jobs", str(max(1, jobs)),
            "--output", str(fragment_db),
        ], work_dir)
        fragment_marker.write_text(json.dumps(fragment_spec, sort_keys=True), encoding="utf-8")
    index_marker = work_dir / "index.complete.json"
    index_spec = {
        "fragment_sha256": sha256_file(fragment_db), "extended_core_fraction": extended_core_fraction,
        "min_radius": min_radius, "max_radius": max_radius, "output_format": "mmpdb",
    }
    if not (native_db.is_file() and index_marker.is_file() and json.loads(index_marker.read_text(encoding="utf-8")) == index_spec):
        native_db.unlink(missing_ok=True)
        _run([
            sys.executable, "-m", "mmpdblib", "index", str(fragment_db),
            "--max-variable-heavies", "none", "--max-variable-ratio", str(1.0 - extended_core_fraction),
            "--min-radius", str(min_radius), "--max-radius", str(max_radius),
            "--out", "mmpdb", "--output", str(native_db),
        ], work_dir)
        index_marker.write_text(json.dumps(index_spec, sort_keys=True), encoding="utf-8")
    return fragment_db, native_db


def extract_pairs(
    native_db: Path,
    endpoints: dict[str, float],
    *,
    higher_is_better: bool,
    min_core_heavy_atoms: int,
    extended_core_fraction: float,
    primary_core_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    query = """
    SELECT p.id AS native_pair_id, re.radius, ef.smarts AS environment_smarts,
           ef.pseudosmiles AS environment_pseudosmiles, ef.parent_smarts,
           r.id AS native_rule_id, lhs.smiles AS variable_from, rhs.smiles AS variable_to,
           cs.smiles AS exact_core_smiles,
           c1.public_id AS compound_id_from, c1.input_smiles AS smiles_from,
           c1.clean_num_heavies AS heavies_from,
           c2.public_id AS compound_id_to, c2.input_smiles AS smiles_to,
           c2.clean_num_heavies AS heavies_to
      FROM pair p
      JOIN rule_environment re ON re.id = p.rule_environment_id
      JOIN environment_fingerprint ef ON ef.id = re.environment_fingerprint_id
      JOIN rule r ON r.id = re.rule_id
      JOIN rule_smiles lhs ON lhs.id = r.from_smiles_id
      JOIN rule_smiles rhs ON rhs.id = r.to_smiles_id
      JOIN constant_smiles cs ON cs.id = p.constant_id
      JOIN compound c1 ON c1.id = p.compound1_id
      JOIN compound c2 ON c2.id = p.compound2_id
     ORDER BY c1.public_id, c2.public_id, r.id, cs.smiles, re.radius
    """
    with closing(sqlite3.connect(native_db)) as connection:
        native = pd.read_sql_query(query, connection)
    identity_columns = ["compound_id_from", "compound_id_to", "variable_from", "variable_to", "exact_core_smiles"]
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    context_rows: list[dict[str, Any]] = []
    for row in native.itertuples(index=False):
        key = (
            str(row.compound_id_from), str(row.compound_id_to), str(row.variable_from),
            str(row.variable_to), str(row.exact_core_smiles),
        )
        record = grouped.setdefault(key, {
            "compound_id_from": str(row.compound_id_from), "compound_id_to": str(row.compound_id_to),
            "smiles_from": str(row.smiles_from), "smiles_to": str(row.smiles_to),
            "variable_from": str(row.variable_from), "variable_to": str(row.variable_to),
            "exact_core_smiles": str(row.exact_core_smiles), "native_rule_id": int(row.native_rule_id),
            "heavies_from": int(row.heavies_from), "heavies_to": int(row.heavies_to),
        })
        radius = int(row.radius)
        context_id = stable_id("CTX", key, radius, str(row.environment_smarts))
        record[f"environment_radius_{radius}"] = context_id
        record[f"environment_smarts_radius_{radius}"] = str(row.environment_smarts)
        record[f"environment_pseudosmiles_radius_{radius}"] = str(row.environment_pseudosmiles)
        context_rows.append({
            "context_id": context_id, "compound_id_from": key[0], "compound_id_to": key[1],
            "variable_from": key[2], "variable_to": key[3], "exact_core_smiles": key[4],
            "native_rule_id": int(row.native_rule_id), "radius": radius,
            "environment_smarts": str(row.environment_smarts),
            "environment_pseudosmiles": str(row.environment_pseudosmiles),
            "parent_smarts": str(row.parent_smarts),
        })
    records: list[dict[str, Any]] = []
    for key, record in grouped.items():
        core_heavies = heavy_atoms(record["exact_core_smiles"])
        fraction_from = core_heavies / max(1, record.pop("heavies_from"))
        fraction_to = core_heavies / max(1, record.pop("heavies_to"))
        if core_heavies < min_core_heavy_atoms or min(fraction_from, fraction_to) < extended_core_fraction:
            continue
        core_class = "primary" if min(fraction_from, fraction_to) >= primary_core_fraction else "extended"
        endpoint_from = endpoints.get(record["compound_id_from"], math.nan)
        endpoint_to = endpoints.get(record["compound_id_to"], math.nan)
        delta = endpoint_to - endpoint_from if math.isfinite(endpoint_from) and math.isfinite(endpoint_to) else math.nan
        transform_id = stable_id("TRF", record["variable_from"], record["variable_to"])
        core_id = stable_id("CORE", record["exact_core_smiles"])
        mmp_id = stable_id("MMP", *key)
        core_molecule = Chem.MolFromSmiles(record["exact_core_smiles"])
        attachment_labels = sorted({atom.GetAtomMapNum() for atom in core_molecule.GetAtoms() if atom.GetAtomicNum() == 0}) if core_molecule else []
        endpoint_missing = not math.isfinite(delta)
        record.update({
            "mmp_id": mmp_id, "endpoint_from": endpoint_from, "endpoint_to": endpoint_to,
            "endpoint_delta": delta, "favorable_delta": delta if higher_is_better else -delta,
            "transform_id": transform_id, "transform_smirks": f"{record['variable_from']}>>{record['variable_to']}",
            "core_id": core_id, "core_heavy_atoms": core_heavies,
            "core_fraction_from": fraction_from, "core_fraction_to": fraction_to,
            "core_molecular_weight": float(Descriptors.MolWt(core_molecule)) if core_molecule else math.nan,
            "core_class": core_class, "eligibility_tier": core_class,
            "cut_count": max(1, record["variable_from"].count("[*:")),
            "attachment_mapping": json.dumps(attachment_labels, separators=(",", ":")),
            "endpoint_missing": endpoint_missing,
            "quality_flags": "missing_endpoint" if endpoint_missing else "",
        })
        records.append(record)
    details = pd.DataFrame(records)
    if details.empty:
        details = pd.DataFrame(columns=DETAIL_COLUMNS)
    else:
        for column in DETAIL_COLUMNS:
            if column not in details:
                details[column] = ""
        details = details[DETAIL_COLUMNS].sort_values("mmp_id").reset_index(drop=True)
    contexts = pd.DataFrame(context_rows, columns=[column for column in CONTEXT_COLUMNS if column != "mmp_id"])
    if len(contexts) and len(details):
        identity = details[identity_columns + ["mmp_id"]].drop_duplicates(identity_columns)
        contexts = contexts.merge(identity, on=identity_columns, how="inner", validate="many_to_one")
        contexts = contexts.drop_duplicates("context_id").sort_values(["mmp_id", "radius", "context_id"]).reset_index(drop=True)
    if "mmp_id" not in contexts:
        contexts["mmp_id"] = pd.Series(dtype="object")
    contexts = contexts[CONTEXT_COLUMNS]
    return details, contexts


def robust_summary(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*group_columns, *SUMMARY_METRIC_COLUMNS])
    output: list[dict[str, Any]] = []
    grouped: Iterable[tuple[Any, pd.DataFrame]] = frame.groupby(group_columns, dropna=False) if len(frame) else []
    for key, group in grouped:
        keys = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_columns, keys))
        group = group.copy()
        group["_effect"] = pd.to_numeric(group["favorable_delta"], errors="coerce")
        has_pair_identity = {"compound_id_from", "compound_id_to"}.issubset(group.columns)
        if has_pair_identity:
            pair_effects = group.groupby(["compound_id_from", "compound_id_to"], dropna=False)["_effect"].median().dropna()
            pair_count = int(group[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0])
            independent_compounds = len(set(group["compound_id_from"].astype(str)) | set(group["compound_id_to"].astype(str)))
        else:
            pair_effects = group["_effect"].dropna()
            pair_count = int(len(group))
            independent_compounds = 0
        effects = pair_effects
        core_medians = group.assign(_effect=pd.to_numeric(group["favorable_delta"], errors="coerce")).groupby("core_id")["_effect"].median().dropna()
        median = float(effects.median()) if len(effects) else math.nan
        direction_consistency = float(max((effects > 0).mean(), (effects < 0).mean())) if len(effects) else math.nan
        loo_signs = []
        if len(core_medians) >= 3:
            for core_id in core_medians.index:
                remainder_frame = group[group["core_id"] != core_id]
                if has_pair_identity:
                    remainder = remainder_frame.groupby(["compound_id_from", "compound_id_to"], dropna=False)["_effect"].median().dropna()
                else:
                    remainder = remainder_frame["_effect"].dropna()
                if len(remainder):
                    loo_signs.append(np.sign(float(remainder.median())))
        row.update({
            "mmp_instance_count": int(len(group)), "pair_count": pair_count,
            "endpoint_pair_count": int(len(effects)), "independent_compound_count": int(independent_compounds),
            "independent_core_count": int(group["core_id"].nunique()),
            "median_favorable_delta": median,
            "q1_favorable_delta": float(effects.quantile(0.25)) if len(effects) else math.nan,
            "q3_favorable_delta": float(effects.quantile(0.75)) if len(effects) else math.nan,
            "iqr_favorable_delta": float(effects.quantile(0.75) - effects.quantile(0.25)) if len(effects) else math.nan,
            "mad_favorable_delta": float((effects - median).abs().median()) if len(effects) else math.nan,
            "direction_consistency": direction_consistency,
            "core_weighted_median": float(core_medians.median()) if len(core_medians) else math.nan,
            "leave_one_core_out_sign_stability": float(np.mean(np.asarray(loo_signs) == np.sign(median))) if loo_signs and median != 0 else math.nan,
        })
        output.append(row)
    return pd.DataFrame(output, columns=[*group_columns, *SUMMARY_METRIC_COLUMNS])


def summary_tables(details: pd.DataFrame, contexts: pd.DataFrame, coverage: pd.DataFrame) -> dict[str, pd.DataFrame]:
    transforms = robust_summary(details, ["transform_id", "variable_from", "variable_to", "transform_smirks"])
    cores = robust_summary(details, ["core_id", "exact_core_smiles", "core_class"])
    transform_core = robust_summary(details, ["transform_id", "core_id", "transform_smirks", "exact_core_smiles"])
    pairs = robust_summary(details, ["compound_id_from", "compound_id_to"])
    if len(pairs):
        pair_index = details.groupby(["compound_id_from", "compound_id_to"], dropna=False).agg(
            transform_count=("transform_id", "nunique"), exact_core_count=("core_id", "nunique"),
            primary_mmp_count=("core_class", lambda values: int((values == "primary").sum())),
            extended_mmp_count=("core_class", lambda values: int((values == "extended").sum())),
            endpoint_delta=("endpoint_delta", "first"),
            mmp_ids=("mmp_id", lambda values: "|".join(sorted(set(map(str, values))))),
        ).reset_index()
        pairs = pairs.merge(pair_index, on=["compound_id_from", "compound_id_to"], how="left")
    else:
        for column in ("transform_count", "exact_core_count", "primary_mmp_count", "extended_mmp_count", "endpoint_delta", "mmp_ids"):
            pairs[column] = pd.Series(dtype="object")
    if len(contexts) and len(details):
        context_effects = contexts.merge(details[["mmp_id", "transform_id", "core_id", "favorable_delta"]], on="mmp_id", how="left")
        context_summary = robust_summary(context_effects, ["transform_id", "radius", "environment_smarts"])
    else:
        context_summary = pd.DataFrame(columns=["transform_id", "radius", "environment_smarts", *SUMMARY_METRIC_COLUMNS])
    coverage_summary = pd.DataFrame([
        {"metric": "input_compounds", "value": int(len(coverage))},
        {"metric": "valid_smiles", "value": int(coverage["valid_smiles"].sum())},
        {"metric": "invalid_smiles", "value": int((~coverage["valid_smiles"]).sum())},
        {"metric": "endpoint_available", "value": int(coverage["endpoint_available"].sum())},
        {"metric": "mmp_rows", "value": int(len(details))},
        {"metric": "compounds_in_mmp", "value": int(len(set(details.get("compound_id_from", [])) | set(details.get("compound_id_to", []))))},
    ])
    return {
        "pair_summary": pairs, "transform_summary": transforms, "core_summary": cores,
        "transform_core_summary": transform_core, "context_summary": context_summary,
        "coverage_summary": coverage_summary,
    }


def write_stable_database(
    path: Path,
    details: pd.DataFrame,
    contexts: pd.DataFrame,
    coverage: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    metadata: dict[str, Any],
) -> None:
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
        connection.executemany("INSERT INTO metadata(key, value_json) VALUES (?, ?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()])
        coverage.to_sql("compounds", connection, index=False)
        transform_columns = ["transform_id", "variable_from", "variable_to", "transform_smirks", "cut_count"]
        core_columns = ["core_id", "exact_core_smiles", "core_heavy_atoms", "core_molecular_weight"]
        details[transform_columns].drop_duplicates("transform_id").to_sql("transforms", connection, index=False)
        details[core_columns].drop_duplicates("core_id").to_sql("cores", connection, index=False)
        details.to_sql("mmp_pairs", connection, index=False)
        contexts.to_sql("mmp_contexts", connection, index=False)
        for name, frame in summaries.items():
            frame.to_sql(name, connection, index=False)
        if "mmp_id" in details:
            connection.execute("CREATE UNIQUE INDEX idx_mmp_pairs_id ON mmp_pairs(mmp_id)")
            connection.execute("CREATE INDEX idx_mmp_pairs_compounds ON mmp_pairs(compound_id_from, compound_id_to)")
            connection.execute("CREATE INDEX idx_mmp_pairs_transform ON mmp_pairs(transform_id)")
            connection.execute("CREATE INDEX idx_mmp_pairs_core ON mmp_pairs(core_id)")
        if "mmp_id" in contexts:
            connection.execute("CREATE INDEX idx_mmp_contexts_mmp ON mmp_contexts(mmp_id)")
        connection.commit()


def copy_native_database(native_db: Path, destination: Path) -> None:
    destination.unlink(missing_ok=True)
    shutil.copy2(native_db, destination)
