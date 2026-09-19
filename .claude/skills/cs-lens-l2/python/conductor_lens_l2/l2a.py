"""L2a transformation-by-context interaction tests."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from conductor_stat_core import TestRecord, assign_finding_ids, base_finding, benjamini_hochberg, derive_seed, empirical_p_value, stable_id


@dataclass(frozen=True)
class L2AResult:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]


def _endpoint_map(endpoints: pd.DataFrame, endpoint_id: str) -> dict[str, float]:
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str)
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])]
    if selected["compound_id"].duplicated().any(): raise ValueError("Duplicate selected Endpoint rows")
    return dict(zip(selected["compound_id"], selected["oriented_value"].astype(float), strict=True))


def _pair_deltas(pairs: pd.DataFrame, values: dict[str, float], *, run_seed: int | None = None, iteration: int | None = None) -> np.ndarray:
    output = np.full(len(pairs), np.nan, dtype=float)
    for constant_key, positions in pairs.groupby("constant_key", sort=True).groups.items():
        indices = np.asarray(sorted(int(value) for value in positions), dtype=int)
        compound_ids = sorted({str(pairs.iloc[index][column]) for index in indices for column in ("compound_from", "compound_to") if str(pairs.iloc[index][column]) in values})
        series_values = np.asarray([values[value] for value in compound_ids], dtype=float)
        if run_seed is not None and iteration is not None and len(series_values) > 1:
            rng = np.random.default_rng(derive_seed(run_seed, str(constant_key), iteration))
            series_values = series_values[rng.permutation(len(series_values))]
        lookup = dict(zip(compound_ids, series_values, strict=True))
        for index in indices:
            row = pairs.iloc[index]; left = lookup.get(str(row["compound_from"])); right = lookup.get(str(row["compound_to"]))
            if left is not None and right is not None: output[index] = float(right - left)
    return output


def run_l2a(
    pairs: pd.DataFrame,
    endpoints: pd.DataFrame,
    context_catalog: pd.DataFrame,
    context_membership: pd.DataFrame,
    endpoint_id: str,
    *,
    run_seed: int,
    min_transform_pairs: int = 3,
    min_pairs_in: int = 3,
    min_pairs_out: int = 3,
    neutral_abs_delta_max: float = 0.28,
    tolerance_variance_max: float = 0.02,
    screen_permutations: int = 100,
    final_permutations: int = 1000,
    screen_p_max: float = 0.05,
    report_q_max: float = 0.05,
    progress_callback: Callable[[int, int], None] | None = None,
) -> L2AResult:
    required = {"pair_id","class","compound_from","compound_to","constant_key","variable_from","variable_to","transformation_id"}
    if required - set(pairs): raise ValueError(f"Pairs table is missing columns: {sorted(required-set(pairs))}")
    if not 1 <= screen_permutations <= final_permutations: raise ValueError("Invalid permutation counts")
    values = _endpoint_map(endpoints, endpoint_id); pairs = pairs.copy().reset_index(drop=True)
    observed_delta = _pair_deltas(pairs, values); pairs["delta"] = observed_delta
    pairs = pairs.loc[np.isfinite(pairs["delta"])].reset_index(drop=True); observed_delta = pairs["delta"].to_numpy(dtype=float)
    eligible_transformations = {str(key) for key, group in pairs.groupby("transformation_id", sort=True) if len(group) >= min_transform_pairs}
    catalog = context_catalog.copy()
    if "is_representative" not in catalog: catalog["is_representative"] = True
    if "eligible" not in catalog: catalog["eligible"] = True
    if "translation_status" not in catalog: catalog["translation_status"] = "native"
    catalog = catalog.loc[catalog["is_representative"].astype(bool) & catalog["eligible"].astype(bool) & ~catalog["translation_status"].eq("untranslatable")]
    allowed_contexts = set(catalog["context_id"].astype(str)); translation = dict(zip(catalog["context_id"].astype(str), catalog["translation_status"].astype(str), strict=True))
    memberships = {str(key): set(group["compound_id"].astype(str)) for key,group in context_membership.groupby(context_membership["context_id"].astype(str), sort=True) if str(key) in allowed_contexts}
    candidates: dict[str, dict[str, Any]] = {}
    for transformation_id, group in pairs.loc[pairs["transformation_id"].astype(str).isin(eligible_transformations)].groupby("transformation_id", sort=True):
        all_positions = group.index.to_numpy(dtype=int); all_values = observed_delta[all_positions]
        if len(all_values) < min_pairs_in + min_pairs_out or float(np.var(all_values, ddof=1)) <= 0: continue
        for context_id, members in sorted(memberships.items()):
            in_positions = np.asarray([index for index in all_positions if str(pairs.loc[index,"compound_from"]) in members and str(pairs.loc[index,"compound_to"]) in members], dtype=int)
            out_positions = np.asarray([index for index in all_positions if str(pairs.loc[index,"compound_from"]) not in members and str(pairs.loc[index,"compound_to"]) not in members], dtype=int)
            if len(in_positions) < min_pairs_in or len(out_positions) < min_pairs_out: continue
            comparison_positions=np.concatenate((in_positions,out_positions)); inside, outside = observed_delta[in_positions], observed_delta[out_positions]; comparison_values=observed_delta[comparison_positions]
            shift = float(np.median(inside) - np.median(outside)); variance_all = float(np.var(comparison_values, ddof=1)); ratio = float(np.var(inside, ddof=1) / variance_all)
            key = stable_id("L2AC", {"transformation":str(transformation_id),"context":context_id,"endpoint":endpoint_id})
            first = group.iloc[0]
            candidates[key] = {"candidate_key":key,"transformation_id":str(transformation_id),"context_id":context_id,"class":str(first["class"]),"variable_from":str(first["variable_from"]),"variable_to":str(first["variable_to"]),"all":comparison_positions,"inside":in_positions,"outside":out_positions,"shift":shift,"variance_ratio":ratio,"median_in":float(np.median(inside)),"median_out":float(np.median(outside)),"variance_in":float(np.var(inside,ddof=1)),"variance_all":variance_all}
    nulls = {(key, question): [] for key in candidates for question in ("mean_shift","variance_reduction")}
    for iteration in range(screen_permutations):
        permuted = _pair_deltas(pairs, values, run_seed=run_seed, iteration=iteration)
        for key,row in candidates.items():
            inside, outside, all_values = permuted[row["inside"]], permuted[row["outside"]], permuted[row["all"]]
            nulls[(key,"mean_shift")].append(float(np.median(inside)-np.median(outside)))
            variance_all = float(np.var(all_values,ddof=1)); nulls[(key,"variance_reduction")].append(float(np.var(inside,ddof=1)/variance_all) if variance_all>0 else math.nan)
        if progress_callback is not None:
            progress_callback(iteration + 1, final_permutations)
    screen_p: dict[tuple[str,str],float] = {}
    survivors: set[tuple[str,str]] = set()
    for key,row in candidates.items():
        for question, statistic, alternative in (("mean_shift",row["shift"],"two_sided_abs"),("variance_reduction",row["variance_ratio"],"lower")):
            p = empirical_p_value(statistic,nulls[(key,question)],alternative); screen_p[(key,question)] = p
            if p <= screen_p_max: survivors.add((key,question))
    for iteration in range(screen_permutations,final_permutations):
        if not survivors: break
        permuted = _pair_deltas(pairs,values,run_seed=run_seed,iteration=iteration)
        for key,question in sorted(survivors):
            row=candidates[key]; inside,outside,all_values=permuted[row["inside"]],permuted[row["outside"]],permuted[row["all"]]
            statistic=float(np.median(inside)-np.median(outside)) if question=="mean_shift" else (float(np.var(inside,ddof=1)/np.var(all_values,ddof=1)) if float(np.var(all_values,ddof=1))>0 else math.nan)
            nulls[(key,question)].append(statistic)
        if progress_callback is not None:
            progress_callback(iteration + 1, final_permutations)
    records: list[TestRecord] = []; record_keys: list[tuple[str,str]] = []
    for key,row in sorted(candidates.items()):
        for question,statistic,alternative in (("mean_shift",row["shift"],"two_sided_abs"),("variance_reduction",row["variance_ratio"],"lower")):
            final=(key,question) in survivors; record_keys.append((key,question)); records.append(TestRecord(candidate_key=f"{key}|{question}",test_id=stable_id("TEST",{"lens":"L2a","candidate":key,"question":question}),family_key=f"L2a|{row['class']}|{row['transformation_id']}|{question}",statistic=float(statistic),alternative=alternative,p_value=empirical_p_value(statistic,nulls[(key,question)],alternative) if final else 1.0,null_iterations=final_permutations if final else screen_permutations,participation=1.0,status="final" if final else "screened_out"))
    adjusted=benjamini_hochberg(records); tests_by_candidate: dict[str,list[tuple[TestRecord,TestRecord,str]]] = defaultdict(list); test_rows=[]
    for (key,question),record,adjusted_record in zip(record_keys,records,adjusted,strict=True):
        row=candidates[key]; test_rows.append({"row_id":stable_id("ROW",{"test_id":record.test_id}),"candidate_key":key,"transformation_id":row["transformation_id"],"context_id":row["context_id"],"question":question,"test_id":record.test_id,"family_key":record.family_key,"statistic":record.statistic,"screen_p_value":screen_p[(key,question)],"p_value":record.p_value,"q_value":adjusted_record.q_value,"null_iterations":record.null_iterations,"status":record.status})
        if record.status=="final" and adjusted_record.q_value is not None and adjusted_record.q_value<=report_q_max: tests_by_candidate[key].append((record,adjusted_record,question))
    evidence_rows=[]; score_rows=[]; provisional=[]
    for key,row in sorted(candidates.items()):
        evidence_id=stable_id("L2A",{"candidate":key}); in_pairs=pairs.loc[row["inside"]]; out_pairs=pairs.loc[row["outside"]]
        evidence_rows.append({"row_id":evidence_id,"candidate_key":key,"transformation_id":row["transformation_id"],"transform_class":row["class"],"context_id":row["context_id"],"variable_from":row["variable_from"],"variable_to":row["variable_to"],"n_in":len(row["inside"]),"n_out":len(row["outside"]),"median_in":row["median_in"],"median_out":row["median_out"],"median_shift":row["shift"],"variance_in":row["variance_in"],"variance_all":row["variance_all"],"variance_ratio":row["variance_ratio"],"pair_ids_in_json":json.dumps(sorted(in_pairs["pair_id"].astype(str).tolist()),separators=(",",":")),"pair_ids_out_json":json.dumps(sorted(out_pairs["pair_id"].astype(str).tolist()),separators=(",",":"))})
        selected_tests=tests_by_candidate.get(key,[])
        if not selected_tests: continue
        finding_tests=[{"test_id":record.test_id,"question":question,"method":"series_endpoint_permutation","statistic":float(record.statistic),"p_value":float(record.p_value),"q_value":float(adjusted_record.q_value),"null_iterations":int(record.null_iterations)} for record,adjusted_record,question in selected_tests]
        compounds=sorted(set(in_pairs["compound_from"].astype(str))|set(in_pairs["compound_to"].astype(str))); labels=[]
        if abs(row["median_in"])<neutral_abs_delta_max and row["variance_in"]<=tolerance_variance_max: labels.append("tolerance")
        direction="positive" if row["shift"]>0 else "negative" if row["shift"]<0 else "flat"; effect=row["shift"] if any(question=="mean_shift" for _,_,question in selected_tests) else 1.0-row["variance_ratio"]
        finding=base_finding(lens="L2a",endpoint_id=endpoint_id,subject_type="transformation",subject_id=row["transformation_id"],condition_id=row["context_id"],effect_direction=direction,effect_size=float(effect),effect_unit="oriented_endpoint_shift" if any(question=="mean_shift" for _,_,question in selected_tests) else "variance_reduction",support_n=len(row["inside"]),tests=finding_tests,falsification_type="series_endpoint_permutation",falsification_parameters={"crossing_pairs_excluded":True},falsification_rule=f"at least one question BH q <= {report_q_max}",entities={"context_ids":[row["context_id"]],"transformation_ids":[row["transformation_id"]],"compound_ids":compounds},citations=[{"citation_id":stable_id("CIT",{"row_id":evidence_id}),"table_ref":f"l2a_evidence.csv#row_id={evidence_id}"}],translation_status=translation.get(row["context_id"],"native"),labels=labels); provisional.append(finding)
        for comparison_group,positions in (("inside",row["inside"]),("outside",row["outside"])):
            for pair_index in positions:
                pair=pairs.loc[pair_index]; score_rows.append({"finding_key":finding["finding_key"],"row_id":stable_id("SCOREROW",{"finding":finding["finding_key"],"pair":pair["pair_id"],"group":comparison_group}),"block_id":str(pair["constant_key"]),"effect":float(observed_delta[pair_index]),"compound_id":str(pair["compound_to"]),"context_id":row["context_id"],"target_id":row["transformation_id"],"pair_from_compound_id":str(pair["compound_from"]),"pair_to_compound_id":str(pair["compound_to"]),"endpoint_from_value":float(values[str(pair["compound_from"])]),"comparison_group":comparison_group,"endpoint_value":float(values[str(pair["compound_to"])]),"actionability_level":"exact"})
    series_member_count = sum(
        len({str(value) for column in ("compound_from", "compound_to") for value in group[column]})
        for _, group in pairs.groupby("constant_key", sort=True)
    )
    metrics={"eligible_transformation_count":len(eligible_transformations),"candidate_count":len(candidates),"test_count":len(records),"final_test_count":len(survivors),"finding_count":len(provisional),"finite_endpoint_count":len(values),"eligible_pair_count":len(pairs),"series_member_count":series_member_count,"class_count":int(pairs["class"].astype(str).nunique()) if not pairs.empty else 0}
    return L2AResult(pd.DataFrame(evidence_rows),pd.DataFrame(test_rows),pd.DataFrame(score_rows),assign_finding_ids(provisional),metrics)
