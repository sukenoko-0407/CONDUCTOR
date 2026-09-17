"""Series-pair SAR transferability tests."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from conductor_stat_core import TestRecord, assign_finding_ids, base_finding, benjamini_hochberg, derive_seed, empirical_p_value, stable_id


@dataclass(frozen=True)
class L7Result:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]


def _rho(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0: return 0.0
    return float(np.corrcoef(rankdata(left), rankdata(right))[0, 1])


def _series(observations: pd.DataFrame, endpoints: pd.DataFrame, endpoint_id: str) -> tuple[dict[str, dict[str, tuple[float, tuple[str, ...]]]], dict[str, str]]:
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id","oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str); selected["oriented_value"] = pd.to_numeric(selected["oriented_value"],errors="coerce"); selected=selected.loc[np.isfinite(selected["oriented_value"])]
    values = dict(zip(selected["compound_id"],selected["oriented_value"].astype(float),strict=True)); result: dict[str,dict[str,tuple[float,tuple[str,...]]]]={}; constants: dict[str,str]={}
    terminal = observations.loc[observations["transform_class"].astype(str).eq("terminal_substitution")]
    for series_key,group in terminal.groupby("series_key",sort=True):
        fragments: dict[str,tuple[float,tuple[str,...]]] = {}; constants[str(series_key)] = str(group.iloc[0]["constant_key"])
        for fragment_id,rows in group.groupby("fragment_id",sort=True):
            ids=tuple(sorted({identifier for raw in rows["compound_ids_json"] for identifier in json.loads(str(raw)) if identifier in values}))
            if ids: fragments[str(fragment_id)]=(float(np.mean([values[value] for value in ids])),ids)
        if len(fragments)>=2: result[str(series_key)]=fragments
    return result,constants


def run_l7(observations: pd.DataFrame,endpoints: pd.DataFrame,endpoint_id: str,*,run_seed: int,min_common_r_groups: int=5,min_abs_spearman_rho: float=0.50,screen_permutations: int=100,final_permutations: int=1000,screen_p_max: float=0.05,report_q_max: float=0.05) -> L7Result:
    if not 1<=screen_permutations<=final_permutations: raise ValueError("Invalid permutation counts")
    endpoint_rows=endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id),["compound_id","oriented_value"]].copy();endpoint_rows["compound_id"]=endpoint_rows["compound_id"].astype(str);endpoint_rows["oriented_value"]=pd.to_numeric(endpoint_rows["oriented_value"],errors="coerce");endpoint_rows=endpoint_rows.loc[np.isfinite(endpoint_rows["oriented_value"])];endpoint_lookup=dict(zip(endpoint_rows["compound_id"],endpoint_rows["oriented_value"].astype(float),strict=True))
    series,constants=_series(observations,endpoints,endpoint_id); candidates: dict[str,dict[str,Any]]={}
    for left_id,right_id in combinations(sorted(series),2):
        common=sorted(set(series[left_id]).intersection(series[right_id]))
        if len(common)<min_common_r_groups: continue
        left=np.asarray([series[left_id][key][0] for key in common],dtype=float); right=np.asarray([series[right_id][key][0] for key in common],dtype=float)
        key=stable_id("L7C",{"series_a":left_id,"series_b":right_id,"endpoint":endpoint_id})
        candidates[key]={"candidate_key":key,"series_a":left_id,"series_b":right_id,"common":common,"left":left,"right":right,"rho":_rho(left,right),"mean_difference":float(np.mean(right-left))}
    nulls={(key,question):[] for key in candidates for question in ("rank_transfer","scaffold_main_effect")}
    for iteration in range(screen_permutations):
        for key,row in candidates.items():
            rng=np.random.default_rng(derive_seed(run_seed,key,iteration)); permuted=row["right"][rng.permutation(len(row["right"]))]
            nulls[(key,"rank_transfer")].append(_rho(row["left"],permuted))
            swaps=rng.integers(0,2,size=len(row["left"]),dtype=np.int8).astype(bool); differences=row["right"]-row["left"]; nulls[(key,"scaffold_main_effect")].append(float(np.mean(np.where(swaps,-differences,differences))))
    screen_p={}; survivors=set()
    for key,row in candidates.items():
        for question,statistic in (("rank_transfer",row["rho"]),("scaffold_main_effect",row["mean_difference"])):
            p=empirical_p_value(statistic,nulls[(key,question)],"two_sided_abs"); screen_p[(key,question)]=p
            if p<=screen_p_max: survivors.add((key,question))
    for iteration in range(screen_permutations,final_permutations):
        if not survivors: break
        for key,question in sorted(survivors):
            row=candidates[key]; rng=np.random.default_rng(derive_seed(run_seed,key,iteration))
            if question=="rank_transfer": statistic=_rho(row["left"],row["right"][rng.permutation(len(row["right"]))])
            else:
                swaps=rng.integers(0,2,size=len(row["left"]),dtype=np.int8).astype(bool); differences=row["right"]-row["left"]; statistic=float(np.mean(np.where(swaps,-differences,differences)))
            nulls[(key,question)].append(statistic)
    records=[]; record_keys=[]
    for key,row in sorted(candidates.items()):
        for question,statistic in (("rank_transfer",row["rho"]),("scaffold_main_effect",row["mean_difference"])):
            final=(key,question) in survivors; record_keys.append((key,question)); records.append(TestRecord(candidate_key=f"{key}|{question}",test_id=stable_id("TEST",{"lens":"L7","candidate":key,"question":question}),family_key="L7",statistic=float(statistic),alternative="two_sided_abs",p_value=empirical_p_value(statistic,nulls[(key,question)],"two_sided_abs") if final else 1.0,null_iterations=final_permutations if final else screen_permutations,participation=1.0,status="final" if final else "screened_out"))
    adjusted=benjamini_hochberg(records); result_by_candidate: dict[str,dict[str,tuple[TestRecord,TestRecord]]]={}; test_rows=[]
    for (key,question),record,adjusted_record in zip(record_keys,records,adjusted,strict=True):
        result_by_candidate.setdefault(key,{})[question]=(record,adjusted_record); test_rows.append({"row_id":stable_id("ROW",{"test_id":record.test_id}),"candidate_key":key,"question":question,"test_id":record.test_id,"family_key":record.family_key,"statistic":record.statistic,"screen_p_value":screen_p[(key,question)],"p_value":record.p_value,"q_value":adjusted_record.q_value,"null_iterations":record.null_iterations,"status":record.status})
    evidence_rows=[]; score_rows=[]; provisional=[]
    for key,row in sorted(candidates.items()):
        evidence_id=stable_id("L7",{"candidate":key}); evidence_rows.append({"row_id":evidence_id,"candidate_key":key,"series_a":row["series_a"],"series_b":row["series_b"],"constant_a":constants[row["series_a"]],"constant_b":constants[row["series_b"]],"common_r_count":len(row["common"]),"spearman_rho":row["rho"],"mean_difference":row["mean_difference"],"common_fragment_ids_json":json.dumps(row["common"],separators=(",",":"))})
        rank_record,rank_adjusted=result_by_candidate[key]["rank_transfer"]; main_record,main_adjusted=result_by_candidate[key]["scaffold_main_effect"]
        rank_q=rank_adjusted.q_value if rank_record.status=="final" else 1.0; main_q=main_adjusted.q_value if main_record.status=="final" else 1.0
        finding_type=None
        if rank_q is not None and rank_q<=report_q_max and row["rho"]<=-min_abs_spearman_rho: finding_type="sar_ranking_reversal"
        elif rank_q is not None and rank_q<=report_q_max and row["rho"]>=min_abs_spearman_rho and main_q is not None and main_q<=report_q_max: finding_type="scaffold_superiority"
        elif rank_q is not None and rank_q<=report_q_max and row["rho"]>=min_abs_spearman_rho and (main_q is None or main_q>report_q_max): finding_type="independent_optimization"
        if finding_type is None: continue
        tests=[{"test_id":rank_record.test_id,"question":"rank_transfer","method":"r_group_label_permutation","statistic":float(rank_record.statistic),"p_value":float(rank_record.p_value),"q_value":float(rank_q),"null_iterations":int(rank_record.null_iterations)},{"test_id":main_record.test_id,"question":"scaffold_main_effect","method":"paired_scaffold_label_permutation","statistic":float(main_record.statistic),"p_value":float(main_record.p_value),"q_value":float(main_q) if main_q is not None else None,"null_iterations":int(main_record.null_iterations)}]
        compound_ids=sorted({identifier for fragment in row["common"] for series_id in (row["series_a"],row["series_b"]) for identifier in series[series_id][fragment][1]}); direction="mixed" if finding_type=="sar_ranking_reversal" else "positive" if row["mean_difference"]>0 else "negative" if row["mean_difference"]<0 else "flat"
        finding=base_finding(lens="L7",endpoint_id=endpoint_id,subject_type="series_pair",subject_id=f"{row['series_a']}|{row['series_b']}",condition_id=None,effect_direction=direction,effect_size=float(row["rho"] if finding_type=="sar_ranking_reversal" else row["mean_difference"]),effect_unit="spearman_rho" if finding_type=="sar_ranking_reversal" else "oriented_endpoint",support_n=len(row["common"]),tests=tests,falsification_type="r_group_and_scaffold_label_permutation",falsification_parameters={"common_r_groups":len(row["common"])},falsification_rule=f"rank BH q <= {report_q_max} and classification thresholds",entities={"scaffold_ids":[row["series_a"],row["series_b"]],"fragment_ids":row["common"],"compound_ids":compound_ids},citations=[{"citation_id":stable_id("CIT",{"row_id":evidence_id}),"table_ref":f"l7_evidence.csv#row_id={evidence_id}"}],labels=[finding_type]); provisional.append(finding)
        for index,fragment_id in enumerate(row["common"]):
            source_ids=series[row["series_a"]][fragment_id][1]; target_ids=series[row["series_b"]][fragment_id][1]; score_rows.append({"finding_key":finding["finding_key"],"row_id":stable_id("SCOREROW",{"finding":finding["finding_key"],"fragment":fragment_id}),"block_id":fragment_id,"effect":float(row["right"][index]-row["left"][index]),"compound_id":target_ids[0],"context_id":"", "target_id":fragment_id,"compound_ids_a_json":json.dumps(list(source_ids),separators=(",",":")),"compound_ids_b_json":json.dumps(list(target_ids),separators=(",",":")),"endpoint_values_a_json":json.dumps([endpoint_lookup[value] for value in source_ids],separators=(",",":")),"endpoint_values_b_json":json.dumps([endpoint_lookup[value] for value in target_ids],separators=(",",":")),"endpoint_left_value":float(row["left"][index]),"endpoint_value":float(row["right"][index]),"actionability_level":"direction_only"})
    metrics={"series_count":len(series),"series_pair_count":len(candidates),"test_count":len(records),"finding_count":len(provisional)}
    return L7Result(pd.DataFrame(evidence_rows),pd.DataFrame(test_rows),pd.DataFrame(score_rows),assign_finding_ids(provisional),metrics)
