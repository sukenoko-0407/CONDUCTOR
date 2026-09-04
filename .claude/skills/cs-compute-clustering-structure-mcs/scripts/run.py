from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))
MCS_MAX_WORKERS = 8
MCS_PAIR_TIMEOUT_SECONDS = 2
MCS_NATIVE_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMBA_NUM_THREADS",
    "RAYON_NUM_THREADS",
)


def _mcs_worker_count(task_count: int) -> int:
    """Use at most eight single-threaded MCS workers within the assigned CPU budget."""
    if task_count < 1:
        return 0
    available: int | None = None
    for name in ("CONDUCTOR_NODE_CPU_CORES", "CONDUCTOR_AVAILABLE_CPU_CORES"):
        raw = os.environ.get(name)
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                continue
            if parsed > 0:
                available = parsed
                break
    if available is None and hasattr(os, "sched_getaffinity"):
        try:
            available = len(os.sched_getaffinity(0))
        except OSError:
            available = None
    if available is None:
        available = os.cpu_count() or 1
    return max(1, min(MCS_MAX_WORKERS, available, task_count))


def _limit_mcs_worker_native_threads() -> None:
    """Prevent a process worker from starting nested native thread pools."""
    for name in MCS_NATIVE_THREAD_VARIABLES:
        os.environ[name] = "1"


def _mcs_pair_search(task: tuple[int, int, bytes, bytes]) -> tuple[int, int, str, bool]:
    """Evaluate one independent molecule pair in a process-safe representation."""
    from rdkit import Chem
    from rdkit.Chem import rdFMCS

    left, right, mol_a_binary, mol_b_binary = task
    mol_a = Chem.Mol(mol_a_binary)
    mol_b = Chem.Mol(mol_b_binary)
    result = rdFMCS.FindMCS(
        [mol_a, mol_b],
        timeout=MCS_PAIR_TIMEOUT_SECONDS,
        ringMatchesRingOnly=True,
        completeRingsOnly=True,
    )
    return left, right, str(result.smartsString or ""), bool(result.canceled)


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
    schema.pop("$schema", None)
    schema.pop("$id", None)
    jsonschema.validate(value, schema)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Run {CAPABILITY['skill_name']}.")
    algorithm = CAPABILITY["implementation"]["algorithm"]
    parser.set_defaults(id_column=None, smiles_column=None, columns=None)
    if algorithm.startswith("structure_"):
        parser.add_argument("--input", required=True, help="CSV input containing compound IDs and SMILES.")
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
    parser.add_argument("--round-id")
    parser.add_argument("--project")
    parser.add_argument("--node-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--min-cluster-size", type=int, default=5)
    if algorithm == "categorical":
        parser.add_argument("--columns", required=True, help="Comma-separated categorical columns.")
    if algorithm == "structure_mcs":
        parser.add_argument("--max-pairs", type=int, default=1000, help="Maximum evaluated molecule pairs (1-1000).")
        parser.add_argument("--max-core-clusters", type=int, default=300, help="Maximum number of retained MCS Clusters.")
        parser.add_argument("--random-seed", type=int, default=61453, help="Seed for reproducible random pair sampling.")
    if algorithm.startswith("vector_"):
        parser.add_argument("--metric", choices=["auto", "tanimoto", "cosine", "euclidean", "manhattan"], default="auto")
        parser.add_argument("--input-representation", help="Description capability ID, for example D002 or D013.")
        parser.add_argument("--description-result", help="Canonical Runtime Description Result 1.0.0 that binds the vector payload and metric.")
        parser.add_argument("--value-semantics", choices=["binary_fingerprint", "sparse_count", "dense_continuous", "dense_shape_moment", "dense_embedding"], help="Required with an explicit non-auto metric for standalone vectors that have no Runtime Description Result.")
        parser.add_argument("--parameter-mode", choices=["auto", "fixed"], default="auto", help="Select parameters from the observed distance geometry, or use explicit fixed values.")
    method = algorithm.split("_", 1)[1] if algorithm.startswith(("structure_", "vector_")) else ("connected_components" if algorithm == "meta_overlap" else None)
    if algorithm.startswith("vector_") and method in {"butina", "connected_components"}:
        parser.add_argument("--distance-cutoff", type=float, help="Native-distance cutoff used in fixed mode.")
        parser.add_argument("--similarity-threshold", type=float, help="Optional bounded-similarity form of the fixed cutoff for Tanimoto or Cosine only.")
    if method == "hierarchical":
        parser.add_argument("--distance-threshold", type=float)
        parser.add_argument("--n-clusters", type=int)
    if method == "dbscan":
        parser.add_argument("--eps", type=float)
        parser.add_argument("--min-samples", type=int, default=5)
    if method in {"louvain", "leiden"}:
        parser.add_argument("--resolution", type=float, default=1.0)
        parser.add_argument("--random-seed", type=int, default=61453)
        parser.add_argument("--n-neighbors", type=int, help="k for the weighted mutual-kNN graph in fixed mode.")
        parser.add_argument("--graph-mode", choices=["mutual-knn"], default="mutual-knn")
    if algorithm == "meta_overlap":
        parser.add_argument("--similarity-threshold", type=float, default=0.55)
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "round_id", "node_id", "attempt_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, --round-id, --node-id, and --attempt-id")
    elif args.project or args.round_id or args.node_id or args.attempt_id:
        parser.error("--project, --round-id, --node-id, and --attempt-id are valid only with --conductor")
    for name in ("min_cluster_size", "max_pairs", "max_core_clusters", "min_samples", "n_clusters", "n_neighbors"):
        if hasattr(args, name) and getattr(args, name) is not None and getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    if algorithm == "structure_mcs" and args.max_pairs > 1000:
        parser.error("--max-pairs must be <= 1000")
    if args.min_cluster_size < 5:
        parser.error("--min-cluster-size must be >= 5")
    if hasattr(args, "random_seed") and args.random_seed < 0:
        parser.error("--random-seed must be >= 0")
    for name in ("distance_threshold", "distance_cutoff", "eps", "resolution"):
        if hasattr(args, name) and getattr(args, name) is not None and getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be > 0")
    if hasattr(args, "similarity_threshold") and args.similarity_threshold is not None and not 0 <= args.similarity_threshold <= 1:
        parser.error("--similarity-threshold must be between 0 and 1")
    if algorithm.startswith("vector_") and args.parameter_mode == "fixed":
        if method in {"butina", "connected_components"} and args.distance_cutoff is None and args.similarity_threshold is None:
            parser.error("fixed mode requires --distance-cutoff or --similarity-threshold")
        if method == "hierarchical" and args.distance_threshold is None and args.n_clusters is None:
            parser.error("fixed mode requires --distance-threshold or --n-clusters")
        if method == "dbscan" and args.eps is None:
            parser.error("fixed mode requires --eps")
        if method in {"louvain", "leiden"} and args.n_neighbors is None:
            parser.error("fixed mode requires --n-neighbors")
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
    paths = [Path(value) for value in args.input] if isinstance(args.input, list) else [Path(args.input)]
    frames = []
    for path in paths:
        header = pd.read_csv(path, nrows=0)
        candidate_id = args.id_column or infer_named(list(header.columns), "id")
        frames.append(pd.read_csv(path, dtype={candidate_id: "string"} if candidate_id else None))
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    source_name = paths[0].stem if len(paths) == 1 else "multiple_memberships"
    digest = value_hash([{"path": str(path.resolve()), "sha256": file_hash(path)} for path in paths])
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
        return root / "CONDUCTOR" / (args.project or source_name) / run_id / "clustering" / CAPABILITY["skill_name"] / str(args.node_id).replace(":", "-") / "attempts" / str(args.attempt_id)
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


