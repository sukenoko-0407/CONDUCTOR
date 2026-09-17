"""T01-T10 executors, deterministic state rules, and bounded tree traversal."""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdPartialCharges
from rdkit.Chem.Scaffolds import MurckoScaffold
from scipy import stats

from conductor_stat_core import benjamini_hochberg, block_bootstrap_indices, canonical_json, content_hash, derive_seed, empirical_p_value, permute_within_blocks, stable_id
from conductor_stat_core.models import TestRecord


TEMPLATES = tuple(f"T{index:02d}" for index in range(1, 11))
REQUIRED_PARAMETERS = {
    "T01": {"axis_id", "level"}, "T02": {"axis_id"}, "T03": {"context_ids"}, "T04": {"target_ids"},
    "T05": set(), "T06": {"context_id", "transformation_id"}, "T07": {"confounders"}, "T08": {"unit_type"},
    "T09": {"sample_n"}, "T10": {"counterexample_rule"},
}


@dataclass(frozen=True)
class ArtifactRegistry:
    observations: pd.DataFrame
    axes: pd.DataFrame
    candidates: pd.DataFrame
    contexts: pd.DataFrame
    random_seed: int = 20260916
    min_group_n: int = 3


@dataclass(frozen=True)
class DeepDiveResult:
    nodes: tuple[dict[str, Any], ...]
    summaries: tuple[dict[str, Any], ...]
    updated_findings: tuple[dict[str, Any], ...]
    logical_calls: int
    failed_logical_calls: int


