from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
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
    algorithm = CAPABILITY["implementation"]["algorithm"]
    parser.set_defaults(smiles=None, compound_id=None, id_column=None, smiles_column=None, columns=None)
    if algorithm.startswith("structure_"):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--input", help="CSV input containing compound IDs and SMILES.")
        source.add_argument("--smiles", action="append", help="SMILES; repeat for multiple compounds.")
        parser.add_argument("--compound-id", action="append")
        parser.add_argument("--id-column")
        parser.add_argument("--smiles-column")
    else:
        parser.add_argument(
            "--input",
            required=True,
            action="append" if algorithm == "meta_overlap" else "store",
            help="Description, categorical, or membership CSV input. Repeat for meta-overlap.",
        )
        parser.add_argument("--id-column")
    parser.add_argument("--output-dir")
    parser.add_argument("--run-id")
    parser.add_argument("--project")
    parser.add_argument("--node-id")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--min-cluster-size", type=int, default=3)
    if algorithm == "categorical":
        parser.add_argument("--columns", required=True, help="Comma-separated categorical columns.")
    if algorithm == "structure_mcs":
        parser.add_argument("--max-pairs", type=int, default=1000, help="Maximum evaluated molecule pairs (1-1000).")
        parser.add_argument("--max-core-groups", type=int, default=300, help="Maximum number of retained MCS groups.")
        parser.add_argument("--random-seed", type=int, default=61453, help="Seed for reproducible random pair sampling.")
    if algorithm.startswith("vector_"):
        parser.add_argument("--metric", choices=["auto", "tanimoto", "cosine", "euclidean", "manhattan"], default="auto")
        parser.add_argument("--input-representation", help="Description capability ID, for example D002 or D013.")
    method = algorithm.split("_", 1)[1] if algorithm.startswith(("structure_", "vector_")) else ("connected_components" if algorithm == "meta_overlap" else None)
    if method in {"butina", "louvain", "leiden", "connected_components"}:
        parser.add_argument("--similarity-threshold", type=float, default=0.55)
    if method == "hierarchical":
        parser.add_argument("--distance-threshold", type=float, default=0.7)
        parser.add_argument("--n-clusters", type=int)
    if method == "dbscan":
        parser.add_argument("--eps", type=float, default=0.5)
        parser.add_argument("--min-samples", type=int, default=3)
    if method in {"louvain", "leiden"}:
        parser.add_argument("--resolution", type=float, default=1.0)
        parser.add_argument("--random-seed", type=int, default=61453)
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "node_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, and --node-id")
    elif args.project or args.node_id:
        parser.error("--project and --node-id are valid only with --conductor")
    for name in ("min_cluster_size", "max_pairs", "max_core_groups", "min_samples", "n_clusters"):
        if hasattr(args, name) and getattr(args, name) is not None and getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    if algorithm == "structure_mcs" and args.max_pairs > 1000:
        parser.error("--max-pairs must be <= 1000")
    if hasattr(args, "random_seed") and args.random_seed < 0:
        parser.error("--random-seed must be >= 0")
    for name in ("distance_threshold", "eps", "resolution"):
        if hasattr(args, name) and getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be > 0")
    if hasattr(args, "similarity_threshold") and not 0 <= args.similarity_threshold <= 1:
        parser.error("--similarity-threshold must be between 0 and 1")
    return args


def infer_named(columns: list[str], kind: str) -> str | None:
    preferred = {
        "id": ["compound_id", "compoundid", "molecule_id", "moleculeid", "id", "chembl_id"],
        "smiles": ["smiles", "canonical_smiles", "isomeric_smiles", "structure"],
    }[kind]
    normalized = {"".join(ch for ch in str(c).lower() if ch.isalnum()): str(c) for c in columns}
    for name in preferred:
        key = "".join(ch for ch in name if ch.isalnum())
        if key in normalized:
            return normalized[key]
    return None