def add_cluster(clusters: dict[str, set[str]], label: str, members: list[str] | set[str], min_size: int) -> None:
    values = {str(value) for value in members}
    if len(values) >= min_size:
        clusters[label] = values


def rule_clusters(base: pd.DataFrame, mols: list[Any], args: argparse.Namespace, algorithm: str) -> tuple[dict[str, set[str]], dict[str, Any]]:
    from rdkit import Chem
    clusters: dict[str, set[str]] = {}
    if algorithm == "structure_murcko":
        from rdkit.Chem.Scaffolds import MurckoScaffold
        buckets: dict[str, list[str]] = defaultdict(list)
        for compound_id, mol in zip(base["compound_id"], mols):
            if mol is not None:
                scaffold = Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol), isomericSmiles=True)
                if scaffold:
                    buckets[scaffold].append(str(compound_id))
        for scaffold, members in buckets.items():
            add_cluster(clusters, scaffold, members, args.min_cluster_size)
        return clusters, {"definition": "Bemis-Murcko scaffold"}
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
            add_cluster(clusters, fragment, members, args.min_cluster_size)
        return clusters, {"definition": algorithm.replace("structure_", "") + " fragments"}
    if algorithm == "structure_mcs":
        from concurrent.futures import ProcessPoolExecutor
        from itertools import combinations
        from rdkit.Chem import rdSubstructLibrary

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

        molecule_binaries = [mol.ToBinary() for _, mol in valid]
        pair_tasks = [
            (left, right, molecule_binaries[left], molecule_binaries[right])
            for left, right in selected_pairs
        ]
        worker_count = _mcs_worker_count(len(pair_tasks))
        _limit_mcs_worker_native_threads()
        if worker_count > 1:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                pair_results = list(executor.map(_mcs_pair_search, pair_tasks, chunksize=1))
        else:
            pair_results = [_mcs_pair_search(task) for task in pair_tasks]

        # Retry only canceled parallel calls after the pool has closed. This avoids
        # losing a core solely because of transient CPU contention while retaining
        # the same timeout and MCS chemistry settings as the legacy implementation.
        successful_smarts: set[str] = set()
        canceled_tasks: list[tuple[int, int, bytes, bytes]] = []
        for task, (_left, _right, smarts, canceled) in zip(pair_tasks, pair_results):
            if canceled:
                canceled_tasks.append(task)
            elif smarts:
                successful_smarts.add(smarts)
        if worker_count > 1:
            for task in canceled_tasks:
                _left, _right, smarts, canceled = _mcs_pair_search(task)
                if not canceled and smarts:
                    successful_smarts.add(smarts)

        # Deduplicate pair-derived SMARTS before scanning the full dataset. The
        # indexed library preserves exact substructure matching while allowing
        # RDKit to use the same bounded CPU allocation for each membership query.
        library = rdSubstructLibrary.SubstructLibrary(
            rdSubstructLibrary.CachedMolHolder(),
            rdSubstructLibrary.PatternHolder(),
        )
        for _, mol in valid:
            library.AddMol(mol)
        for smarts in sorted(successful_smarts):
            query = Chem.MolFromSmarts(smarts)
            if query is None:
                continue
            matched_indices = library.GetMatches(
                query,
                recursionPossible=True,
                useChirality=False,
                useQueryQueryMatches=False,
                numThreads=max(1, worker_count),
                maxResults=len(valid),
            )
            members = {valid[int(index)][0] for index in matched_indices}
            if len(members) >= args.min_cluster_size:
                candidates[smarts] = members
        ranked = sorted(candidates.items(), key=lambda item: (-len(item[1]), item[0]))[: args.max_core_clusters]
        for smarts, members in ranked:
            clusters[smarts] = members
        return clusters, {
            "definition": "pair-seeded MCS",
            "pair_population": pair_population,
            "evaluated_pair_count": len(selected_pairs),
            "evaluated_pair_limit": args.max_pairs,
            "pair_sampling": sampling,
            "random_seed": args.random_seed,
        }
    raise ValueError(f"Unsupported rule clustering: {algorithm}")


def description_contract(args: argparse.Namespace) -> dict[str, Any]:
    result_path_value = getattr(args, "description_result", None)
    if not result_path_value:
        if args.conductor:
            raise ValueError("CONDUCTOR Vector Clustering requires --description-result")
        if not getattr(args, "value_semantics", None) or args.metric == "auto":
            raise ValueError("Standalone vectors without --description-result require --value-semantics and an explicit non-auto --metric")
        expected_metric = {"binary_fingerprint": "tanimoto", "sparse_count": "cosine", "dense_continuous": "euclidean", "dense_shape_moment": "manhattan", "dense_embedding": "cosine"}[args.value_semantics]
        if args.metric != expected_metric:
            raise ValueError(f"{args.value_semantics} vectors require --metric {expected_metric}")
        return {"value_semantics": args.value_semantics, "natural_metric": args.metric, "feature_columns": []}
    if getattr(args, "value_semantics", None):
        raise ValueError("--value-semantics cannot be combined with --description-result; the canonical result is authoritative")
    result_path = Path(result_path_value).resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_json(result, "description_result.schema.json")
    declared_payload = (result_path.parent / result["payload"]).resolve()
    if Path(args.input).resolve() != declared_payload:
        raise ValueError("--input does not match the payload bound by --description-result")
    representation = str(args.input_representation or "").upper()
    result_representation = str(result["capability_id"]).upper()
    if representation and representation != result_representation:
        raise ValueError("--input-representation conflicts with --description-result")
    return result


