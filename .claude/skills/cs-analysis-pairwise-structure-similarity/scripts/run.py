from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from operator_report import render_operator_report


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
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


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2), encoding="utf-8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(clean_json(value), sort_keys=True).encode("utf-8")).hexdigest()


def validate_json(value: dict[str, Any], schema_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required in CONDUCTOR mode") from exc
    schema = json.loads((SKILL_DIR / "schemas" / schema_name).read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Run {CAPABILITY['skill_name']}.")
    operator = CAPABILITY["implementation"]["operator"]
    dependencies = set(CAPABILITY.get("dependencies") or [])
    parser.set_defaults(description=None, smiles_column=None)
    parser.add_argument("--input", required=True, help="Original CSV with compound ID and endpoint.")
    parser.add_argument("--property-column", required=True)
    parser.add_argument("--id-column")
    if operator in {"pairwise_structure_similarity", "activity_cliff", "cluster_structural_diversity"}:
        parser.add_argument("--smiles-column")
    parser.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, default=None)
    if "description" in dependencies:
        parser.add_argument("--description", required=True, help="Description CSV or Parquet.")
    parser.add_argument(
        "--membership",
        required="clustering" in dependencies,
        help="Long or wide Clustering membership CSV. Optional for scoped reruns of otherwise global Operators.",
    )
    parser.add_argument("--target-cluster", help="Cluster used for a within-cluster or first between-clusters scope.")
    parser.add_argument("--comparison-cluster", help="Second Cluster used with --scope-mode between-clusters.")
    parser.add_argument("--scope-mode", choices=["global", "within-cluster", "between-clusters"], default="global")
    parser.add_argument(
        "--reference-scope",
        choices=["global", "local"],
        default="global",
        help="Fit non-Tanimoto Description preprocessing globally or inside the selected scope.",
    )
    parser.add_argument("--clustering-representation")
    parser.add_argument("--evaluation-representation")
    parser.add_argument("--clustering-node-id", help="Source Clustering execution Node ID for CONDUCTOR provenance.")
    parser.add_argument("--description-node-id", help="Source Description execution Node ID for CONDUCTOR provenance.")
    parser.add_argument("--scope-compound-set-hash", help="Canonical explicit-scope identity assigned by the Orchestrator.")
    parser.add_argument("--output-dir")
    parser.add_argument("--run-id")
    parser.add_argument("--project")
    parser.add_argument("--node-id")
    parser.add_argument("--round-id", help="Reserved CONDUCTOR Round ID.")
    parser.add_argument("--attempt-id", help="Runtime-assigned attempt ID for this Node.")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    if operator in {"knn_activity_consistency", "sali"}:
        parser.add_argument("--k", type=int, default=10)
        parser.add_argument("--metric", choices=["auto", "cosine", "euclidean", "manhattan", "tanimoto"], default="auto")
    if operator in {"cluster_profile", "cluster_enrichment"}:
        parser.add_argument("--high-quantile", type=float, default=0.8)
        parser.add_argument("--low-quantile", type=float, default=0.2)
    if operator == "activity_cliff":
        parser.add_argument("--similarity-threshold", type=float, default=0.8)
        parser.add_argument("--activity-delta-threshold", type=float, default=1.0)
    if operator in {"pairwise_structure_similarity", "activity_cliff", "cluster_structural_diversity"}:
        parser.add_argument("--max-pairs", type=int, default=200000)
        parser.add_argument("--random-seed", type=int, default=61453, help="Seed for uniform random sampling when eligible pairs exceed --max-pairs.")
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "node_id", "round_id", "attempt_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, --node-id, --round-id, and --attempt-id")
    elif args.project or args.node_id or args.round_id or args.attempt_id:
        parser.error("--project, --node-id, --round-id, and --attempt-id are valid only with --conductor")
    if hasattr(args, "k") and args.k < 1:
        parser.error("--k must be >= 1")
    if hasattr(args, "max_pairs") and args.max_pairs < 1:
        parser.error("--max-pairs must be >= 1")
    if hasattr(args, "random_seed") and args.random_seed < 0:
        parser.error("--random-seed must be >= 0")
    for name in ("high_quantile", "low_quantile", "similarity_threshold"):
        if hasattr(args, name) and not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    if hasattr(args, "high_quantile") and args.low_quantile >= args.high_quantile:
        parser.error("--low-quantile must be smaller than --high-quantile")
    if hasattr(args, "activity_delta_threshold") and args.activity_delta_threshold < 0:
        parser.error("--activity-delta-threshold must be >= 0")
    if args.target_cluster and args.scope_mode == "global":
        args.scope_mode = "within-cluster"
    if operator == "cluster_overlap" and args.target_cluster:
        parser.error("Cluster overlap compares multiple Clusters and does not accept --target-cluster")
    if args.scope_mode != "global" and not args.membership:
        parser.error("A local scope requires --membership")
    if args.scope_mode == "within-cluster" and not args.target_cluster:
        parser.error("--scope-mode within-cluster requires --target-cluster")
    if args.scope_mode == "between-clusters":
        if operator not in {"pairwise_structure_similarity", "knn_activity_consistency", "sali", "activity_cliff"}:
            parser.error("--scope-mode between-clusters is supported only by pairwise, kNN, SALI, and activity-cliff Operators")
        if not args.target_cluster or not args.comparison_cluster:
            parser.error("--scope-mode between-clusters requires --target-cluster and --comparison-cluster")
        if args.target_cluster == args.comparison_cluster:
            parser.error("--target-cluster and --comparison-cluster must differ")
    elif args.comparison_cluster:
        parser.error("--comparison-cluster is valid only with --scope-mode between-clusters")
    return args