def load_input(args: argparse.Namespace) -> tuple[pd.DataFrame, str, str]:
    if args.input:
        paths = [Path(value) for value in args.input] if isinstance(args.input, list) else [Path(args.input)]
        frames = []
        for path in paths:
            header = pd.read_csv(path, nrows=0)
            candidate_id = args.id_column or infer_named(list(header.columns), "id")
            frames.append(pd.read_csv(path, dtype={candidate_id: "string"} if candidate_id else None))
        df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        source_name = paths[0].stem if len(paths) == 1 else "multiple_memberships"
        digest = value_hash([{"path": str(path.resolve()), "sha256": file_hash(path)} for path in paths])
    else:
        smiles = list(args.smiles or [])
        ids = list(args.compound_id or [])
        if ids and len(ids) != len(smiles):
            raise ValueError("--compound-id count must match --smiles count")
        df = pd.DataFrame({"compound_id": ids or [f"CMPD_{i:06d}" for i in range(1, len(smiles) + 1)], "smiles": smiles})
        source_name = "smiles"
        digest = value_hash({"compound_ids": df["compound_id"].astype(str).tolist(), "smiles": smiles})
    if df.empty:
        raise ValueError("At least one input row is required")
    id_column = args.id_column or infer_named(list(df.columns), "id")
    if id_column is None:
        df.insert(0, "compound_id", [f"CMPD_{i:06d}" for i in range(1, len(df) + 1)])
        id_column = "compound_id"
    if id_column not in df.columns:
        raise ValueError(f"ID column not found: {id_column}")
    if df[id_column].isna().any():
        raise ValueError("Compound IDs must be non-empty and unique")
    ids = df[id_column].astype(str).str.strip()
    allow_repeated_members = CAPABILITY["implementation"]["algorithm"] == "meta_overlap"
    if ids.eq("").any() or (ids.duplicated().any() and not allow_repeated_members):
        raise ValueError("Compound IDs must be non-empty and unique")
    if id_column != "compound_id":
        df = df.rename(columns={id_column: "compound_id"})
    else:
        df["compound_id"] = ids
    return df, source_name, digest


def default_output(args: argparse.Namespace, source_name: str, run_id: str) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    root = find_workspace() / "results"
    if args.conductor:
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "grouping" / CAPABILITY["skill_name"] / str(args.node_id).replace(":", "-")
    return root / "clustering" / source_name / CAPABILITY["skill_name"] / run_id


def structure_table(df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, list[Any], list[str]]:
    from rdkit import Chem
    smiles_column = args.smiles_column or infer_named(list(df.columns), "smiles")
    if smiles_column is None or smiles_column not in df.columns:
        raise ValueError("SMILES column could not be inferred; specify --smiles-column")
    mols: list[Any] = []
    warnings: list[str] = []
    for compound_id, value in zip(df["compound_id"], df[smiles_column]):
        smiles = "" if pd.isna(value) else str(value)
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        mols.append(mol)
        if mol is None:
            warnings.append(f"{compound_id}: invalid SMILES")
    result = pd.DataFrame({"compound_id": df["compound_id"].astype(str), "input_smiles": df[smiles_column]})
    return result, mols, warnings


def add_group(groups: dict[str, set[str]], label: str, members: list[str] | set[str], min_size: int) -> None:
    values = {str(value) for value in members}
    if len(values) >= min_size:
        groups[label] = values


