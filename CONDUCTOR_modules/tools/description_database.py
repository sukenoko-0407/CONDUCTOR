from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0.0"
COMMON_COLUMNS = (
    "compound_id",
    "input_smiles",
    "mol_parse_ok",
    "description_error",
)
CALCULATION_VERSION_PATTERN = re.compile(r"^[1-9][0-9]*$")


def required_calculation_version(capability: dict[str, Any]) -> str:
    """Return the explicit Description calculation contract version."""
    value = capability.get("calculation_version")
    if not isinstance(value, str) or not CALCULATION_VERSION_PATTERN.fullmatch(value):
        raise ValueError(
            "Description capability calculation_version must be an explicit "
            "positive-integer string"
        )
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def object_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def row_json(row: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        try:
            import pandas as pd

            if pd.isna(value):
                value = None
        except (ImportError, TypeError, ValueError):
            pass
        normalized[str(key)] = value
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def canonical_smiles(value: Any) -> tuple[str, bool]:
    raw = "" if value is None else str(value)
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError("RDKit is required for Description cache identity") from exc
    molecule = Chem.MolFromSmiles(raw) if raw else None
    if molecule is None:
        return raw, False
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True), True


def database_root(project_root: Path, program_name: str) -> Path:
    return project_root / "data" / "description_database" / program_name


def database_path(
    project_root: Path,
    program_name: str,
    capability_id: str,
    skill_name: str,
) -> Path:
    return (
        database_root(project_root, program_name)
        / f"{capability_id}__{skill_name}"
        / "description.sqlite3"
    )


def audit_path(database: Path) -> Path:
    return database.parent / "audit.jsonl"


def program_registry_path(database: Path) -> Path:
    return database.parent.parent / "compound_registry.sqlite3"


