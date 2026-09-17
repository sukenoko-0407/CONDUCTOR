"""Five-axis scoring, fixed gates, ranking, and duplicate retention."""

from __future__ import annotations

import math
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats

from conductor_stat_core import ENTITY_KEYS, assign_finding_ids, block_bootstrap_indices


ACTIONABILITY = {"exact": 1.0, "direction_only": 0.6, "descriptive": 0.2}


@dataclass(frozen=True)
class ScoringResult:
    findings: tuple[dict[str, Any], ...]
    scores: pd.DataFrame
    gate: dict[str, Any]


def _primary_q(finding: dict[str, Any]) -> float:
    values = [float(item["q_value"]) for item in finding["tests"] if item.get("q_value") is not None]
    return min(values) if values else 1.0


def _bootstrap_survival(values: np.ndarray, blocks: list[str], parent_effect: float, *, iterations: int, seed: int) -> float:
    if len(values) < 2 or not blocks: return 0.0
    parent_sign = 1 if parent_effect > 0 else -1 if parent_effect < 0 else 0
    survived = 0
    for sample in block_bootstrap_indices(blocks, iterations, seed):
        selected = values[sample.indices]; mean = float(np.mean(selected)); standard = float(np.std(selected, ddof=1)) if len(selected)>1 else math.nan
        if len(selected)>1 and standard>0 and math.isfinite(standard): p_value=float(stats.ttest_1samp(selected,0.0).pvalue)
        elif mean != 0: p_value=0.0
        else: p_value=1.0
        direction = 1 if mean>0 else -1 if mean<0 else 0
        survived += bool(direction==parent_sign and p_value<=0.05)
    return survived/iterations