def infer_column(columns: list[str], kind: str) -> str | None:
    preferred = {
        "id": ["compound_id", "compoundid", "molecule_id", "moleculeid", "id", "chembl_id"],
        "smiles": ["smiles", "canonical_smiles", "isomeric_smiles", "structure"],
    }[kind]
    mapping = {"".join(ch for ch in str(column).lower() if ch.isalnum()): str(column) for column in columns}
    for candidate in preferred:
        key = "".join(ch for ch in candidate if ch.isalnum())
        if key in mapping:
            return mapping[key]
    return None


def load_property(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, str, str | None, str, list[str]]:
    if args.higher_is_better is None:
        raise ValueError("--higher-is-better or --no-higher-is-better is required")
    path = Path(args.input)
    header = pd.read_csv(path, nrows=0)
    id_column = args.id_column or infer_column(list(header.columns), "id")
    original = pd.read_csv(path, dtype={id_column: "string"} if id_column else None)
    if id_column is None or id_column not in original.columns:
        raise ValueError("ID column could not be inferred; specify --id-column")
    if args.property_column not in original.columns:
        raise ValueError(f"Property column not found: {args.property_column}")
    if original[id_column].isna().any():
        raise ValueError("Compound IDs must be non-empty and unique")
    ids = original[id_column].astype(str).str.strip()
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError("Compound IDs must be non-empty and unique")
    smiles_column = args.smiles_column or infer_column(list(original.columns), "smiles")
    numeric_property = pd.to_numeric(original[args.property_column], errors="coerce")
    missing_property_count = int(numeric_property.isna().sum())
    input_warnings = [f"{missing_property_count} rows with missing or non-numeric endpoint values were excluded"] if missing_property_count else []
    table = pd.DataFrame({"compound_id": ids, "property_value": numeric_property})
    if smiles_column and smiles_column in original.columns:
        table["input_smiles"] = original[smiles_column]
    table = table.dropna(subset=["property_value"]).copy()
    if len(table) < 2:
        raise ValueError("At least two numeric property values are required")
    return original, table, id_column, smiles_column, file_hash(path), input_warnings