def _connect_program_registry(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS compounds (
            compound_id TEXT PRIMARY KEY,
            calculation_smiles TEXT NOT NULL,
            calculation_smiles_sha256 TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            first_source_run_id TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _connect(path: Path, *, create: bool = True) -> sqlite3.Connection:
    if not create and not path.is_file():
        raise FileNotFoundError(f"Description Database does not exist: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    _initialize(connection)
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            calculation_version TEXT NOT NULL,
            skill_version TEXT NOT NULL,
            configuration_signature TEXT NOT NULL,
            compound_id TEXT NOT NULL,
            original_input_smiles TEXT NOT NULL,
            original_input_smiles_sha256 TEXT NOT NULL,
            calculation_smiles TEXT NOT NULL,
            calculation_smiles_sha256 TEXT NOT NULL,
            schema_signature TEXT NOT NULL,
            feature_columns_json TEXT NOT NULL,
            value_semantics TEXT NOT NULL,
            natural_metric TEXT NOT NULL,
            row_json TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            record_status TEXT NOT NULL DEFAULT 'active',
            computed_at TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            source_round_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            invalidated_at TEXT,
            invalidated_by TEXT,
            invalidation_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS records_lookup
        ON records(configuration_signature, compound_id, calculation_smiles_sha256, record_status);
        CREATE INDEX IF NOT EXISTS records_compound
        ON records(compound_id, record_status);
        CREATE TABLE IF NOT EXISTS compound_registry (
            compound_id TEXT PRIMARY KEY,
            calculation_smiles TEXT NOT NULL,
            calculation_smiles_sha256 TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            first_source_run_id TEXT NOT NULL
        );
        """
    )
    stored = connection.execute(
        "SELECT value FROM metadata WHERE key='schema_version'"
    ).fetchone()
    if stored and stored["value"] != SCHEMA_VERSION:
        raise RuntimeError(
            "Unsupported Description Database schema_version "
            f"{stored['value']!r}; expected {SCHEMA_VERSION!r}"
        )
    connection.execute(
        "INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version',?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def environment_signature(skill_dir: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    env_dir = skill_dir / "env"
    for name in ("pixi.toml", "pixi.lock", "model_path.txt"):
        path = env_dir / name
        if path.is_file():
            values[name] = file_hash(path)
    model_pointer = env_dir / "model_path.txt"
    if model_pointer.is_file():
        raw = model_pointer.read_text(encoding="utf-8").strip()
        model_dir = Path(raw).expanduser()
        if not model_dir.is_absolute():
            model_dir = (model_pointer.parent / model_dir).resolve()
        if model_dir.is_dir():
            model_files: list[dict[str, Any]] = []
            for path in sorted(item for item in model_dir.rglob("*") if item.is_file()):
                relative = path.relative_to(model_dir).as_posix()
                stat = path.stat()
                item: dict[str, Any] = {"path": relative, "size": stat.st_size}
                if path.name in {
                    "config.json", "tokenizer_config.json",
                    "special_tokens_map.json", "vocab.json",
                }:
                    item["sha256"] = file_hash(path)
                model_files.append(item)
            values["model"] = object_hash(model_files)
        else:
            values["model"] = {"unresolved_path": raw}
    return values


def calculation_signature(
    capability: dict[str, Any],
    parameters: dict[str, Any],
    dataset_signature: str | None = None,
) -> str:
    calculation_version = required_calculation_version(capability)
    defaults = dict(capability.get("default_parameters") or {})
    defaults.update(parameters)
    payload: dict[str, Any] = {
        "capability_id": capability["capability_id"],
        "skill_name": capability["skill_name"],
        "calculation_version": calculation_version,
        "parameters": defaults,
        "implementation": capability.get("implementation", {}),
        "representation_id": capability.get("representation_id"),
        "value_semantics": capability.get("value_semantics"),
        "natural_metric": capability.get("natural_metric"),
        "environment": environment_signature(Path(capability["_skill_dir"])),
    }
    if dataset_signature is not None:
        payload["chemical_dataset_signature"] = dataset_signature
    return object_hash(payload)


def is_batch_dependent(
    capability: dict[str, Any], parameters: dict[str, Any]
) -> bool:
    merged = dict(capability.get("default_parameters") or {})
    merged.update(parameters)
    algorithm = str((capability.get("implementation") or {}).get("algorithm", ""))
    return algorithm == "gobbi_pharm2d" and str(merged.get("reduction", "none")) == "svd"


def _dataset_identity(
    dataset_path: Path, id_column: str, smiles_column: str
) -> tuple[Any, list[dict[str, Any]], str]:
    import pandas as pd

    header = pd.read_csv(dataset_path, nrows=0)
    missing = [
        column for column in (id_column, smiles_column)
        if column not in header.columns
    ]
    if missing:
        raise ValueError(f"Description cache input is missing columns: {missing}")
    frame = pd.read_csv(dataset_path, dtype={id_column: "string"})
    ids = frame[id_column].astype("string")
    if ids.isna().any() or ids.str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError("Description cache requires non-null unique compound IDs")
    identities: list[dict[str, Any]] = []
    for compound_id, raw_value in zip(ids.astype(str), frame[smiles_column]):
        raw = "" if pd.isna(raw_value) else str(raw_value)
        calculation, parse_ok = canonical_smiles(raw)
        identities.append({
            "compound_id": compound_id,
            "original_input_smiles": raw,
            "original_input_smiles_sha256": text_hash(raw),
            "calculation_smiles": calculation,
            "calculation_smiles_sha256": text_hash(calculation),
            "canonicalize_ok": parse_ok,
        })
    dataset_signature = object_hash([
        (item["compound_id"], item["calculation_smiles"])
        for item in identities
    ])
    return frame, identities, dataset_signature


def _append_audit(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def prepare_cache_plan(
    *,
    project_root: Path,
    program_name: str,
    dataset_path: Path,
    id_column: str,
    smiles_column: str,
    capability: dict[str, Any],
    parameters: dict[str, Any],
    scratch: Path,
    source_run_id: str,
) -> dict[str, Any]:
    calculation_version = required_calculation_version(capability)
    frame, identities, dataset_signature = _dataset_identity(
        dataset_path, id_column, smiles_column
    )
    batch_dependent = is_batch_dependent(capability, parameters)
    config_signature = calculation_signature(
        capability,
        parameters,
        dataset_signature if batch_dependent else None,
    )
    db_path = database_path(
        project_root, program_name, capability["capability_id"], capability["skill_name"]
    )
    manifest_path = db_path.parent.parent / "database_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists():
        try:
            with manifest_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "program_name": program_name,
                    "storage": "sqlite-per-description",
                    "compound_registry": "compound_registry.sqlite3",
                    "created_at": utc_now(),
                }, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            pass
    hit_ids: list[str] = []
    miss_ids: list[str] = []
    mismatch_ids: list[str] = []
    version_mismatch_ids: list[str] = []
    configuration_mismatch_ids: list[str] = []
    cache_source_versions: dict[str, int] = {}
    registry_path = program_registry_path(db_path)
    registry: dict[str, str] = {}
    if registry_path.is_file():
        with closing(_connect_program_registry(registry_path)) as connection:
            registry = {
                row["compound_id"]: row["calculation_smiles_sha256"]
                for row in connection.execute(
                    "SELECT compound_id, calculation_smiles_sha256 FROM compounds"
                )
            }
    for item in identities:
        registered = registry.get(item["compound_id"])
        if registered is not None and registered != item["calculation_smiles_sha256"]:
            mismatch_ids.append(item["compound_id"])
    if db_path.is_file() and not mismatch_ids:
        with closing(_connect(db_path, create=False)) as connection:
            for item in identities:
                row = connection.execute(
                    """
                    SELECT record_id, calculation_version, skill_version
                    FROM records
                    WHERE configuration_signature=? AND compound_id=?
                      AND calculation_smiles_sha256=? AND record_status='active'
                    ORDER BY record_id DESC LIMIT 1
                    """,
                    (
                        config_signature,
                        item["compound_id"],
                        item["calculation_smiles_sha256"],
                    ),
                ).fetchone()
                if row:
                    hit_ids.append(item["compound_id"])
                    source_key = (
                        f"calculation={row['calculation_version']};"
                        f"skill={row['skill_version']}"
                    )
                    cache_source_versions[source_key] = (
                        cache_source_versions.get(source_key, 0) + 1
                    )
                    continue
                miss_ids.append(item["compound_id"])
                alternatives = connection.execute(
                    """
                    SELECT calculation_version, configuration_signature
                    FROM records
                    WHERE compound_id=? AND calculation_smiles_sha256=?
                      AND record_status='active'
                    ORDER BY record_id DESC
                    """,
                    (item["compound_id"], item["calculation_smiles_sha256"]),
                ).fetchall()
                if alternatives:
                    if any(
                        str(value["calculation_version"])
                        == calculation_version
                        for value in alternatives
                    ):
                        configuration_mismatch_ids.append(item["compound_id"])
                    else:
                        version_mismatch_ids.append(item["compound_id"])
    elif not mismatch_ids:
        miss_ids = [item["compound_id"] for item in identities]
    if mismatch_ids:
        raise ValueError(
            "The same compound ID has a different canonical structure in this "
            f"Program: {mismatch_ids[:10]}"
        )
    if batch_dependent and miss_ids:
        hit_ids = []
        miss_ids = [item["compound_id"] for item in identities]
        cache_source_versions = {}
    subset_path: Path | None = None
    if miss_ids:
        selected = frame.loc[frame[id_column].astype(str).isin(set(miss_ids))].copy()
        canonical_map = {
            item["compound_id"]: item["calculation_smiles"] for item in identities
        }
        selected[smiles_column] = selected[id_column].astype(str).map(canonical_map)
        subset_path = scratch / "description_cache_miss_input.csv"
        subset_path.parent.mkdir(parents=True, exist_ok=True)
        selected.to_csv(subset_path, index=False)
    return {
        "schema_version": SCHEMA_VERSION,
        "program_name": program_name,
        "database_path": str(db_path.resolve()),
        "calculation_version": calculation_version,
        "skill_version": str(capability["version"]),
        "configuration_signature": config_signature,
        "chemical_dataset_signature": dataset_signature,
        "batch_dependent": batch_dependent,
        "source_dataset_path": str(dataset_path.resolve()),
        "source_dataset_sha256": file_hash(dataset_path),
        "id_column": id_column,
        "smiles_column": smiles_column,
        "input_count": len(identities),
        "hit_ids": hit_ids,
        "miss_ids": miss_ids,
        "hit_count": len(hit_ids),
        "miss_count": len(miss_ids),
        "structure_mismatch_count": 0,
        "version_mismatch_count": len(version_mismatch_ids),
        "configuration_mismatch_count": len(configuration_mismatch_ids),
        "cache_source_versions": cache_source_versions,
        "subset_path": str(subset_path.resolve()) if subset_path else None,
        "source_run_id": source_run_id,
    }


def _active_rows(plan: dict[str, Any], ids: Iterable[str]) -> dict[str, sqlite3.Row]:
    wanted = [str(value) for value in ids]
    if not wanted:
        return {}
    path = Path(plan["database_path"])
    with closing(_connect(path, create=False)) as connection:
        placeholders = ",".join("?" for _ in wanted)
        rows = connection.execute(
            f"""
            SELECT * FROM records
            WHERE configuration_signature=? AND record_status='active'
              AND compound_id IN ({placeholders})
            ORDER BY record_id DESC
            """,
            (plan["configuration_signature"], *wanted),
        ).fetchall()
    result: dict[str, sqlite3.Row] = {}
    for row in rows:
        result.setdefault(str(row["compound_id"]), row)
    missing = sorted(set(wanted) - set(result))
    if missing:
        raise RuntimeError(
            "Description cache records disappeared after planning: "
            + ", ".join(missing[:10])
        )
    schema_signatures = {row["schema_signature"] for row in result.values()}
    if len(schema_signatures) > 1:
        raise RuntimeError(
            "Description cache contains incompatible active feature schemas for one configuration"
        )
    return result


def _read_payload(path: Path) -> Any:
    import pandas as pd

    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    header = pd.read_csv(path, nrows=0)
    dtypes = {"compound_id": "string"} if "compound_id" in header.columns else None
    return pd.read_csv(path, dtype=dtypes)


def _payload_path(output: Path, capability: dict[str, Any]) -> Path | None:
    output_contract = capability.get("output") or {}
    candidates: list[str] = []
    if output_contract.get("filename"):
        candidates.append(str(output_contract["filename"]))
    if output_contract.get("basename"):
        candidates.extend([
            f"{output_contract['basename']}.csv",
            f"{output_contract['basename']}.parquet",
        ])
    for name in candidates:
        path = output / name
        if path.is_file():
            return path
    return None


def finalize_cached_output(
    *,
    plan: dict[str, Any],
    output: Path,
    request: dict[str, Any],
    capability: dict[str, Any],
) -> Path:
    import pandas as pd

    dataset_path = Path(plan["source_dataset_path"])
    if file_hash(dataset_path) != plan["source_dataset_sha256"]:
        raise ValueError("Run input changed after Description cache planning")
    _, identities, _ = _dataset_identity(
        dataset_path, plan["id_column"], plan["smiles_column"]
    )
    hits = _active_rows(plan, plan["hit_ids"])
    hit_records = {
        compound_id: json.loads(row["row_json"])
        for compound_id, row in hits.items()
    }
    miss_frame = pd.DataFrame()
    payload_path = _payload_path(output, capability)
    if plan["miss_count"]:
        if payload_path is None:
            raise FileNotFoundError("Description Skill did not produce its configured payload")
        miss_frame = _read_payload(payload_path)
        if "compound_id" not in miss_frame.columns:
            raise ValueError("Description miss payload has no compound_id column")
        miss_frame["compound_id"] = miss_frame["compound_id"].astype(str)
        actual_misses = miss_frame["compound_id"].tolist()
        if actual_misses != list(plan["miss_ids"]):
            raise ValueError(
                "Description miss payload order/content differs from the cache plan"
            )
        columns = list(miss_frame.columns)
        if hits:
            cached_features = json.loads(
                next(iter(hits.values()))["feature_columns_json"]
            )
            calculated_features = [
                column for column in columns if column not in COMMON_COLUMNS
            ]
            if cached_features != calculated_features:
                raise RuntimeError(
                    "Description cache feature schema differs from the newly calculated payload"
                )
    else:
        if not hits:
            raise RuntimeError("Warm Description cache plan has no active records")
        first = next(iter(hits.values()))
        columns = [*COMMON_COLUMNS]
        feature_columns = json.loads(first["feature_columns_json"])
        columns.extend(column for column in feature_columns if column not in columns)
        payload_path = output / f"{capability['output']['basename']}.csv"
        output.mkdir(parents=True, exist_ok=True)
    miss_records = {
        str(row["compound_id"]): row.to_dict()
        for _, row in miss_frame.iterrows()
    }
    full_rows: list[dict[str, Any]] = []
    for identity in identities:
        compound_id = identity["compound_id"]
        row = hit_records.get(compound_id, miss_records.get(compound_id))
        if row is None:
            raise RuntimeError(f"Description merge lost compound {compound_id}")
        full_rows.append(row)
    full = pd.DataFrame(full_rows)
    missing_columns = [column for column in columns if column not in full.columns]
    if missing_columns:
        raise RuntimeError(
            f"Description cache rows are missing payload columns: {missing_columns[:10]}"
        )
    full = full.loc[:, columns]
    if payload_path.suffix.lower() == ".parquet":
        full.to_parquet(payload_path, index=False)
    else:
        full.to_csv(payload_path, index=False)
    feature_columns = [column for column in full.columns if column not in COMMON_COLUMNS]
    errors = []
    if "description_error" in full.columns:
        for _, row in full.loc[
            full["description_error"].fillna("").astype(str).ne("")
        ].iterrows():
            errors.append({
                "compound_id": str(row["compound_id"]),
                "error_type": str(row["description_error"]),
                "message": str(row["description_error"]),
            })
    warnings = [f"{len(errors)} row-level errors were recorded"] if errors else []
    manifest_path = output / "description_manifest.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file() else {}
    )
    identity = request["identity"]
    manifest = {
        **existing_manifest,
        "schema_version": "2.0.0",
        "conductor_version": str(request.get("conductor_version", "0.1.10")),
        "artifact_stage": "description",
        "run_id": identity["run_id"],
        "node_id": identity["node_id"],
        "attempt_id": identity["attempt_id"],
        "capability_id": identity["capability_id"],
        "skill_name": identity["skill_name"],
        "skill_version": capability["version"],
        "calculation_version": plan["calculation_version"],
        "representation_id": capability.get("representation_id"),
        "input": plan["source_dataset_path"],
        "input_hash": plan["source_dataset_sha256"],
        "value_semantics": capability.get("value_semantics"),
        "natural_metric": capability.get("natural_metric"),
        "feature_columns": feature_columns,
        "row_count": int(len(full)),
        "valid_molecule_count": int(
            full.get("mol_parse_ok", pd.Series(False, index=full.index))
            .fillna(False).astype(bool).sum()
        ),
        "feature_count": len(feature_columns),
        "output": payload_path.name,
        "format": "parquet" if payload_path.suffix.lower() == ".parquet" else "csv",
        "warnings": warnings,
        "errors": errors,
        "cache": {
            key: plan[key] for key in (
                "program_name", "database_path", "calculation_version",
                "configuration_signature", "hit_count", "miss_count",
                "structure_mismatch_count", "version_mismatch_count",
                "configuration_mismatch_count", "cache_source_versions",
                "batch_dependent",
            )
        },
        "created_at": utc_now(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    warnings_path = output / "warnings.json"
    warnings_path.write_text(
        json.dumps({"warnings": warnings, "errors": errors}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    event_path = output / "execution_event.json"
    existing_event = (
        json.loads(event_path.read_text(encoding="utf-8"))
        if event_path.is_file() else {}
    )
    started_at = existing_event.get("started_at", request.get("created_at", utc_now()))
    event = {
        **existing_event,
        "schema_version": "2.0.0",
        **identity,
        "status": "succeeded",
        "input_hash": plan["source_dataset_sha256"],
        "cache": manifest["cache"],
        "artifacts": [
            {"type": "description", "path": payload_path.name, "sha256": file_hash(payload_path)},
            {"type": "manifest", "path": manifest_path.name, "sha256": file_hash(manifest_path)},
            {"type": "warnings", "path": warnings_path.name, "sha256": file_hash(warnings_path)},
        ],
        "warnings": warnings,
        "started_at": started_at,
        "finished_at": utc_now(),
    }
    event_path.write_text(
        json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload_path


def register_misses(
    *,
    plan: dict[str, Any],
    payload_path: Path,
    manifest: dict[str, Any],
    identity: dict[str, Any],
) -> int:
    if not plan["miss_ids"]:
        return 0
    _, identities, _ = _dataset_identity(
        Path(plan["source_dataset_path"]), plan["id_column"], plan["smiles_column"]
    )
    identity_by_id = {item["compound_id"]: item for item in identities}
    frame = _read_payload(payload_path)
    frame["compound_id"] = frame["compound_id"].astype(str)
    rows = frame.loc[frame["compound_id"].isin(set(plan["miss_ids"]))]
    feature_columns = [str(value) for value in manifest["feature_columns"]]
    schema_signature = object_hash({
        "feature_columns": feature_columns,
        "value_semantics": manifest["value_semantics"],
        "natural_metric": manifest["natural_metric"],
    })
    path = Path(plan["database_path"])
    inserted = 0
    audit_events: list[dict[str, Any]] = []
    registry_path = program_registry_path(path)
    with closing(_connect_program_registry(registry_path)) as registry_connection:
        registry_connection.execute("BEGIN IMMEDIATE")
        try:
            for item in identities:
                existing = registry_connection.execute(
                    "SELECT calculation_smiles_sha256 FROM compounds WHERE compound_id=?",
                    (item["compound_id"],),
                ).fetchone()
                if existing and existing["calculation_smiles_sha256"] != item["calculation_smiles_sha256"]:
                    raise ValueError(
                        "The same compound ID has a different canonical structure in this Program: "
                        + item["compound_id"]
                    )
                registry_connection.execute(
                    """
                    INSERT OR IGNORE INTO compounds(
                        compound_id, calculation_smiles, calculation_smiles_sha256,
                        first_seen_at, first_source_run_id
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        item["compound_id"], item["calculation_smiles"],
                        item["calculation_smiles_sha256"], utc_now(),
                        identity["run_id"],
                    ),
                )
            registry_connection.commit()
        except Exception:
            registry_connection.rollback()
            raise
    with closing(_connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for item in identities:
                existing = connection.execute(
                    "SELECT calculation_smiles_sha256 FROM compound_registry WHERE compound_id=?",
                    (item["compound_id"],),
                ).fetchone()
                if existing and existing["calculation_smiles_sha256"] != item["calculation_smiles_sha256"]:
                    raise ValueError(
                        "The same compound ID has a different canonical structure in this Program: "
                        + item["compound_id"]
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO compound_registry(
                        compound_id, calculation_smiles, calculation_smiles_sha256,
                        first_seen_at, first_source_run_id
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        item["compound_id"], item["calculation_smiles"],
                        item["calculation_smiles_sha256"], utc_now(),
                        identity["run_id"],
                    ),
                )
            for _, row in rows.iterrows():
                compound_id = str(row["compound_id"])
                item = identity_by_id[compound_id]
                raw_error = row.get("description_error", "")
                try:
                    import pandas as pd

                    error = "" if pd.isna(raw_error) else str(raw_error)
                except (TypeError, ValueError):
                    error = str(raw_error or "")
                raw_parse_ok = row.get("mol_parse_ok", False)
                parse_ok = (
                    bool(raw_parse_ok)
                    if isinstance(raw_parse_ok, bool)
                    else str(raw_parse_ok).strip().lower() in {"true", "1", "yes"}
                )
                if error and error != "invalid_smiles":
                    continue
                if parse_ok:
                    numeric = row[feature_columns]
                    try:
                        import pandas as pd
                        import numpy as np

                        values = numeric.apply(pd.to_numeric, errors="coerce")
                        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
                            continue
                    except (TypeError, ValueError):
                        continue
                outcome_status = "ok" if parse_ok and not error else "invalid_smiles"
                encoded_row = row_json(row.to_dict())
                existing = connection.execute(
                    """
                    SELECT record_id, row_json FROM records
                    WHERE configuration_signature=? AND compound_id=?
                      AND calculation_smiles_sha256=? AND record_status='active'
                    ORDER BY record_id DESC LIMIT 1
                    """,
                    (
                        plan["configuration_signature"], compound_id,
                        item["calculation_smiles_sha256"],
                    ),
                ).fetchone()
                if existing:
                    if existing["row_json"] != encoded_row:
                        raise RuntimeError(
                            "Concurrent Description cache writes produced different payloads "
                            f"for {compound_id}"
                        )
                    continue
                connection.execute(
                    """
                    INSERT INTO records(
                        calculation_version, skill_version, configuration_signature,
                        compound_id, original_input_smiles,
                        original_input_smiles_sha256, calculation_smiles,
                        calculation_smiles_sha256, schema_signature,
                        feature_columns_json, value_semantics, natural_metric,
                        row_json, outcome_status, record_status, computed_at,
                        source_run_id, source_round_id, source_node_id
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        plan["calculation_version"], plan["skill_version"],
                        plan["configuration_signature"], compound_id,
                        item["original_input_smiles"],
                        item["original_input_smiles_sha256"],
                        item["calculation_smiles"],
                        item["calculation_smiles_sha256"], schema_signature,
                        json.dumps(feature_columns, ensure_ascii=False),
                        manifest["value_semantics"], manifest["natural_metric"],
                        encoded_row, outcome_status, "active", utc_now(),
                        identity["run_id"], identity["round_id"], identity["node_id"],
                    ),
                )
                inserted += 1
                audit_events.append({
                    "timestamp": utc_now(), "event": "RECORD_REGISTERED",
                    "compound_id": compound_id,
                    "configuration_signature": plan["configuration_signature"],
                    "source_run_id": identity["run_id"],
                    "source_node_id": identity["node_id"],
                })
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    for event in audit_events:
        _append_audit(audit_path(path), event)
    return inserted


def inspect_records(
    path: Path, compound_id: str | None = None
) -> list[dict[str, Any]]:
    with closing(_connect(path, create=False)) as connection:
        query = "SELECT * FROM records"
        values: tuple[Any, ...] = ()
        if compound_id is not None:
            query += " WHERE compound_id=?"
            values = (compound_id,)
        query += " ORDER BY record_id DESC"
        rows = connection.execute(query, values).fetchall()
    return [dict(row) for row in rows]


def invalidate_records(
    path: Path,
    *,
    compound_id: str,
    reason: str,
    operator: str,
) -> list[int]:
    if not reason.strip():
        raise ValueError("Description cache invalidation requires a reason")
    timestamp = utc_now()
    with closing(_connect(path, create=False)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT record_id, row_json FROM records WHERE compound_id=? AND record_status='active'",
            (compound_id,),
        ).fetchall()
        record_ids = [int(row["record_id"]) for row in rows]
        if not record_ids:
            connection.rollback()
            return []
        connection.execute(
            """
            UPDATE records SET record_status='invalidated', invalidated_at=?,
                invalidated_by=?, invalidation_reason=?
            WHERE compound_id=? AND record_status='active'
            """,
            (timestamp, operator, reason.strip(), compound_id),
        )
        connection.commit()
    for row in rows:
        _append_audit(audit_path(path), {
            "timestamp": timestamp,
            "event": "RECORD_INVALIDATED",
            "record_id": int(row["record_id"]),
            "compound_id": compound_id,
            "operator": operator,
            "reason": reason.strip(),
            "old_record_sha256": text_hash(str(row["row_json"])),
        })
    return record_ids