def rule_groups(base: pd.DataFrame, mols: list[Any], args: argparse.Namespace, algorithm: str) -> tuple[dict[str, set[str]], dict[str, Any]]:
    from rdkit import Chem
    groups: dict[str, set[str]] = {}
    if algorithm == "structure_murcko":
        from rdkit.Chem.Scaffolds import MurckoScaffold
        buckets: dict[str, list[str]] = defaultdict(list)
        for compound_id, mol in zip(base["compound_id"], mols):
            if mol is not None:
                scaffold = Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol), isomericSmiles=True)
                if scaffold:
                    buckets[scaffold].append(str(compound_id))
        for scaffold, members in buckets.items():
            add_group(groups, scaffold, members, args.min_cluster_size)
        return groups, {"definition": "Bemis-Murcko scaffold"}
    if algorithm in {"structure_brics", "structure_recap"}:
        buckets: dict[str, list[str]] = defaultdict(list)
        if algorithm == "structure_brics":
            from rdkit.Chem import BRICS
            for compound_id, mol in zip(base["compound_id"], mols):
                if mol is not None:
                    for fragment in BRICS.BRICSDecompose(mol):
                        buckets[str(fragment)].append(str(compound_id))
        else:
            from rdkit.Chem import Recap
            for compound_id, mol in zip(base["compound_id"], mols):
                if mol is not None:
                    tree = Recap.RecapDecompose(mol)
                    for fragment in tree.GetLeaves().keys():
                        buckets[str(fragment)].append(str(compound_id))
        for fragment, members in buckets.items():
            add_group(groups, fragment, members, args.min_cluster_size)
        return groups, {"definition": algorithm.replace("structure_", "") + " fragments"}
    if algorithm == "structure_mcs":
        from itertools import combinations
        from rdkit.Chem import rdFMCS
        valid = [(str(cid), mol) for cid, mol in zip(base["compound_id"], mols) if mol is not None]
        candidates: dict[str, set[str]] = {}
        pair_population = len(valid) * (len(valid) - 1) // 2
        if pair_population <= args.max_pairs:
            selected_pairs = list(combinations(range(len(valid)), 2))
            sampling = "exhaustive"
        else:
            rng = random.Random(args.random_seed)
            selected: set[tuple[int, int]] = set()
            while len(selected) < args.max_pairs:
                left, right = rng.sample(range(len(valid)), 2)
                selected.add((left, right) if left < right else (right, left))
            selected_pairs = sorted(selected)
            sampling = "uniform_random_without_replacement"
        for left, right in selected_pairs:
            _, mol_a = valid[left]
            _, mol_b = valid[right]
            result = rdFMCS.FindMCS([mol_a, mol_b], timeout=2, ringMatchesRingOnly=True, completeRingsOnly=True)
            if result.canceled or not result.smartsString:
                continue
            query = Chem.MolFromSmarts(result.smartsString)
            members = {cid for cid, mol in valid if query is not None and mol.HasSubstructMatch(query)}
            if len(members) >= args.min_cluster_size:
                candidates[result.smartsString] = members
        ranked = sorted(candidates.items(), key=lambda item: (-len(item[1]), item[0]))[: args.max_core_groups]
        for smarts, members in ranked:
            groups[smarts] = members
        return groups, {
            "definition": "pair-seeded MCS",
            "pair_population": pair_population,
            "evaluated_pair_count": len(selected_pairs),
            "evaluated_pair_limit": args.max_pairs,
            "pair_sampling": sampling,
            "random_seed": args.random_seed,
        }
    raise ValueError(f"Unsupported rule grouping: {algorithm}")


def resolve_vector_metric(values: pd.DataFrame, features: list[str], args: argparse.Namespace) -> str:
    observed = values.to_numpy(dtype=float)
    finite = observed[np.isfinite(observed)]
    is_binary = bool(finite.size) and bool(np.isin(finite, [0.0, 1.0]).all())
    representation = str(args.input_representation or "").upper()
    fingerprint_ids = {"D002", "D003", "D007", "D008", "D009", "D010"}
    requested = args.metric
    if is_binary and requested not in {"auto", "tanimoto"}:
        raise ValueError("Binary Description vectors require --metric tanimoto")
    if representation in fingerprint_ids and requested not in {"auto", "tanimoto"}:
        raise ValueError(f"{representation} fingerprint vectors require --metric tanimoto")
    if requested == "tanimoto" and finite.size and np.any(finite < 0):
        raise ValueError("--metric tanimoto requires non-negative Description values")
    if requested != "auto":
        return requested
    if is_binary or representation in fingerprint_ids or representation == "D002":
        return "tanimoto"
    if representation == "D013":
        return "manhattan"
    if representation in {"D004", "D005", "D017", "D019"}:
        return "cosine"
    feature_names = [str(feature).lower() for feature in features]
    if any(name.startswith(("usr__", "usrcat__")) for name in feature_names):
        return "manhattan"
    if any("embedding" in name or "svd" in name for name in feature_names):
        return "cosine"
    sparse_nonnegative = bool(finite.size) and bool(np.all(finite >= 0)) and float(np.count_nonzero(finite)) / float(finite.size) < 0.5
    return "cosine" if sparse_nonnegative else "euclidean"