def resolve_vector_metric(values: pd.DataFrame, features: list[str], args: argparse.Namespace, contract: dict[str, Any]) -> str:
    observed = values.to_numpy(dtype=float)
    finite = observed[np.isfinite(observed)]
    is_binary = bool(finite.size) and bool(np.isin(finite, [0.0, 1.0]).all())
    representation = str(args.input_representation or "").upper()
    contract_representation = str(contract.get("capability_id") or "").upper()
    representation = representation or contract_representation
    semantics = str(contract.get("value_semantics") or "")
    bound_metric = str(contract.get("natural_metric") or "")
    fingerprint_ids = {"D002", "D003", "D007", "D008", "D009", "D010", "D011"}
    representation_metrics = {
        **{item: "tanimoto" for item in fingerprint_ids},
        "D004": "cosine",
        "D005": "cosine",
        "D006": "cosine",
        "D013": "manhattan",
        "D020": "cosine",
    }
    representation_metric = representation_metrics.get(representation) if not bound_metric else None
    requested = args.metric
    if semantics == "binary_fingerprint" and requested not in {"auto", "tanimoto"}:
        raise ValueError("Binary Description vectors require --metric tanimoto")
    if representation_metric == "tanimoto" and requested not in {"auto", "tanimoto"}:
        raise ValueError(f"{representation} fingerprint vectors require --metric tanimoto")
    if not bound_metric and representation_metric and requested not in {"auto", representation_metric}:
        raise ValueError(f"Requested metric {requested} conflicts with {representation} metric {representation_metric}")
    if not bound_metric and not representation_metric and not semantics and is_binary and requested not in {"auto", "tanimoto"}:
        raise ValueError("Binary Description vectors require --metric tanimoto")
    if requested == "tanimoto" and finite.size and np.any(finite < 0):
        raise ValueError("--metric tanimoto requires non-negative Description values")
    if requested != "auto":
        if bound_metric and requested != bound_metric:
            raise ValueError(f"Requested metric {requested} conflicts with the Description Result metric {bound_metric}")
        return requested
    if bound_metric:
        return bound_metric
    if representation_metric:
        return representation_metric
    if is_binary or semantics == "binary_fingerprint":
        return "tanimoto"
    feature_names = [str(feature).lower() for feature in features]
    if any(name.startswith(("usr__", "usrcat__")) for name in feature_names):
        return "manhattan"
    if any("embedding" in name or "svd" in name for name in feature_names):
        return "cosine"
    sparse_nonnegative = bool(finite.size) and bool(np.all(finite >= 0)) and float(np.count_nonzero(finite)) / float(finite.size) < 0.5
    return "cosine" if sparse_nonnegative else "euclidean"


