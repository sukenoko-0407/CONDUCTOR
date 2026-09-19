"""Context catalog, overlap deduplication, and deterministic translation."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import BRICS, Recap, rdFMCS
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.cluster import AgglomerativeClustering
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from conductor_stat_core import content_hash, stable_id


COMMON_COLUMNS = frozenset({"compound_id", "input_smiles", "mol_parse_ok", "description_error"})


@dataclass(frozen=True)
class ContextBuildResult:
    catalog: pd.DataFrame
    membership: pd.DataFrame
    deduplication: pd.DataFrame
    translations: pd.DataFrame
    activity_diagnostic: pd.DataFrame
    metrics: dict[str, Any]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    header = pd.read_csv(path, nrows=0)
    dtypes = {"compound_id": "string"} if "compound_id" in header.columns else None
    return pd.read_csv(path, dtype=dtypes)


def _cluster_id(space_id: str, count: int, index: int, members: list[str]) -> str:
    digest = content_hash(
        {"schema_version": "0.2.1", "space_id": space_id, "cluster_count": count, "members": sorted(members)}
    )[:16]
    return f"CL|{space_id}|k{count}|c{index}|{digest}"


def _quantile_id(feature_id: str, percentile: int, cutoff: float, members: list[str]) -> str:
    digest = content_hash(
        {
            "schema_version": "0.2.1",
            "feature_id": feature_id,
            "percentile": percentile,
            "cutoff": float(cutoff),
            "members": sorted(members),
        }
    )[:16]
    safe_feature = feature_id.replace("|", "_")
    return f"QT|{safe_feature}|q{percentile}|{digest}"


def _cluster_contexts(
    spaces: list[dict[str, Any]],
    compound_ids: list[str],
    cluster_counts: Iterable[int],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    rows: list[dict[str, Any]] = []
    members: dict[str, set[str]] = {}
    expected = set(compound_ids)
    for space in sorted(spaces, key=lambda item: item["space_id"]):
        metadata = json.loads(Path(space["distance_metadata_path"]).read_text(encoding="utf-8"))
        matrix = np.load(Path(space["distance_path"]), mmap_mode="r", allow_pickle=False)
        source_ids = [str(value) for value in metadata["compound_ids"]]
        if set(source_ids) != expected or matrix.shape != (len(source_ids), len(source_ids)):
            raise ValueError(f"Distance artifact does not match compounds for {space['space_id']}")
        eligible_set = {
            str(value)
            for value in metadata.get("eligible_compound_ids", source_ids)
        }
        if not eligible_set.issubset(expected):
            raise ValueError(
                f"Distance eligibility contains unknown compounds for {space['space_id']}"
            )
        eligible_ids = [
            identifier for identifier in compound_ids if identifier in eligible_set
        ]
        positions = {identifier: index for index, identifier in enumerate(source_ids)}
        order = [positions[identifier] for identifier in eligible_ids]
        aligned = np.asarray(matrix[np.ix_(order, order)], dtype=float)
        if not np.isfinite(aligned).all():
            raise ValueError(
                f"Eligible distance artifact contains non-finite values for {space['space_id']}"
            )
        for count in sorted(set(int(value) for value in cluster_counts)):
            if count < 2 or count > len(eligible_ids):
                continue
            labels = AgglomerativeClustering(n_clusters=count, metric="precomputed", linkage="average").fit_predict(aligned)
            clusters = [sorted(eligible_ids[index] for index in np.where(labels == label)[0]) for label in sorted(set(labels))]
            clusters.sort(key=lambda values: (values[0], content_hash(values)))
            for index, values in enumerate(clusters):
                context_id = _cluster_id(str(space["space_id"]), count, index, values)
                members[context_id] = set(values)
                rows.append(
                    {
                        "context_id": context_id,
                        "context_type": "cluster",
                        "axis_id": f"CL|{space['space_id']}|k{count}",
                        "source_space_id": space["space_id"],
                        "source_tier": int(space["tier"]),
                        "structurality": space["structurality"],
                        "feature_id": "",
                        "cutoff": np.nan,
                        "scaffold_type": "",
                        "scaffold_key": "",
                        "calibration_scope": True,
                    }
                )
    return rows, members


def _tier1_matrix(
    spaces: list[dict[str, Any]],
    compound_ids: list[str],
) -> tuple[pd.DataFrame, dict[str, tuple[str, str]]]:
    combined = pd.DataFrame(index=pd.Index(compound_ids, name="compound_id"))
    provenance: dict[str, tuple[str, str]] = {}
    for space in sorted((item for item in spaces if int(item["tier"]) == 1), key=lambda item: item["space_id"]):
        frame = _read_table(Path(space["path"]))
        frame["compound_id"] = frame["compound_id"].astype(str)
        if frame["compound_id"].duplicated().any():
            raise ValueError(f"Duplicate compound_id in {space['space_id']}")
        frame = frame.set_index("compound_id").reindex(compound_ids)
        for column in frame.columns:
            if column in COMMON_COLUMNS:
                continue
            feature_id = f"{space['space_id']}:{column}"
            combined[feature_id] = pd.to_numeric(frame[column], errors="coerce")
            provenance[feature_id] = (str(space["space_id"]), str(column))
    if combined.empty:
        raise ValueError("At least one Tier 1 feature space is required")
    return combined, provenance


def _quantile_contexts(
    tier1: pd.DataFrame,
    quantiles: Iterable[float],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    rows: list[dict[str, Any]] = []
    members: dict[str, set[str]] = {}
    for feature_id in sorted(tier1.columns):
        values = tier1[feature_id]
        finite = values[np.isfinite(values)]
        if finite.empty:
            continue
        for quantile in sorted(set(float(value) for value in quantiles)):
            if not 0 < quantile < 1:
                raise ValueError("Context quantiles must lie strictly between 0 and 1")
            cutoff = float(np.quantile(finite.to_numpy(dtype=float), quantile))
            selected = sorted(values.index[np.isfinite(values) & values.le(cutoff)].astype(str))
            percentile = int(round(quantile * 100))
            context_id = _quantile_id(feature_id, percentile, cutoff, selected)
            members[context_id] = set(selected)
            rows.append(
                {
                    "context_id": context_id,
                    "context_type": "quantile",
                    "axis_id": f"QT|{feature_id}",
                    "source_space_id": feature_id.split(":", 1)[0],
                    "source_tier": 1,
                    "structurality": "non_structural",
                    "feature_id": feature_id,
                    "cutoff": cutoff,
                    "scaffold_type": "",
                    "scaffold_key": "",
                    "calibration_scope": True,
                }
            )
    return rows, members


def _scaffold_keys(molecule: Chem.Mol) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {"murcko": set(), "brics": set(), "recap": set()}
    murcko = MurckoScaffold.GetScaffoldForMol(molecule)
    if murcko.GetNumAtoms():
        result["murcko"].add(Chem.MolToSmiles(murcko, canonical=True, isomericSmiles=True))
    result["brics"].update(str(value) for value in BRICS.BRICSDecompose(molecule, returnMols=False))
    tree = Recap.RecapDecompose(molecule)
    if tree is not None:
        result["recap"].update(str(value) for value in tree.GetAllChildren())
    return result


def _mcs_key(scaffolds: Iterable[Chem.Mol]) -> str:
    """Return an auditable MCS SMARTS for a topology-equivalent scaffold group."""
    unique = {
        Chem.MolToSmiles(scaffold, canonical=True, isomericSmiles=True): scaffold
        for scaffold in scaffolds
    }
    ordered = [unique[key] for key in sorted(unique)]
    if not ordered:
        raise ValueError("MCS context requires at least one scaffold")
    if len(ordered) == 1:
        generic = MurckoScaffold.MakeScaffoldGeneric(ordered[0])
        return Chem.MolToSmarts(generic)
    match = rdFMCS.FindMCS(
        ordered,
        atomCompare=rdFMCS.AtomCompare.CompareAny,
        bondCompare=rdFMCS.BondCompare.CompareAny,
        ringMatchesRingOnly=True,
        completeRingsOnly=True,
    )
    if match.canceled or match.numAtoms == 0 or not match.smartsString:
        raise RuntimeError("MCS calculation did not produce a complete scaffold key")
    return str(match.smartsString)


def _scaffold_contexts(compounds: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    grouping: dict[tuple[str, str], set[str]] = defaultdict(set)
    mcs_groups: dict[str, dict[str, Chem.Mol]] = defaultdict(dict)
    for row in compounds.sort_values("compound_id").itertuples(index=False):
        molecule = Chem.MolFromSmiles(str(row.canonical_smiles))
        if molecule is None:
            continue
        murcko = MurckoScaffold.GetScaffoldForMol(molecule)
        if murcko.GetNumAtoms():
            generic = MurckoScaffold.MakeScaffoldGeneric(murcko)
            topology_key = Chem.MolToSmiles(generic, canonical=True, isomericSmiles=False)
            mcs_groups[topology_key][str(row.compound_id)] = murcko
        for scaffold_type, keys in _scaffold_keys(molecule).items():
            for key in keys:
                if key:
                    grouping[(scaffold_type, key)].add(str(row.compound_id))
    for topology_key in sorted(mcs_groups):
        scaffold_by_compound = mcs_groups[topology_key]
        key = _mcs_key(scaffold_by_compound.values())
        grouping[("mcs", key)].update(scaffold_by_compound)
    rows: list[dict[str, Any]] = []
    members: dict[str, set[str]] = {}
    for (scaffold_type, key), identifiers in sorted(grouping.items()):
        context_id = stable_id(
            "SC",
            {"schema_version": "0.2.1", "scaffold_type": scaffold_type, "canonical_scaffold_key": key},
        )
        members[context_id] = set(identifiers)
        rows.append(
            {
                "context_id": context_id,
                "context_type": "scaffold",
                "axis_id": f"SC|{scaffold_type}",
                "source_space_id": None,
                "source_tier": None,
                "structurality": "structural",
                "feature_id": "",
                "cutoff": np.nan,
                "scaffold_type": scaffold_type,
                "scaffold_key": key,
                "calibration_scope": scaffold_type == "murcko",
            }
        )
    return rows, members


class _DisjointSet:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            value, self.parent[value] = self.parent[value], root
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def deduplicate_contexts(
    memberships: dict[str, set[str]],
    threshold: float = 0.90,
) -> pd.DataFrame:
    identifiers = sorted(memberships)
    disjoint = _DisjointSet(identifiers)
    inverted: dict[str, list[str]] = defaultdict(list)
    for context_id, compounds in memberships.items():
        for compound_id in compounds:
            inverted[compound_id].append(context_id)
    intersections: dict[tuple[str, str], int] = defaultdict(int)
    for contexts in inverted.values():
        for left, right in combinations(sorted(contexts), 2):
            intersections[(left, right)] += 1
    for (left, right), intersection in sorted(intersections.items()):
        union = len(memberships[left]) + len(memberships[right]) - intersection
        if union and intersection / union >= threshold:
            disjoint.union(left, right)
    components: dict[str, list[str]] = defaultdict(list)
    for identifier in identifiers:
        components[disjoint.find(identifier)].append(identifier)
    rows: list[dict[str, Any]] = []
    for component, values in sorted(components.items()):
        representative = sorted(values, key=lambda item: (-len(memberships[item]), item))[0]
        component_id = stable_id("DEDUP", {"members": sorted(values)})
        for identifier in sorted(values):
            rows.append(
                {
                    "context_id": identifier,
                    "dedup_component_id": component_id,
                    "representative_context_id": representative,
                    "is_representative": identifier == representative,
                    "component_size": len(values),
                }
            )
    return pd.DataFrame(rows).sort_values("context_id").reset_index(drop=True)


def _translations(
    catalog: pd.DataFrame,
    memberships: dict[str, set[str]],
    tier1: pd.DataFrame,
    minimum_auc: float,
    random_seed: int,
) -> pd.DataFrame:
    feature_ids = sorted(tier1.columns)
    matrix = tier1[feature_ids].to_numpy(dtype=float)
    compound_ids = tier1.index.astype(str).tolist()
    rows: list[dict[str, Any]] = []
    targets = catalog.loc[catalog["context_type"].eq("cluster") & catalog["source_tier"].eq(3)]
    for context in targets.sort_values("context_id").itertuples(index=False):
        member_set = memberships[str(context.context_id)]
        target = np.asarray([identifier in member_set for identifier in compound_ids], dtype=int)
        positives, negatives = int(target.sum()), int((1 - target).sum())
        status = "not_testable"
        auc: float | None = None
        coefficients: list[dict[str, Any]] = []
        narrative = ""
        if min(positives, negatives) >= 3:
            pipeline = Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    ("model", LogisticRegression(solver="liblinear", random_state=random_seed)),
                ]
            )
            folds = StratifiedKFold(n_splits=3, shuffle=True, random_state=random_seed)
            probability = cross_val_predict(pipeline, matrix, target, cv=folds, method="predict_proba")[:, 1]
            auc = float(roc_auc_score(target, probability))
            if auc >= minimum_auc:
                pipeline.fit(matrix, target)
                model = pipeline.named_steps["model"]
                ordered = sorted(
                    zip(feature_ids, model.coef_[0], strict=True),
                    key=lambda item: (-abs(float(item[1])), item[0]),
                )
                coefficients = [
                    {"feature_id": feature_id, "coefficient": float(coefficient), "direction": "higher" if coefficient > 0 else "lower"}
                    for feature_id, coefficient in ordered
                    if float(coefficient) != 0.0
                ][:3]
                narrative = "; ".join(f"{item['direction']} {item['feature_id']}" for item in coefficients)
                status = "translated"
            else:
                status = "untranslatable"
        rows.append(
            {
                "context_id": context.context_id,
                "status": status,
                "auc": auc,
                "positive_n": positives,
                "negative_n": negatives,
                "top_features_json": json.dumps(coefficients, ensure_ascii=False, separators=(",", ":")),
                "description": narrative,
            }
        )
    columns = ["context_id", "status", "auc", "positive_n", "negative_n", "top_features_json", "description"]
    return pd.DataFrame(rows, columns=columns)


def _activity_diagnostic(endpoints: pd.DataFrame, endpoint_id: str) -> pd.DataFrame:
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    finite = selected["oriented_value"][np.isfinite(selected["oriented_value"])]
    cutoff = float(np.quantile(finite, 0.80)) if not finite.empty else np.nan
    selected["favorable"] = np.isfinite(selected["oriented_value"]) & selected["oriented_value"].ge(cutoff)
    selected["endpoint_id"] = endpoint_id
    selected["cutoff_quantile"] = 0.80
    selected["cutoff_value"] = cutoff
    selected["diagnostic_context_id"] = stable_id(
        "AD", {"schema_version": "0.2.1", "endpoint_id": endpoint_id, "quantile": 0.80, "cutoff": cutoff}
    ) if np.isfinite(cutoff) else ""
    return selected[["compound_id", "endpoint_id", "oriented_value", "favorable", "cutoff_quantile", "cutoff_value", "diagnostic_context_id"]]


def build_contexts(
    compounds: pd.DataFrame,
    endpoints: pd.DataFrame,
    feature_spaces: list[dict[str, Any]],
    endpoint_id: str,
    *,
    cluster_counts: Iterable[int] = (10, 20, 40),
    quantiles: Iterable[float] = (0.25, 0.50, 0.75),
    min_endpoint_n: int = 5,
    jaccard_threshold: float = 0.90,
    translation_auc_min: float = 0.70,
    random_seed: int = 20260916,
) -> ContextBuildResult:
    required = {"compound_id", "canonical_smiles"}
    if required - set(compounds.columns):
        raise ValueError(f"Compounds table is missing columns: {sorted(required - set(compounds.columns))}")
    compounds = compounds.copy()
    compounds["compound_id"] = compounds["compound_id"].astype(str)
    if compounds["compound_id"].duplicated().any():
        raise ValueError("Compounds table requires unique compound_id values")
    compound_ids = compounds.sort_values("compound_id")["compound_id"].tolist()
    compounds = compounds.set_index("compound_id").loc[compound_ids].reset_index()
    tier1, _ = _tier1_matrix(feature_spaces, compound_ids)
    cluster_rows, cluster_members = _cluster_contexts(feature_spaces, compound_ids, cluster_counts)
    quantile_rows, quantile_members = _quantile_contexts(tier1, quantiles)
    scaffold_rows, scaffold_members = _scaffold_contexts(compounds)
    rows = cluster_rows + quantile_rows + scaffold_rows
    memberships = {**cluster_members, **quantile_members, **scaffold_members}
    if len(memberships) != len(rows):
        raise RuntimeError("Context identifier collision")
    catalog = pd.DataFrame(rows).sort_values("context_id").reset_index(drop=True)
    catalog["condition_depth"] = 1
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str)
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    finite_ids = set(selected.loc[np.isfinite(selected["oriented_value"]), "compound_id"])
    catalog["member_count"] = catalog["context_id"].map(lambda identifier: len(memberships[identifier]))
    catalog["endpoint_valid_count"] = catalog["context_id"].map(lambda identifier: len(memberships[identifier] & finite_ids))
    catalog["eligible"] = catalog["endpoint_valid_count"].ge(min_endpoint_n)
    deduplication = deduplicate_contexts(memberships, jaccard_threshold)
    catalog = catalog.merge(
        deduplication[["context_id", "representative_context_id", "is_representative"]],
        on="context_id",
        how="left",
        validate="one_to_one",
    )
    catalog["dedup_status"] = np.where(catalog["is_representative"], "representative", "near_duplicate")
    membership_rows = [
        {"context_id": context_id, "compound_id": compound_id}
        for context_id in sorted(memberships)
        for compound_id in sorted(memberships[context_id])
    ]
    membership = pd.DataFrame(membership_rows, columns=["context_id", "compound_id"])
    translations = _translations(catalog, memberships, tier1, translation_auc_min, random_seed)
    translation_status = dict(zip(translations["context_id"], translations["status"], strict=True))
    catalog["translation_status"] = (
        catalog["context_id"].map(translation_status).replace({"not_testable": "untranslatable"}).fillna("native")
    )
    activity = _activity_diagnostic(endpoints, endpoint_id)
    calibration_count = int(catalog["calibration_scope"].sum())
    translated_auc = translations.loc[translations["status"].eq("translated"), "auc"]
    metrics = {
        "context_count": len(catalog),
        "representative_count": int(catalog["is_representative"].sum()),
        "eligible_count": int(catalog["eligible"].sum()),
        "calibration_scope_count": calibration_count,
        "translation_count": len(translations),
        "untranslatable_count": int(translations["status"].eq("untranslatable").sum()),
        "translation_auc_median": float(translated_auc.median()) if not translated_auc.empty else None,
    }
    return ContextBuildResult(catalog, membership, deduplication, translations, activity, metrics)