def _confounder_model(
    endpoints: pd.DataFrame,
    endpoint_id: str,
    confounders: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Fit Endpoint ~ MW + cLogP + TPSA + scaffold dummies once, then residualize."""
    required={"compound_id","mw","clogp","tpsa","scaffold_id"}
    missing=required-set(confounders.columns)
    if missing: raise ValueError(f"Confounder table is missing columns: {sorted(missing)}")
    if confounders["compound_id"].astype(str).duplicated().any(): raise ValueError("Confounder table has duplicate compound_id values")
    selected=endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id),["compound_id","oriented_value"]].copy(); selected["compound_id"]=selected["compound_id"].astype(str); selected["oriented_value"]=pd.to_numeric(selected["oriented_value"],errors="coerce"); selected=selected.loc[np.isfinite(selected["oriented_value"])]
    table=confounders.copy(); table["compound_id"]=table["compound_id"].astype(str); table=table.set_index("compound_id")
    if set(selected["compound_id"])-set(table.index): raise ValueError("Confounder table is incomplete for the selected Endpoint")
    training=table.loc[selected["compound_id"].tolist()]
    numeric=[]; medians=[]
    for name in ("mw","clogp","tpsa"):
        values=pd.to_numeric(training[name],errors="coerce").to_numpy(dtype=float); median=float(np.nanmedian(values))
        if not math.isfinite(median): raise ValueError(f"Confounder has no finite values: {name}")
        numeric.append(np.where(np.isfinite(values),values,median)); medians.append(median)
    scaffolds=training["scaffold_id"].fillna("").astype(str); levels=sorted(set(scaffolds)); dummy_levels=levels[1:]
    columns=[np.ones(len(training)),*numeric,*[scaffolds.eq(level).to_numpy(dtype=float) for level in dummy_levels]]
    design=np.column_stack(columns); target=selected["oriented_value"].to_numpy(dtype=float); coefficients=np.linalg.lstsq(design,target,rcond=None)[0]
    predictions:dict[str,float]={}
    for compound_id,row in table.iterrows():
        vector=[1.0]
        for name,median in zip(("mw","clogp","tpsa"),medians,strict=True):
            value=pd.to_numeric(pd.Series([row[name]]),errors="coerce").iloc[0]; vector.append(float(value) if math.isfinite(float(value)) else median)
        scaffold="" if pd.isna(row["scaffold_id"]) else str(row["scaffold_id"]); vector.extend(float(scaffold==level) for level in dummy_levels); predictions[str(compound_id)]=float(np.asarray(vector)@coefficients)
    observed=dict(zip(selected["compound_id"],target,strict=True)); residuals={compound_id:float(value-predictions[compound_id]) for compound_id,value in observed.items()}
    return residuals,predictions,["MW","cLogP","TPSA","scaffold_class"]


def _json_ids(value:Any)->list[str]:
    parsed=json.loads(str(value))
    if not isinstance(parsed,list): raise ValueError("Expected a JSON list of compound IDs")
    return [str(item) for item in parsed]


def _mean_lookup(identifiers:list[str],values:dict[str,float])->float:
    missing=[value for value in identifiers if value not in values]
    if missing: raise ValueError(f"Residualized Endpoint is missing compounds: {missing[:5]}")
    return float(np.mean([values[value] for value in identifiers]))


def _exact_adjusted_effect(
    finding:dict[str,Any],
    rows:pd.DataFrame,
    residuals:dict[str,float],
    predictions:dict[str,float],
) -> float:
    """Recompute the Lens effect statistic on its residualized minimum observation unit."""
    lens=str(finding["lens"]); raw=float(finding["claim"]["effect_size"]); unit=str(finding["claim"]["effect_unit"])
    if rows.empty: raise ValueError(f"{lens} Finding has no score observations")
    if lens=="L1b":
        required={"compound_id","neighbor_compound_ids_json"}
        if required-set(rows.columns): raise ValueError("L1b score observations lack exact neighbor identities")
        global_values=np.asarray(list(residuals.values()),dtype=float); variance=float(np.var(global_values,ddof=1))
        errors=[]
        for row in rows.itertuples(index=False): errors.append((residuals[str(row.compound_id)]-_mean_lookup(_json_ids(row.neighbor_compound_ids_json),residuals))**2)
        return float(1.0-np.mean(errors)/variance) if variance>0 else 0.0
    if lens=="L5":
        required={"compound_id","context_role","feature_value"}
        if required-set(rows.columns): raise ValueError("L5 score observations lack context/feature values")
        correlations=[]
        for role in ("a","b"):
            group=rows.loc[rows["context_role"].astype(str).eq(role)]; x=pd.to_numeric(group["feature_value"],errors="coerce").to_numpy(dtype=float); y=np.asarray([residuals[str(value)] for value in group["compound_id"]],dtype=float); finite=np.isfinite(x)&np.isfinite(y)
            if int(finite.sum())<3 or float(np.std(x[finite]))<=1e-12 or float(np.std(y[finite]))<=1e-12: return 0.0
            correlations.append(float(np.corrcoef(x[finite],y[finite])[0,1]))
        epsilon=np.finfo(float).eps; return float(np.arctanh(np.clip(correlations[0],-1+epsilon,1-epsilon))-np.arctanh(np.clip(correlations[1],-1+epsilon,1-epsilon)))
    if lens=="L2a":
        required={"pair_from_compound_id","pair_to_compound_id","comparison_group"}
        if required-set(rows.columns): raise ValueError("L2a score observations lack pair identities/groups")
        deltas=np.asarray([residuals[str(row.pair_to_compound_id)]-residuals[str(row.pair_from_compound_id)] for row in rows.itertuples(index=False)],dtype=float); groups=rows["comparison_group"].astype(str).to_numpy(); inside=deltas[groups=="inside"]; outside=deltas[groups=="outside"]
        if unit=="variance_reduction":
            variance=float(np.var(deltas,ddof=1)); return float(1.0-np.var(inside,ddof=1)/variance) if variance>0 and len(inside)>1 else 0.0
        return float(np.median(inside)-np.median(outside))
    if lens=="L2b":
        required={"subject_compound_ids_json","series_fragments_compound_ids_json"}
        if required-set(rows.columns): raise ValueError("L2b score observations lack series membership")
        series_residuals=[]
        for row in rows.itertuples(index=False):
            subject=_mean_lookup(_json_ids(row.subject_compound_ids_json),residuals); fragments=json.loads(str(row.series_fragments_compound_ids_json)); means=[_mean_lookup([str(value) for value in group],residuals) for group in fragments]; series_residuals.append(subject-float(np.mean(means)))
        return float(np.var(series_residuals,ddof=1)) if unit=="oriented_endpoint_variance" else float(np.mean(series_residuals))
    if lens=="L7":
        required={"compound_ids_a_json","compound_ids_b_json"}
        if required-set(rows.columns): raise ValueError("L7 score observations lack both series members")
        left=np.asarray([_mean_lookup(_json_ids(value),residuals) for value in rows["compound_ids_a_json"]],dtype=float); right=np.asarray([_mean_lookup(_json_ids(value),residuals) for value in rows["compound_ids_b_json"]],dtype=float)
        if unit=="spearman_rho":
            if len(left)<2 or float(np.std(left))<=1e-12 or float(np.std(right))<=1e-12: return 0.0
            return float(stats.spearmanr(left,right).statistic)
        return float(np.mean(right-left))
    if lens=="L4":
        candidate_id=str(rows.iloc[0]["candidate_id"]); sources=[str(value) for value in finding["entities"].get("compound_ids",[])]
        if candidate_id not in predictions or any(value not in predictions for value in sources): raise ValueError("L4 confounder predictions are incomplete for candidate/source compounds")
        confounder_delta=predictions[candidate_id]-float(np.mean([predictions[value] for value in sources])); density=float(pd.to_numeric(rows["density_gap"],errors="coerce").min()) if "density_gap" in rows else 1.0; return float(raw-confounder_delta*density)
    raise ValueError(f"Unsupported Lens for exact confounder adjustment: {lens}")


def _entity_set(finding: dict[str, Any]) -> set[tuple[str,str]]:
    return {(kind,str(value)) for kind in ENTITY_KEYS for value in finding["entities"].get(kind,[])}


def merge_duplicate_findings(findings: list[dict[str, Any]]) -> None:
    eligible=[item for item in findings if item["state"]["pipeline"]=="reportable"]
    ordered=sorted(eligible,key=lambda item:(-float(item["scores"]["composite"]),_primary_q(item),item["finding_key"]))
    for index,winner in enumerate(ordered):
        if winner["state"]["pipeline"]=="merged": continue
        winner_entities=_entity_set(winner)
        for loser in ordered[index+1:]:
            if loser["state"]["pipeline"]=="merged" or loser["claim"]["subject_type"]!=winner["claim"]["subject_type"]: continue
            if len(winner_entities.intersection(_entity_set(loser)))>=2:
                loser["merged_into"]=winner["finding_id"]; loser["state"]["pipeline"]="merged"


def score_findings(findings: Iterable[dict[str, Any]],observations: pd.DataFrame,endpoints: pd.DataFrame,endpoint_id: str,*,run_seed: int,confounders:pd.DataFrame|None=None,bootstrap_iterations: int=200,statistical_strength_min: float=0.50,robustness_min: float=0.70,display_k: int=10) -> ScoringResult:
    result=list(assign_finding_ids(findings)); by_key={str(key):group.copy() for key,group in observations.groupby(observations["finding_key"].astype(str),sort=True)} if not observations.empty else {}
    endpoint_values=pd.to_numeric(endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id),"oriented_value"],errors="coerce"); endpoint_values=endpoint_values[np.isfinite(endpoint_values)].to_numpy(dtype=float)
    if len(endpoint_values)<2: raise ValueError("Scoring requires at least two finite Endpoint values")
    y_median=float(np.median(endpoint_values)); y_top=float(np.quantile(endpoint_values,0.95)); denominator=y_top-y_median
    residuals:dict[str,float]={}; predictions:dict[str,float]={}; confounder_names:list[str]=[]
    if confounders is not None: residuals,predictions,confounder_names=_confounder_model(endpoints,endpoint_id,confounders)
    lenses: dict[str,list[dict[str,Any]]]={}
    for finding in result: lenses.setdefault(str(finding["lens"]),[]).append(finding)
    for rows in lenses.values():
        ordered=sorted(rows,key=lambda item:(_primary_q(item),item["finding_key"])); count=len(ordered)
        for rank,finding in enumerate(ordered,start=1): finding["scores"]["statistical_strength"]=float(1.0-(rank-1)/count)
    score_rows=[]
    for finding in result:
        rows=by_key.get(finding["finding_key"],pd.DataFrame()); raw=float(finding["claim"]["effect_size"])
        if rows.empty:
            if confounders is not None: raise ValueError(f"Finding has no score observations: {finding['finding_key']}")
            robustness=0.0; adjusted=raw; non_triviality=1.0 if raw!=0 else 0.0; tested=[]; actionability=0.2; frontier=0.5
        else:
            effects=pd.to_numeric(rows["effect"],errors="coerce").to_numpy(dtype=float); finite=np.isfinite(effects); rows=rows.loc[finite].reset_index(drop=True); effects=effects[finite]; blocks=rows["block_id"].fillna("").astype(str).tolist()
            robustness=_bootstrap_survival(effects,blocks,raw,iterations=bootstrap_iterations,seed=run_seed+int(finding["finding_key"].split("|")[-1][:8],16)) if len(effects)>=2 else 0.0
            if confounders is None:
                adjusted=raw; non_triviality=1.0 if raw!=0 else 0.0; tested=[]
            else:
                adjusted=_exact_adjusted_effect(finding,rows,residuals,predictions); non_triviality=0.0 if raw==0 else float(np.clip(adjusted/raw,0.0,1.0)); tested=confounder_names
            levels=[ACTIONABILITY.get(str(value),0.2) for value in rows.get("actionability_level",pd.Series(["descriptive"]*len(rows)))]; actionability=max(levels) if levels else 0.2
            if actionability==0.2 or denominator<=0: frontier=0.5 if actionability==0.2 else 0.0
            else:
                observed=pd.to_numeric(rows.get("endpoint_value",pd.Series(dtype=float)),errors="coerce"); observed=observed[np.isfinite(observed)].to_numpy(dtype=float); y_reach=float(np.max(observed+raw)) if len(observed) else y_median; frontier=float(np.clip((y_reach-y_median)/denominator,0.0,1.0))
        finding["triviality"]={"confounders_tested":tested,"raw_effect_size":raw,"adjusted_effect_size":float(adjusted),"verdict":"notable" if non_triviality>=0.5 else "mostly_trivial"}
        finding["scores"]["robustness"]=float(np.clip(robustness,0.0,1.0)); finding["scores"]["non_triviality"]=float(np.clip(non_triviality,0.0,1.0)); finding["scores"]["actionability"]=float(actionability); finding["scores"]["frontier_relevance"]=float(frontier); finding["scores"]["composite"]=float(non_triviality*actionability*frontier)
        passed=float(finding["scores"]["statistical_strength"])>=statistical_strength_min and robustness>=robustness_min; finding["state"]["pipeline"]="reportable" if passed else "candidate"
        score_rows.append({"finding_id":finding["finding_id"],"finding_key":finding["finding_key"],"lens":finding["lens"],"primary_q":_primary_q(finding),**finding["scores"],"passed_gate":passed})
    merge_duplicate_findings(result)
    ranked=sorted((item for item in result if item["state"]["pipeline"]=="reportable"),key=lambda item:(-float(item["scores"]["composite"]),_primary_q(item),item["finding_key"]))
    for rank,finding in enumerate(ranked,start=1): finding["scores"]["rank"]=rank
    score_by_key={row["finding_key"]:row for row in score_rows}
    for finding in result: score_by_key[finding["finding_key"]]["rank"]=finding["scores"]["rank"]; score_by_key[finding["finding_key"]]["pipeline_state"]=finding["state"]["pipeline"]; score_by_key[finding["finding_key"]]["merged_into"]=finding["merged_into"]
    gate={"statistical_strength_min":statistical_strength_min,"robustness_min":robustness_min,"display_k":display_k,"candidate_count":len(result),"gate_pass_count":sum(item["state"]["pipeline"] in {"reportable","merged"} for item in result),"reportable_count":len(ranked),"status":"succeeded" if len(ranked)>=display_k else "needs_design_review"}
    return ScoringResult(tuple(result),pd.DataFrame(score_rows).sort_values(["passed_gate","composite","finding_key"],ascending=[False,False,True]).reset_index(drop=True),gate)