def vector_distances(df: pd.DataFrame, args: argparse.Namespace) -> tuple[list[int], np.ndarray, np.ndarray, list[str], str]:
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import pairwise_distances
    from sklearn.preprocessing import StandardScaler
    excluded = {"compound_id", "input_smiles", "canonical_smiles", "mol_parse_ok", "description_error", "descriptor_error", "cluster_id"}
    features = [column for column in df.columns if column not in excluded and pd.api.types.is_numeric_dtype(df[column])]
    if not features:
        raise ValueError("No numeric feature columns were found")
    valid_mask = df[features].notna().any(axis=1)
    if "mol_parse_ok" in df.columns:
        parse_ok = df["mol_parse_ok"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        valid_mask &= parse_ok
    positions = np.flatnonzero(valid_mask.to_numpy()).tolist()
    if not positions:
        empty = np.zeros((0, 0), dtype=float)
        return [], empty, empty, features, args.metric
    features = [column for column in features if df.iloc[positions][column].notna().any()]
    if not features:
        raise ValueError("No usable numeric feature columns were found")
    values = df.iloc[positions][features]
    resolved_metric = resolve_vector_metric(values, features, args)
    if resolved_metric == "tanimoto":
        matrix = SimpleImputer(strategy="constant", fill_value=0).fit_transform(values).astype(float)
        dot = matrix @ matrix.T
        squared = np.sum(matrix * matrix, axis=1)
        denominator = squared[:, None] + squared[None, :] - dot
        similarity = np.divide(dot, denominator, out=np.zeros_like(dot, dtype=float), where=denominator > 0)
        np.fill_diagonal(similarity, 1.0)
        distance = 1.0 - np.clip(similarity, 0.0, 1.0)
    else:
        matrix = SimpleImputer(strategy="median").fit_transform(values)
        if resolved_metric in {"euclidean", "manhattan"}:
            matrix = StandardScaler().fit_transform(matrix)
        distance = pairwise_distances(matrix, metric=resolved_metric)
        similarity = 1.0 - distance if resolved_metric == "cosine" else 1.0 / (1.0 + distance)
    return positions, distance, similarity, features, resolved_metric


def labels_from_method(distance: np.ndarray, similarity: np.ndarray, args: argparse.Namespace, method: str) -> np.ndarray:
    if len(distance) == 0:
        return np.array([], dtype=int)
    if len(distance) == 1:
        return np.array([0], dtype=int)
    if method == "butina":
        from rdkit.ML.Cluster import Butina
        condensed = [float(1.0 - similarity[i, j]) for i in range(1, len(similarity)) for j in range(i)]
        clusters = Butina.ClusterData(condensed, len(distance), 1.0 - args.similarity_threshold, isDistData=True)
        labels = np.full(len(distance), -1, dtype=int)
        for label, members in enumerate(clusters):
            labels[list(members)] = label
        return labels
    if method == "hierarchical":
        from sklearn.cluster import AgglomerativeClustering
        kwargs: dict[str, Any] = {"metric": "precomputed", "linkage": "average"}
        if args.n_clusters:
            kwargs["n_clusters"] = args.n_clusters
        else:
            kwargs.update({"n_clusters": None, "distance_threshold": args.distance_threshold})
        return AgglomerativeClustering(**kwargs).fit_predict(distance)
    if method == "dbscan":
        from sklearn.cluster import DBSCAN
        return DBSCAN(eps=args.eps, min_samples=args.min_samples, metric="precomputed").fit_predict(distance)
    import networkx as nx
    graph = nx.Graph()
    graph.add_nodes_from(range(len(distance)))
    for i in range(len(distance)):
        for j in range(i + 1, len(distance)):
            if similarity[i, j] >= args.similarity_threshold:
                graph.add_edge(i, j, weight=float(similarity[i, j]))
    if graph.number_of_edges() == 0:
        communities = [{node} for node in graph.nodes()]
    elif method == "connected_components":
        communities = list(nx.connected_components(graph))
    elif method == "louvain":
        communities = list(nx.community.louvain_communities(graph, weight="weight", resolution=args.resolution, seed=args.random_seed))
    elif method == "leiden":
        try:
            import igraph as ig
            import leidenalg
        except ImportError as exc:
            raise RuntimeError("igraph and leidenalg are required for Leiden") from exc
        edges = list(graph.edges())
        igraph = ig.Graph(n=len(distance), edges=edges, directed=False)
        weights = [float(graph.edges[edge]["weight"]) for edge in edges]
        partition = leidenalg.find_partition(igraph, leidenalg.RBConfigurationVertexPartition, weights=weights or None, resolution_parameter=args.resolution, seed=args.random_seed)
        communities = [set(members) for members in partition]
    else:
        raise ValueError(f"Unknown clustering method: {method}")
    labels = np.full(len(distance), -1, dtype=int)
    for label, members in enumerate(communities):
        labels[list(members)] = label
    return labels


def labeled_groups(ids: list[str], labels: np.ndarray, min_size: int) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for compound_id, label in zip(ids, labels):
        if int(label) >= 0:
            groups[str(int(label))].add(str(compound_id))
    return {label: members for label, members in groups.items() if len(members) >= min_size}


def categorical_groups(df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, set[str]], dict[str, Any]]:
    columns = [value.strip() for value in (args.columns or "").split(",") if value.strip()]
    if not columns:
        raise ValueError("--columns is required for categorical clustering")
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"Categorical columns not found: {missing}")
    groups: dict[str, set[str]] = {}
    for column in columns:
        for value, frame in df.dropna(subset=[column]).groupby(column):
            add_group(groups, f"{column}={value}", frame["compound_id"].astype(str).tolist(), args.min_cluster_size)
    return groups, {"columns": columns}