def numeric_summary(values: np.ndarray) -> dict[str, Any]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return {"count": 0}
    quantiles = np.quantile(finite, [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "standard_deviation": float(np.std(finite)),
        "q01": float(quantiles[0]),
        "q05": float(quantiles[1]),
        "q10": float(quantiles[2]),
        "q25": float(quantiles[3]),
        "median": float(quantiles[4]),
        "q75": float(quantiles[5]),
        "q90": float(quantiles[6]),
        "q95": float(quantiles[7]),
        "q99": float(quantiles[8]),
    }


def kth_neighbor_distances(distance: np.ndarray, k: int) -> np.ndarray:
    n = len(distance)
    if n <= 1:
        return np.array([], dtype=float)
    bounded_k = min(max(1, int(k)), n - 1)
    work = np.asarray(distance, dtype=float).copy()
    np.fill_diagonal(work, np.inf)
    return np.partition(work, bounded_k - 1, axis=1)[:, bounded_k - 1]


def distance_profile(
    distance: np.ndarray,
    metric: str,
    raw_feature_count: int,
    feature_count: int,
    removed_features: dict[str, int],
    input_count: int,
    valid_count: int,
    zero_vector_count: int,
) -> dict[str, Any]:
    if len(distance) > 1:
        pairwise = distance[np.triu_indices(len(distance), 1)]
    else:
        pairwise = np.array([], dtype=float)
    pair_summary = numeric_summary(pairwise)
    neighbor_summaries: dict[str, Any] = {}
    for k in (1, 4, 5, 10):
        if len(distance) > k:
            neighbor_summaries[str(k)] = numeric_summary(kth_neighbor_distances(distance, k))
    pair_median = float(pair_summary.get("median") or 0.0)
    local_median = float((neighbor_summaries.get("4") or neighbor_summaries.get("1") or {}).get("median") or 0.0)
    q10 = float(pair_summary.get("q10") or 0.0)
    q90 = float(pair_summary.get("q90") or 0.0)
    concentration = (q90 - q10) / pair_median if pair_median > 0 else None
    local_global_ratio = local_median / pair_median if pair_median > 0 else None
    zero_pairs = int(np.count_nonzero(np.isclose(pairwise, 0.0, atol=1e-12)))
    weak_contrast = bool(
        local_global_ratio is not None
        and concentration is not None
        and local_global_ratio >= 0.85
        and concentration <= 0.25
    )
    return {
        "profile_version": "1.0.0",
        "metric": metric,
        "input_compound_count": int(input_count),
        "valid_vector_count": int(valid_count),
        "invalid_or_missing_vector_count": int(input_count - valid_count),
        "raw_feature_count": int(raw_feature_count),
        "effective_feature_count": int(feature_count),
        "removed_features": removed_features,
        "zero_vector_count": int(zero_vector_count),
        "zero_distance_pair_count": zero_pairs,
        "pairwise_distance": pair_summary,
        "neighbor_distance": neighbor_summaries,
        "local_to_global_distance_ratio": local_global_ratio,
        "distance_concentration": concentration,
        "weak_distance_contrast": weak_contrast,
    }


def vector_distances(df: pd.DataFrame, args: argparse.Namespace) -> tuple[list[int], np.ndarray, list[str], str, dict[str, Any]]:
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import pairwise_distances
    from sklearn.preprocessing import StandardScaler
    contract = description_contract(args)
    excluded = {"compound_id", "input_smiles", "canonical_smiles", "mol_parse_ok", "description_error", "descriptor_error", "cluster_id"}
    declared_features = [str(column) for column in contract.get("feature_columns") or []]
    if declared_features:
        missing_declared = [column for column in declared_features if column not in df.columns]
        if missing_declared:
            raise ValueError(f"Description payload is missing Result-bound feature columns: {missing_declared[:10]}")
        features = [column for column in declared_features if pd.api.types.is_numeric_dtype(df[column])]
        non_numeric = sorted(set(declared_features) - set(features))
        if non_numeric:
            raise ValueError(f"Description feature columns must be numeric: {non_numeric[:10]}")
    else:
        features = [column for column in df.columns if column not in excluded and pd.api.types.is_numeric_dtype(df[column])]
    if not features:
        raise ValueError("No numeric feature columns were found")
    raw_feature_count = len(features)
    valid_mask = df[features].notna().any(axis=1)
    if "mol_parse_ok" in df.columns:
        parse_ok = df["mol_parse_ok"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        valid_mask &= parse_ok
    positions = np.flatnonzero(valid_mask.to_numpy()).tolist()
    if not positions:
        empty = np.zeros((0, 0), dtype=float)
        empty_metric = str(contract.get("natural_metric") or args.metric)
        profile = distance_profile(empty, empty_metric, raw_feature_count, 0, {"all_missing": raw_feature_count, "constant": 0}, len(df), 0, 0)
        return [], empty, [], empty_metric, profile
    all_missing = [column for column in features if not df.iloc[positions][column].notna().any()]
    features = [column for column in features if column not in all_missing]
    if not features:
        raise ValueError("No usable numeric feature columns were found")
    values = df.iloc[positions][features]
    if contract.get("row_count") is not None and int(contract["row_count"]) != len(df):
        raise ValueError("Description Result row_count does not match the vector payload")
    if declared_features and int(contract["feature_count"]) != len(declared_features):
        raise ValueError("Description Result feature_count does not match feature_columns")
    resolved_metric = resolve_vector_metric(values, features, args, contract)
    if resolved_metric == "tanimoto":
        matrix = SimpleImputer(strategy="constant", fill_value=0).fit_transform(values).astype(float)
    else:
        matrix = SimpleImputer(strategy="median").fit_transform(values)
    variances = np.nanvar(matrix, axis=0)
    keep = np.isfinite(variances) & (variances > 0)
    constant_count = int(np.count_nonzero(~keep))
    matrix = matrix[:, keep]
    features = [feature for feature, retained in zip(features, keep) if bool(retained)]
    if not features:
        raise ValueError("All numeric feature columns are constant after imputation")
    row_norms = np.linalg.norm(matrix, axis=1)
    zero_rows = np.isclose(row_norms, 0.0, atol=1e-15)
    zero_vector_count = int(np.count_nonzero(zero_rows))
    if resolved_metric in {"euclidean", "manhattan"}:
        matrix = StandardScaler().fit_transform(matrix)
    if resolved_metric == "tanimoto":
        dot = matrix @ matrix.T
        squared = np.sum(matrix * matrix, axis=1)
        denominator = squared[:, None] + squared[None, :] - dot
        similarity = np.divide(dot, denominator, out=np.zeros_like(dot, dtype=float), where=denominator > 0)
        similarity[np.ix_(zero_rows, zero_rows)] = 1.0
        np.fill_diagonal(similarity, 1.0)
        distance = 1.0 - np.clip(similarity, 0.0, 1.0)
    else:
        distance = pairwise_distances(matrix, metric=resolved_metric)
        if resolved_metric == "cosine" and zero_vector_count:
            distance[np.ix_(zero_rows, zero_rows)] = 0.0
    if not np.isfinite(distance).all():
        raise ValueError("Distance matrix contains non-finite values")
    np.fill_diagonal(distance, 0.0)
    profile = distance_profile(
        distance,
        resolved_metric,
        raw_feature_count,
        len(features),
        {"all_missing": len(all_missing), "constant": constant_count},
        len(df),
        len(positions),
        zero_vector_count,
    )
    return positions, distance, features, resolved_metric, profile


def butina_labels(distance: np.ndarray, cutoff: float) -> np.ndarray:
    if len(distance) == 0:
        return np.array([], dtype=int)
    if len(distance) == 1:
        return np.array([0], dtype=int)
    from rdkit.ML.Cluster import Butina
    condensed = [float(distance[i, j]) for i in range(1, len(distance)) for j in range(i)]
    clusters = Butina.ClusterData(condensed, len(distance), float(cutoff), isDistData=True)
    labels = np.full(len(distance), -1, dtype=int)
    for label, members in enumerate(clusters):
        labels[list(members)] = label
    return labels


def graph_labels(graph: Any, args: argparse.Namespace, method: str) -> np.ndarray:
    import networkx as nx
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
        igraph = ig.Graph(n=graph.number_of_nodes(), edges=edges, directed=False)
        weights = [float(graph.edges[edge]["weight"]) for edge in edges]
        partition = leidenalg.find_partition(igraph, leidenalg.RBConfigurationVertexPartition, weights=weights or None, resolution_parameter=args.resolution, seed=args.random_seed)
        communities = [set(members) for members in partition]
    else:
        raise ValueError(f"Unknown clustering method: {method}")
    labels = np.full(graph.number_of_nodes(), -1, dtype=int)
    for label, members in enumerate(communities):
        labels[list(members)] = label
    return labels


def radius_graph(distance: np.ndarray, cutoff: float) -> Any:
    import networkx as nx
    graph = nx.Graph()
    graph.add_nodes_from(range(len(distance)))
    for left in range(len(distance)):
        for right in range(left + 1, len(distance)):
            if float(distance[left, right]) <= float(cutoff):
                graph.add_edge(left, right, weight=max(1e-12, 1.0 / (1.0 + float(distance[left, right]))))
    return graph


def mutual_knn_graph(distance: np.ndarray, k: int) -> tuple[Any, dict[str, Any]]:
    import networkx as nx
    n = len(distance)
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    if n <= 1:
        return graph, {"k": 0, "edge_count": 0, "isolated_node_count": n, "mean_degree": 0.0}
    bounded_k = min(max(1, int(k)), n - 1)
    work = np.asarray(distance, dtype=float).copy()
    np.fill_diagonal(work, np.inf)
    neighbors = np.argpartition(work, bounded_k - 1, axis=1)[:, :bounded_k]
    neighbor_sets = [set(int(value) for value in row) for row in neighbors]
    local_scale = kth_neighbor_distances(distance, bounded_k)
    positive = local_scale[local_scale > 0]
    fallback = float(np.median(positive)) if positive.size else 1.0
    local_scale = np.where(local_scale > 0, local_scale, fallback)
    for left in range(n):
        for right in sorted(neighbor_sets[left]):
            if right <= left or left not in neighbor_sets[right]:
                continue
            raw_distance = float(distance[left, right])
            denominator = max(float(local_scale[left] * local_scale[right]), 1e-12)
            weight = 1.0 if raw_distance <= 1e-12 else math.exp(-((raw_distance * raw_distance) / denominator))
            graph.add_edge(left, right, weight=max(weight, 1e-12), distance=raw_distance)
    degrees = [degree for _, degree in graph.degree()]
    return graph, {
        "graph_mode": "mutual-knn",
        "k": bounded_k,
        "edge_count": int(graph.number_of_edges()),
        "isolated_node_count": int(sum(degree == 0 for degree in degrees)),
        "mean_degree": float(np.mean(degrees)) if degrees else 0.0,
        "max_degree": int(max(degrees)) if degrees else 0,
        "component_count": int(nx.number_connected_components(graph)),
        "largest_component_ratio": float(max((len(item) for item in nx.connected_components(graph)), default=0) / n) if n else 0.0,
    }


def partition_statistics(labels: np.ndarray, distance: np.ndarray, min_size: int) -> dict[str, Any]:
    from sklearn.metrics import silhouette_score
    n = len(labels)
    counts = Counter(int(label) for label in labels if int(label) >= 0)
    retained = {label: count for label, count in counts.items() if count >= min_size}
    retained_labels = set(retained)
    retained_mask = np.array([int(label) in retained_labels for label in labels], dtype=bool)
    assigned = int(np.count_nonzero(retained_mask))
    noise = int(np.count_nonzero(labels < 0))
    singleton = int(sum(count for count in counts.values() if count == 1))
    filtered_small = int(sum(count for count in counts.values() if 1 < count < min_size))
    cluster_count = len(retained)
    largest = max(retained.values(), default=0)
    silhouette: float | None = None
    if cluster_count >= 2 and assigned > cluster_count:
        selected_distance = distance[np.ix_(retained_mask, retained_mask)]
        selected_labels = labels[retained_mask]
        try:
            silhouette = float(silhouette_score(selected_distance, selected_labels, metric="precomputed"))
        except ValueError:
            silhouette = None
    return {
        "valid_vector_count": n,
        "raw_cluster_count": len(counts),
        "registered_cluster_count": cluster_count,
        "registered_membership_count": assigned,
        "coverage": float(assigned / n) if n else 0.0,
        "noise_count": noise,
        "noise_ratio": float(noise / n) if n else 0.0,
        "singleton_count": singleton,
        "singleton_ratio": float(singleton / n) if n else 0.0,
        "filtered_small_cluster_membership_count": filtered_small,
        "largest_cluster_count": int(largest),
        "largest_cluster_ratio": float(largest / n) if n else 0.0,
        "silhouette": silhouette,
        "collapsed": bool(cluster_count == 1 and assigned == n and n > 0),
        "fragmented": bool(cluster_count == 0 and n >= min_size),
    }


def candidate_stabilities(candidates: list[dict[str, Any]]) -> None:
    from sklearn.metrics import adjusted_rand_score
    for index, candidate in enumerate(candidates):
        values: list[float] = []
        for neighbor in (index - 1, index + 1):
            if 0 <= neighbor < len(candidates):
                values.append(float(adjusted_rand_score(candidate["labels"], candidates[neighbor]["labels"])))
        candidate["statistics"]["adjacent_parameter_stability"] = float(np.mean(values)) if values else 1.0


def candidate_score(candidate: dict[str, Any]) -> float:
    stats = candidate["statistics"]
    if stats["registered_cluster_count"] == 0 or stats["collapsed"]:
        return float("-inf")
    stability = float(stats.get("adjacent_parameter_stability", 0.0))
    silhouette = stats.get("silhouette")
    silhouette_score = 0.5 if silhouette is None else max(0.0, min(1.0, (float(silhouette) + 1.0) / 2.0))
    coverage_score = min(float(stats["coverage"]), 0.8) / 0.8
    cluster_score = min(int(stats["registered_cluster_count"]), 4) / 4.0
    dominance_penalty = max(0.0, (float(stats["largest_cluster_ratio"]) - 0.5) / 0.5)
    return 0.35 * stability + 0.25 * silhouette_score + 0.20 * coverage_score + 0.20 * cluster_score - 0.30 * dominance_penalty


def quality_flags(stats: dict[str, Any], profile: dict[str, Any], graph: dict[str, Any] | None = None) -> list[str]:
    flags: list[str] = []
    if stats.get("fragmented"):
        flags.append("fragmented")
    if stats.get("collapsed"):
        flags.append("collapsed")
    if float(stats.get("largest_cluster_ratio") or 0.0) >= 0.5:
        flags.append("dominant_cluster")
    if float(stats.get("noise_ratio") or 0.0) >= 0.5:
        flags.append("high_noise")
    if float(stats.get("adjacent_parameter_stability") or 1.0) < 0.5:
        flags.append("unstable")
    if profile.get("weak_distance_contrast"):
        flags.append("weak_distance_contrast")
    if graph:
        n = max(1, int(profile.get("valid_vector_count") or 0))
        if int(graph.get("edge_count") or 0) == 0 or int(graph.get("isolated_node_count") or 0) >= n * 0.8:
            flags.append("sparse_graph")
        possible = n * (n - 1) / 2
        if possible and float(graph.get("edge_count") or 0) / possible >= 0.8:
            flags.append("dense_graph")
    return sorted(set(flags))


def knee_value(values: np.ndarray) -> float | None:
    finite = np.sort(np.asarray(values, dtype=float)[np.isfinite(values)])
    if not finite.size:
        return None
    if finite.size < 3 or math.isclose(float(finite[0]), float(finite[-1])):
        return float(np.median(finite))
    x = np.linspace(0.0, 1.0, finite.size)
    y = (finite - finite[0]) / (finite[-1] - finite[0])
    return float(finite[int(np.argmax(x - y))])


def unique_values(values: list[float]) -> list[float]:
    return sorted({round(float(value), 12) for value in values if value is not None and math.isfinite(float(value)) and float(value) >= 0})


def radius_candidates(distance: np.ndarray, k: int, quantiles: tuple[float, ...]) -> list[float]:
    local = kth_neighbor_distances(distance, k)
    finite = local[np.isfinite(local)]
    if not finite.size:
        return []
    values = [float(np.quantile(finite, quantile)) for quantile in quantiles]
    elbow = knee_value(finite)
    if elbow is not None:
        values.append(elbow)
    return unique_values(values)


def candidate_record(parameters: dict[str, Any], labels: np.ndarray, distance: np.ndarray, min_size: int, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {"parameters": parameters, "labels": labels, "statistics": partition_statistics(labels, distance, min_size)}
    if graph:
        record["graph"] = graph
    return record


def select_candidate(candidates: list[dict[str, Any]], profile: dict[str, Any], mode: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    if not candidates:
        return None, "no_usable_partition", ["fragmented"]
    candidate_stabilities(candidates)
    for candidate in candidates:
        candidate["score"] = candidate_score(candidate)
    if mode == "fixed":
        selected = candidates[0]
        status = "selected" if selected["statistics"]["registered_cluster_count"] > 0 else "no_usable_partition"
    else:
        eligible = [candidate for candidate in candidates if math.isfinite(float(candidate["score"]))]
        selected = max(eligible, key=lambda candidate: (candidate["score"], -float(next(iter(candidate["parameters"].values()), 0) or 0))) if eligible else None
        status = "selected" if selected is not None else "no_usable_partition"
        if selected is not None and profile.get("weak_distance_contrast"):
            silhouette = selected["statistics"].get("silhouette")
            if silhouette is not None and float(silhouette) <= 0.02:
                status = "no_usable_partition"
    if selected is None:
        fallback = max(candidates, key=lambda candidate: candidate["statistics"]["registered_membership_count"])
        return fallback, status, quality_flags(fallback["statistics"], profile, fallback.get("graph"))
    return selected, status, quality_flags(selected["statistics"], profile, selected.get("graph"))


def fixed_distance_cutoff(args: argparse.Namespace, metric: str) -> float:
    if args.distance_cutoff is not None:
        return float(args.distance_cutoff)
    if metric not in {"tanimoto", "cosine"}:
        raise ValueError("--similarity-threshold is valid only for Tanimoto or Cosine; use --distance-cutoff")
    return 1.0 - float(args.similarity_threshold)


def hierarchical_candidates(distance: np.ndarray, args: argparse.Namespace) -> list[dict[str, Any]]:
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    if len(distance) <= 1:
        return [candidate_record({"n_clusters": 1}, np.zeros(len(distance), dtype=int), distance, args.min_cluster_size)]
    linkage_matrix = linkage(squareform(distance, checks=False), method="average")
    if args.parameter_mode == "fixed":
        if args.n_clusters is not None:
            labels = fcluster(linkage_matrix, t=int(args.n_clusters), criterion="maxclust") - 1
            return [candidate_record({"n_clusters": int(args.n_clusters)}, labels.astype(int), distance, args.min_cluster_size)]
        cutoff = float(args.distance_threshold)
        labels = fcluster(linkage_matrix, t=cutoff, criterion="distance") - 1
        return [candidate_record({"distance_cutoff": cutoff}, labels.astype(int), distance, args.min_cluster_size)]
    merge_distances = linkage_matrix[:, 2]
    gaps = np.diff(merge_distances)
    ranked = np.argsort(gaps)[::-1][: min(8, len(gaps))] if gaps.size else np.array([], dtype=int)
    cutoffs = [float((merge_distances[index] + merge_distances[index + 1]) / 2.0) for index in ranked]
    if not cutoffs:
        cutoffs = [float(np.median(merge_distances))]
    candidates = []
    for cutoff in sorted(set(cutoffs)):
        labels = fcluster(linkage_matrix, t=cutoff, criterion="distance") - 1
        candidates.append(candidate_record({"distance_cutoff": cutoff}, labels.astype(int), distance, args.min_cluster_size))
    return candidates


def vector_partition(distance: np.ndarray, args: argparse.Namespace, method: str, metric: str, profile: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    from sklearn.cluster import DBSCAN
    candidates: list[dict[str, Any]] = []
    if len(distance) == 0:
        return np.array([], dtype=int), {"selection_status": "invalid_input", "quality_flags": ["fragmented"], "candidates": [], "selected_parameters": None}
    if method == "butina":
        cutoffs = [fixed_distance_cutoff(args, metric)] if args.parameter_mode == "fixed" else radius_candidates(distance, args.min_cluster_size - 1, (0.25, 0.50, 0.75))
        candidates = [candidate_record({"distance_cutoff": cutoff}, butina_labels(distance, cutoff), distance, args.min_cluster_size) for cutoff in cutoffs]
    elif method == "dbscan":
        if args.parameter_mode == "fixed":
            eps_values = [float(args.eps)]
        else:
            eps_values = radius_candidates(distance, max(1, args.min_samples - 1), (0.50, 0.75, 0.90))
        for eps in eps_values:
            labels = DBSCAN(eps=eps, min_samples=args.min_samples, metric="precomputed").fit_predict(distance)
            candidates.append(candidate_record({"eps": eps, "min_samples": args.min_samples}, labels.astype(int), distance, args.min_cluster_size))
    elif method == "hierarchical":
        candidates = hierarchical_candidates(distance, args)
    elif method == "connected_components":
        cutoffs = [fixed_distance_cutoff(args, metric)] if args.parameter_mode == "fixed" else radius_candidates(distance, args.min_cluster_size - 1, (0.10, 0.25, 0.50))
        for cutoff in cutoffs:
            graph = radius_graph(distance, cutoff)
            labels = graph_labels(graph, args, "connected_components")
            graph_details = {
                "graph_mode": "radius",
                "distance_cutoff": cutoff,
                "edge_count": graph.number_of_edges(),
                "isolated_node_count": sum(degree == 0 for _, degree in graph.degree()),
                "component_count": __import__("networkx").number_connected_components(graph),
                "largest_component_ratio": max((len(item) for item in __import__("networkx").connected_components(graph)), default=0) / len(distance),
            }
            candidates.append(candidate_record({"distance_cutoff": cutoff}, labels, distance, args.min_cluster_size, graph_details))
    elif method in {"louvain", "leiden"}:
        if args.parameter_mode == "fixed":
            k_values = [int(args.n_neighbors)]
            resolutions = [float(args.resolution)]
        else:
            n = len(distance)
            k_values = sorted({min(n - 1, max(1, value)) for value in (args.min_cluster_size - 1, 8, min(32, max(4, round(math.sqrt(n)))))})
            resolutions = sorted({round(args.resolution * factor, 6) for factor in (0.75, 1.0, 1.25)})
        for k in k_values:
            graph, graph_details = mutual_knn_graph(distance, k)
            for resolution in resolutions:
                local_args = argparse.Namespace(**vars(args))
                local_args.resolution = resolution
                labels = graph_labels(graph, local_args, method)
                candidates.append(candidate_record({"n_neighbors": k, "resolution": resolution, "graph_mode": "mutual-knn"}, labels, distance, args.min_cluster_size, graph_details))
    else:
        raise ValueError(f"Unsupported Vector Clustering method: {method}")
    selected, status, flags = select_candidate(candidates, profile, args.parameter_mode)
    labels = selected["labels"] if selected is not None else np.full(len(distance), -1, dtype=int)
    serializable_candidates = [
        {
            "parameters": candidate["parameters"],
            "statistics": candidate["statistics"],
            "graph": candidate.get("graph"),
            "score": candidate.get("score"),
        }
        for candidate in candidates
    ]
    return labels, {
        "parameter_mode": args.parameter_mode,
        "selection_status": status,
        "quality_flags": flags,
        "selected_parameters": selected["parameters"] if selected is not None and status == "selected" else None,
        "selected_statistics": selected["statistics"] if selected is not None else {},
        "selection_method": "bounded_activity_blind_distance_geometry_v1",
        "candidates": serializable_candidates,
    }


def labeled_clusters_with_reasons(ids: list[str], labels: np.ndarray, min_size: int, selection_status: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    raw: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, str] = {}
    if selection_status != "selected":
        return {}, {str(compound_id): "no_usable_partition" for compound_id in ids}
    for compound_id, label in zip(ids, labels):
        if int(label) < 0:
            reasons[str(compound_id)] = "algorithm_noise"
        else:
            raw[str(int(label))].add(str(compound_id))
    retained: dict[str, set[str]] = {}
    for label, members in raw.items():
        if len(members) >= min_size:
            retained[label] = members
        else:
            reason = "singleton_cluster" if len(members) == 1 else "filtered_small_cluster"
            for compound_id in members:
                reasons[compound_id] = reason
    return retained, reasons


def labels_from_method(distance: np.ndarray, similarity: np.ndarray, args: argparse.Namespace, method: str) -> np.ndarray:
    """Legacy helper retained only for overlap-based meta Clustering."""
    if method != "connected_components":
        raise ValueError("Legacy label dispatch supports connected components only")
    cutoff = 1.0 - float(args.similarity_threshold)
    return graph_labels(radius_graph(distance, cutoff), args, "connected_components")


def categorical_clusters(df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, set[str]], dict[str, Any]]:
    columns = [value.strip() for value in (args.columns or "").split(",") if value.strip()]
    if not columns:
        raise ValueError("--columns is required for categorical clustering")
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"Categorical columns not found: {missing}")
    clusters: dict[str, set[str]] = {}
    for column in columns:
        for value, frame in df.dropna(subset=[column]).groupby(column):
            add_cluster(clusters, f"{column}={value}", frame["compound_id"].astype(str).tolist(), args.min_cluster_size)
    return clusters, {"columns": columns}


def meta_overlap_clusters(df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, set[str]], dict[str, Any]]:
    def active_mask(values: pd.Series) -> pd.Series:
        text = values.astype(str).str.strip().str.lower()
        return text.isin({"true", "yes", "y"}) | (pd.to_numeric(values, errors="coerce").fillna(0) > 0)

    long_cluster_column = "cluster_id" if "cluster_id" in df.columns else None
    if long_cluster_column and "compound_id" in df.columns:
        active = df if "membership_value" not in df.columns else df.loc[active_mask(df["membership_value"])]
        active = active.loc[active[long_cluster_column].notna() & active[long_cluster_column].astype(str).str.strip().ne("")]
        member_sets = {str(cluster): set(frame["compound_id"].astype(str)) for cluster, frame in active.groupby(long_cluster_column)}
    else:
        id_column = "compound_id"
        member_sets = {str(column): set(df.loc[active_mask(df[column]), id_column].astype(str)) for column in df.columns if column != id_column}
        member_sets = {cluster_id: members for cluster_id, members in member_sets.items() if members}
    names = sorted(member_sets)
    if not names:
        return {}, {"source_cluster_count": 0}
    distance = np.zeros((len(names), len(names)), dtype=float)
    for i, left in enumerate(names):
        for j, right in enumerate(names):
            union = member_sets[left] | member_sets[right]
            similarity = len(member_sets[left] & member_sets[right]) / len(union) if union else 0.0
            distance[i, j] = 1.0 - similarity
    labels = labels_from_method(distance, 1.0 - distance, args, "connected_components")
    clusters: dict[str, set[str]] = {}
    for label in sorted(set(labels)):
        source_clusters = [names[i] for i, value in enumerate(labels) if value == label]
        members = set().union(*(member_sets[name] for name in source_clusters)) if source_clusters else set()
        add_cluster(clusters, "+".join(source_clusters), members, args.min_cluster_size)
    return clusters, {"source_cluster_count": len(names)}


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    run_id = args.run_id or run_id_now()
    df, source_name, input_hash = load_input(args)
    outdir = default_output(args, source_name, run_id)
    if outdir.exists() and any(outdir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
        for name in ["cluster_membership.csv", "cluster_summary.csv", "clustering_diagnostics.csv", "distance_profile.json", "cluster_registry.json", "clustering_manifest.json", "warnings.json", "execution_event.json"]:
            (outdir / name).unlink(missing_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    algorithm = CAPABILITY["implementation"]["algorithm"]
    warnings: list[str] = []
    details: dict[str, Any] = {}
    vector_profile: dict[str, Any] | None = None
    unassigned_reasons: dict[str, str] = {}
    if algorithm.startswith("structure_"):
        base, mols, parse_warnings = structure_table(df, args)
        warnings.extend(parse_warnings)
        if algorithm not in {"structure_murcko", "structure_mcs", "structure_brics", "structure_recap"}:
            raise ValueError(f"Unsupported direct-structure clustering algorithm: {algorithm}")
        clusters, details = rule_clusters(base, mols, args, algorithm)
    elif algorithm.startswith("vector_"):
        positions, distance, features, resolved_metric, vector_profile = vector_distances(df, args)
        method = algorithm.removeprefix("vector_")
        labels, selection = vector_partition(distance, args, method, resolved_metric, vector_profile)
        ids = [str(df.iloc[position]["compound_id"]) for position in positions]
        clusters, unassigned_reasons = labeled_clusters_with_reasons(ids, labels, args.min_cluster_size, selection["selection_status"])
        details = {
            "feature_count": len(features),
            "requested_metric": args.metric,
            "metric": resolved_metric,
            "input_representation": args.input_representation,
            "method": method,
            **selection,
        }
        warnings.extend(f"Vector Clustering quality flag: {flag}" for flag in selection["quality_flags"])
    elif algorithm == "categorical":
        clusters, details = categorical_clusters(df, args)
    elif algorithm == "meta_overlap":
        clusters, details = meta_overlap_clusters(df, args)
    else:
        raise ValueError(f"Unsupported clustering algorithm: {algorithm}")
    membership_rows: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    registry_definition = details
    if algorithm.startswith("vector_"):
        registry_definition = {
            key: details.get(key)
            for key in ("method", "metric", "input_representation", "parameter_mode", "selection_status", "selected_parameters", "quality_flags")
        }
    for local_number, (label, members) in enumerate(sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0])), 1):
        local_cluster_id = f"LCL{local_number:06d}"
        registry.append({"local_cluster_id": local_cluster_id, "cluster_label": label, "clustering_capability_id": CAPABILITY["clustering_id"], "skill_name": CAPABILITY["skill_name"], "source_node_id": args.node_id, "source_description_id": getattr(args, "input_representation", None), "definition": registry_definition, "compound_count": len(members), "activity_blind": True})
        membership_rows.extend({"cluster_id": local_cluster_id, "compound_id": compound_id, "membership_value": 1.0, "membership_reason": label} for compound_id in sorted(members))
    assigned_ids = set().union(*clusters.values()) if clusters else set()
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
                else unassigned_reasons.get(compound_id, "unassigned")
            ),
        }
        for compound_id in sorted(input_ids - assigned_ids)
    )
    membership = pd.DataFrame(membership_rows, columns=["cluster_id", "compound_id", "membership_value", "membership_reason"])
    summary = pd.DataFrame(
        [
            {
                "cluster_id": row["local_cluster_id"],
                "cluster_label": row["cluster_label"],
                "compound_count": row["compound_count"],
                "clustering_id": CAPABILITY["clustering_id"],
            }
            for row in registry
        ],
        columns=["cluster_id", "cluster_label", "compound_count", "clustering_id"],
    )
    membership_path = outdir / "cluster_membership.csv"
    summary_path = outdir / "cluster_summary.csv"
    diagnostics_path = outdir / "clustering_diagnostics.csv"
    membership.to_csv(membership_path, index=False)
    summary.to_csv(summary_path, index=False)
    unassigned_breakdown = Counter(
        str(row["membership_reason"])
        for row in membership_rows
        if float(row["membership_value"]) <= 0
    )
    diagnostic_row = {
        "clustering_id": CAPABILITY["clustering_id"],
        "method": details.get("method") or algorithm,
        "metric": details.get("metric"),
        "parameter_mode": details.get("parameter_mode"),
        "selection_status": details.get("selection_status", "selected"),
        "selected_parameters": json.dumps(clean_json(details.get("selected_parameters")), ensure_ascii=False, sort_keys=True),
        "quality_flags": "|".join(details.get("quality_flags") or []),
        "cluster_count": len(registry),
        "membership_count": int((membership["membership_value"] > 0).sum()),
        "unassigned_count": int((membership["membership_value"] <= 0).sum()),
        "coverage": float(len(assigned_ids) / len(input_ids)) if input_ids else 0.0,
        "largest_cluster_ratio": float((details.get("selected_statistics") or {}).get("largest_cluster_ratio") or 0.0),
        "unassigned_breakdown": json.dumps(dict(sorted(unassigned_breakdown.items())), ensure_ascii=False, sort_keys=True),
    }
    pd.DataFrame([diagnostic_row]).to_csv(diagnostics_path, index=False)
    config = {key: value for key, value in vars(args).items() if key not in {"smiles", "compound_id"}}
    input_label = ";".join(args.input) if isinstance(args.input, list) else (args.input or "inline_smiles")
    manifest = {"schema_version": "2.0.0", "conductor_version": "0.1.10", "artifact_stage": "clustering", "run_id": run_id, "node_id": args.node_id, "attempt_id": args.attempt_id, "capability_id": CAPABILITY["capability_id"], "clustering_id": CAPABILITY["clustering_id"], "skill_name": CAPABILITY["skill_name"], "skill_version": CAPABILITY["version"], "input": input_label, "input_hash": input_hash, "value_semantics": "cluster_membership", "natural_metric": details.get("metric"), "cluster_count": len(registry), "membership_count": int((membership["membership_value"] > 0).sum()), "unassigned_count": int((membership["membership_value"] <= 0).sum()), "unassigned_breakdown": dict(sorted(unassigned_breakdown.items())), "selection_status": details.get("selection_status", "selected"), "quality_flags": details.get("quality_flags") or [], "details": details, "warnings": warnings, "outputs": [membership_path.name, summary_path.name, diagnostics_path.name], "created_at": utc_now()}
    if args.conductor:
        if vector_profile is not None:
            write_json(outdir / "distance_profile.json", vector_profile)
            manifest["outputs"].append("distance_profile.json")
        validate_json(manifest, "artifact_manifest.schema.json")
        write_json(outdir / "clustering_manifest.json", manifest)
        write_json(outdir / "warnings.json", {"warnings": warnings})
    if args.conductor:
        write_json(outdir / "cluster_registry.json", registry)
        artifacts = [{"type": "cluster_membership", "path": membership_path.name, "sha256": file_hash(membership_path)}, {"type": "cluster_summary", "path": summary_path.name, "sha256": file_hash(summary_path)}, {"type": "clustering_diagnostics", "path": diagnostics_path.name, "sha256": file_hash(diagnostics_path)}, {"type": "cluster_registry", "path": "cluster_registry.json", "sha256": file_hash(outdir / "cluster_registry.json")}, {"type": "manifest", "path": "clustering_manifest.json", "sha256": file_hash(outdir / "clustering_manifest.json")}]
        if vector_profile is not None:
            artifacts.append({"type": "distance_profile", "path": "distance_profile.json", "sha256": file_hash(outdir / "distance_profile.json")})
        event = {"schema_version": "2.0.0", "project": args.project, "run_id": run_id, "round_id": args.round_id, "node_id": args.node_id, "attempt_id": args.attempt_id, "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded", "input_hash": input_hash, "config_hash": value_hash(config), "configuration": config, "artifacts": artifacts, "warnings": warnings, "started_at": started_at, "finished_at": utc_now()}
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