def _effect_test(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if len(finite) < 2: return (float(np.mean(finite)) if len(finite) else 0.0), 1.0
    effect=float(np.mean(finite)); standard=float(np.std(finite,ddof=1))
    if standard <= 1e-12 * max(1.0, abs(effect)): return effect, 0.0 if effect!=0 else 1.0
    return effect,float(stats.ttest_1samp(finite,0.0).pvalue)


def _rows(parent: Mapping[str, Any], registry: ArtifactRegistry) -> pd.DataFrame:
    rows=registry.observations.loc[registry.observations["finding_key"].astype(str).eq(str(parent["finding_key"]))].copy()
    if rows.empty: raise ValueError("No observations registered for parent Finding")
    rows["effect"]=pd.to_numeric(rows["effect"],errors="coerce"); return rows.loc[np.isfinite(rows["effect"])].reset_index(drop=True)


def _lens_effect(parent:Mapping[str,Any],rows:pd.DataFrame)->tuple[float,np.ndarray]:
    """Replay the parent Lens effect on exactly the supplied observation subset."""
    lens=str(parent["lens"]); unit=str(parent["claim"]["effect_unit"]); elementary=pd.to_numeric(rows["effect"],errors="coerce").to_numpy(dtype=float)
    if lens=="L1b":
        required={"compound_id","neighbor_compound_ids_json","endpoint_value","global_variance"}
        if required-set(rows): raise ValueError("L1b observations lack replay fields")
        endpoint=dict(zip(rows["compound_id"].astype(str),pd.to_numeric(rows["endpoint_value"],errors="coerce"),strict=True)); errors=[]
        for row in rows.itertuples(index=False):
            source=getattr(row,"neighbor_order_compound_ids_json",row.neighbor_compound_ids_json); neighbor_k=int(getattr(row,"neighbor_k",len(json.loads(str(row.neighbor_compound_ids_json))))); neighbors=[str(value) for value in json.loads(str(source)) if str(value) in endpoint][:neighbor_k]
            if not neighbors: continue
            errors.append((endpoint[str(row.compound_id)]-float(np.mean([endpoint[value] for value in neighbors])))**2)
        variance=float(pd.to_numeric(rows["global_variance"],errors="coerce").iloc[0]); effect=float(1.0-np.mean(errors)/variance) if errors and variance>0 else 0.0
    elif lens=="L5":
        required={"context_role","feature_value","endpoint_value"}
        if required-set(rows): raise ValueError("L5 observations lack replay fields")
        correlations=[]
        for role in ("a","b"):
            group=rows.loc[rows["context_role"].astype(str).eq(role)]; x=pd.to_numeric(group["feature_value"],errors="coerce").to_numpy(dtype=float); y=pd.to_numeric(group["endpoint_value"],errors="coerce").to_numpy(dtype=float); finite=np.isfinite(x)&np.isfinite(y)
            if int(finite.sum())<3 or float(np.std(x[finite]))<=1e-12 or float(np.std(y[finite]))<=1e-12: raise ValueError("L5 subset cannot support both correlations")
            correlations.append(float(np.corrcoef(x[finite],y[finite])[0,1]))
        epsilon=np.finfo(float).eps; effect=float(np.arctanh(np.clip(correlations[0],-1+epsilon,1-epsilon))-np.arctanh(np.clip(correlations[1],-1+epsilon,1-epsilon)))
    elif lens=="L2a":
        if "comparison_group" not in rows: raise ValueError("L2a observations lack comparison_group")
        groups=rows["comparison_group"].astype(str).to_numpy(); inside=elementary[groups=="inside"]; outside=elementary[groups=="outside"]
        if len(inside)<2 or len(outside)<2: raise ValueError("L2a replay requires inside and outside pairs")
        if unit=="variance_reduction":
            variance=float(np.var(elementary,ddof=1)); effect=float(1.0-np.var(inside,ddof=1)/variance) if variance>0 else 0.0
        else: effect=float(np.median(inside)-np.median(outside))
    elif lens=="L2b":
        effect=float(np.var(elementary,ddof=1)) if unit=="oriented_endpoint_variance" else float(np.mean(elementary))
    elif lens=="L7":
        if unit=="spearman_rho":
            left=pd.to_numeric(rows["endpoint_left_value"],errors="coerce").to_numpy(dtype=float); right=pd.to_numeric(rows["endpoint_value"],errors="coerce").to_numpy(dtype=float)
            if len(left)<2 or float(np.std(left))<=1e-12 or float(np.std(right))<=1e-12: raise ValueError("L7 replay requires varying paired series")
            effect=float(stats.spearmanr(left,right).statistic)
        else: effect=float(np.mean(elementary))
    elif lens=="L4":
        required={"endpoint_value","density_gap","global_median"}
        if required-set(rows): raise ValueError("L4 observations lack neighborhood replay fields")
        lower_bounds=[]
        for _,group in rows.groupby(rows["block_id"].astype(str),sort=True):
            values=pd.to_numeric(group["endpoint_value"],errors="coerce").to_numpy(dtype=float);values=values[np.isfinite(values)]
            if len(values)<2:continue
            standard_error=float(np.std(values,ddof=1)/math.sqrt(len(values)));lower_bounds.append(float(np.mean(values)-stats.t.ppf(0.95,len(values)-1)*standard_error))
        if not lower_bounds:raise ValueError("L4 replay has fewer than two neighbors in every Description space")
        density=float(pd.to_numeric(rows["density_gap"],errors="coerce").min());effect=float(min(lower_bounds)*density)
    else: raise ValueError(f"No DeepDive replay adapter for Lens {lens}")
    return effect,elementary


def _residualize_response(values:np.ndarray,frame:pd.DataFrame,names:list[str])->tuple[np.ndarray,float]:
    columns=[]
    for name in names:
        if name not in frame: raise ValueError(f"Chemical axis is unavailable: {name}")
        numeric=pd.to_numeric(frame[name],errors="coerce"); finite=int(np.isfinite(numeric).sum())
        if finite>=2:
            array=numeric.to_numpy(dtype=float); median=float(np.nanmedian(array)); columns.append(np.where(np.isfinite(array),array,median))
        else:
            levels=sorted(set(frame[name].fillna("").astype(str))); columns.extend(frame[name].fillna("").astype(str).eq(level).to_numpy(dtype=float) for level in levels[1:])
    if not columns: raise ValueError("Requested confounders produce no design columns")
    design=np.column_stack([np.ones(len(values)),*columns]); fitted=design@np.linalg.lstsq(design,values,rcond=None)[0]; residual=values-fitted+float(np.mean(values)); explained=1.0-float(np.var(residual)/np.var(values)) if float(np.var(values))>0 else 0.0
    return residual,float(np.clip(explained,0.0,1.0))


def _nested_endpoint_residuals(rows:pd.DataFrame,axes:pd.DataFrame,fields:list[tuple[str,str]],confounders:list[str])->tuple[dict[str,float],float]:
    endpoint:dict[str,float]={}
    for row in rows.itertuples(index=False):
        for id_field,value_field in fields:
            identifier_groups=json.loads(str(getattr(row,id_field)));value_groups=json.loads(str(getattr(row,value_field)))
            if identifier_groups and isinstance(identifier_groups[0],str):identifier_groups=[identifier_groups];value_groups=[value_groups]
            for identifiers,values in zip(identifier_groups,value_groups,strict=True):
                for identifier,value in zip(identifiers,values,strict=True):
                    identifier=str(identifier);number=float(value)
                    if identifier in endpoint and not math.isclose(endpoint[identifier],number,rel_tol=1e-12,abs_tol=1e-15):raise ValueError(f"Conflicting Endpoint values for {identifier}")
                    endpoint[identifier]=number
    frame=pd.DataFrame({"compound_id":sorted(endpoint)});frame["endpoint_value"]=[endpoint[value] for value in frame["compound_id"]];joined=frame.merge(axes[["compound_id",*confounders]],on="compound_id",how="left",validate="one_to_one");adjusted,explained=_residualize_response(joined["endpoint_value"].to_numpy(dtype=float),joined,confounders);return dict(zip(joined["compound_id"].astype(str),adjusted,strict=True)),explained


def _predict_confounder_component(values:np.ndarray,training:pd.DataFrame,prediction:pd.DataFrame,names:list[str])->tuple[np.ndarray,np.ndarray]:
    train_columns=[np.ones(len(training))];prediction_columns=[np.ones(len(prediction))]
    for name in names:
        if name not in training or name not in prediction:raise ValueError(f"Chemical axis is unavailable: {name}")
        numeric=pd.to_numeric(training[name],errors="coerce")
        if int(np.isfinite(numeric).sum())>=2:
            left=numeric.to_numpy(dtype=float);median=float(np.nanmedian(left));train_columns.append(np.where(np.isfinite(left),left,median));right=pd.to_numeric(prediction[name],errors="coerce").to_numpy(dtype=float);prediction_columns.append(np.where(np.isfinite(right),right,median))
        else:
            levels=sorted(set(training[name].fillna("").astype(str)))
            for level in levels[1:]:train_columns.append(training[name].fillna("").astype(str).eq(level).to_numpy(dtype=float));prediction_columns.append(prediction[name].fillna("").astype(str).eq(level).to_numpy(dtype=float))
    design=np.column_stack(train_columns);target=np.column_stack(prediction_columns);coefficients=np.linalg.lstsq(design,values,rcond=None)[0];return design@coefficients,target@coefficients


def rerun_lens_effect(parent:Mapping[str,Any],rows:pd.DataFrame,axes:pd.DataFrame,confounders:list[str]|None=None)->tuple[float,float,dict[str,Any]]:
    """Lens-specific replay adapter used by T03, T04, T07, and T08."""
    replay=rows.copy(); explained=0.0
    if confounders:
        lens=str(parent["lens"]); axis=axes.copy(); axis["compound_id"]=axis["compound_id"].astype(str); lookup=axis.set_index("compound_id")
        if lens in {"L1b","L5"}:
            joined=replay.drop(columns=[name for name in confounders if name in replay]).merge(axis[["compound_id",*confounders]],on="compound_id",how="left",validate="many_to_one"); values=pd.to_numeric(joined["endpoint_value"],errors="coerce").to_numpy(dtype=float); adjusted,explained=_residualize_response(values,joined,confounders); replay=joined; replay["endpoint_value"]=adjusted
        elif lens=="L2a":
            designs=[]
            for row in replay.itertuples(index=False):
                left=lookup.loc[str(row.pair_from_compound_id)]; right=lookup.loc[str(row.pair_to_compound_id)]; material={}
                for name in confounders:
                    left_value=left[name]; right_value=right[name]
                    try: material[name]=float(right_value)-float(left_value)
                    except (TypeError,ValueError): material[name]=f"{left_value}->{right_value}"
                designs.append(material)
            adjusted,explained=_residualize_response(pd.to_numeric(replay["effect"],errors="coerce").to_numpy(dtype=float),pd.DataFrame(designs),confounders); replay["effect"]=adjusted
        elif lens=="L2b":
            residuals,explained=_nested_endpoint_residuals(replay,axis,[("series_fragments_compound_ids_json","series_fragments_endpoint_values_json")],confounders);adjusted=[]
            for row in replay.itertuples(index=False):
                subject=[str(value) for value in json.loads(str(row.subject_compound_ids_json))];fragments=[[str(value) for value in group] for group in json.loads(str(row.series_fragments_compound_ids_json))];adjusted.append(float(np.mean([residuals[value] for value in subject]))-float(np.mean([np.mean([residuals[value] for value in group]) for group in fragments])))
            replay["effect"]=adjusted
        elif lens=="L7":
            residuals,explained=_nested_endpoint_residuals(replay,axis,[("compound_ids_a_json","endpoint_values_a_json"),("compound_ids_b_json","endpoint_values_b_json")],confounders);left=[];right=[]
            for row in replay.itertuples(index=False):
                ids_a=[str(value) for value in json.loads(str(row.compound_ids_a_json))];ids_b=[str(value) for value in json.loads(str(row.compound_ids_b_json))];left.append(float(np.mean([residuals[value] for value in ids_a])));right.append(float(np.mean([residuals[value] for value in ids_b])))
            replay["endpoint_left_value"]=left;replay["endpoint_value"]=right;replay["effect"]=np.asarray(right)-np.asarray(left)
        elif lens=="L4":
            candidate_id=str(replay.iloc[0]["candidate_id"]);sources=[str(value) for value in parent["entities"].get("compound_ids",[])];required_ids=[candidate_id,*sources]
            if any(value not in lookup.index for value in required_ids):raise ValueError("L4 T07 requires candidate and source chemical axes")
            training=replay[["compound_id","endpoint_value"]].drop_duplicates("compound_id").merge(axis[["compound_id",*confounders]],on="compound_id",how="left",validate="one_to_one");prediction=axis.set_index("compound_id").loc[required_ids].reset_index();fitted,predicted=_predict_confounder_component(pd.to_numeric(training["endpoint_value"],errors="coerce").to_numpy(dtype=float),training,prediction,confounders);total=float(np.sum((pd.to_numeric(training["endpoint_value"],errors="coerce").to_numpy(dtype=float)-np.mean(pd.to_numeric(training["endpoint_value"],errors="coerce")))**2));residual=float(np.sum((pd.to_numeric(training["endpoint_value"],errors="coerce").to_numpy(dtype=float)-fitted)**2));explained=0.0 if total<=0 else float(np.clip(1.0-residual/total,0.0,1.0));raw,_=_lens_effect(parent,replay);density=float(pd.to_numeric(replay["density_gap"],errors="coerce").min());effect=float(raw-(predicted[0]-float(np.mean(predicted[1:])))*density);_,p_value=_effect_test(pd.to_numeric(replay["effect"],errors="coerce").to_numpy(dtype=float));return effect,p_value,{"explained_fraction":explained,"replay_method":"L4_candidate_source_confounder_delta"}
        else: raise ValueError(f"T07 is not testable for Lens {lens} with registered axes")
    effect,elementary=_lens_effect(parent,replay); _,p_value=_effect_test(elementary); return effect,p_value,{"explained_fraction":explained,"replay_method":f"{parent['lens']}_minimum_unit"}


def _hammett_assignment(molecule:Chem.Mol,scaffold_atoms:set[int],table:pd.DataFrame)->dict[str,Any]|None:
    """Return one unambiguous directly attached substituent at meta/para to the other attachment."""
    attachment_atoms=sorted({atom_index for atom_index in scaffold_atoms if any(neighbor.GetIdx() not in scaffold_atoms for neighbor in molecule.GetAtomWithIdx(atom_index).GetNeighbors())})
    if len(attachment_atoms)!=2:return None
    ring=None
    for candidate in molecule.GetRingInfo().AtomRings():
        if len(candidate)==6 and set(attachment_atoms).issubset(candidate) and all(molecule.GetAtomWithIdx(index).GetIsAromatic() for index in candidate):
            ring=set(candidate);break
    if ring is None:return None
    path=Chem.GetShortestPath(molecule,attachment_atoms[0],attachment_atoms[1])
    if not path or not set(path).issubset(ring):return None
    distance=len(path)-1
    position="meta" if distance==2 else "para" if distance==3 else None
    if position is None:return None
    matches=[]
    for record in table.itertuples(index=False):
        pattern=Chem.MolFromSmarts(str(record.smarts))
        if pattern is None:raise ValueError(f"Invalid Hammett SMARTS: {record.smarts}")
        for match in molecule.GetSubstructMatches(pattern,uniquify=True):
            matched=set(match)
            if not matched or not matched.isdisjoint(scaffold_atoms):continue
            attached={neighbor.GetIdx() for atom_index in matched for neighbor in molecule.GetAtomWithIdx(atom_index).GetNeighbors() if neighbor.GetIdx() in scaffold_atoms}
            if len(attached)==1 and next(iter(attached)) in attachment_atoms:
                matches.append((str(record.substituent),next(iter(attached)),float(getattr(record,f"sigma_{position}")),str(record.source),str(record.license)))
    unique=sorted(set(matches))
    if len(unique)!=1:return None
    substituent,attached,sigma,source,license_name=unique[0]
    other=attachment_atoms[0] if attached==attachment_atoms[1] else attachment_atoms[1]
    return {"hammett_substituent":substituent,"hammett_position":position,"hammett_sigma":sigma,"hammett_source":source,"hammett_license":license_name,"hammett_attachment_atom":attached,"hammett_reference_atom":other}


def build_chemical_axes(compounds: pd.DataFrame, hammett_path: Path | None = None) -> pd.DataFrame:
    hammett_version = "not_loaded"
    table=pd.DataFrame()
    if hammett_path is not None:
        table = pd.read_csv(hammett_path, sep="\t")
        required = {"version", "substituent", "smarts", "sigma_meta", "sigma_para", "source", "license"}
        if required - set(table):
            raise ValueError(f"Hammett table is missing columns: {sorted(required-set(table))}")
        if table.empty or table["version"].astype(str).nunique() != 1:
            raise ValueError("Hammett table requires one non-empty version")
        hammett_version = str(table.iloc[0]["version"])
    rows=[]
    for row in compounds.sort_values("compound_id").itertuples(index=False):
        molecule=Chem.MolFromSmiles(str(row.canonical_smiles))
        if molecule is None: continue
        scaffold=MurckoScaffold.GetScaffoldForMol(molecule); scaffold_key=Chem.MolToSmiles(scaffold,canonical=True) if scaffold.GetNumAtoms() else "acyclic";match=molecule.GetSubstructMatch(scaffold) if scaffold.GetNumAtoms() else ();scaffold_atoms=set(match)
        rdPartialCharges.ComputeGasteigerCharges(molecule); substituent_atoms=[atom for atom in molecule.GetAtoms() if atom.GetIdx() not in scaffold_atoms] or list(molecule.GetAtoms());charges=[float(atom.GetProp("_GasteigerCharge")) for atom in substituent_atoms if atom.HasProp("_GasteigerCharge") and math.isfinite(float(atom.GetProp("_GasteigerCharge")))]
        charge=float(np.sum(charges)) if charges else 0.0; attachment="none"
        if scaffold.GetNumAtoms():
            ranks=Chem.CanonicalRankAtoms(scaffold)
            attached=[match.index(atom.GetIdx()) for atom in molecule.GetAtoms() if atom.GetIdx() in scaffold_atoms and any(neighbor.GetIdx() not in scaffold_atoms for neighbor in atom.GetNeighbors())]
            if attached: attachment=f"{min(ranks[index] for index in attached)/max(1,len(ranks)-1):.6f}"
        hammett=_hammett_assignment(molecule,scaffold_atoms,table) if not table.empty and scaffold.GetNumAtoms() else None
        rows.append({"compound_id":str(row.compound_id),"scaffold_class":scaffold_key,"substituent_heavy_atoms":float(sum(atom.GetAtomicNum()>1 for atom in substituent_atoms)),"mw":float(Descriptors.MolWt(molecule)),"clogp":float(Crippen.MolLogP(molecule)),"tpsa":float(Descriptors.TPSA(molecule)),"hbd":float(Lipinski.NumHDonors(molecule)),"hba":float(Lipinski.NumHAcceptors(molecule)),"has_ring":"yes" if molecule.GetRingInfo().NumRings()>0 else "no","stereochemistry":"present" if Chem.FindMolChiralCenters(molecule,includeUnassigned=True) else "absent","gasteiger_fragment_charge":charge,"electronic_effect_source":f"hammett_{hammett['hammett_position']}" if hammett else "gasteiger_fallback","hammett_version":hammett_version,"hammett_substituent":hammett["hammett_substituent"] if hammett else "","hammett_position":hammett["hammett_position"] if hammett else "","hammett_sigma":hammett["hammett_sigma"] if hammett else math.nan,"hammett_source":hammett["hammett_source"] if hammett else "","hammett_license":hammett["hammett_license"] if hammett else "","attachment_position":attachment})
    result=pd.DataFrame(rows)
    if result.empty:return result
    charges=result["gasteiger_fragment_charge"].to_numpy(dtype=float);median=float(np.median(charges));mad=float(np.median(np.abs(charges-median)));scale=1.4826*mad
    z=np.zeros(len(charges),dtype=float) if scale<=np.finfo(float).eps else (charges-median)/scale
    result["electronic_effect_z"]=z
    hammett_mask=np.isfinite(pd.to_numeric(result["hammett_sigma"],errors="coerce")); sigma=pd.to_numeric(result["hammett_sigma"],errors="coerce").to_numpy(dtype=float)
    fallback=np.where(z>=0.5,"EWG",np.where(z<=-0.5,"EDG","neutral")); hammett_class=np.where(sigma>0,"EWG",np.where(sigma<0,"EDG","neutral"))
    result["electronic_effect_value"]=np.where(hammett_mask,sigma,z);result["electronic_effect"]=np.where(hammett_mask,hammett_class,fallback)
    return result


def _validate_parameters(template_id: str, parameters: Mapping[str, Any]) -> None:
    if template_id not in REQUIRED_PARAMETERS: raise ValueError(f"Unknown template_id: {template_id}")
    missing=REQUIRED_PARAMETERS[template_id]-set(parameters)
    if missing: raise ValueError(f"{template_id} is missing parameters: {sorted(missing)}")
    if template_id in {"T03","T04"}:
        key="context_ids" if template_id=="T03" else "target_ids"; values=parameters[key]
        if not isinstance(values,list) or not 1<=len(values)<=3: raise ValueError(f"{key} must contain one to three IDs")


def _base_result(template_id: str, parameters: Mapping[str, Any], status: str, reason: str, **values: Any) -> dict[str, Any]:
    return {"template_id":template_id,"parameter_hash":content_hash(parameters),"execution_status":status,"family_key":values.pop("family_key",f"{template_id}|global"),"primary_n":int(values.pop("primary_n",0)),"comparator_n":int(values.pop("comparator_n",0)),"parent_effect":float(values.pop("parent_effect",0.0)),"child_effect":values.pop("child_effect",None),"effect_direction":values.pop("effect_direction","flat"),"p_value":values.pop("p_value",None),"q_value":values.pop("q_value",None),"statistics":values,"reason":reason}


def execute_template(template_id: str,parent_finding: Mapping[str,Any],parameter_object: Mapping[str,Any],artifact_registry: ArtifactRegistry) -> dict[str,Any]:
    _validate_parameters(template_id,parameter_object); rows=_rows(parent_finding,artifact_registry); effects=rows["effect"].to_numpy(dtype=float); parent_effect=float(parent_finding["claim"]["effect_size"]); minimum=artifact_registry.min_group_n
    def finished(effect: float,p_value: float,*,primary_n:int=len(rows),comparator_n:int=0,**extra:Any)->dict[str,Any]:
        direction="positive" if effect>0 else "negative" if effect<0 else "flat"; return _base_result(template_id,parameter_object,"completed","completed",primary_n=primary_n,comparator_n=comparator_n,parent_effect=parent_effect,child_effect=float(effect),effect_direction=direction,p_value=float(p_value),q_value=float(p_value),**extra)
    if template_id=="T01":
        axis=str(parameter_object["axis_id"]); level=str(parameter_object["level"])
        if axis not in artifact_registry.axes: return _base_result(template_id,parameter_object,"not_testable","unknown axis",parent_effect=parent_effect)
        joined=rows.merge(artifact_registry.axes[["compound_id",axis]],on="compound_id",how="left"); mask=joined[axis].astype(str).eq(level); left=joined.loc[mask,"effect"].to_numpy(dtype=float); right=joined.loc[~mask,"effect"].to_numpy(dtype=float)
        if len(left)<minimum or len(right)<minimum:return _base_result(template_id,parameter_object,"not_testable","minimum group n not met",primary_n=len(left),comparator_n=len(right),parent_effect=parent_effect)
        left_effect,left_p=_effect_test(left);right_effect,right_p=_effect_test(right);tests=benjamini_hochberg([TestRecord("primary","T01A",f"{parent_finding['finding_id']}|T01|{axis}",left_effect,"two_sided_abs",left_p),TestRecord("comparator","T01B",f"{parent_finding['finding_id']}|T01|{axis}",right_effect,"two_sided_abs",right_p)])
        result=finished(left_effect,float(tests[0].q_value),primary_n=len(left),comparator_n=len(right),family_key=f"{parent_finding['finding_id']}|T01|{axis}",comparator_effect=right_effect,comparator_p=right_p,comparator_q=tests[1].q_value,effect_ratio=abs(left_effect/parent_effect) if parent_effect else None,axis_id=axis,level=level);return result
    if template_id=="T02":
        axis=str(parameter_object["axis_id"])
        if axis not in artifact_registry.axes:return _base_result(template_id,parameter_object,"not_testable","unknown axis",parent_effect=parent_effect)
        joined=rows.merge(artifact_registry.axes[["compound_id",axis]],on="compound_id",how="left");levels=sorted(value for value in joined[axis].dropna().unique())
        groups=[joined.loc[joined[axis].eq(level),"effect"].to_numpy(dtype=float) for level in levels]
        if "block_id" not in joined:return _base_result(template_id,parameter_object,"not_testable","observations lack block_id",parent_effect=parent_effect)
        if len(levels)<3 or any(len(group)<3 for group in groups):return _base_result(template_id,parameter_object,"not_testable","requires three ordered levels with n>=3",parent_effect=parent_effect)
        medians=np.asarray([np.median(group) for group in groups]);rho=float(stats.spearmanr(np.arange(len(levels)),medians).statistic);null=[]
        participation=[]
        for iteration in range(1000):
            rng=np.random.default_rng(derive_seed(artifact_registry.random_seed,f"T02|{axis}",iteration));permuted,fraction=permute_within_blocks(joined["effect"].to_numpy(dtype=float),joined["block_id"].tolist(),rng);participation.append(fraction);null_medians=np.asarray([np.median(permuted[joined[axis].eq(level).to_numpy()]) for level in levels]);null.append(float(stats.spearmanr(np.arange(len(levels)),null_medians).statistic))
        return finished(rho,empirical_p_value(rho,null,"two_sided_abs"),primary_n=len(joined),axis_id=axis,levels=[str(value) for value in levels],level_medians=medians.tolist(),permutation_participation=float(np.mean(participation)))
    if template_id in {"T03","T04"}:
        column="context_id" if template_id=="T03" else "target_id"; identifiers=[str(value) for value in parameter_object["context_ids" if template_id=="T03" else "target_ids"]]
        if column not in rows:return _base_result(template_id,parameter_object,"not_testable",f"observations lack {column}",parent_effect=parent_effect)
        selected=rows.loc[rows[column].astype(str).isin(identifiers)].reset_index(drop=True)
        if len(selected)<minimum:return _base_result(template_id,parameter_object,"not_testable","minimum n not met",primary_n=len(selected),parent_effect=parent_effect)
        try: effect,p_value,replay=rerun_lens_effect(parent_finding,selected,artifact_registry.axes)
        except ValueError as exc:return _base_result(template_id,parameter_object,"not_testable",str(exc),primary_n=len(selected),parent_effect=parent_effect)
        return finished(effect,p_value,primary_n=len(selected),selected_ids=identifiers,**replay)
    if template_id=="T05":
        iterations=int(parameter_object.get("iterations",500));blocks=rows["block_id"].fillna("").astype(str).tolist();sampled=[]
        for sample in block_bootstrap_indices(blocks,iterations,artifact_registry.random_seed):sampled.append(float(np.mean(effects[sample.indices])))
        low,high=np.quantile(sampled,[0.025,0.975]);median=float(np.median(sampled));return finished(median,1.0,primary_n=len(rows),ci_low=float(low),ci_high=float(high),sign_match_rate=float(np.mean(np.sign(sampled)==np.sign(parent_effect))),iterations=iterations)
    if template_id=="T06":
        context_id=str(parameter_object["context_id"]);transformation_id=str(parameter_object["transformation_id"]);candidates=artifact_registry.candidates
        required={"context_id","transformation_id","validation_status"}
        if required-set(candidates):return _base_result(template_id,parameter_object,"not_testable",f"candidate registry lacks {sorted(required-set(candidates))}",parent_effect=parent_effect)
        selected=candidates.loc[candidates["context_id"].astype(str).eq(context_id)&candidates["transformation_id"].astype(str).eq(transformation_id)]
        valid=selected.loc[selected["validation_status"].astype(str).eq("valid")]
        return finished(float(len(valid)),1.0,primary_n=len(valid),candidate_row_ids=valid.get("row_id",pd.Series(dtype=str)).astype(str).tolist(),context_id=context_id,transformation_id=transformation_id)
    if template_id=="T07":
        confounders=[str(value) for value in parameter_object["confounders"]]
        if not confounders:return _base_result(template_id,parameter_object,"not_testable","no requested confounders",parent_effect=parent_effect)
        try: effect,p_value,replay=rerun_lens_effect(parent_finding,rows,artifact_registry.axes,confounders)
        except (KeyError,ValueError) as exc:return _base_result(template_id,parameter_object,"not_testable",str(exc),primary_n=len(rows),parent_effect=parent_effect)
        return finished(effect,p_value,primary_n=len(rows),confounders=confounders,**replay)
    if template_id=="T08":
        if len(effects)<=minimum:return _base_result(template_id,parameter_object,"not_testable","minimum n not met after deletion",primary_n=len(effects),parent_effect=parent_effect)
        try: full,_,_=rerun_lens_effect(parent_finding,rows,artifact_registry.axes);changes=[]
        except ValueError as exc:return _base_result(template_id,parameter_object,"not_testable",str(exc),primary_n=len(rows),parent_effect=parent_effect)
        for index in range(len(rows)):
            reduced=rows.drop(index=rows.index[index]).reset_index(drop=True)
            try: effect,p_value,replay=rerun_lens_effect(parent_finding,reduced,artifact_registry.axes)
            except ValueError: continue
            changes.append((abs(effect-full),index,effect,p_value,replay))
        if not changes:return _base_result(template_id,parameter_object,"not_testable","no valid Lens replay after deletion",primary_n=len(rows),parent_effect=parent_effect)
        _,index,effect,p_value,replay=max(changes,key=lambda value:(value[0],-value[1]));return finished(effect,p_value,primary_n=len(rows)-1,influential_row_id=str(rows.iloc[index]["row_id"]),effect_change=float(effect-full),unit_type=str(parameter_object["unit_type"]),**replay)
    if template_id=="T09":
        sample_n=int(parameter_object["sample_n"]);iterations=int(parameter_object.get("iterations",1000))
        if sample_n<minimum or sample_n>len(rows):return _base_result(template_id,parameter_object,"not_testable","invalid sample_n",primary_n=len(rows),parent_effect=parent_effect)
        if "block_id" not in rows:return _base_result(template_id,parameter_object,"not_testable","observations lack block_id",primary_n=len(rows),parent_effect=parent_effect)
        block_indices=[group.index.to_numpy(dtype=int) for _,group in rows.groupby(rows["block_id"].fillna("").astype(str),sort=True)]
        null=[]
        for iteration in range(iterations):
            rng=np.random.default_rng(derive_seed(artifact_registry.random_seed,f"{parent_finding['finding_key']}|T09",iteration))
            # Randomized subset-sum selects whole blocks only; rows from a block are never split.
            choices:dict[int,tuple[int,...]]={0:()}
            for block_index in rng.permutation(len(block_indices)):
                size=len(block_indices[int(block_index)])
                for total,selected_blocks in list(choices.items())[::-1]:
                    new_total=total+size
                    if new_total<=sample_n and new_total not in choices:choices[new_total]=selected_blocks+(int(block_index),)
            if sample_n not in choices:continue
            indices=np.concatenate([block_indices[index] for index in choices[sample_n]])
            null.append(float(np.mean(effects[indices])))
        participation=float(len(null)/iterations) if iterations else 0.0
        if not null:return _base_result(template_id,parameter_object,"not_testable","no whole-block sample matches sample_n",primary_n=len(rows),parent_effect=parent_effect,participation=participation,iterations=iterations)
        observed=float(np.mean(effects));return finished(observed,empirical_p_value(observed,null,"two_sided_abs"),primary_n=sample_n,null_q05=float(np.quantile(null,0.05)),null_q95=float(np.quantile(null,0.95)),iterations=iterations,participation=participation)
    if template_id=="T10":
        parent_sign=np.sign(parent_effect);counter=rows.loc[np.sign(rows["effect"])!=parent_sign];success=int(len(rows)-len(counter));p_value=float(stats.binomtest(success,len(rows),0.5,alternative="two-sided").pvalue) if len(rows) else 1.0;effect=float((success-len(counter))/len(rows)) if len(rows) else 0.0;return finished(effect,p_value,primary_n=len(rows),counterexample_row_ids=counter["row_id"].astype(str).tolist(),counterexample_rate=float(len(counter)/len(rows)),counterexample_rule=str(parameter_object["counterexample_rule"]))
    raise AssertionError(template_id)


def judge_state(template_id: str,result: Mapping[str,Any],parent_effect: float) -> str:
    if result["execution_status"]!="completed":return "INCONCLUSIVE"
    if template_id=="T06":return "SURVIVED" if int(result["primary_n"])>0 else "INCONCLUSIVE"
    if template_id=="T05":
        low=float(result["statistics"]["ci_low"]);high=float(result["statistics"]["ci_high"])
        if low>0 and parent_effect>0 or high<0 and parent_effect<0:return "SURVIVED"
        if low>0 and parent_effect<0 or high<0 and parent_effect>0:return "REFUTED"
        return "INCONCLUSIVE"
    effect=result.get("child_effect");q_value=result.get("q_value")
    if template_id=="T01" and effect is not None:
        comparator=float(result["statistics"].get("comparator_effect",0.0));comparator_q=float(result["statistics"].get("comparator_q",1.0));same=np.sign(effect)==np.sign(parent_effect)
        if q_value is not None and float(q_value)<=0.05 and same and (comparator_q>0.05 or abs(comparator)<0.5*abs(parent_effect)):return "WEAKENED"
    if q_value is not None and float(q_value)<=0.05:
        return "SURVIVED" if np.sign(float(effect))==np.sign(parent_effect) else "REFUTED"
    return "INCONCLUSIVE"


def run_deep_dive(findings:list[dict[str,Any]],registry:ArtifactRegistry,selector:Callable[[dict[str,Any],list[str],list[dict[str,Any]]],list[dict[str,Any]]],summarizer:Callable[[dict[str,Any],list[dict[str,Any]]],dict[str,Any]]|None=None,*,max_depth:int=3,max_children:int=3,max_tests_per_finding:int=15,stop_after_consecutive_inconclusive:int=2)->DeepDiveResult:
    nodes=[];summaries=[];updated=[];logical_calls=0;failed_calls=0
    for source in findings:
        finding=json.loads(json.dumps(source));root_id=stable_id("DDROOT",{"finding":finding["finding_id"]});root={"node_id":root_id,"parent_node_id":None,"finding_id":finding["finding_id"],"depth":0,"template_id":"ROOT","parameters":{},"parameter_hash":content_hash({}),"execution_status":"not_run","state":"not_dived","result":None,"citations":[]};tree=[root];queue=deque([(root,[],0)]);budget=0
        while queue and budget<max_tests_per_finding:
            parent,path,inconclusive=queue.popleft();allowed=list(TEMPLATES)
            try:selections=selector(finding,allowed,tree);logical_calls+=1
            except Exception:selections=[];logical_calls+=1;failed_calls+=1
            if not isinstance(selections,list):selections=[];failed_calls+=1
            for selection in selections[:max_children]:
                if budget>=max_tests_per_finding:break
                budget+=1;template_id=str(selection.get("template_id",""));parameters=selection.get("parameters",{});signature=f"{template_id}|{canonical_json(parameters)}"
                if signature in path:continue
                try:result=execute_template(template_id,finding,parameters,registry);state=judge_state(template_id,result,float(finding["claim"]["effect_size"]));status=result["execution_status"]
                except Exception as exc:result=_base_result(template_id if template_id in TEMPLATES else "T01",parameters,"failed",str(exc),parent_effect=float(finding["claim"]["effect_size"]));state="INCONCLUSIVE";status="failed"
                node_id=stable_id("DD",{"parent":parent["node_id"],"template":template_id,"parameters":parameters});node={"node_id":node_id,"parent_node_id":parent["node_id"],"finding_id":finding["finding_id"],"depth":parent["depth"]+1,"template_id":template_id,"parameters":parameters,"parameter_hash":content_hash(parameters),"execution_status":status,"state":state,"result":result,"citations":[]};tree.append(node)
                next_inconclusive=inconclusive+1 if state=="INCONCLUSIVE" else 0
                if state in {"SURVIVED","WEAKENED"} and node["depth"]<max_depth and next_inconclusive<stop_after_consecutive_inconclusive:queue.append((node,path+[signature],next_inconclusive))
        final_states=[node["state"] for node in tree[1:]];finding["state"]["deep_dive"]="REFUTED" if "REFUTED" in final_states else "WEAKENED" if "WEAKENED" in final_states else "SURVIVED" if "SURVIVED" in final_states else "INCONCLUSIVE"
        if finding["state"]["deep_dive"]=="REFUTED":finding["state"]["pipeline"]="refuted"
        if summarizer is not None:
            try:summary=summarizer(finding,tree);logical_calls+=1
            except Exception:summary={"narrative":None,"citations":[]};logical_calls+=1;failed_calls+=1
        else:summary={"narrative":None,"citations":[]}
        finding["narrative"] = summary.get("narrative")
        summaries.append({"finding_id":finding["finding_id"],**summary});nodes.extend(tree);updated.append(finding)
    return DeepDiveResult(tuple(nodes),tuple(summaries),tuple(updated),logical_calls,failed_calls)
