"""Canonical immutable MMP database construction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem

from conductor_stat_core import canonical_json, stable_id

from .chemistry import (
    attachment_neutral_structure,
    attachment_topology_unlabeled,
    core_similarity_mapping,
    environment_signature,
    heavy_atom_count,
)
from .fragmentation import (
    FragmentationConfig,
    FragmentationRecord,
    fragment_compound,
    pair_variable_mapping,
)


_FP_GENERATOR = AllChem.GetMorganGenerator(radius=2, fpSize=2048)


@dataclass(frozen=True)
class FragmentDatabaseResult:
    fragmentations: pd.DataFrame
    pairs: pd.DataFrame
    transformations: pd.DataFrame
    similar_core_map: pd.DataFrame
    observations: pd.DataFrame
    exclusions: pd.DataFrame
    pair_endpoint_values: pd.DataFrame
    cliffs: pd.DataFrame
    metrics: dict[str, Any]


def _collision_checked_ids(prefix: str, values: Iterable[dict[str, Any]]) -> list[str]:
    seen: dict[str, str] = {}
    result: list[str] = []
    for value in values:
        identifier = stable_id(prefix, value)
        payload = canonical_json(value)
        if identifier in seen and seen[identifier] != payload:
            raise RuntimeError(f"Stable identifier collision: {identifier}")
        seen[identifier] = payload
        result.append(identifier)
    return result


def _records_frame(records: list[FragmentationRecord]) -> pd.DataFrame:
    values: list[dict[str, Any]] = []
    id_inputs: list[dict[str, Any]] = []
    for record in records:
        identifier_input = {
            "schema_version": "0.2.1",
            "compound_id": record.compound_id,
            "class": record.transform_class,
            "constant_key": record.constant_key,
            "variable_smiles": record.variable_smiles,
            "attachment_mapping": list(record.attachment_mapping),
            "status": record.status,
            "exclusion_reason": record.exclusion_reason,
        }
        id_inputs.append(identifier_input)
        values.append(
            {
                "compound_id": record.compound_id,
                "class": record.transform_class,
                "constant_key": record.constant_key,
                "variable_smiles": record.variable_smiles,
                "cut_count": record.cut_count,
                "attachment_mapping_json": json.dumps(record.attachment_mapping, separators=(",", ":")),
                "mapping_status": record.mapping_status,
                "variable_variants_json": json.dumps(record.variable_variants, separators=(",", ":")),
                "status": record.status,
                "exclusion_reason": record.exclusion_reason,
            }
        )
    identifiers = _collision_checked_ids("FRAG", id_inputs)
    for row, identifier in zip(values, identifiers, strict=True):
        row["fragmentation_id"] = identifier
    columns = [
        "fragmentation_id",
        "compound_id",
        "class",
        "constant_key",
        "variable_smiles",
        "cut_count",
        "attachment_mapping_json",
        "mapping_status",
        "variable_variants_json",
        "status",
        "exclusion_reason",
    ]
    return pd.DataFrame(values, columns=columns).sort_values("fragmentation_id").reset_index(drop=True)


def _build_pairs(records: list[FragmentationRecord]) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[FragmentationRecord]] = defaultdict(list)
    for record in records:
        if record.status == "accepted":
            groups[(record.transform_class, record.constant_key)].append(record)
    pair_rows: list[dict[str, Any]] = []
    ambiguous: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for (transform_class, constant_key), members in sorted(groups.items()):
        members = sorted(members, key=lambda item: (item.compound_id, item.variable_smiles))
        for left, right in combinations(members, 2):
            if left.compound_id == right.compound_id or left.variable_smiles == right.variable_smiles:
                continue
            variables = pair_variable_mapping(left, right)
            if variables is None:
                ambiguous.append(
                    {
                        "compound_id": f"{left.compound_id}|{right.compound_id}",
                        "class": transform_class,
                        "constant_key": constant_key,
                        "variable_smiles": "",
                        "cut_count": str(left.cut_count),
                        "status": "ambiguous",
                        "exclusion_reason": "ambiguous_mapping",
                    }
                )
                continue
            variable_from, variable_to = variables
            if variable_from in left.variable_variants and variable_to in right.variable_variants:
                compound_from, compound_to = left.compound_id, right.compound_id
            elif variable_from in right.variable_variants and variable_to in left.variable_variants:
                compound_from, compound_to = right.compound_id, left.compound_id
            else:
                ambiguous.append(
                    {
                        "compound_id": f"{left.compound_id}|{right.compound_id}",
                        "class": transform_class,
                        "constant_key": constant_key,
                        "variable_smiles": "",
                        "cut_count": str(left.cut_count),
                        "status": "ambiguous",
                        "exclusion_reason": "ambiguous_direction",
                    }
                )
                continue
            transformation_input = {
                "schema_version": "0.2.1",
                "class": transform_class,
                "variable_from": variable_from,
                "variable_to": variable_to,
                "attachment_mapping": list(left.attachment_mapping),
            }
            transformation_id = stable_id("TR", transformation_input)
            dedup_key = (transformation_id, constant_key, compound_from, compound_to)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            pair_input = {
                "schema_version": "0.2.1",
                "transformation_id": transformation_id,
                "constant_key": constant_key,
                "compound_from": compound_from,
                "compound_to": compound_to,
            }
            pair_rows.append(
                {
                    "pair_id": stable_id("PAIR", pair_input),
                    "class": transform_class,
                    "compound_from": compound_from,
                    "compound_to": compound_to,
                    "constant_key": constant_key,
                    "variable_from": variable_from,
                    "variable_to": variable_to,
                    "transformation_id": transformation_id,
                }
            )
    columns = [
        "pair_id",
        "class",
        "compound_from",
        "compound_to",
        "constant_key",
        "variable_from",
        "variable_to",
        "transformation_id",
    ]
    frame = pd.DataFrame(pair_rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values("pair_id").reset_index(drop=True)
    return frame, ambiguous


def _transformations(pairs: pd.DataFrame) -> pd.DataFrame:
    columns = ["transformation_id", "class", "variable_from", "variable_to", "pair_count"]
    if pairs.empty:
        return pd.DataFrame(columns=columns)
    result = (
        pairs.groupby(
            ["transformation_id", "class", "variable_from", "variable_to"],
            as_index=False,
            sort=True,
        )
        .size()
        .rename(columns={"size": "pair_count"})
    )
    return result[columns].sort_values("transformation_id").reset_index(drop=True)


def _endpoint_map(endpoints: pd.DataFrame, endpoint_id: str) -> dict[str, float]:
    required = {"compound_id", "endpoint_id", "oriented_value"}
    missing = required - set(endpoints.columns)
    if missing:
        raise ValueError(f"Endpoint table is missing columns: {sorted(missing)}")
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id)].copy()
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])]
    return selected.groupby(selected["compound_id"].astype(str))["oriented_value"].mean().to_dict()


def _pair_endpoint_values(pairs: pd.DataFrame, endpoint_values: dict[str, float]) -> pd.DataFrame:
    columns = ["row_id", "pair_id", "endpoint_id", "value_from", "value_to", "endpoint_delta_oriented"]
    rows: list[dict[str, Any]] = []
    for row in pairs.itertuples(index=False):
        value_from = endpoint_values.get(str(row.compound_from))
        value_to = endpoint_values.get(str(row.compound_to))
        if value_from is None or value_to is None:
            continue
        rows.append(
            {
                "row_id": stable_id("ROW", {"pair_id": row.pair_id, "endpoint": "selected"}),
                "pair_id": row.pair_id,
                "endpoint_id": "selected",
                "value_from": value_from,
                "value_to": value_to,
                "endpoint_delta_oriented": value_to - value_from,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _observations(records: list[FragmentationRecord], endpoint_values: dict[str, float]) -> pd.DataFrame:
    grouped: dict[tuple[str, str], list[FragmentationRecord]] = defaultdict(list)
    for record in records:
        if record.status == "accepted" and record.compound_id in endpoint_values:
            grouped[(record.transform_class, record.constant_key)].append(record)
    rows: list[dict[str, Any]] = []
    for (transform_class, constant_key), members in sorted(grouped.items()):
        by_variable: dict[str, set[str]] = defaultdict(set)
        for member in members:
            by_variable[member.variable_smiles].add(member.compound_id)
        if len(by_variable) < 2:
            continue
        series_key = stable_id(
            "SERIES",
            {"schema_version": "0.2.1", "class": transform_class, "constant_key": constant_key},
        )
        for variable, compound_ids in sorted(by_variable.items()):
            finite_ids = sorted(identifier for identifier in compound_ids if identifier in endpoint_values)
            if not finite_ids:
                continue
            values = [endpoint_values[identifier] for identifier in finite_ids]
            fragment_id = stable_id(
                "FRAG",
                {"schema_version": "0.2.1", "class": transform_class, "variable_smiles": variable},
            )
            row_key = {"series_key": series_key, "fragment_id": fragment_id, "compound_ids": finite_ids}
            rows.append(
                {
                    "row_id": stable_id("ROW", row_key),
                    "series_key": series_key,
                    "transform_class": transform_class,
                    "constant_key": constant_key,
                    "fragment_id": fragment_id,
                    "fragment_smiles": variable,
                    "compound_ids_json": json.dumps(finite_ids, separators=(",", ":")),
                    "n_compounds": len(finite_ids),
                    "endpoint_mean": float(np.mean(values)),
                }
            )
    columns = [
        "row_id",
        "series_key",
        "transform_class",
        "constant_key",
        "fragment_id",
        "fragment_smiles",
        "compound_ids_json",
        "n_compounds",
        "endpoint_mean",
    ]
    return pd.DataFrame(rows, columns=columns).sort_values("row_id").reset_index(drop=True)


def _mcs_mapping_task(task: tuple[str, str, float]) -> dict[str, Any]:
    left, right, minimum_tanimoto = task
    return core_similarity_mapping(left, right, minimum_tanimoto=minimum_tanimoto)


def _similar_core_map(
    records: list[FragmentationRecord],
    minimum_tanimoto: float,
    workers: int,
) -> pd.DataFrame:
    keys_by_class: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for record in records:
        if record.status != "accepted":
            continue
        smiles = record.constant_key.replace(" | ", ".")
        topology = attachment_topology_unlabeled(smiles)
        keys_by_class[(record.transform_class, record.cut_count, topology)].add(record.constant_key)
    rows: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], tuple[str, str, float]]] = []
    for (transform_class, cut_count, _), key_set in sorted(keys_by_class.items()):
        keys = sorted(key_set)
        molecules = [Chem.MolFromSmiles(key.replace(" | ", ".")) for key in keys]
        valid = [(key, mol, _FP_GENERATOR.GetFingerprint(mol)) for key, mol in zip(keys, molecules, strict=True) if mol]
        for index, (left, _, left_fp) in enumerate(valid):
            later = valid[index + 1 :]
            similarities = DataStructs.BulkTanimotoSimilarity(left_fp, [item[2] for item in later])
            for (right, _, _), similarity in zip(later, similarities, strict=True):
                if similarity < minimum_tanimoto:
                    continue
                left_smiles = left.replace(" | ", ".")
                right_smiles = right.replace(" | ", ".")
                coverage = min(
                    heavy_atom_count(left_smiles) / max(1, heavy_atom_count(right_smiles)),
                    heavy_atom_count(right_smiles) / max(1, heavy_atom_count(left_smiles)),
                )
                if attachment_neutral_structure(left_smiles) == attachment_neutral_structure(right_smiles):
                    similarity_class = "exact"
                    mapping = {"core_tanimoto": similarity, "mcs_coverage": coverage, "mapping_status": "symmetry_equivalent"}
                elif environment_signature(left_smiles, 2) == environment_signature(right_smiles, 2):
                    similarity_class = "radius2"
                    mapping = {"core_tanimoto": similarity, "mcs_coverage": coverage, "mapping_status": "environment_equivalent"}
                elif environment_signature(left_smiles, 1) == environment_signature(right_smiles, 1):
                    similarity_class = "radius1"
                    mapping = {"core_tanimoto": similarity, "mcs_coverage": coverage, "mapping_status": "environment_equivalent"}
                else:
                    similarity_class = "mcs_mapped"
                    mapping = None
                base = {
                    "map_id": stable_id(
                        "MAP",
                        {"class": transform_class, "cut_count": cut_count, "core_a": left, "core_b": right},
                    ),
                    "core_a": left,
                    "core_b": right,
                    "similarity_class": similarity_class,
                    "attachment_mapping_json": "[]",
                }
                if mapping is None:
                    pending.append((base, (left_smiles, right_smiles, minimum_tanimoto)))
                else:
                    rows.append(
                        {
                            **base,
                            "tanimoto": float(mapping["core_tanimoto"]),
                            "mcs_coverage": float(mapping["mcs_coverage"]),
                            "status": str(mapping["mapping_status"]),
                        }
                    )
    if pending:
        tasks = [task for _, task in pending]
        if workers > 1:
            # Import lazily so single-worker runs do not load the platform
            # multiprocessing extension unnecessarily.
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=workers) as executor:
                mappings = executor.map(_mcs_mapping_task, tasks, chunksize=8)
                resolved = list(mappings)
        else:
            resolved = [_mcs_mapping_task(task) for task in tasks]
        for (base, _), mapping in zip(pending, resolved, strict=True):
            rows.append(
                {
                    **base,
                    "tanimoto": float(mapping["core_tanimoto"]),
                    "mcs_coverage": float(mapping["mcs_coverage"]),
                    "status": str(mapping["mapping_status"]),
                }
            )
    columns = [
        "map_id",
        "core_a",
        "core_b",
        "similarity_class",
        "tanimoto",
        "mcs_coverage",
        "attachment_mapping_json",
        "status",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    return frame.sort_values("map_id").reset_index(drop=True) if not frame.empty else frame


def _cliffs(
    compounds: pd.DataFrame,
    endpoint_values: dict[str, float],
    pairs: pd.DataFrame,
    minimum_tanimoto: float,
    minimum_delta: float,
) -> pd.DataFrame:
    pair_lookup: dict[frozenset[str], list[str]] = defaultdict(list)
    for row in pairs.itertuples(index=False):
        pair_lookup[frozenset((str(row.compound_from), str(row.compound_to)))].append(str(row.transformation_id))
    valid: list[tuple[str, Any, Any]] = []
    for row in compounds.itertuples(index=False):
        identifier = str(row.compound_id)
        if identifier not in endpoint_values:
            continue
        smiles = str(getattr(row, "canonical_smiles", getattr(row, "smiles", "")))
        molecule = Chem.MolFromSmiles(smiles)
        if molecule:
            valid.append((identifier, molecule, _FP_GENERATOR.GetFingerprint(molecule)))
    rows: list[dict[str, Any]] = []
    for index, (left_id, _, left_fp) in enumerate(valid):
        later = valid[index + 1 :]
        similarities = DataStructs.BulkTanimotoSimilarity(left_fp, [item[2] for item in later])
        for (right_id, _, _), similarity in zip(later, similarities, strict=True):
            delta = endpoint_values[right_id] - endpoint_values[left_id]
            if similarity < minimum_tanimoto or abs(delta) < minimum_delta:
                continue
            transformations = sorted(set(pair_lookup.get(frozenset((left_id, right_id)), [])))
            key = {"left": left_id, "right": right_id, "space": "builtin_morgan_radius2"}
            rows.append(
                {
                    "row_id": stable_id("CLIFF", key),
                    "space_id": "builtin_morgan_radius2",
                    "compound_a": left_id,
                    "compound_b": right_id,
                    "similarity": float(similarity),
                    "endpoint_delta_oriented": float(delta),
                    "extraction_status": "extracted" if transformations else "not_extractable",
                    "transformation_ids_json": json.dumps(transformations, separators=(",", ":")),
                }
            )
    columns = [
        "row_id",
        "space_id",
        "compound_a",
        "compound_b",
        "similarity",
        "endpoint_delta_oriented",
        "extraction_status",
        "transformation_ids_json",
    ]
    return pd.DataFrame(rows, columns=columns)


def _table_hash(frame: pd.DataFrame) -> str:
    rows = frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")
    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()


def _write_database(
    path: Path,
    fragmentations: pd.DataFrame,
    pairs: pd.DataFrame,
    transformations: pd.DataFrame,
    similar_core_map: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        database_fragmentations = fragmentations.drop(columns=["variable_variants_json"])
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            connection.execute(
                'CREATE TABLE fragmentations(fragmentation_id TEXT PRIMARY KEY, compound_id TEXT NOT NULL, "class" TEXT NOT NULL, constant_key TEXT NOT NULL, variable_smiles TEXT NOT NULL, cut_count INTEGER NOT NULL, attachment_mapping_json TEXT NOT NULL, mapping_status TEXT NOT NULL, status TEXT NOT NULL, exclusion_reason TEXT)'
            )
            connection.execute(
                'CREATE TABLE pairs(pair_id TEXT PRIMARY KEY, "class" TEXT NOT NULL, compound_from TEXT NOT NULL, compound_to TEXT NOT NULL, constant_key TEXT NOT NULL, variable_from TEXT NOT NULL, variable_to TEXT NOT NULL, transformation_id TEXT NOT NULL)'
            )
            connection.execute(
                'CREATE TABLE transformations(transformation_id TEXT PRIMARY KEY, "class" TEXT NOT NULL, variable_from TEXT NOT NULL, variable_to TEXT NOT NULL, pair_count INTEGER NOT NULL)'
            )
            connection.execute(
                "CREATE TABLE similar_core_map(map_id TEXT PRIMARY KEY, core_a TEXT NOT NULL, core_b TEXT NOT NULL, similarity_class TEXT NOT NULL, tanimoto REAL NOT NULL, mcs_coverage REAL NOT NULL, attachment_mapping_json TEXT NOT NULL, status TEXT NOT NULL)"
            )
            database_fragmentations.to_sql("fragmentations", connection, if_exists="append", index=False)
            pairs.to_sql("pairs", connection, if_exists="append", index=False)
            transformations.to_sql("transformations", connection, if_exists="append", index=False)
            similar_core_map.to_sql("similar_core_map", connection, if_exists="append", index=False)
            connection.execute('CREATE INDEX idx_fragmentations_class_constant ON fragmentations("class", constant_key)')
            connection.execute("CREATE INDEX idx_pairs_transformation ON pairs(transformation_id)")
            connection.execute("CREATE INDEX idx_pairs_from ON pairs(compound_from)")
            connection.execute("CREATE INDEX idx_pairs_to ON pairs(compound_to)")
            completed = dict(metadata)
            completed["complete"] = True
            completed["tables"] = {
                "fragmentations": {"count": len(database_fragmentations), "sha256": _table_hash(database_fragmentations)},
                "pairs": {"count": len(pairs), "sha256": _table_hash(pairs)},
                "transformations": {"count": len(transformations), "sha256": _table_hash(transformations)},
                "similar_core_map": {"count": len(similar_core_map), "sha256": _table_hash(similar_core_map)},
            }
            connection.executemany(
                "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
                [(key, json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)) for key, value in sorted(completed.items())],
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
            connection.commit()
        finally:
            connection.close()
        if path.exists():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            path.unlink()
        os.replace(temporary, path)
        os.chmod(path, stat.S_IREAD)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_csv(temporary, index=False, lineterminator="\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_fragment_database(
    compounds: pd.DataFrame,
    endpoints: pd.DataFrame,
    endpoint_id: str,
    output_directory: Path,
    *,
    fragmentation_config: FragmentationConfig | None = None,
    cliff_tanimoto_min: float = 0.75,
    cliff_abs_delta_min: float = 0.42,
    similar_core_workers: int = 1,
) -> FragmentDatabaseResult:
    required = {"compound_id", "canonical_smiles"}
    missing = required - set(compounds.columns)
    if missing:
        raise ValueError(f"Compounds table is missing columns: {sorted(missing)}")
    output_directory.mkdir(parents=True, exist_ok=True)
    config = fragmentation_config or FragmentationConfig()
    records: list[FragmentationRecord] = []
    for row in compounds.sort_values("compound_id").itertuples(index=False):
        if hasattr(row, "mol_parse_ok") and not bool(row.mol_parse_ok):
            records.extend(fragment_compound(str(row.compound_id), "", config))
        else:
            records.extend(fragment_compound(str(row.compound_id), str(row.canonical_smiles), config))
    fragmentations = _records_frame(records)
    pairs, pair_ambiguities = _build_pairs(records)
    transformations = _transformations(pairs)
    endpoint_values = _endpoint_map(endpoints, endpoint_id)
    pair_values = _pair_endpoint_values(pairs, endpoint_values)
    if not pair_values.empty:
        pair_values["endpoint_id"] = endpoint_id
    observations = _observations(records, endpoint_values)
    similar = _similar_core_map(records, cliff_tanimoto_min, max(1, int(similar_core_workers)))
    cliffs = _cliffs(compounds, endpoint_values, pairs, cliff_tanimoto_min, cliff_abs_delta_min)
    exclusions = fragmentations.loc[fragmentations["status"].ne("accepted")].copy()
    exclusions = exclusions.drop(columns=["variable_variants_json", "mapping_status"])
    if pair_ambiguities:
        extra = pd.DataFrame(pair_ambiguities)
        extra.insert(0, "fragmentation_id", [stable_id("EXCL", row) for row in pair_ambiguities])
        extra["attachment_mapping_json"] = "[]"
        exclusions = pd.concat([exclusions, extra[exclusions.columns]], ignore_index=True)
    exclusions = exclusions.sort_values("fragmentation_id").reset_index(drop=True)
    metadata = {
        "schema_version": "0.2.1",
        "endpoint_independent": True,
        "fragmentation_config": asdict(config),
    }
    _write_database(output_directory / "mmp.sqlite", fragmentations, pairs, transformations, similar, metadata)
    _write_csv_atomic(observations, output_directory / "fragment_observations.csv")
    _write_csv_atomic(exclusions, output_directory / "fragmentation_exclusions.csv")
    _write_csv_atomic(pair_values, output_directory / "pair_endpoint_values.csv")
    _write_csv_atomic(cliffs, output_directory / "cliff_candidates.csv")
    metrics = {
        "fragmentation_count": int(fragmentations["status"].eq("accepted").sum()),
        "exclusion_count": len(exclusions),
        "pair_count": len(pairs),
        "transformation_count": len(transformations),
        "series_count": int(observations["series_key"].nunique()) if not observations.empty else 0,
        "observation_count": len(observations),
        "similar_core_count": len(similar),
        "cliff_count": len(cliffs),
        "pair_count_by_class": pairs.groupby("class").size().sort_index().to_dict() if not pairs.empty else {},
    }
    return FragmentDatabaseResult(
        fragmentations,
        pairs,
        transformations,
        similar,
        observations,
        exclusions,
        pair_values,
        cliffs,
        metrics,
    )