def meta_overlap_groups(df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, set[str]], dict[str, Any]]:
    def active_mask(values: pd.Series) -> pd.Series:
        text = values.astype(str).str.strip().str.lower()
        return text.isin({"true", "yes", "y"}) | (pd.to_numeric(values, errors="coerce").fillna(0) > 0)

    long_group_column = "cluster_id" if "cluster_id" in df.columns else ("group_id" if "group_id" in df.columns else None)
    if long_group_column and "compound_id" in df.columns:
        active = df if "membership_value" not in df.columns else df.loc[active_mask(df["membership_value"])]
        active = active.loc[active[long_group_column].notna() & active[long_group_column].astype(str).str.strip().ne("")]
        member_sets = {str(group): set(frame["compound_id"].astype(str)) for group, frame in active.groupby(long_group_column)}
    else:
        id_column = "compound_id"
        member_sets = {str(column): set(df.loc[active_mask(df[column]), id_column].astype(str)) for column in df.columns if column != id_column}
        member_sets = {group_id: members for group_id, members in member_sets.items() if members}
    names = sorted(member_sets)
    if not names:
        return {}, {"source_group_count": 0}
    distance = np.zeros((len(names), len(names)), dtype=float)
    for i, left in enumerate(names):
        for j, right in enumerate(names):
            union = member_sets[left] | member_sets[right]
            similarity = len(member_sets[left] & member_sets[right]) / len(union) if union else 0.0
            distance[i, j] = 1.0 - similarity
    labels = labels_from_method(distance, 1.0 - distance, args, "connected_components")
    groups: dict[str, set[str]] = {}
    for label in sorted(set(labels)):
        source_groups = [names[i] for i, value in enumerate(labels) if value == label]
        members = set().union(*(member_sets[name] for name in source_groups)) if source_groups else set()
        add_group(groups, "+".join(source_groups), members, args.min_cluster_size)
    return groups, {"source_group_count": len(names)}


