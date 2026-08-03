from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def find_workspace() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / ".claude").exists() and (candidate / "catalog").exists():
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
    parser.set_defaults(description=None, membership=None, smiles_column=None, target_group=None)
    parser.add_argument("--input", required=True, help="Original CSV with compound ID and endpoint.")
    parser.add_argument("--property-column", required=True)
    parser.add_argument("--id-column")
    if operator in {"pairwise_structure_similarity", "activity_cliff", "group_structural_diversity"}:
        parser.add_argument("--smiles-column")
    parser.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, default=None)
    if "description" in dependencies:
        parser.add_argument("--description", required=True, help="Description CSV or Parquet.")
    if "grouping" in dependencies:
        parser.add_argument("--membership", required=True, help="Long or wide Grouping membership CSV.")
    elif operator == "activity_distribution":
        parser.add_argument("--membership", help="Optional long or wide Grouping membership CSV.")
    if operator in {"group_profile", "activity_distribution"}:
        parser.add_argument("--target-group")
    parser.add_argument("--grouping-representation")
    parser.add_argument("--evaluation-representation")
    parser.add_argument("--output-dir")
    parser.add_argument("--run-id")
    parser.add_argument("--project")
    parser.add_argument("--node-id")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    if operator in {"knn_activity_consistency", "sali"}:
        parser.add_argument("--k", type=int, default=10)
        parser.add_argument("--metric", choices=["cosine", "euclidean", "manhattan", "tanimoto"], default="cosine")
    if operator in {"group_profile", "group_enrichment"}:
        parser.add_argument("--high-quantile", type=float, default=0.8)
        parser.add_argument("--low-quantile", type=float, default=0.2)
    if operator == "activity_cliff":
        parser.add_argument("--similarity-threshold", type=float, default=0.8)
        parser.add_argument("--activity-delta-threshold", type=float, default=1.0)
    if operator in {"pairwise_structure_similarity", "activity_cliff", "group_structural_diversity"}:
        parser.add_argument("--max-pairs", type=int, default=200000)
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "node_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, and --node-id")
    elif args.project or args.node_id:
        parser.error("--project and --node-id are valid only with --conductor")
    if hasattr(args, "k") and args.k < 1:
        parser.error("--k must be >= 1")
    if hasattr(args, "max_pairs") and args.max_pairs < 1:
        parser.error("--max-pairs must be >= 1")
    for name in ("high_quantile", "low_quantile", "similarity_threshold"):
        if hasattr(args, name) and not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    if hasattr(args, "high_quantile") and args.low_quantile >= args.high_quantile:
        parser.error("--low-quantile must be smaller than --high-quantile")
    if hasattr(args, "activity_delta_threshold") and args.activity_delta_threshold < 0:
        parser.error("--activity-delta-threshold must be >= 0")
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
    original = pd.read_csv(path)
    id_column = args.id_column or infer_column(list(original.columns), "id")
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