def load_description(
    path_text: str | None,
    property_table: pd.DataFrame,
    reference_property_table: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame | None, list[str], pd.DataFrame | None]:
    if not path_text:
        return None, [], None
    path = Path(path_text)
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
        id_column = infer_column(list(frame.columns), "id")
    else:
        header = pd.read_csv(path, nrows=0)
        id_column = infer_column(list(header.columns), "id")
        frame = pd.read_csv(path, dtype={id_column: "string"} if id_column else None)
    if id_column is None:
        raise ValueError("Description compound ID column could not be inferred")
    if id_column != "compound_id":
        frame = frame.rename(columns={id_column: "compound_id"})
    if frame["compound_id"].isna().any():
        raise ValueError("Description compound IDs must be non-empty and unique")
    frame["compound_id"] = frame["compound_id"].astype(str).str.strip()
    if frame["compound_id"].eq("").any() or frame["compound_id"].duplicated().any():
        raise ValueError("Description compound IDs must be non-empty and unique")
    excluded = {"compound_id", "input_smiles", "canonical_smiles", "mol_parse_ok", "description_error", "descriptor_error"}
    features = [column for column in frame.columns if column not in excluded and pd.api.types.is_numeric_dtype(frame[column]) and frame[column].notna().any()]
    if not features:
        raise ValueError("Description contains no usable numeric feature columns")
    valid_mask = frame[features].notna().any(axis=1)
    if "mol_parse_ok" in frame.columns:
        valid_mask &= frame["mol_parse_ok"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
    frame = frame.loc[valid_mask].copy()
    selected_columns = ["compound_id", *features]
    merged = property_table[["compound_id", "property_value"]].merge(frame[selected_columns], on="compound_id", how="inner")
    reference_source = reference_property_table if reference_property_table is not None else property_table
    reference = reference_source[["compound_id", "property_value"]].merge(frame[selected_columns], on="compound_id", how="inner")
    return merged, features, reference


def membership_sets(path_text: str | None, valid_ids: set[str]) -> dict[str, set[str]]:
    if not path_text:
        return {}
    header = pd.read_csv(path_text, nrows=0)
    membership_id_column = infer_column(list(header.columns), "id")
    frame = pd.read_csv(path_text, dtype={membership_id_column: "string"} if membership_id_column else None)
    clusters: dict[str, set[str]] = {}
    def active_mask(values: pd.Series) -> pd.Series:
        text = values.astype(str).str.strip().str.lower()
        truthy = text.isin({"true", "yes", "y"})
        numeric = pd.to_numeric(values, errors="coerce").fillna(0) > 0
        return truthy | numeric

    if {"cluster_id", "compound_id"}.issubset(frame.columns):
        if "membership_value" in frame.columns:
            frame = frame.loc[active_mask(frame["membership_value"])]
        for cluster_id, cluster_frame in frame.groupby("cluster_id"):
            clusters[str(cluster_id)] = set(cluster_frame["compound_id"].astype(str)) & valid_ids
    else:
        id_column = infer_column(list(frame.columns), "id")
        if id_column is None:
            raise ValueError("Membership ID column could not be inferred")
        ids = frame[id_column].astype(str)
        for column in frame.columns:
            if column == id_column:
                continue
            mask = active_mask(frame[column])
            clusters[str(column)] = set(ids[mask]) & valid_ids
    return {key: value for key, value in clusters.items() if value}


def apply_scope(
    property_table: pd.DataFrame,
    clusters: dict[str, set[str]],
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    all_ids = set(property_table["compound_id"].astype(str))
    if args.scope_mode == "global":
        selected_ids = all_ids
    elif args.scope_mode == "within-cluster":
        if args.target_cluster not in clusters:
            raise ValueError(f"Unknown target Cluster: {args.target_cluster}")
        selected_ids = clusters[args.target_cluster]
    else:
        missing = [cluster_id for cluster_id in (args.target_cluster, args.comparison_cluster) if cluster_id not in clusters]
        if missing:
            raise ValueError(f"Unknown cluster(s): {missing}")
        selected_ids = clusters[args.target_cluster] | clusters[args.comparison_cluster]
    scoped = property_table[property_table["compound_id"].isin(selected_ids)].copy()
    if len(scoped) < 2:
        raise ValueError("The selected scope must contain at least two numeric endpoint values")
    total = max(1, len(property_table))
    scope = {
        "mode": args.scope_mode,
        "target_cluster_id": args.target_cluster,
        "comparison_cluster_id": args.comparison_cluster,
        "sample_count": int(len(scoped)),
        "sample_fraction": float(len(scoped) / total),
        "compound_set_hash": value_hash(sorted(scoped["compound_id"].astype(str).tolist())),
        "reference_scope": args.reference_scope,
    }
    if args.target_cluster in clusters:
        scope["target_cluster_size"] = len(clusters[args.target_cluster])
        scope["target_cluster_fraction"] = len(clusters[args.target_cluster]) / total
    if args.comparison_cluster in clusters:
        scope["comparison_cluster_size"] = len(clusters[args.comparison_cluster])
        scope["comparison_cluster_fraction"] = len(clusters[args.comparison_cluster]) / total
        overlap = clusters[args.target_cluster] & clusters[args.comparison_cluster]
        scope["cluster_overlap_count"] = len(overlap)
    return scoped, scope


def default_output(args: argparse.Namespace, run_id: str) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    root = find_workspace() / "results"
    source_name = Path(args.input).stem
    if args.conductor:
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "analysis" / CAPABILITY["skill_name"] / str(args.node_id).replace(":", "-") / "attempts" / str(args.attempt_id)
    return root / "analysis" / source_name / CAPABILITY["skill_name"] / run_id


def cluster_frames(property_table: pd.DataFrame, clusters: dict[str, set[str]], target_cluster: str | None) -> list[tuple[str | None, pd.DataFrame]]:
    if not clusters:
        return [(None, property_table)]
    selected = {target_cluster: clusters[target_cluster]} if target_cluster else clusters
    return [(cluster_id, property_table[property_table["compound_id"].isin(members)].copy()) for cluster_id, members in selected.items() if cluster_id in clusters]


def activity_distribution(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for cluster_id, frame in cluster_frames(property_table, clusters, args.target_cluster):
        values = frame["property_value"]
        rows.append({"cluster_id": cluster_id or "GLOBAL", "sample_count": len(values), "mean": values.mean(), "median": values.median(), "std": values.std(ddof=1), "min": values.min(), "q25": values.quantile(0.25), "q75": values.quantile(0.75), "max": values.max(), "missing_count": 0})
    result = pd.DataFrame(rows)
    return result, {"analyzed_scope_count": len(result), "global_median": float(property_table["property_value"].median())}


def cluster_profile(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not clusters:
        raise ValueError("--membership is required for cluster profile")
    global_values = property_table["property_value"]
    high = float(global_values.quantile(args.high_quantile)); low = float(global_values.quantile(args.low_quantile))
    rows = []
    for cluster_id, frame in cluster_frames(property_table, clusters, args.target_cluster):
        values = frame["property_value"]
        rows.append({"cluster_id": cluster_id, "sample_count": len(values), "property_mean": values.mean(), "property_median": values.median(), "property_std": values.std(ddof=1), "property_iqr": values.quantile(0.75) - values.quantile(0.25), "property_range": values.max() - values.min(), "high_activity_fraction": float((values >= high).mean()) if args.higher_is_better else float((values <= low).mean()), "low_activity_fraction": float((values <= low).mean()) if args.higher_is_better else float((values >= high).mean())})
    result = pd.DataFrame(rows)
    return result, {"cluster_count": len(result), "high_threshold": high, "low_threshold": low}


def cluster_enrichment(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not clusters:
        raise ValueError("--membership is required for cluster enrichment")
    from scipy.stats import fisher_exact, mannwhitneyu
    values = property_table["property_value"]
    threshold = float(values.quantile(args.high_quantile if args.higher_is_better else args.low_quantile))
    favorable = values >= threshold if args.higher_is_better else values <= threshold
    property_table = property_table.assign(favorable=favorable.to_numpy())
    rows = []
    all_ids = set(property_table["compound_id"])
    selected_clusters = {args.target_cluster: clusters[args.target_cluster]} if args.target_cluster else clusters
    for cluster_id, members in selected_clusters.items():
        in_cluster = property_table["compound_id"].isin(members)
        a = int((in_cluster & property_table["favorable"]).sum()); b = int((in_cluster & ~property_table["favorable"]).sum())
        c = int((~in_cluster & property_table["favorable"]).sum()); d = int((~in_cluster & ~property_table["favorable"]).sum())
        odds, fisher_p = fisher_exact([[a, b], [c, d]])
        inside = property_table.loc[in_cluster, "property_value"]; outside = property_table.loc[~in_cluster, "property_value"]
        mw_p = mannwhitneyu(inside, outside, alternative="two-sided").pvalue if len(inside) and len(outside) else np.nan
        rows.append({"cluster_id": cluster_id, "sample_count": len(inside), "favorable_count": a, "favorable_fraction": a / max(1, a + b), "global_favorable_fraction": (a + c) / max(1, len(all_ids)), "odds_ratio": odds, "fisher_pvalue": fisher_p, "mannwhitney_pvalue": mw_p, "median_shift_vs_global": inside.median() - values.median()})
    result = pd.DataFrame(rows).sort_values(["fisher_pvalue", "cluster_id"])
    return result, {"cluster_count": len(result), "favorable_threshold": threshold}


def pairwise_structure(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray, list[str], dict[str, Any]]:
    if "input_smiles" not in property_table.columns:
        raise ValueError("A SMILES column is required")
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    ids: list[str] = []
    props: list[float] = []
    fps = []
    warnings: list[str] = []
    for row in property_table.itertuples(index=False):
        mol = Chem.MolFromSmiles(str(row.input_smiles))
        if mol is None:
            warnings.append(f"{row.compound_id}: invalid SMILES")
            continue
        ids.append(str(row.compound_id)); props.append(float(row.property_value)); fps.append(generator.GetFingerprint(mol))
    rng = random.Random(args.random_seed)
    selected_pairs: list[tuple[int, int]] = []
    eligible_pair_count = 0
    for i, j in combinations(range(len(ids)), 2):
        if args.scope_mode == "between-clusters":
            left_to_right = ids[i] in clusters[args.target_cluster] and ids[j] in clusters[args.comparison_cluster]
            right_to_left = ids[j] in clusters[args.target_cluster] and ids[i] in clusters[args.comparison_cluster]
            if not (left_to_right or right_to_left):
                continue
        eligible_pair_count += 1
        if len(selected_pairs) < args.max_pairs:
            selected_pairs.append((i, j))
        else:
            replacement = rng.randrange(eligible_pair_count)
            if replacement < args.max_pairs:
                selected_pairs[replacement] = (i, j)
    sampled = eligible_pair_count > args.max_pairs
    if sampled:
        warnings.append(f"Eligible pairs uniformly sampled to {args.max_pairs} with seed {args.random_seed}")
    pair_rows = []
    for i, j in sorted(selected_pairs):
        similarity = float(DataStructs.TanimotoSimilarity(fps[i], fps[j]))
        pair_rows.append({"compound_id_a": ids[i], "compound_id_b": ids[j], "similarity": similarity, "distance": 1.0 - similarity, "property_a": props[i], "property_b": props[j], "abs_delta_property": abs(props[i] - props[j])})
    columns = ["compound_id_a", "compound_id_b", "similarity", "distance", "property_a", "property_b", "abs_delta_property"]
    sampling = {"eligible_pair_count": eligible_pair_count, "evaluated_pair_count": len(selected_pairs), "pair_sampling": "uniform_random_without_replacement" if sampled else "exhaustive", "random_seed": args.random_seed}
    return pd.DataFrame(pair_rows, columns=columns), np.asarray(props, dtype=float), warnings, sampling


def pairwise_similarity_analysis(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    pairs, _, warnings, sampling = pairwise_structure(property_table, clusters, args)
    summary = {"pair_count": len(pairs), "mean_similarity": float(pairs["similarity"].mean()) if len(pairs) else None, "median_similarity": float(pairs["similarity"].median()) if len(pairs) else None, "p90_similarity": float(pairs["similarity"].quantile(0.9)) if len(pairs) else None, **sampling}
    return pairs, summary, warnings


def activity_cliff(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    pairs, _, warnings, sampling = pairwise_structure(property_table, clusters, args)
    cliffs = pairs[(pairs["similarity"] >= args.similarity_threshold) & (pairs["abs_delta_property"] >= args.activity_delta_threshold)].copy()
    if len(cliffs):
        cliffs["cliff_score"] = cliffs["abs_delta_property"] / np.maximum(1.0 - cliffs["similarity"], 1e-6)
        cliffs = cliffs.sort_values("cliff_score", ascending=False)
    return cliffs, {"pair_count": len(pairs), "cliff_count": len(cliffs), "cliff_density": len(cliffs) / max(1, len(pairs)), "similarity_threshold": args.similarity_threshold, "activity_delta_threshold": args.activity_delta_threshold, **sampling}, warnings


def resolve_metric(matrix: np.ndarray, features: list[str], args: argparse.Namespace) -> str:
    requested = args.metric
    representation = str(args.evaluation_representation or "").upper()
    feature_names = [str(feature).lower() for feature in features]
    fingerprint_ids = {"D002", "D003", "D007", "D008", "D009", "D010"}
    is_latent = representation == "D020" or any("embedding" in name or "svd" in name for name in feature_names)
    declared_binary = representation in fingerprint_ids
    inferred_binary = not representation and bool(matrix.size) and bool(np.all((matrix == 0) | (matrix == 1)))
    is_fingerprint = declared_binary or (
        not representation and bool(feature_names)
        and all(name.startswith(("morgan_", "maccs_", "rdkitfp_", "patternfp_", "layeredfp_")) for name in feature_names)
    )
    is_binary = declared_binary or inferred_binary
    is_usr = representation == "D013" or any(name.startswith(("usr__", "usrcat__")) for name in feature_names)
    nonnegative_integer = bool(matrix.size) and bool(np.all(matrix >= 0) and np.allclose(matrix, np.round(matrix)))
    sparse = bool(matrix.size) and float(np.count_nonzero(matrix)) / float(matrix.size) < 0.5

    if requested == "auto":
        if is_fingerprint or is_binary:
            return "tanimoto"
        if is_usr:
            return "manhattan"
        if is_latent or (nonnegative_integer and sparse):
            return "cosine"
        return "euclidean"
    if is_binary and requested != "tanimoto":
        raise ValueError("Binary Description vectors require --metric tanimoto")
    if is_fingerprint and requested != "tanimoto":
        raise ValueError(f"{representation or 'Fingerprint'} representations require --metric tanimoto")
    if requested == "tanimoto" and np.any(matrix < 0):
        raise ValueError("--metric tanimoto requires non-negative Description values")
    return requested


def description_matrix(
    description: pd.DataFrame | None,
    features: list[str],
    args: argparse.Namespace,
    reference_description: pd.DataFrame | None = None,
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, str]:
    if description is None or not features:
        raise ValueError("--description with numeric features is required")
    if len(description) < 2:
        raise ValueError("At least two compounds with endpoint and Description values are required")
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import pairwise_distances
    from sklearn.preprocessing import StandardScaler
    fit_frame = reference_description if args.reference_scope == "global" and reference_description is not None else description
    imputer = SimpleImputer(strategy="median").fit(fit_frame[features])
    matrix = imputer.transform(description[features])
    reference_matrix = imputer.transform(fit_frame[features])
    resolved_metric = resolve_metric(matrix, features, args)
    if resolved_metric in {"euclidean", "manhattan"}:
        scaler = StandardScaler().fit(reference_matrix)
        matrix = scaler.transform(matrix)
    if resolved_metric == "tanimoto":
        dot = matrix @ matrix.T
        squared = np.sum(matrix * matrix, axis=1)
        denominator = squared[:, None] + squared[None, :] - dot
        similarity = np.divide(dot, denominator, out=np.zeros_like(dot, dtype=float), where=denominator > 0)
        distance = 1.0 - np.clip(similarity, 0.0, 1.0)
        np.fill_diagonal(distance, 0.0)
    else:
        distance = pairwise_distances(matrix, metric=resolved_metric)
    return description["compound_id"].astype(str).tolist(), description["property_value"].to_numpy(float), matrix, distance, resolved_metric


def knn_edges(
    description: pd.DataFrame | None,
    features: list[str],
    clusters: dict[str, set[str]],
    args: argparse.Namespace,
    reference_description: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ids, properties, _, distance, resolved_metric = description_matrix(description, features, args, reference_description)
    effective_k = min(args.k, len(ids) - 1)
    rows = []
    for i in range(len(ids)):
        if args.scope_mode == "between-clusters":
            if ids[i] in clusters[args.target_cluster]:
                candidate_indices = [j for j, compound_id in enumerate(ids) if j != i and compound_id in clusters[args.comparison_cluster]]
            elif ids[i] in clusters[args.comparison_cluster]:
                candidate_indices = [j for j, compound_id in enumerate(ids) if j != i and compound_id in clusters[args.target_cluster]]
            else:
                candidate_indices = []
            neighbors = sorted(candidate_indices, key=lambda j: distance[i, j])[:effective_k]
        else:
            neighbors = [int(j) for j in np.argsort(distance[i]) if int(j) != i][:effective_k]
        for rank, j in enumerate(neighbors, start=1):
            rows.append({"compound_id": ids[i], "neighbor_id": ids[j], "neighbor_rank": rank, "distance": distance[i, j], "property_value": properties[i], "neighbor_property_value": properties[j], "abs_delta_property": abs(properties[i] - properties[j])})
    frame = pd.DataFrame(rows)
    corr = frame[["property_value", "neighbor_property_value"]].corr(method="spearman").iloc[0, 1] if len(frame) else np.nan
    return frame, {"sample_count": len(ids), "effective_k": effective_k, "requested_metric": args.metric, "metric": resolved_metric, "reference_scope": args.reference_scope, "median_abs_delta_property": frame["abs_delta_property"].median() if len(frame) else np.nan, "neighbor_property_spearman": corr}


def sali_analysis(
    description: pd.DataFrame | None,
    features: list[str],
    clusters: dict[str, set[str]],
    args: argparse.Namespace,
    reference_description: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, summary = knn_edges(description, features, clusters, args, reference_description)
    frame["sali"] = frame["abs_delta_property"] / np.maximum(frame["distance"], 1e-6)
    frame = frame.sort_values("sali", ascending=False)
    top_columns = ["compound_id", "neighbor_id", "neighbor_rank", "distance", "abs_delta_property", "sali"]
    summary.update({
        "landscape_scope": "directed_k_nearest_neighbor_edges",
        "sali_definition": "abs_delta_property / max(distance, 1e-6)",
        "mean_sali": frame["sali"].mean(),
        "median_sali": frame["sali"].median(),
        "p75_sali": frame["sali"].quantile(0.75),
        "p90_sali": frame["sali"].quantile(0.9),
        "p95_sali": frame["sali"].quantile(0.95),
        "max_sali": frame["sali"].max(),
        "near_zero_distance_edge_count": int((frame["distance"] <= 1e-6).sum()),
        "top_sali_pairs": frame[top_columns].head(20).to_dict(orient="records"),
        "interpretation_guidance": {
            "high_upper_tail": "localized cliffs or steep regions that require chemical and assay-context explanation",
            "low_center_and_upper_tail": "a comparatively smooth landscape in this representation, potentially consistent with good property organization",
            "comparison_limit": "raw SALI scales are compared within the same endpoint scale and metric; use neighbor property deltas and ranks across different metrics",
        },
    })
    return frame, summary


def descriptor_correlation(description: pd.DataFrame | None, features: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if description is None:
        raise ValueError("--description is required")
    from scipy.stats import pearsonr, spearmanr
    rows = []
    for feature in features:
        frame = description[[feature, "property_value"]].dropna()
        if len(frame) < 3 or frame[feature].nunique() < 2:
            continue
        pearson = pearsonr(frame[feature], frame["property_value"])
        spearman = spearmanr(frame[feature], frame["property_value"])
        rows.append({"feature": feature, "sample_count": len(frame), "pearson_r": pearson.statistic, "pearson_pvalue": pearson.pvalue, "spearman_rho": spearman.statistic, "spearman_pvalue": spearman.pvalue})
    result = pd.DataFrame(rows, columns=["feature", "sample_count", "pearson_r", "pearson_pvalue", "spearman_rho", "spearman_pvalue"])
    if len(result):
        result["max_abs_association"] = result[["pearson_r", "spearman_rho"]].abs().max(axis=1)
        result = result.sort_values("max_abs_association", ascending=False)
    return result, {"tested_feature_count": len(result), "top_features": result.head(10)["feature"].tolist() if len(result) else []}


def cluster_overlap(clusters: dict[str, set[str]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not clusters:
        raise ValueError("--membership is required")
    rows = []
    for left, right in combinations(sorted(clusters), 2):
        intersection = clusters[left] & clusters[right]; union = clusters[left] | clusters[right]
        rows.append({"cluster_id_a": left, "cluster_id_b": right, "intersection_count": len(intersection), "union_count": len(union), "jaccard": len(intersection) / len(union) if union else 0.0})
    result = pd.DataFrame(rows, columns=["cluster_id_a", "cluster_id_b", "intersection_count", "union_count", "jaccard"])
    return result, {"cluster_count": len(clusters), "pair_count": len(result), "max_jaccard": result["jaccard"].max() if len(result) else None}


def cluster_structural_diversity(property_table: pd.DataFrame, clusters: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    if not clusters:
        raise ValueError("--membership is required")
    rows = []
    warnings: list[str] = []
    sampling_by_cluster: dict[str, Any] = {}
    selected_clusters = {args.target_cluster: clusters[args.target_cluster]} if args.target_cluster else clusters
    for cluster_id, members in selected_clusters.items():
        cluster_table = property_table[property_table["compound_id"].isin(members)]
        pairs, _, pair_warnings, sampling = pairwise_structure(cluster_table, clusters, args)
        sampling_by_cluster[str(cluster_id)] = sampling
        warnings.extend(f"{cluster_id}: {warning}" for warning in pair_warnings)
        rows.append({"cluster_id": cluster_id, "sample_count": len(cluster_table), "pair_count": len(pairs), "mean_tanimoto": pairs["similarity"].mean() if len(pairs) else np.nan, "median_tanimoto": pairs["similarity"].median() if len(pairs) else np.nan, "p90_tanimoto": pairs["similarity"].quantile(0.9) if len(pairs) else np.nan, "structural_diversity_score": 1.0 - pairs["similarity"].mean() if len(pairs) else np.nan})
    result = pd.DataFrame(rows)
    return result, {"cluster_count": len(result), "pair_sampling_by_cluster": sampling_by_cluster}, warnings


def execute(
    operator: str,
    property_table: pd.DataFrame,
    clusters: dict[str, set[str]],
    description: pd.DataFrame | None,
    features: list[str],
    args: argparse.Namespace,
    reference_description: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    if operator == "activity_distribution":
        result, summary = activity_distribution(property_table, clusters, args); return result, summary, []
    if operator == "cluster_profile":
        result, summary = cluster_profile(property_table, clusters, args); return result, summary, []
    if operator == "cluster_enrichment":
        result, summary = cluster_enrichment(property_table, clusters, args); return result, summary, []
    if operator == "pairwise_structure_similarity":
        return pairwise_similarity_analysis(property_table, clusters, args)
    if operator == "activity_cliff":
        return activity_cliff(property_table, clusters, args)
    if operator == "descriptor_activity_correlation":
        result, summary = descriptor_correlation(description, features); return result, summary, []
    if operator == "knn_activity_consistency":
        result, summary = knn_edges(description, features, clusters, args, reference_description); return result, summary, []
    if operator == "sali":
        result, summary = sali_analysis(description, features, clusters, args, reference_description); return result, summary, []
    if operator == "cluster_overlap":
        result, summary = cluster_overlap(clusters); return result, summary, []
    if operator == "cluster_structural_diversity":
        return cluster_structural_diversity(property_table, clusters, args)
    raise ValueError(f"Unsupported operator: {operator}")


def generated_result_records(result: pd.DataFrame, operator: str) -> list[dict[str, Any]]:
    if not len(result):
        return []
    cluster_columns = {"cluster_id", "cluster_id_a", "cluster_id_b"}
    if cluster_columns.intersection(result.columns):
        limit = 5000
    elif operator == "descriptor_activity_correlation":
        limit = 100
    else:
        return []
    records = []
    for index, row in result.head(limit).iterrows():
        records.append({"record_id": f"{operator}:{index}", "values": clean_json(row.to_dict())})
    return records


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    run_id = args.run_id or run_id_now()
    _, full_property_table, id_column, smiles_column, property_input_hash, input_warnings = load_property(args)
    input_components = [{"role": "endpoint", "path": str(Path(args.input).resolve()), "sha256": property_input_hash}]
    if args.description:
        description_path = Path(args.description)
        input_components.append({"role": "description", "path": str(description_path.resolve()), "sha256": file_hash(description_path)})
    if args.membership:
        membership_path = Path(args.membership)
        input_components.append({"role": "membership", "path": str(membership_path.resolve()), "sha256": file_hash(membership_path)})
    input_hash = value_hash(input_components)
    clusters = membership_sets(args.membership, set(full_property_table["compound_id"]))
    operator = CAPABILITY["implementation"]["operator"]
    scoped_property_table, scope = apply_scope(full_property_table, clusters, args)
    if args.scope_compound_set_hash:
        scope["selection_hash"] = args.scope_compound_set_hash
    cluster_context_operators = {"cluster_profile", "cluster_enrichment", "cluster_overlap", "cluster_structural_diversity"}
    property_table = full_property_table if operator in cluster_context_operators else scoped_property_table
    description, features, reference_description = load_description(args.description, scoped_property_table, full_property_table)
    outdir = default_output(args, run_id)
    if outdir.exists() and any(outdir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
        for name in [CAPABILITY["output"]["filename"], "operator_report.html", "analysis_manifest.json", "operator_summary.json", "warnings.json", "execution_event.json"]:
            (outdir / name).unlink(missing_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    result, summary, warnings = execute(operator, property_table, clusters, description, features, args, reference_description)
    summary["scope"] = scope
    warnings = input_warnings + warnings
    result_path = outdir / CAPABILITY["output"]["filename"]
    result.to_csv(result_path, index=False)
    target_cluster = args.target_cluster
    supporting_compounds: list[str] = []
    supporting_pairs: list[dict[str, Any]] = []
    if "compound_id" in result.columns:
        supporting_compounds = list(dict.fromkeys(result["compound_id"].dropna().astype(str).head(100).tolist()))
    if {"compound_id_a", "compound_id_b"}.issubset(result.columns):
        pair_columns = [column for column in ("compound_id_a", "compound_id_b", "similarity", "distance", "abs_delta_property", "cliff_score") if column in result.columns]
        supporting_pairs = result[pair_columns].head(100).to_dict(orient="records")
    elif {"compound_id", "neighbor_id"}.issubset(result.columns):
        pair_columns = [column for column in ("compound_id", "neighbor_id", "neighbor_rank", "distance", "abs_delta_property", "sali") if column in result.columns]
        supporting_pairs = result[pair_columns].head(100).rename(columns={"compound_id": "compound_id_a", "neighbor_id": "compound_id_b"}).to_dict(orient="records")
    if operator == "sali":
        human_summary = (
            f"{CAPABILITY['display_name']} analyzed {scope['sample_count']} scoped endpoint rows with "
            f"{summary.get('metric')} distance. Median SALI={clean_json(summary.get('median_sali'))}, "
            f"p95 SALI={clean_json(summary.get('p95_sali'))}. Inspect the upper tail for localized cliffs "
            "and the center plus upper tail for overall landscape smoothness."
        )
        uncertainty = {
            "metric_scale_dependence": "Raw SALI values depend on the endpoint scale and selected distance metric.",
            "measurement_context": "High SALI pairs require assay-error and condition checks before chemical interpretation.",
        }
    else:
        human_summary = f"{CAPABILITY['display_name']} analyzed scope={scope['mode']} with {scope['sample_count']} endpoint rows. See {result_path.name}."
        uncertainty = None
    source_nodes = [value for value in (args.description_node_id, args.clustering_node_id) if value]
    result_ref = f"{args.node_id}@{args.attempt_id}" if args.conductor else f"standalone:{value_hash([run_id, CAPABILITY['operator_id'], scope['compound_set_hash']])[:16]}"
    if args.conductor and args.scope_mode == "within-cluster" and args.target_cluster:
        result_ref += f"/{args.target_cluster}"
    operator_summary = {
        "schema_version": "1.0.0", "result_ref": result_ref, "node_id": args.node_id, "attempt_id": args.attempt_id,
        "operator_id": CAPABILITY["operator_id"], "operator_name": CAPABILITY["display_name"], "run_id": run_id, "round_id": args.round_id,
        "scope": scope, "scope_context": {"description_node_ids": [args.description_node_id] if args.description_node_id else [], "clustering_node_ids": [args.clustering_node_id] if args.clustering_node_id else [], "cluster_ids": [value for value in (args.target_cluster, args.comparison_cluster) if value]},
        "sample_count": int(scope["sample_count"]), "endpoint": {"column": args.property_column, "higher_is_better": bool(args.higher_is_better)}, "metric": summary.get("metric"), "headline": human_summary,
        "key_metrics": summary, "top_records": generated_result_records(result, operator),
        "supporting_compounds": supporting_compounds, "supporting_pairs": supporting_pairs,
        "limitations": [item for item in [*(warnings or []), *(uncertainty.values() if uncertainty else [])] if item],
        "warnings": list(warnings or []), "primary_artifact": {"path": result_path.name, "sha256": file_hash(result_path)},
        "source_nodes": source_nodes, "evaluation_representation": args.evaluation_representation,
        "clustering_representation": args.clustering_representation, "created_at": utc_now(),
    }
    config = {key: value for key, value in vars(args).items()}
    manifest = {"schema_version": "2.0.0", "conductor_version": "0.1.3", "artifact_stage": "analysis", "run_id": run_id, "node_id": args.node_id, "attempt_id": args.attempt_id, "capability_id": CAPABILITY["capability_id"], "operator_id": CAPABILITY["operator_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"], "input": args.input, "input_hash": input_hash, "value_semantics": "operator_result", "natural_metric": summary.get("metric"), "id_column": id_column, "property_column": args.property_column, "higher_is_better": args.higher_is_better, "description": args.description, "membership": args.membership, "scope": scope, "output": result_path.name, "warnings": warnings, "created_at": utc_now(), "configuration": config}
    if args.conductor:
        report_path = outdir / "operator_report.html"
        report_path.write_text(
            render_operator_report(CAPABILITY, args, result, summary, operator_summary, manifest, result_path),
            encoding="utf-8",
        )
        report_artifact = {"type": "operator_report", "path": report_path.name, "sha256": file_hash(report_path)}
        manifest["report"] = report_path.name
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "analysis_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings})
    if args.conductor:
        validate_json(operator_summary, "operator_summary.schema.json")
        write_json(outdir / "operator_summary.json", operator_summary)
        event = {"schema_version": "2.0.0", "project": args.project, "run_id": run_id, "round_id": args.round_id, "node_id": args.node_id, "attempt_id": args.attempt_id, "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded", "input_hash": input_hash, "config_hash": value_hash(config), "configuration": config, "artifacts": [{"type": "operator_result", "path": result_path.name, "sha256": file_hash(result_path)}, {"type": "operator_report", "path": "operator_report.html", "sha256": file_hash(outdir / "operator_report.html")}, {"type": "operator_summary", "path": "operator_summary.json", "sha256": file_hash(outdir / "operator_summary.json")}, {"type": "manifest", "path": "analysis_manifest.json", "sha256": file_hash(outdir / "analysis_manifest.json")}], "warnings": warnings, "started_at": started_at, "finished_at": utc_now()}
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