def stable_group_id(label: str, members: set[str], args: argparse.Namespace) -> str:
    if args.conductor and args.node_id:
        context = re.sub(r"[^A-Za-z0-9]+", "_", str(args.node_id)).strip("_").upper()
    else:
        context = CAPABILITY["clustering_id"]
    identity = value_hash({"label": str(label), "members": sorted(str(member) for member in members)})[:16].upper()
    return f"G_{context}_{identity}"


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    run_id = args.run_id or run_id_now()
    df, source_name, input_hash = load_input(args)
    outdir = default_output(args, source_name, run_id)
    if outdir.exists() and any(outdir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
        for name in ["cluster_membership.csv", "cluster_summary.csv", "group_registry.json", "grouping_manifest.json", "warnings.json", "execution_event.json"]:
            (outdir / name).unlink(missing_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    algorithm = CAPABILITY["implementation"]["algorithm"]
    warnings: list[str] = []
    details: dict[str, Any] = {}
    if algorithm.startswith("structure_"):
        base, mols, parse_warnings = structure_table(df, args)
        warnings.extend(parse_warnings)
        if algorithm not in {"structure_murcko", "structure_mcs", "structure_brics", "structure_recap"}:
            raise ValueError(f"Unsupported direct-structure grouping algorithm: {algorithm}")
        groups, details = rule_groups(base, mols, args, algorithm)
    elif algorithm.startswith("vector_"):
        positions, distance, similarity, features, resolved_metric = vector_distances(df, args)
        method = algorithm.removeprefix("vector_")
        labels = labels_from_method(distance, similarity, args, method)
        ids = [str(df.iloc[position]["compound_id"]) for position in positions]
        groups = labeled_groups(ids, labels, args.min_cluster_size)
        details = {"feature_count": len(features), "requested_metric": args.metric, "metric": resolved_metric, "input_representation": args.input_representation, "method": method}
    elif algorithm == "categorical":
        groups, details = categorical_groups(df, args)
    elif algorithm == "meta_overlap":
        groups, details = meta_overlap_groups(df, args)
    else:
        raise ValueError(f"Unsupported clustering algorithm: {algorithm}")
    membership_rows: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    for label, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        group_id = stable_group_id(label, members, args)
        registry.append({"group_id": group_id, "group_label": label, "grouping_capability_id": CAPABILITY["clustering_id"], "skill_name": CAPABILITY["skill_name"], "source_node_id": args.node_id, "source_description_id": getattr(args, "input_representation", None), "definition": details, "compound_count": len(members), "activity_blind": True})
        membership_rows.extend({"cluster_id": group_id, "compound_id": compound_id, "membership_value": 1.0, "membership_reason": label} for compound_id in sorted(members))
    assigned_ids = set().union(*groups.values()) if groups else set()
    input_ids = set(df["compound_id"].astype(str))
    if algorithm.startswith("structure_"):
        invalid_ids = {
            str(base.iloc[position]["compound_id"])
            for position, mol in enumerate(mols)
            if mol is None
        }
        missing_vector_ids: set[str] = set()
    elif algorithm.startswith("vector_"):
        invalid_ids = {
            str(row["compound_id"])
            for _, row in df.iterrows()
            if "mol_parse_ok" in df.columns and str(row["mol_parse_ok"]).strip().lower() not in {"true", "1", "yes"}
        }
        valid_vector_ids = {str(df.iloc[position]["compound_id"]) for position in positions}
        missing_vector_ids = input_ids - invalid_ids - valid_vector_ids
    else:
        invalid_ids = set()
        missing_vector_ids = set()
    membership_rows.extend(
        {
            "cluster_id": "",
            "compound_id": compound_id,
            "membership_value": 0.0,
            "membership_reason": (
                "invalid_smiles" if compound_id in invalid_ids
                else "missing_description_vector" if compound_id in missing_vector_ids
                else "unassigned"
            ),
        }
        for compound_id in sorted(input_ids - assigned_ids)
    )
    membership = pd.DataFrame(membership_rows, columns=["cluster_id", "compound_id", "membership_value", "membership_reason"])
    summary = pd.DataFrame([{"cluster_id": row["group_id"], "cluster_label": row["group_label"], "compound_count": row["compound_count"], "clustering_id": CAPABILITY["clustering_id"]} for row in registry])
    membership_path = outdir / "cluster_membership.csv"
    summary_path = outdir / "cluster_summary.csv"
    membership.to_csv(membership_path, index=False)
    summary.to_csv(summary_path, index=False)
    config = {key: value for key, value in vars(args).items() if key not in {"smiles", "compound_id"}}
    input_label = ";".join(args.input) if isinstance(args.input, list) else (args.input or "inline_smiles")
    manifest = {"schema_version": "1.0.0", "conductor_version": "4.0.0", "run_id": run_id, "capability_id": CAPABILITY["capability_id"], "clustering_id": CAPABILITY["clustering_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"], "input": input_label, "input_hash": input_hash, "cluster_count": len(registry), "membership_count": int((membership["membership_value"] > 0).sum()), "unassigned_count": int((membership["membership_value"] <= 0).sum()), "details": details, "warnings": warnings, "outputs": [membership_path.name, summary_path.name], "created_at": utc_now()}
    if args.conductor:
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "grouping_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings})
    if args.conductor:
        write_json(outdir / "group_registry.json", registry)
        event = {"schema_version": "1.0.0", "project": args.project, "run_id": run_id, "node_id": args.node_id, "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded", "input_hash": input_hash, "config_hash": value_hash(config), "configuration": config, "artifacts": [{"type": "group_membership", "path": membership_path.name, "sha256": file_hash(membership_path)}, {"type": "group_registry", "path": "group_registry.json", "sha256": file_hash(outdir / "group_registry.json")}, {"type": "manifest", "path": "grouping_manifest.json", "sha256": file_hash(outdir / "grouping_manifest.json")}], "warnings": warnings, "started_at": started_at, "finished_at": utc_now()}
        validate_json(event, "execution_event.schema.json")
        write_json(outdir / "execution_event.json", event)
    print(outdir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