def load_description(path_text: str | None, property_table: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    if not path_text:
        return None, []
    path = Path(path_text)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    id_column = infer_column(list(frame.columns), "id")
    if id_column is None:
        raise ValueError("Description compound ID column could not be inferred")
    if id_column != "compound_id":
        frame = frame.rename(columns={id_column: "compound_id"})
    frame["compound_id"] = frame["compound_id"].astype(str)
    excluded = {"compound_id", "input_smiles", "canonical_smiles", "mol_parse_ok", "description_error", "descriptor_error"}
    features = [column for column in frame.columns if column not in excluded and pd.api.types.is_numeric_dtype(frame[column])]
    merged = property_table[["compound_id", "property_value"]].merge(frame[["compound_id", *features]], on="compound_id", how="inner")
    return merged, features


def membership_sets(path_text: str | None, valid_ids: set[str]) -> dict[str, set[str]]:
    if not path_text:
        return {}
    frame = pd.read_csv(path_text)
    groups: dict[str, set[str]] = {}
    if {"cluster_id", "compound_id"}.issubset(frame.columns):
        for group_id, group in frame.groupby("cluster_id"):
            groups[str(group_id)] = set(group["compound_id"].astype(str)) & valid_ids
    elif {"group_id", "compound_id"}.issubset(frame.columns):
        for group_id, group in frame.groupby("group_id"):
            groups[str(group_id)] = set(group["compound_id"].astype(str)) & valid_ids
    else:
        id_column = infer_column(list(frame.columns), "id")
        if id_column is None:
            raise ValueError("Membership ID column could not be inferred")
        ids = frame[id_column].astype(str)
        for column in frame.columns:
            if column == id_column:
                continue
            mask = pd.to_numeric(frame[column], errors="coerce").fillna(0) > 0
            groups[str(column)] = set(ids[mask]) & valid_ids
    return {key: value for key, value in groups.items() if value}


def default_output(args: argparse.Namespace, run_id: str) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    root = find_workspace() / "results"
    source_name = Path(args.input).stem
    if args.conductor:
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "analysis" / CAPABILITY["skill_name"]
    return root / "analysis" / source_name / CAPABILITY["skill_name"] / run_id


def group_frames(property_table: pd.DataFrame, groups: dict[str, set[str]], target_group: str | None) -> list[tuple[str | None, pd.DataFrame]]:
    if not groups:
        return [(None, property_table)]
    selected = {target_group: groups[target_group]} if target_group else groups
    return [(group_id, property_table[property_table["compound_id"].isin(members)].copy()) for group_id, members in selected.items() if group_id in groups]


def activity_distribution(property_table: pd.DataFrame, groups: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for group_id, frame in group_frames(property_table, groups, args.target_group):
        values = frame["property_value"]
        rows.append({"group_id": group_id or "GLOBAL", "sample_count": len(values), "mean": values.mean(), "median": values.median(), "std": values.std(ddof=1), "min": values.min(), "q25": values.quantile(0.25), "q75": values.quantile(0.75), "max": values.max(), "missing_count": 0})
    result = pd.DataFrame(rows)
    return result, {"analyzed_scope_count": len(result), "global_median": float(property_table["property_value"].median())}


def group_profile(property_table: pd.DataFrame, groups: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not groups:
        raise ValueError("--membership is required for group profile")
    global_values = property_table["property_value"]
    high = float(global_values.quantile(args.high_quantile)); low = float(global_values.quantile(args.low_quantile))
    rows = []
    for group_id, frame in group_frames(property_table, groups, args.target_group):
        values = frame["property_value"]
        rows.append({"group_id": group_id, "sample_count": len(values), "property_mean": values.mean(), "property_median": values.median(), "property_std": values.std(ddof=1), "property_iqr": values.quantile(0.75) - values.quantile(0.25), "property_range": values.max() - values.min(), "high_activity_fraction": float((values >= high).mean()) if args.higher_is_better else float((values <= low).mean()), "low_activity_fraction": float((values <= low).mean()) if args.higher_is_better else float((values >= high).mean())})
    result = pd.DataFrame(rows)
    return result, {"group_count": len(result), "high_threshold": high, "low_threshold": low}


def group_enrichment(property_table: pd.DataFrame, groups: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not groups:
        raise ValueError("--membership is required for group enrichment")
    from scipy.stats import fisher_exact, mannwhitneyu
    values = property_table["property_value"]
    threshold = float(values.quantile(args.high_quantile if args.higher_is_better else args.low_quantile))
    favorable = values >= threshold if args.higher_is_better else values <= threshold
    property_table = property_table.assign(favorable=favorable.to_numpy())
    rows = []
    all_ids = set(property_table["compound_id"])
    for group_id, members in groups.items():
        in_group = property_table["compound_id"].isin(members)
        a = int((in_group & property_table["favorable"]).sum()); b = int((in_group & ~property_table["favorable"]).sum())
        c = int((~in_group & property_table["favorable"]).sum()); d = int((~in_group & ~property_table["favorable"]).sum())
        odds, fisher_p = fisher_exact([[a, b], [c, d]])
        inside = property_table.loc[in_group, "property_value"]; outside = property_table.loc[~in_group, "property_value"]
        mw_p = mannwhitneyu(inside, outside, alternative="two-sided").pvalue if len(inside) and len(outside) else np.nan
        rows.append({"group_id": group_id, "sample_count": len(inside), "favorable_count": a, "favorable_fraction": a / max(1, a + b), "global_favorable_fraction": (a + c) / max(1, len(all_ids)), "odds_ratio": odds, "fisher_pvalue": fisher_p, "mannwhitney_pvalue": mw_p, "median_shift_vs_global": inside.median() - values.median()})
    result = pd.DataFrame(rows).sort_values(["fisher_pvalue", "group_id"])
    return result, {"group_count": len(result), "favorable_threshold": threshold}


def pairwise_structure(property_table: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
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
    pair_rows = []
    for pair_index, (i, j) in enumerate(combinations(range(len(ids)), 2)):
        if pair_index >= args.max_pairs:
            warnings.append(f"Pair enumeration capped at {args.max_pairs}")
            break
        similarity = float(DataStructs.TanimotoSimilarity(fps[i], fps[j]))
        pair_rows.append({"compound_id_a": ids[i], "compound_id_b": ids[j], "similarity": similarity, "distance": 1.0 - similarity, "property_a": props[i], "property_b": props[j], "abs_delta_property": abs(props[i] - props[j])})
    columns = ["compound_id_a", "compound_id_b", "similarity", "distance", "property_a", "property_b", "abs_delta_property"]
    return pd.DataFrame(pair_rows, columns=columns), np.asarray(props, dtype=float), warnings


def pairwise_similarity_analysis(property_table: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    pairs, _, warnings = pairwise_structure(property_table, args)
    summary = {"pair_count": len(pairs), "mean_similarity": float(pairs["similarity"].mean()) if len(pairs) else None, "median_similarity": float(pairs["similarity"].median()) if len(pairs) else None, "p90_similarity": float(pairs["similarity"].quantile(0.9)) if len(pairs) else None}
    return pairs, summary, warnings


def activity_cliff(property_table: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    pairs, _, warnings = pairwise_structure(property_table, args)
    cliffs = pairs[(pairs["similarity"] >= args.similarity_threshold) & (pairs["abs_delta_property"] >= args.activity_delta_threshold)].copy()
    if len(cliffs):
        cliffs["cliff_score"] = cliffs["abs_delta_property"] / np.maximum(1.0 - cliffs["similarity"], 1e-6)
        cliffs = cliffs.sort_values("cliff_score", ascending=False)
    return cliffs, {"pair_count": len(pairs), "cliff_count": len(cliffs), "cliff_density": len(cliffs) / max(1, len(pairs)), "similarity_threshold": args.similarity_threshold, "activity_delta_threshold": args.activity_delta_threshold}, warnings


def description_matrix(description: pd.DataFrame | None, features: list[str], args: argparse.Namespace) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    if description is None or not features:
        raise ValueError("--description with numeric features is required")
    if len(description) < 2:
        raise ValueError("At least two compounds with endpoint and Description values are required")
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import pairwise_distances
    from sklearn.preprocessing import StandardScaler
    matrix = SimpleImputer(strategy="median").fit_transform(description[features])
    if args.metric not in {"tanimoto"}:
        matrix = StandardScaler().fit_transform(matrix)
    if args.metric == "tanimoto":
        binary = matrix > 0
        intersection = binary.astype(int) @ binary.astype(int).T
        sums = binary.sum(axis=1)
        union = sums[:, None] + sums[None, :] - intersection
        distance = 1.0 - np.divide(intersection, union, out=np.zeros_like(intersection, dtype=float), where=union != 0)
    else:
        distance = pairwise_distances(matrix, metric=args.metric)
    return description["compound_id"].astype(str).tolist(), description["property_value"].to_numpy(float), matrix, distance


def knn_edges(description: pd.DataFrame | None, features: list[str], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    ids, properties, _, distance = description_matrix(description, features, args)
    effective_k = min(args.k, len(ids) - 1)
    rows = []
    for i in range(len(ids)):
        neighbors = np.argsort(distance[i])[1 : effective_k + 1]
        for rank, j in enumerate(neighbors, start=1):
            rows.append({"compound_id": ids[i], "neighbor_id": ids[j], "neighbor_rank": rank, "distance": distance[i, j], "property_value": properties[i], "neighbor_property_value": properties[j], "abs_delta_property": abs(properties[i] - properties[j])})
    frame = pd.DataFrame(rows)
    corr = frame[["property_value", "neighbor_property_value"]].corr(method="spearman").iloc[0, 1] if len(frame) else np.nan
    return frame, {"sample_count": len(ids), "effective_k": effective_k, "median_abs_delta_property": frame["abs_delta_property"].median() if len(frame) else np.nan, "neighbor_property_spearman": corr}


def sali_analysis(description: pd.DataFrame | None, features: list[str], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, summary = knn_edges(description, features, args)
    frame["sali"] = frame["abs_delta_property"] / np.maximum(frame["distance"], 1e-6)
    summary.update({"median_sali": frame["sali"].median(), "p90_sali": frame["sali"].quantile(0.9), "p95_sali": frame["sali"].quantile(0.95)})
    return frame.sort_values("sali", ascending=False), summary


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


def group_overlap(groups: dict[str, set[str]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not groups:
        raise ValueError("--membership is required")
    rows = []
    for left, right in combinations(sorted(groups), 2):
        intersection = groups[left] & groups[right]; union = groups[left] | groups[right]
        rows.append({"group_id_a": left, "group_id_b": right, "intersection_count": len(intersection), "union_count": len(union), "jaccard": len(intersection) / len(union) if union else 0.0})
    result = pd.DataFrame(rows, columns=["group_id_a", "group_id_b", "intersection_count", "union_count", "jaccard"])
    return result, {"group_count": len(groups), "pair_count": len(result), "max_jaccard": result["jaccard"].max() if len(result) else None}


def group_structural_diversity(property_table: pd.DataFrame, groups: dict[str, set[str]], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    if not groups:
        raise ValueError("--membership is required")
    rows = []
    warnings: list[str] = []
    for group_id, members in groups.items():
        group_table = property_table[property_table["compound_id"].isin(members)]
        pairs, _, pair_warnings = pairwise_structure(group_table, args)
        warnings.extend(f"{group_id}: {warning}" for warning in pair_warnings)
        rows.append({"group_id": group_id, "sample_count": len(group_table), "pair_count": len(pairs), "mean_tanimoto": pairs["similarity"].mean() if len(pairs) else np.nan, "median_tanimoto": pairs["similarity"].median() if len(pairs) else np.nan, "p90_tanimoto": pairs["similarity"].quantile(0.9) if len(pairs) else np.nan, "structural_diversity_score": 1.0 - pairs["similarity"].mean() if len(pairs) else np.nan})
    result = pd.DataFrame(rows)
    return result, {"group_count": len(result)}, warnings


def execute(operator: str, property_table: pd.DataFrame, groups: dict[str, set[str]], description: pd.DataFrame | None, features: list[str], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    if operator == "activity_distribution":
        result, summary = activity_distribution(property_table, groups, args); return result, summary, []
    if operator == "group_profile":
        result, summary = group_profile(property_table, groups, args); return result, summary, []
    if operator == "group_enrichment":
        result, summary = group_enrichment(property_table, groups, args); return result, summary, []
    if operator == "pairwise_structure_similarity":
        return pairwise_similarity_analysis(property_table, args)
    if operator == "activity_cliff":
        return activity_cliff(property_table, args)
    if operator == "descriptor_activity_correlation":
        result, summary = descriptor_correlation(description, features); return result, summary, []
    if operator == "knn_activity_consistency":
        result, summary = knn_edges(description, features, args); return result, summary, []
    if operator == "sali":
        result, summary = sali_analysis(description, features, args); return result, summary, []
    if operator == "group_overlap":
        result, summary = group_overlap(groups); return result, summary, []
    if operator == "group_structural_diversity":
        return group_structural_diversity(property_table, groups, args)
    raise ValueError(f"Unsupported operator: {operator}")


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    run_id = args.run_id or run_id_now()
    _, property_table, id_column, smiles_column, input_hash, input_warnings = load_property(args)
    description, features = load_description(args.description, property_table)
    groups = membership_sets(args.membership, set(property_table["compound_id"]))
    operator = CAPABILITY["implementation"]["operator"]
    outdir = default_output(args, run_id)
    if outdir.exists() and any(outdir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
    outdir.mkdir(parents=True, exist_ok=True)
    result, summary, warnings = execute(operator, property_table, groups, description, features, args)
    warnings = input_warnings + warnings
    result_path = outdir / CAPABILITY["output"]["filename"]
    result.to_csv(result_path, index=False)
    target_group = args.target_group
    supporting_compounds: list[str] = []
    supporting_pairs: list[dict[str, Any]] = []
    if "compound_id" in result.columns:
        supporting_compounds = result["compound_id"].dropna().astype(str).head(100).tolist()
    if {"compound_id_a", "compound_id_b"}.issubset(result.columns):
        supporting_pairs = result[["compound_id_a", "compound_id_b"]].head(100).to_dict(orient="records")
    evidence = {
        "schema_version": "1.0.0", "evidence_id": f"{run_id}:{CAPABILITY['operator_id']}:{target_group or 'GLOBAL'}:0001",
        "operator_id": CAPABILITY["operator_id"], "operator_name": CAPABILITY["display_name"], "operator_version": CAPABILITY["version"], "run_id": run_id,
        "target_group_id": target_group, "grouping_representation": args.grouping_representation, "evaluation_representation": args.evaluation_representation,
        "input_features": features, "sample_count": int(len(property_table)), "result_type": operator, "result_values": summary,
        "statistical_significance": {key: value for key, value in summary.items() if "pvalue" in key or "qvalue" in key} or None,
        "uncertainty": None, "applicability_conditions": [f"endpoint={args.property_column}", f"higher_is_better={args.higher_is_better}"],
        "warnings": warnings, "supporting_compounds": supporting_compounds, "supporting_pairs": supporting_pairs,
        "generated_evidence": [], "machine_readable_summary": summary,
        "human_readable_summary": f"{CAPABILITY['display_name']} analyzed {len(property_table)} valid endpoint rows. See {result_path.name}.",
        "artifacts": [{"type": "operator_result", "path": result_path.name, "sha256": file_hash(result_path)}], "created_at": utc_now()
    }
    config = {key: value for key, value in vars(args).items()}
    manifest = {"schema_version": "1.0.0", "conductor_version": "4.0.0", "run_id": run_id, "capability_id": CAPABILITY["capability_id"], "operator_id": CAPABILITY["operator_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"], "input": args.input, "input_hash": input_hash, "id_column": id_column, "property_column": args.property_column, "higher_is_better": args.higher_is_better, "description": args.description, "membership": args.membership, "output": result_path.name, "warnings": warnings, "created_at": utc_now()}
    if args.conductor:
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "analysis_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings})
    if args.conductor:
        validate_json(evidence, "evidence.schema.json")
        write_json(outdir / "evidence.json", evidence)
        event = {"schema_version": "1.0.0", "project": args.project, "run_id": run_id, "node_id": args.node_id, "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded", "input_hash": input_hash, "config_hash": value_hash(config), "configuration": config, "artifacts": [{"type": "operator_result", "path": result_path.name, "sha256": file_hash(result_path)}, {"type": "evidence", "path": "evidence.json"}, {"type": "manifest", "path": "analysis_manifest.json"}], "warnings": warnings, "started_at": started_at, "finished_at": utc_now()}
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
