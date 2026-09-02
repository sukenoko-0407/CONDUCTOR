from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from batch_skill_common import (
    analysis_units,
    dataset as request_dataset,
    finish as finish_request,
    frame_html,
    html_page,
    image_uri,
    parse_request,
)

from mmp_engine import (
    build_native_database,
    extract_pairs,
    load_input,
    sha256_file,
    summary_tables,
    utc_now,
    write_stable_database,
)
from mmp_outputs import (
    load_database,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def fragment_job_count(available_cpu_cores: int, requested_jobs: int | None) -> int:
    maximum = min(8, int(available_cpu_cores))
    jobs = int(requested_jobs) if requested_jobs is not None else maximum
    if jobs < 1 or jobs > maximum:
        raise ValueError("--fragment-jobs must be between 1 and min(8, --available-cpu-cores)")
    return jobs


def value_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return clean_json(value.item())
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def attachment_topology_signature(molecule: Any) -> tuple[str, ...]:
    """Return a deterministic signature for every dummy-atom attachment site."""
    signatures: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0:
            continue
        for neighbor in dummy.GetNeighbors():
            bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
            signatures.append(
                ":".join(
                    (
                        str(neighbor.GetAtomicNum()),
                        "aromatic" if neighbor.GetIsAromatic() else "aliphatic",
                        "ring" if neighbor.IsInRing() else "chain",
                        str(bond.GetBondType()) if bond is not None else "UNKNOWN",
                    )
                )
            )
    return tuple(sorted(signatures))


def export_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def global_build(args: argparse.Namespace, outdir: Path, *, persist_database: bool) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    valid, coverage, warnings = load_input(input_path, args.id_column, args.smiles_column, args.endpoint_column, args.max_compounds)
    if not (0 < args.min_core_fraction <= 1):
        raise ValueError("--min-core-fraction must satisfy 0 < value <= 1")
    if args.min_core_heavy_atoms < 1 or args.max_variable_heavy_atoms < 1:
        raise ValueError("Core and variable heavy-atom limits must be positive")
    if not (0 <= args.min_radius <= args.max_radius <= 5):
        raise ValueError("Environment radius must satisfy 0 <= min <= max <= 5")
    if not args.extended_search and (args.num_cuts > 2 or args.max_radius > 2):
        raise ValueError("3 cuts or radius 3-5 require explicit --extended-search")
    jobs = fragment_job_count(args.available_cpu_cores, args.fragment_jobs)
    _, native_work = build_native_database(
        valid, outdir / "_work", jobs=jobs, num_cuts=args.num_cuts,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        extended_core_fraction=args.min_core_fraction,
        min_radius=args.min_radius, max_radius=args.max_radius, cut_smarts=args.cut_smarts,
        max_variable_heavy_atoms=args.max_variable_heavy_atoms,
    )
    endpoint_map = dict(zip(valid["compound_id"], valid["endpoint"]))
    details, contexts, filter_stats = extract_pairs(
        native_work, endpoint_map, higher_is_better=args.higher_is_better,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        min_core_fraction=args.min_core_fraction,
    )
    parameter_record = {
        "num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts,
        "min_core_heavy_atoms": args.min_core_heavy_atoms,
        "min_core_fraction": args.min_core_fraction,
        "max_variable_heavy_atoms": args.max_variable_heavy_atoms,
        "min_radius": args.min_radius, "max_radius": args.max_radius,
        "extended_search": args.extended_search,
    }
    if len(details):
        details["_compound_pair_key"] = details["compound_id_from"].astype(str) + "\x1f" + details["compound_id_to"].astype(str)
        details["transform_pair_support"] = details.groupby("transform_id")["_compound_pair_key"].transform("nunique")
        details["transform_independent_core_support"] = details.groupby("transform_id")["core_id"].transform("nunique")
        details["core_pair_support"] = details.groupby("core_id")["_compound_pair_key"].transform("nunique")
        details["compound_pair_transform_count"] = details.groupby(["compound_id_from", "compound_id_to"])["transform_id"].transform("nunique")
        compound_support = pd.concat([
            details[["compound_id_from", "mmp_id"]].rename(columns={"compound_id_from": "compound_id"}),
            details[["compound_id_to", "mmp_id"]].rename(columns={"compound_id_to": "compound_id"}),
        ]).groupby("compound_id")["mmp_id"].nunique()
        details["compound_from_mmp_support"] = details["compound_id_from"].map(compound_support)
        details["compound_to_mmp_support"] = details["compound_id_to"].map(compound_support)
        low_support = details["transform_pair_support"] < 3
        details.loc[low_support & details["quality_flags"].eq(""), "quality_flags"] = "low_transform_support"
        details.loc[low_support & details["quality_flags"].ne(""), "quality_flags"] += "|low_transform_support"
        details = details.drop(columns=["_compound_pair_key"])
    details["source_node_id"] = args.node_id or ""
    details["input_sha256"] = sha256_file(input_path)
    details["parameter_hash"] = value_hash(parameter_record)
    details["engine_version"] = "mmpdb-3.1.4"
    metadata = {
        "schema_version": "1.0.0", "engine": "mmpdb", "engine_version": "3.1.4",
        "input_path": str(input_path), "input_sha256": sha256_file(input_path),
        "id_column": args.id_column, "smiles_column": args.smiles_column,
        "endpoint_column": args.endpoint_column, "higher_is_better": args.higher_is_better,
        "core_policy": {"min_heavy_atoms": args.min_core_heavy_atoms, "min_fraction_both_compounds": args.min_core_fraction, "max_variable_heavy_atoms": args.max_variable_heavy_atoms},
        "fragment_policy": {"num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts, "salt_remover": "<none>", "smallest_transformation_only": False, "symmetric": False, "extended_search": args.extended_search},
        "parameter_hash": value_hash(parameter_record),
        "environment_radius": [args.min_radius, args.max_radius],
        "input_count": int(len(coverage)), "endpoint_available_count": int(coverage["endpoint_available"].sum()),
        "mmp_count": int(len(details)), "filter_stats": filter_stats,
        "created_at": utc_now(),
    }
    counts = {
        "input compounds": len(coverage), "MMP rows": len(details),
        "transforms": int(details["transform_id"].nunique()) if len(details) else 0,
        "exact cores": int(details["core_id"].nunique()) if len(details) else 0,
    }
    artifacts: list[str] = []
    if persist_database:
        summaries = summary_tables(details, contexts, coverage)
        export_frame(details, outdir / "mmp_pair_detail.csv")
        coverage.to_csv(outdir / "compound_coverage.csv", index=False)
        for name, frame in summaries.items():
            frame.to_csv(outdir / f"{name}.csv", index=False)
        stable_database = outdir / "mmp_database.sqlite"
        write_stable_database(stable_database, details, contexts, coverage, metadata)
        artifacts = [
            "mmp_database.sqlite", "mmp_pair_detail.csv",
            "pair_summary.csv", "transform_summary.csv", "core_summary.csv",
            "transform_core_summary.csv", "context_summary.csv",
            "coverage_summary.csv", "compound_coverage.csv",
        ]
        storage_profile = {
            "schema_version": "1.0.0",
            "database_bytes": stable_database.stat().st_size,
            "detail_csv_bytes": (outdir / "mmp_pair_detail.csv").stat().st_size,
            "native_work_database_bytes": native_work.stat().st_size,
            "native_work_database_retained": False,
            "table_rows": {
                "compounds": int(len(coverage)), "mmp_pairs": int(len(details)),
                "mmp_contexts": int(len(contexts)),
                "transforms": int(details["transform_id"].nunique()) if len(details) else 0,
                "cores": int(details["core_id"].nunique()) if len(details) else 0,
            },
            "filter_stats": filter_stats,
            "created_at": utc_now(),
        }
        write_json(outdir / "mmp_storage_profile.json", storage_profile)
        artifacts.append("mmp_storage_profile.json")
    negative_result = not bool(details["favorable_delta"].notna().any()) if len(details) else True
    return {
        "input": str(input_path), "input_hash": sha256_file(input_path), "endpoint": args.endpoint_column,
        "higher_is_better": args.higher_is_better, "scope": "global", "cluster_id": None,
        "primary": "mmp_pair_detail.csv", "counts": counts, "negative_result": negative_result,
        "warnings": warnings, "artifacts": artifacts, "details": details,
        "core_policy": metadata["core_policy"], "source_nodes": args.source_node_id, "clustering_node_ids": [],
        "sample_count": int(coverage["endpoint_available"].sum()),
    }


def run_execution_request() -> int:
    """Execute the 0.1.9 human-centred MMP contract.

    Type-I and Type-II expose only target-connected one-cut pairs.  They still
    fragment the Run dataset so every observed neighbour can be found, but do
    not persist comprehensive summaries or SQLite.  Type-III is the explicit
    complete database/export mode.
    """
    request, outdir, capability = parse_request()
    parameters = request.get("parameters", {})
    role = str(parameters.get("role", "type-i")).lower()
    if role not in {"type-i", "type-ii", "type-iii"}:
        raise ValueError("MMP parameters.role must be one of: type-i, type-ii, type-iii")
    data, compound_id, smiles, endpoint = request_dataset(request)
    higher_is_better = bool(request.get("endpoint", {}).get("higher_is_better"))
    cuts = int(parameters.get("cuts", 1))
    if cuts != 1:
        raise ValueError("CONDUCTOR 0.1.9 MMP Type-I/II/III require cuts=1 for interpretability")
    radius_min = int(parameters.get("radius_min", 0)); radius_max = int(parameters.get("radius_max", 2))
    if not (0 <= radius_min <= radius_max <= 2):
        raise ValueError("MMP radius must satisfy 0 <= radius_min <= radius_max <= 2")
    identity = request["identity"]
    dataset_input = next((item for item in request.get("inputs", []) if item.get("role") == "dataset"), None)
    if not dataset_input:
        raise ValueError("MMP Execution Request requires one dataset input role")
    args = argparse.Namespace(
        role=role, input=str(Path(dataset_input["path"]).resolve()),
        id_column=compound_id, smiles_column=smiles, endpoint_column=endpoint,
        higher_is_better=higher_is_better, max_compounds=int(parameters.get("max_compounds", 2000)),
        available_cpu_cores=int(request.get("resources", {}).get("node_cpu_cores", 1)),
        fragment_jobs=None, num_cuts=1, extended_search=False, cut_smarts="default",
        min_core_heavy_atoms=int(parameters.get("min_core_heavy_atoms", 8)),
        min_core_fraction=float(parameters.get("min_core_fraction", .5)),
        max_variable_heavy_atoms=int(parameters.get("max_variable_heavy_atoms", 10)),
        min_radius=radius_min, max_radius=radius_max,
        node_id=identity["node_id"], source_node_id=[item.get("source_node_id") for item in request.get("inputs", []) if item.get("source_node_id")],
    )
    database_input = next((item for item in request.get("inputs", []) if item.get("role") == "mmp_database"), None)
    reused_database = False
    build_warnings: list[str] = []
    if database_input is not None:
        if role != "type-ii":
            raise ValueError("An existing Type-III mmp_database input is accepted only for Type-II")
        database_path = Path(str(database_input.get("path", ""))).resolve()
        if not database_path.is_file():
            raise FileNotFoundError(f"Explicit Type-III MMP database does not exist: {database_path}")
        details, database_metadata = load_database(database_path)
        expected_hash = str(database_metadata.get("input_sha256", ""))
        actual_hash = sha256_file(Path(dataset_input["path"]).resolve())
        if expected_hash != actual_hash:
            raise ValueError("Explicit Type-III MMP database was built from a different input CSV")
        if str(database_metadata.get("endpoint_column")) != endpoint or bool(database_metadata.get("higher_is_better")) != higher_is_better:
            raise ValueError("Explicit Type-III MMP database endpoint contract does not match this Run")
        if database_metadata.get("schema_version") != "1.0.0" or int(database_metadata.get("fragment_policy", {}).get("num_cuts", 0)) != 1:
            raise ValueError("Explicit Type-III MMP database is not a CONDUCTOR 0.1.9 one-cut database")
        database_radius = [int(value) for value in database_metadata.get("environment_radius", [])]
        if database_radius != [radius_min, radius_max]:
            raise ValueError(
                f"Explicit Type-III MMP database radius {database_radius} does not match requested radius {[radius_min, radius_max]}"
            )
        reused_database = True
    else:
        build = global_build(args, outdir, persist_database=role == "type-iii")
        details = build["details"]
        build_warnings = list(build.get("warnings", []))
        shutil.rmtree(outdir / "_work", ignore_errors=True)
    details_path = outdir / "mmp_pair_detail.csv"
    top_k = int(parameters.get("top_k", 5))
    if top_k < 1:
        raise ValueError("MMP top_k must be at least 1")
    target_rows: list[dict[str, str]] = []
    if role == "type-i":
        units = analysis_units(request) if any(item.get("role") == "analysis_unit_membership" for item in request.get("inputs", [])) else {"GLOBAL": set(data[compound_id])}
        ranked = data.dropna(subset=[endpoint]).sort_values(
            [endpoint, compound_id], ascending=[not higher_is_better, True], kind="mergesort"
        )
        for unit_id, members in units.items():
            for rank, value in enumerate(ranked.loc[ranked[compound_id].isin(members), compound_id].head(top_k), 1):
                target_rows.append({"analysis_unit_id": unit_id, "target_compound_id": str(value), "target_rank": str(rank)})
    elif role == "type-ii":
        requested = parameters.get("target_compound_ids") or []
        if isinstance(requested, str): requested = [requested]
        requested = [str(value) for value in requested]
        if len(requested) != len(set(requested)):
            raise ValueError("Type-II target_compound_ids must be unique")
        known = set(data[compound_id])
        missing = [value for value in requested if value not in known]
        if missing: raise ValueError(f"Type-II target compound_id values are not present in this Run: {missing}")
        target_rows = [{"analysis_unit_id": "HIT_TO_LEAD", "target_compound_id": value, "target_rank": str(index + 1)} for index, value in enumerate(requested)]
        if not target_rows: raise ValueError("Type-II requires parameters.target_compound_ids")
    else:
        target_rows = [{"analysis_unit_id": "DATABASE", "target_compound_id": "", "target_rank": ""}]
    targets = pd.DataFrame(target_rows)
    if role == "type-iii":
        target_pairs = details.copy(); target_pairs.insert(0, "analysis_unit_id", "DATABASE"); target_pairs.insert(1, "target_compound_id", "")
    else:
        parts = []
        for _, target in targets.iterrows():
            mask = details["compound_id_from"].astype(str).eq(target["target_compound_id"]) | details["compound_id_to"].astype(str).eq(target["target_compound_id"])
            part = details.loc[mask].copy()
            part.insert(0, "analysis_unit_id", target["analysis_unit_id"]); part.insert(1, "target_compound_id", target["target_compound_id"]); part.insert(2, "target_rank", target["target_rank"])
            target_is_to=part["compound_id_to"].astype(str).eq(str(target["target_compound_id"]))
            part["neighbor_compound_id"]=part["compound_id_from"].where(target_is_to,part["compound_id_to"])
            part["target_smiles"]=part["smiles_to"].where(target_is_to,part["smiles_from"])
            part["neighbor_smiles"]=part["smiles_from"].where(target_is_to,part["smiles_to"])
            raw=pd.to_numeric(part["favorable_delta"],errors="coerce")
            part["favorable_delta_toward_target"]=raw.where(target_is_to,-raw)
            part["favorable_delta_from_target_to_neighbor"]=-part["favorable_delta_toward_target"]
            part["variable_neighbor"]=part["variable_from"].where(target_is_to,part["variable_to"])
            part["variable_target"]=part["variable_to"].where(target_is_to,part["variable_from"])
            parts.append(part)
        target_pairs = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    primary = details_path if role == "type-iii" else outdir / "mmp_target_pairs.csv"
    targets_path = outdir / "mmp_targets.csv"
    if role != "type-iii": targets.to_csv(targets_path, index=False)
    if role != "type-iii" and len(target_pairs):
        effect_column = "favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"
        favorable = pd.to_numeric(target_pairs[effect_column], errors="coerce")
        target_pairs["effect_direction"] = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        target_pairs["effect_class"] = "unfavorable_observed"
        target_pairs.loc[favorable.gt(0), "effect_class"] = "favorable_observed"
        target_pairs.loc[favorable.isna() | favorable.eq(0), "effect_class"] = "neutral_or_missing"
        target_pairs.to_csv(primary, index=False)
    elif role != "type-iii":
        target_pairs.to_csv(primary,index=False)
    if role != "type-iii":
        if len(target_pairs):
            target_counts = target_pairs.groupby(["analysis_unit_id", "target_compound_id"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"),
                favorable_toward_target_fraction=("favorable_delta_toward_target", lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
                favorable_from_target_to_neighbor_fraction=("favorable_delta_from_target_to_neighbor", lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
            ).reset_index()
            target_summary = targets.merge(target_counts, on=["analysis_unit_id", "target_compound_id"], how="left")
        else:
            target_summary = targets.copy(); target_summary["mmp_pair_count"] = 0; target_summary["favorable_toward_target_fraction"] = 0.0; target_summary["favorable_from_target_to_neighbor_fraction"] = 0.0
        target_summary["mmp_pair_count"] = target_summary["mmp_pair_count"].fillna(0).astype(int)
        for column in ("favorable_toward_target_fraction", "favorable_from_target_to_neighbor_fraction"):
            target_summary[column] = target_summary[column].fillna(0.0)
        effect_fraction = target_summary["favorable_toward_target_fraction"] if role == "type-i" else target_summary["favorable_from_target_to_neighbor_fraction"]
        target_summary["effect_direction"] = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        target_summary["effect_summary"] = "mixed"
        target_summary.loc[effect_fraction.ge(.6), "effect_summary"] = "favorable_observed"
        target_summary.loc[effect_fraction.eq(0), "effect_summary"] = "no_favorable_observed"
        target_summary["underexplored"] = target_summary["mmp_pair_count"].lt(3)
    else:
        target_summary = targets
    target_summary_path = outdir / "mmp_target_summary.csv"
    if role != "type-iii": target_summary.to_csv(target_summary_path, index=False)
    extra_artifacts = [targets_path, target_summary_path] if role != "type-iii" else []
    if role != "type-iii":
        summary_effect_column = "favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"
        summary_effect_direction = "neighbor_to_target" if role == "type-i" else "target_to_neighbor"
        if len(target_pairs):
            transform_summary = target_pairs.groupby(["analysis_unit_id", "target_compound_id", "transform_id", "transform_smirks"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"), median_favorable_delta=(summary_effect_column, "median"),
                favorable_observed_fraction=(summary_effect_column, lambda values: pd.to_numeric(values, errors="coerce").gt(0).mean()),
                exact_core_count=("core_id", "nunique"),
            ).reset_index()
            core_summary = target_pairs.groupby(["analysis_unit_id", "target_compound_id", "core_id", "exact_core_smiles"], dropna=False).agg(
                mmp_pair_count=("mmp_id", "nunique"), median_favorable_delta=(summary_effect_column, "median"), transform_count=("transform_id", "nunique"),
            ).reset_index()
        else:
            transform_summary = pd.DataFrame(columns=["analysis_unit_id","target_compound_id","transform_id","transform_smirks","mmp_pair_count","median_favorable_delta","favorable_observed_fraction","exact_core_count"])
            core_summary = pd.DataFrame(columns=["analysis_unit_id","target_compound_id","core_id","exact_core_smiles","mmp_pair_count","median_favorable_delta","transform_count"])
        transform_summary["effect_direction"] = summary_effect_direction
        core_summary["effect_direction"] = summary_effect_direction
        transform_path=outdir/"mmp_target_transform_summary.csv"; core_path=outdir/"mmp_target_core_summary.csv"; transform_summary.to_csv(transform_path,index=False); core_summary.to_csv(core_path,index=False); extra_artifacts.extend([transform_path,core_path])
    if role == "type-ii" and len(target_pairs):
        from rdkit import Chem, DataStructs
        from rdkit.Chem import rdFMCS
        target_cores=sorted(set(target_pairs["exact_core_smiles"].dropna().astype(str))); all_cores=sorted(set(details["exact_core_smiles"].dropna().astype(str)))
        matches=[]
        for target_core in target_cores:
            target_mol=Chem.MolFromSmiles(target_core); target_fp=Chem.RDKFingerprint(target_mol) if target_mol else None
            if target_mol is None: continue
            target_heavy=max(1,sum(atom.GetAtomicNum()>1 for atom in target_mol.GetAtoms())); target_topology=attachment_topology_signature(target_mol)
            for reference_core in all_cores:
                if reference_core==target_core: continue
                reference_mol=Chem.MolFromSmiles(reference_core)
                if reference_mol is None or attachment_topology_signature(reference_mol)!=target_topology: continue
                similarity=float(DataStructs.TanimotoSimilarity(target_fp,Chem.RDKFingerprint(reference_mol)))
                if similarity < float(parameters.get("near_core_tanimoto",.70)): continue
                mcs=rdFMCS.FindMCS([target_mol,reference_mol],timeout=3,ringMatchesRingOnly=True,completeRingsOnly=True)
                if mcs.canceled:
                    continue
                reference_heavy=max(1,sum(atom.GetAtomicNum()>1 for atom in reference_mol.GetAtoms())); mcs_heavy=sum(atom.GetAtomicNum()>1 for atom in Chem.MolFromSmarts(mcs.smartsString).GetAtoms()) if mcs.smartsString else 0
                coverage_target=mcs_heavy/target_heavy; coverage_reference=mcs_heavy/reference_heavy
                if min(coverage_target,coverage_reference) >= float(parameters.get("near_core_mcs_coverage",.60)):
                    matches.append({"target_core":target_core,"exact_core_smiles":reference_core,"attachment_topology":"|".join(target_topology),"core_tanimoto":similarity,"mcs_coverage_target":coverage_target,"mcs_coverage_reference":coverage_reference})
        match_frame=pd.DataFrame(matches)
        if len(match_frame):
            near=details.merge(match_frame,on="exact_core_smiles",how="inner")
            near["absolute_favorable_delta"] = pd.to_numeric(near["favorable_delta"], errors="coerce").abs()
            near=near.sort_values(["core_tanimoto","absolute_favorable_delta"],ascending=[False,False]).head(int(parameters.get("near_core_reference_limit",5000)))
        else:
            near=pd.DataFrame(columns=[
                "target_core", "exact_core_smiles", "attachment_topology",
                "core_tanimoto", "mcs_coverage_target", "mcs_coverage_reference",
            ])
        near_path=outdir/"mmp_near_core_references.csv"; near.to_csv(near_path,index=False); extra_artifacts.append(near_path)
    report = outdir / "mmp_report.html"; target_report_links=[]
    if role != "type-iii":
        from rdkit import Chem
        from rdkit.Chem import Draw
        for _,target in targets.drop_duplicates("target_compound_id").iterrows():
            target_id=str(target["target_compound_id"]); part=target_pairs.loc[target_pairs["target_compound_id"].astype(str).eq(target_id)].copy() if len(target_pairs) else pd.DataFrame(); unit_labels=", ".join(sorted(set(targets.loc[targets["target_compound_id"].astype(str).eq(target_id),"analysis_unit_id"].astype(str))))
            if len(part) and "mmp_id" in part:
                part=part.drop_duplicates("mmp_id")
            safe_prefix="".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in target_id)[:64] or "target"
            # Distinct IDs can normalize to the same filename (for example A/B
            # and A?B).  Preserve the readable prefix while binding every
            # target report to a collision-resistant ID-derived suffix.
            safe=f"{safe_prefix}_{hashlib.sha256(target_id.encode('utf-8')).hexdigest()[:12]}"
            svg_path=outdir/f"mmp_map_{safe}.svg"
            display_effect = "favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"
            display_label = "Δ neighbor→target" if role == "type-i" else "Δ target→neighbor"
            target_smiles=str(data.loc[data[compound_id].astype(str).eq(target_id),smiles].iloc[0]); display=part.sort_values(display_effect,ascending=False).drop_duplicates("neighbor_compound_id").head(11) if len(part) else part
            molecules=[Chem.MolFromSmiles(target_smiles),*[Chem.MolFromSmiles(str(value)) for value in display.get("neighbor_smiles",pd.Series(dtype=str))]]; legends=[f"TARGET {target_id}",*[f"{row.neighbor_compound_id}\n{display_label}={getattr(row, display_effect):.3g}" if pd.notna(getattr(row, display_effect)) else str(row.neighbor_compound_id) for row in display.itertuples()]]
            valid=[(mol,legend) for mol,legend in zip(molecules,legends) if mol is not None]
            if valid: svg_path.write_text(str(Draw.MolsToGridImage([item[0] for item in valid],molsPerRow=4,subImgSize=(260,220),legends=[item[1] for item in valid],useSVG=True)),encoding="utf-8")
            escaped_target = html.escape(target_id)
            escaped_units = html.escape(unit_labels)
            page_path=outdir/f"mmp_target_{safe}.html"; image=f"<img src='{image_uri(svg_path)}'>" if svg_path.is_file() else "<p>構造図を生成できませんでした。</p>"; direction_text="隣接化合物から対象へ向かう" if role == "type-i" else "対象から隣接化合物へ向かう"; page_path.write_text(html_page(f"MMP target {target_id}",f"<h1>MMP target {escaped_target}</h1><div class='card'><p>対象Analysis unit: {escaped_units}</p>{image}</div><div class='card'><p>{display_label}が正なら、{direction_text}変換がFavorableです。0件も正しいNegative Resultです。underexploredは結論ではなく観測MMP数の少なさを示します。</p>{frame_html(part,1000)}</div>"),encoding="utf-8"); target_report_links.append((target_id,page_path,svg_path if svg_path.is_file() else None))
    links="".join(
        f"<li><a href='{html.escape(path.name, quote=True)}'>{html.escape(target_id)}</a></li>"
        for target_id,path,_ in target_report_links
    )
    effect_note = "隣接化合物からTop対象へ向かう方向" if role == "type-i" else ("指定Hitから隣接化合物へ向かう方向" if role == "type-ii" else "Databaseのcanonical方向")
    report.write_text(html_page("MMP analysis", f"<h1>MMP analysis {role}</h1><div class='card'><p>1-cut / environment radius {radius_min}–{radius_max}. Agentの結論ではなく、対象化合物に接続する観測MMPを提示します。主effectは{effect_note}でFavorableを正とします。CSVには両方向のFavorable差を保持します。</p>{frame_html(target_summary, 200)}<ul>{links}</ul></div><div class='card'><h2>Target-connected MMP</h2>{frame_html(target_pairs, 300)}</div>"), encoding="utf-8")
    extra_artifacts.extend([path for _,path,_ in target_report_links]); extra_artifacts.extend([svg for _,_,svg in target_report_links if svg is not None])
    if role == "type-iii":
        extra_artifacts.extend(path for path in outdir.iterdir() if path.is_file() and path not in {primary,report})
    else:
        # Type-I/II are human-centred target analyses. The complete database and
        # global summary exports belong exclusively to explicit Type-III.
        keep={primary.name,targets_path.name,target_summary_path.name,"mmp_target_transform_summary.csv","mmp_target_core_summary.csv","mmp_near_core_references.csv","mmp_report.html",*[path.name for _,path,_ in target_report_links],*[svg.name for _,_,svg in target_report_links if svg is not None]}
        for path in list(outdir.iterdir()):
            if path.name not in keep:
                if path.is_dir(): shutil.rmtree(path,ignore_errors=True)
                else: path.unlink(missing_ok=True)
    finish_request(request, outdir, capability, primary=primary, summary={"role": role, "target_count": len(targets) if role != "type-iii" else None, "target_connected_pair_rows": len(target_pairs), "database_pair_rows": len(details) if role == "type-iii" else None, "targets_without_mmp": int((target_summary.get("mmp_pair_count", pd.Series(dtype=int)) == 0).sum()) if role != "type-iii" else None, "cuts": 1, "radius": [radius_min, radius_max], "reused_explicit_type_iii_database": reused_database, "negative_result": len(target_pairs) == 0}, report=report, extra_artifacts=extra_artifacts, warnings=build_warnings)
    return 0


def run() -> int:
    if sys.argv[1:] in (["--help"], ["-h"]):
        print("Usage: run.py --request <execution_request.json>")
        return 0
    if sys.argv[1:2] != ["--request"] or len(sys.argv) != 3:
        raise SystemExit(
            "Usage: run.py --request <execution_request.json>. "
            "Use the Launcher with --conductor-request in managed execution."
        )
    return run_execution_request()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
