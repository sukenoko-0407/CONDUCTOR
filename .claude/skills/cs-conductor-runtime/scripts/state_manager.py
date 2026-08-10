from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import sys
import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


VERSION="0.1.0"; STATE_SCHEMA="2.0.0"; BRIEF_SCHEMA="2.0.0"; SUMMARY_SCHEMA="2.0.0"
NODE_INFO={"description":("description_node","ND"),"clustering":("clustering_node","NC"),"analysis":("analysis_node","NA"),"interpretation":("interpretation_node","NI")}
TERMINAL={"succeeded","failed","unavailable","not_applicable","skipped","waived"}; MAX_BRIEF_BYTES=50*1024; MAX_CANDIDATES=20


def utc_now()->str:return datetime.now(timezone.utc).isoformat()
def stamp()->str:return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
def sha_file(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()
def value_hash(value:Any)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":")).encode()).hexdigest()
def read_json(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding="utf-8"))
def read_jsonl(path:Path)->list[dict[str,Any]]:
    if not path.is_file():return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def atomic_text(path:Path,text:str)->None:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+f".{os.getpid()}.tmp");tmp.write_text(text,encoding="utf-8");os.replace(tmp,path)
def write_json(path:Path,value:Any)->None:atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2,default=str)+"\n")
def write_jsonl(path:Path,rows:Iterable[dict[str,Any]])->None:atomic_text(path,"".join(json.dumps(row,ensure_ascii=False,default=str)+"\n" for row in rows))
def append_jsonl(path:Path,row:dict[str,Any])->None:
    rows=read_jsonl(path);rows.append(row);write_jsonl(path,rows)
def read_csv(path:Path)->list[dict[str,str]]:
    if not path.is_file():return []
    with path.open(encoding="utf-8-sig",newline="") as handle:return list(csv.DictReader(handle))
def write_csv(path:Path,fields:list[str],rows:Iterable[dict[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+f".{os.getpid()}.tmp")
    with tmp.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)
    os.replace(tmp,path)


def workspace()->Path:
    for root in [Path(__file__).resolve(),*Path(__file__).resolve().parents,Path.cwd(),*Path.cwd().parents]:
        if (root/"CONDUCTOR_modules"/"catalog"/"catalog.json").is_file():return root
    raise FileNotFoundError("CONDUCTOR_modules/catalog/catalog.json not found")
def validate(value:dict[str,Any],schema:str)->None:
    import jsonschema
    jsonschema.validate(value,read_json(workspace()/"CONDUCTOR_modules"/"schemas"/schema))
def catalog()->dict[str,dict[str,Any]]:
    value=read_json(workspace()/"CONDUCTOR_modules"/"catalog"/"catalog.json")
    if value.get("conductor_version")!=VERSION:raise ValueError("Catalog version does not match Runtime")
    return {item["capability_id"]:item for item in value["capabilities"]}
def profile()->dict[str,Any]:
    value=read_json(workspace()/"CONDUCTOR_modules"/"catalog"/"analysis_profile.json")
    if value.get("schema_version")!="2.0.0":raise ValueError("Analysis profile schema_version must be 2.0.0")
    return value


@contextmanager
def lock(path:Path,timeout:float=30)->Iterator[None]:
    target=path.with_suffix(path.suffix+".lock");deadline=time.time()+timeout;fd=None
    while fd is None:
        try:fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,f"{os.getpid()} {utc_now()}".encode())
        except FileExistsError:
            if time.time()>deadline:raise TimeoutError(f"State lock timeout: {target}")
            time.sleep(.05)
    try:yield
    finally:
        if fd is not None:os.close(fd)
        target.unlink(missing_ok=True)


def token_hash(token:str)->str:return hashlib.sha256(token.encode()).hexdigest()
def parse_time(value:str|None)->datetime|None:
    if not value:return None
    return datetime.fromisoformat(value.replace("Z","+00:00"))
def lease_live(state:dict[str,Any])->bool:
    lease=state["orchestration_control"]["lease"];expires=parse_time(lease.get("expires_at"));return bool(lease.get("token_hash") and expires and expires>datetime.now(timezone.utc))
def require_writer(state:dict[str,Any],a:argparse.Namespace)->None:
    lease=state["orchestration_control"]["lease"]
    if not lease_live(state):raise PermissionError("No live Orchestrator lease")
    if not getattr(a,"lease_token",None) or token_hash(a.lease_token)!=lease.get("token_hash"):raise PermissionError("Lease token does not own this Run")
def touch_lease(state:dict[str,Any])->None:
    lease=state["orchestration_control"]["lease"];minutes=int(lease.get("duration_minutes") or 30);now=datetime.now(timezone.utc);lease["heartbeat_at"]=now.isoformat();lease["expires_at"]=(now+timedelta(minutes=minutes)).isoformat()


def nodes(state:dict[str,Any])->dict[str,dict[str,Any]]:return {item["node_id"]:item for item in state["execution_graph"]["nodes"]}
def active_round(state:dict[str,Any],required:bool=True)->dict[str,Any]|None:
    rid=state["round_control"].get("active_round_id");item=next((r for r in state["round_control"]["rounds"] if r["round_id"]==rid),None)
    if required and item is None:raise ValueError("No active Round")
    return item
def execution_round(node:dict[str,Any])->str|None:
    """Return the Round that currently owns execution of a stable Node."""
    value=node.get("execution_round_id")
    if value:return str(value)
    return None if node.get("status")=="deferred" else node.get("round_id")
def history(state:dict[str,Any],action:str,**details:Any)->None:state.setdefault("history",[]).append({"at":utc_now(),"action":action,**details})
def allocate(state:dict[str,Any],entity:str)->str:
    state["counters"][entity]+=1
    if entity in {v[0] for v in NODE_INFO.values()}:
        prefix=next(prefix for _,(key,prefix) in NODE_INFO.items() if key==entity);return f"{prefix}{state['counters'][entity]:06d}"
    prefix={"cluster":"CL","insight":"INS","action":"ACT"}[entity];width=6 if entity=="cluster" else 4;return f"{prefix}{state['counters'][entity]:0{width}d}"
def signature(capability_id:str,deps:list[str],params:dict[str,Any],role:str="")->str:return value_hash({"capability_id":capability_id,"dependencies":sorted(deps),"parameters":params,"role":role})


def validate_dag(state:dict[str,Any])->None:
    lookup=nodes(state);degree={key:0 for key in lookup};adj=defaultdict(list)
    for edge in state["execution_graph"]["edges"]:
        if edge["source"] not in lookup or edge["target"] not in lookup:raise ValueError("DAG edge references unknown Node")
        adj[edge["source"]].append(edge["target"]);degree[edge["target"]]+=1
    queue=deque(k for k,v in degree.items() if v==0);seen=0
    while queue:
        source=queue.popleft();seen+=1
        for target in adj[source]:
            degree[target]-=1
            if degree[target]==0:queue.append(target)
    if seen!=len(lookup):raise ValueError("Execution graph contains a cycle")
def validate_state(state:dict[str,Any])->None:
    if state.get("schema_version")!=STATE_SCHEMA or state.get("conductor_version")!=VERSION:raise ValueError("This Runtime accepts only CONDUCTOR 0.1.0 State schema 2.0.0")
    validate_dag(state);validate(state,"state.schema.json")


def index_paths(root:Path)->dict[str,Any]:
    return {
        "coverage":{"path":str((root/"indices"/"coverage.json").resolve())},
        "operator_results":{"path":str((root/"indices"/"operator_results.jsonl").resolve()),"count":0},
        "insights":{"path":str((root/"indices"/"insight_ledger.jsonl").resolve()),"count":0},
        "next_actions":{"path":str((root/"indices"/"next_action_ledger.jsonl").resolve()),"count":0},
        "clusters":{"registry_path":str((root/"clusters"/"cluster_registry.csv").resolve()),"matrix_paths":[],"cluster_count":0},
    }
def latest(rows:list[dict[str,Any]],key:str)->dict[str,dict[str,Any]]:
    result={}
    for row in rows:
        identity=row[key]
        if identity not in result or int(row.get("revision",1))>=int(result[identity].get("revision",1)):result[identity]=row
    return result


def round_time(state:dict[str,Any])->dict[str,Any]:
    item=active_round(state,False)
    if not item:return {"status":"no_active_round","remaining_minutes":0,"reserve_minutes":0}
    deadline=parse_time(item["execution_control"].get("deadline_at"));remaining=(deadline-datetime.now(timezone.utc)).total_seconds()/60 if deadline else 10**9;reserve=int(item["execution_control"].get("interpretation_reserve_minutes",30));status="available" if remaining>reserve else "interpretation_reserve" if remaining>0 else "expired"
    return {"status":status,"remaining_minutes":max(0,round(remaining,2)),"reserve_minutes":reserve,"deadline_at":item["execution_control"].get("deadline_at")}
def phase_terminal(state:dict[str,Any],phase:str)->bool:
    item=active_round(state,False)
    if not item:return False
    relevant=[n for n in state["execution_graph"]["nodes"] if n["phase"]==phase and execution_round(n)==item["round_id"]]
    # Planning has already resolved successful historic signatures.  An empty
    # current-Round set therefore means that there is nothing left to execute.
    return all(n["status"] in TERMINAL|{"deferred"} for n in relevant)
def node_error(state:dict[str,Any],node:dict[str,Any])->str|None:
    item=active_round(state,False)
    if not item or execution_round(node)!=item["round_id"]:return "Node is not assigned to the active Round"
    if node.get("human_approval") in {"required","bundle_pending"}:return "human approval required"
    lookup=nodes(state)
    for dep in node["dependencies"]:
        if lookup[dep]["status"]!="succeeded":return f"dependency {dep} is {lookup[dep]['status']}"
    if node["stage"]!="interpretation" and round_time(state)["status"] in {"interpretation_reserve","expired"}:return "Interpretation reserve"
    return None
def runnable(state:dict[str,Any])->list[dict[str,Any]]:
    running=sum(n["status"]=="running" for n in state["execution_graph"]["nodes"]);limit=max(0,int(state["run"]["parallel_limit"])-running)
    order={"basic_compute":0,"initial_global":1,"initial_local":2,"additional_exploration":3,"deep_dive":4,"human_directed":5};stages={"description":0,"clustering":1,"analysis":2,"interpretation":3}
    rows=[n for n in state["execution_graph"]["nodes"] if n["status"] in {"pending","stale"} and node_error(state,n) is None];rows.sort(key=lambda n:(order[n["phase"]],stages[n["stage"]],n["node_id"]));return rows[:limit]


def primary(node:dict[str,Any],cap:dict[str,Any])->Path:
    attempts=[a for a in node.get("execution_attempts",[]) if a.get("status")=="succeeded"]
    base=Path(node["output_dir"])/"attempts"/(attempts[-1]["attempt_id"] if attempts else "")
    if node["stage"]=="description":return base/f"{cap['output']['basename']}.csv"
    if node["stage"]=="clustering":return Path(node.get("promoted_membership_path") or base/"cluster_membership.csv")
    if node["stage"]=="analysis":return base/cap["output"]["filename"]
    return base/"interpretation.json"
def promoted_manifest(node:dict[str,Any],name:str)->Path:
    attempts=[a for a in node.get("execution_attempts",[]) if a.get("status")=="succeeded"]
    return Path(node["output_dir"])/"attempts"/attempts[-1]["attempt_id"]/name


def add_node(state:dict[str,Any],caps:dict[str,dict[str,Any]],capability_id:str,deps:list[str],phase:str,reason:str,parameters:dict[str,Any]|None=None)->tuple[dict[str,Any],bool]:
    cap=caps[capability_id];params={**(cap.get("default_parameters") or {}),**(parameters or {})};role=str(params.get("role") or params.get("scope_mode") or "");sig=signature(capability_id,deps,params,role);rid=active_round(state)["round_id"]
    existing=next((n for n in state["execution_graph"]["nodes"] if n["analysis_signature"]==sig and n["status"]!="stale"),None)
    if existing:
        if existing["status"]=="deferred":
            existing.update({"status":"pending","execution_round_id":rid,"phase":phase,"current_attempt_id":None})
            existing.setdefault("reactivations",[]).append({"round_id":rid,"at":utc_now(),"reason":reason});return existing,True
        return existing,False
    stage=cap["stage"];key,_=NODE_INFO[stage];node_id=allocate(state,key);root=Path(state["run"]["run_root"])
    node={"node_id":node_id,"stage":stage,"capability_id":capability_id,"skill_name":cap["skill_name"],"round_id":rid,"requested_round_id":rid,"execution_round_id":rid,"phase":phase,"dependencies":list(dict.fromkeys(deps)),"parameters":params,"analysis_signature":sig,"selection_basis":{"reason":reason,"source":"human" if phase=="human_directed" else "runtime"},"status":"pending","human_approval":"bundle_pending" if cap.get("cost",{}).get("human_approval_required") and phase=="basic_compute" else "not_required","execution_attempts":[],"current_attempt_id":None,"output_dir":str((root/stage/cap["skill_name"]/node_id).resolve()),"created_at":utc_now()}
    state["execution_graph"]["nodes"].append(node);state["execution_graph"]["edges"].extend({"source":dep,"target":node_id} for dep in node["dependencies"]);return node,True


def succeeded(state:dict[str,Any],stage:str,ids:Iterable[str]|None=None)->list[dict[str,Any]]:
    accepted=set(ids or []);return [n for n in state["execution_graph"]["nodes"] if n["stage"]==stage and n["status"]=="succeeded" and (not accepted or n["capability_id"] in accepted)]
def dependency_sets(cap:dict[str,Any],descs:list[dict[str,Any]],clusters:list[dict[str,Any]],scope:str)->list[list[str]]:
    deps=cap.get("dependencies") or []
    if cap["capability_id"]=="A005":return []
    if deps==["description"]:return [[d["node_id"]] for d in descs]
    if deps==["clustering"]:return [[c["node_id"]] for c in clusters]
    if set(deps)=={"description","clustering"}:return [[d["node_id"],c["node_id"]] for d in descs for c in clusters]
    return [[]]


def plan_basic(state:dict[str,Any])->list[str]:
    caps=catalog();p=profile();planned=[];basic=p["basic_compute"]
    description_ids=basic.get("description_capabilities") or [k for k,v in caps.items() if v["stage"]=="description"]
    for cid in description_ids:
        node,created=add_node(state,caps,cid,[],"basic_compute",f"基本計算として{cid}を生成する。")
        if created:planned.append(node["node_id"])
    for cid in basic.get("direct_structure_clustering",[]):
        node,created=add_node(state,caps,cid,[],"basic_compute",f"構造Clustering {cid}を実行する。")
        if created:planned.append(node["node_id"])
    desc_lookup={n["capability_id"]:n for n in state["execution_graph"]["nodes"] if n["stage"]=="description"}
    for cid in basic.get("vector_clustering_capabilities",[]):
        for did in basic.get("vector_clustering_representations",[]):
            if did in desc_lookup:
                node,created=add_node(state,caps,cid,[desc_lookup[did]["node_id"]],"basic_compute",f"{did}上でVector Clustering {cid}を実行する。",{"input_representation":did})
                if created:planned.append(node["node_id"])
    item=active_round(state);item["plans"]["basic_compute"]=True;history(state,"basic_planned",planned_count=len(planned));return planned


def plan_initial_global(state:dict[str,Any])->list[str]:
    caps=catalog();p=profile();master=p["initial_exploration"]["description_master_panel"];descs=succeeded(state,"description",master);clusters=succeeded(state,"clustering");planned=[]
    for aid in p["initial_exploration"]["global_operator_capabilities"]:
        cap=caps[aid]
        if aid=="A005":
            panel=cap["fixed_description_panel"];lookup={n["capability_id"]:n for n in succeeded(state,"description")}
            if all(cid in lookup for cid in panel):
                deps=[lookup[cid]["node_id"] for cid in panel];node,created=add_node(state,caps,aid,deps,"initial_global","固定6 DescriptionのGlobal feature model。",{"role":"global-model"})
                if created:planned.append(node["node_id"])
            continue
        compatible=[]
        for deps in dependency_sets(cap,descs,clusters,"global"):
            params={"scope_mode":"global"}
            if aid in {"A003","A004"}:params={"role":"projection-fit"}
            node,created=add_node(state,caps,aid,deps,"initial_global",f"初期Global探索として{aid}を適用する。",params)
            if created:planned.append(node["node_id"])
            compatible.append(node)
    active_round(state)["plans"]["initial_global"]=True;history(state,"initial_global_planned",planned_count=len(planned));return planned


def cluster_rows(state:dict[str,Any],source_node:str|None=None)->list[dict[str,str]]:
    rows=read_csv(Path(state["indices"]["clusters"]["registry_path"]));return [r for r in rows if not source_node or r.get("source_node_id")==source_node]
def cluster_metric_rows(state:dict[str,Any],source_node:str,operator_id:str)->dict[str,dict[str,str]]:
    candidates=[r for r in read_jsonl(Path(state["indices"]["operator_results"]["path"])) if r.get("operator_id")==operator_id and source_node in (r.get("source_nodes") or [])]
    if not candidates:return {}
    path=Path(str(candidates[-1].get("artifact_path") or ""))
    return {str(row.get("cluster_id")):row for row in read_csv(path) if row.get("cluster_id")} if path.is_file() else {}
def metric_value(row:dict[str,str],key:str,default:float=float("-inf"))->float:
    try:
        value=float(row.get(key) or default);return value if value==value else default
    except (TypeError,ValueError):return default
def representative_clusters(state:dict[str,Any],node:dict[str,Any],limit:int)->list[str]:
    rows=[r for r in cluster_rows(state,node["node_id"]) if r.get("status","active")=="active"]
    if not rows:return []
    total=max(1,int(state["run"]["row_count"]));local=[r for r in rows if float(r["compound_count"])/total<=.5] or rows;selected=[]
    def take(ordered:list[dict[str,str]])->None:
        for row in ordered:
            if row["cluster_id"] not in selected:selected.append(row["cluster_id"]);break
    take(sorted(local,key=lambda r:(-int(r["compound_count"]),r["cluster_id"])))
    take(sorted(local,key=lambda r:(abs(float(r["compound_count"])/total-.2),-int(r["compound_count"]),r["cluster_id"])))
    profiles=cluster_metric_rows(state,node["node_id"],"A010")
    take(sorted(local,key=lambda r:(-metric_value(profiles.get(r["cluster_id"],{}),"property_std"),r["cluster_id"])))
    diversity=cluster_metric_rows(state,node["node_id"],"A013")
    take(sorted(local,key=lambda r:(-metric_value(diversity.get(r["cluster_id"],{}),"mean_tanimoto"),r["cluster_id"])))
    fallback=sorted(rows,key=lambda r:(float(r["compound_count"])/total>.5,abs(float(r["compound_count"])/total-.2),-int(r["compound_count"]),value_hash(r["cluster_id"])))
    for row in fallback:
        if len(selected)>=limit:break
        if row["cluster_id"] not in selected:selected.append(row["cluster_id"])
    return selected[:limit]


def plan_initial_local(state:dict[str,Any])->list[str]:
    caps=catalog();p=profile();master=p["initial_exploration"]["description_master_panel"];descs=succeeded(state,"description",master);clusters=succeeded(state,"clustering");planned=[];limit=int(p["initial_exploration"].get("representative_clusters_per_clustering",3))
    projection_ids=set(p["initial_exploration"].get("projection_overlay_capabilities",[]))
    projections=[n for n in succeeded(state,"analysis",projection_ids) if n.get("parameters",{}).get("role")=="projection-fit"]
    for cluster_node in clusters:
        selected=representative_clusters(state,cluster_node,limit)
        for cluster_id in selected:
            for aid in p["initial_exploration"]["local_operator_capabilities"]:
                cap=caps[aid]
                if "within-cluster" not in cap.get("scope_support",[]):continue
                for deps in dependency_sets(cap,descs,[cluster_node],"within-cluster"):
                    node,created=add_node(state,caps,aid,deps,"initial_local",f"代表Cluster {cluster_id}のLocal探索。",{"scope_mode":"within-cluster","target_cluster":cluster_id})
                    if created:planned.append(node["node_id"])
            # Projection overlay reuses the completed Global coordinates.  The
            # Analysis-to-Analysis edge makes a refit impossible by construction.
            for projection in projections:
                node,created=add_node(state,caps,projection["capability_id"],[projection["node_id"],cluster_node["node_id"]],"initial_local",f"Global投影へ代表Cluster {cluster_id}を重ねる。",{"role":"cluster-overlay","target_cluster":cluster_id})
                if created:planned.append(node["node_id"])
        # A005 survey is one batch Node per Clustering, not one Node per Cluster.
        a005=caps.get("A005");global_model=next((n for n in succeeded(state,"analysis",["A005"]) if n["parameters"].get("role")=="global-model"),None);lookup={n["capability_id"]:n for n in succeeded(state,"description")}
        if a005 and global_model and all(cid in lookup for cid in a005["fixed_description_panel"]):
            deps=[lookup[cid]["node_id"] for cid in a005["fixed_description_panel"]]+[cluster_node["node_id"],global_model["node_id"]]
            node,created=add_node(state,caps,"A005",deps,"initial_local",f"{cluster_node['node_id']}の全適格Cluster model survey。",{"role":"cluster-survey","min_local_samples":30})
            if created:planned.append(node["node_id"])
    active_round(state)["plans"]["initial_local"]=True;history(state,"initial_local_planned",planned_count=len(planned));return planned


def candidate_cells(state:dict[str,Any])->list[dict[str,Any]]:
    caps=catalog();p=profile();descs=succeeded(state,"description",p["initial_exploration"]["description_master_panel"]);clusters=succeeded(state,"clustering");existing={n["analysis_signature"] for n in state["execution_graph"]["nodes"] if n["status"] not in {"stale","deferred"}};result=[]
    for aid in p["additional_exploration"]["operator_capabilities"]:
        cap=caps[aid]
        for scope in ("global","within-cluster"):
            if scope not in cap.get("scope_support",[]):continue
            if scope=="global":targets=[(None,None)]
            else:targets=[(node,cid) for node in clusters for cid in representative_clusters(state,node,5)]
            for cluster_node,cid in targets:
                for deps in dependency_sets(cap,descs,[cluster_node] if cluster_node else [],scope):
                    params={"scope_mode":scope,**({"target_cluster":cid} if cid else {})};sig=signature(aid,deps,{**(cap.get("default_parameters") or {}),**params},scope)
                    if sig not in existing:result.append({"capability_id":aid,"dependencies":deps,"parameters":params,"signature":sig,"stratum":[aid,scope,(cluster_node or {}).get("capability_id")]})
    return result
def balanced_candidates(state:dict[str,Any],count:int,seed:int)->list[dict[str,Any]]:
    candidates=candidate_cells(state);usage=Counter()
    for n in state["execution_graph"]["nodes"]:
        if n["stage"]=="analysis":usage[(n["capability_id"],n["parameters"].get("scope_mode"))]+=1
    return sorted(candidates,key=lambda c:(usage[(c["capability_id"],c["parameters"].get("scope_mode"))],value_hash([seed,c["signature"]])))[:count]


def interpretation_gate(state:dict[str,Any],rid:str|None=None)->dict[str,Any]:
    round_id=rid or (active_round(state,False) or {}).get("round_id")
    if not round_id:return {"status":"not_required","reason":"no active Round"}
    analyses=[n for n in state["execution_graph"]["nodes"] if execution_round(n)==round_id and n["stage"]=="analysis" and n["status"]=="succeeded"]
    interps=[n for n in state["execution_graph"]["nodes"] if execution_round(n)==round_id and n["stage"]=="interpretation" and n["status"]=="succeeded"]
    latest_analysis=max((parse_time(n.get("finished_at")) or datetime.min.replace(tzinfo=timezone.utc) for n in analyses),default=datetime.min.replace(tzinfo=timezone.utc));valid=[]
    for n in interps:
        base=Path(n.get("final_output_dir",n["output_dir"]));paths=[base/name for name in ("interpretation.json","interpretation.md","interpretation.html","quality_report.json")]
        try:quality=read_json(base/"quality_report.json") if (base/"quality_report.json").is_file() else {}
        except Exception:quality={}
        if all(p.is_file() and p.stat().st_size for p in paths) and quality.get("status")=="pass" and (parse_time(n.get("finished_at")) or datetime.min.replace(tzinfo=timezone.utc))>=latest_analysis:valid.append(n["node_id"])
    return {"status":"satisfied" if valid else "required","analysis_node_ids":[n["node_id"] for n in analyses],"valid_interpretation_node_ids":valid}


def audit_latest(state:dict[str,Any])->dict[str,Any]|None:
    root=Path(state["run"]["run_root"])/"audit";items=[]
    for path in root.glob("*/audit.json") if root.is_dir() else []:
        try:items.append(read_json(path))
        except Exception:pass
    return sorted(items,key=lambda x:x.get("created_at",""))[-1] if items else None
def required_action(state:dict[str,Any])->dict[str,Any]:
    item=active_round(state,False)
    if not item:return {"code":"START_NEXT_ROUND","next_round_id":f"RND{state['round_control']['next_round_number']:04d}"}
    running=[n["node_id"] for n in state["execution_graph"]["nodes"] if n["status"]=="running"]
    if running:return {"code":"WAIT_OR_RECONCILE_RUNNING","node_ids":running[:MAX_CANDIDATES]}
    if not item["plans"].get("basic_compute"):return {"code":"PLAN_BASIC"}
    bundle=state["run"]["high_cost_bundle"]
    if bundle["status"]=="pending" and any(n["human_approval"]=="bundle_pending" for n in state["execution_graph"]["nodes"]):return {"code":"REQUEST_BASIC_BUNDLE_APPROVAL","capability_ids":bundle["capability_ids"]}
    ready=runnable(state)
    if ready:return {"code":"EXECUTE_RUNNABLE_BATCH","node_ids":[n["node_id"] for n in ready]}
    if not phase_terminal(state,"basic_compute"):return {"code":"RESOLVE_BASIC_GAPS"}
    if not item["plans"].get("initial_global"):return {"code":"PLAN_INITIAL_GLOBAL"}
    if not phase_terminal(state,"initial_global"):return {"code":"RESOLVE_INITIAL_GLOBAL_GAPS"}
    if not item["plans"].get("initial_local"):return {"code":"PLAN_INITIAL_LOCAL"}
    if not phase_terminal(state,"initial_local"):return {"code":"RESOLVE_INITIAL_LOCAL_GAPS"}
    gate=interpretation_gate(state)
    if gate["status"]=="satisfied":
        latest_audit=audit_latest(state);interp=max((parse_time(n.get("finished_at")) for n in state["execution_graph"]["nodes"] if execution_round(n)==item["round_id"] and n["stage"]=="interpretation" and n["status"]=="succeeded"),default=None)
        if not latest_audit or latest_audit.get("mode")!="full" or latest_audit.get("status")!="pass" or (interp and (parse_time(latest_audit.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))<interp):return {"code":"RUN_FULL_AUDIT"}
        return {"code":"CLOSE_ROUND","round_id":item["round_id"]}
    if round_time(state)["status"] in {"interpretation_reserve","expired"} or item.get("finish_requested"):return {"code":"PLAN_INTERPRETATION","defer_pending":True}
    candidates=balanced_candidates(state,MAX_CANDIDATES,int(item["round_id"].removeprefix("RND")))
    if candidates:return {"code":"SCIENTIFIC_DECISION","candidate_count":len(candidate_cells(state)),"candidates":candidates,"allowed_decisions":["plan-additional","add human-directed/deep-dive Node","finish exploration and plan Interpretation"]}
    return {"code":"PLAN_INTERPRETATION","defer_pending":False}


def state_summary(state:dict[str,Any])->dict[str,Any]:
    status=Counter(n["status"] for n in state["execution_graph"]["nodes"]);stage={s:Counter(n["status"] for n in state["execution_graph"]["nodes"] if n["stage"]==s) for s in NODE_INFO}
    insights=list(latest(read_jsonl(Path(state["indices"]["insights"]["path"])),"insight_id").values());actions=list(latest(read_jsonl(Path(state["indices"]["next_actions"]["path"])),"action_id").values())
    priority=[{key:i.get(key) for key in ("insight_id","revision","title","attention","round_id","interpretation_node_id")} for i in insights if i.get("attention")=="priority"][-20:]
    open_actions=[{key:a.get(key) for key in ("action_id","revision","title","status","round_id","source_insights")} for a in actions if a.get("status")=="open"][-20:]
    return {"schema_version":SUMMARY_SCHEMA,"run":{k:state["run"].get(k) for k in ("run_id","project","input","endpoint","higher_is_better","row_count","parallel_limit")},"active_round_id":state["round_control"]["active_round_id"],"next_round_number":state["round_control"]["next_round_number"],"node_count":len(state["execution_graph"]["nodes"]),"status_counts":dict(status),"stage_counts":{k:dict(v) for k,v in stage.items()},"cluster_count":state["indices"]["clusters"]["cluster_count"],"operator_result_count":state["indices"]["operator_results"]["count"],"priority_insights":priority,"open_next_actions":open_actions,"time_budget":round_time(state),"interpretation_gate":interpretation_gate(state),"updated_at":state["updated_at"]}
def brief(state:dict[str,Any])->dict[str,Any]:
    value={"schema_version":BRIEF_SCHEMA,"run_id":state["run"]["run_id"],"active_round_id":state["round_control"]["active_round_id"],"required_control_action":required_action(state),"facts":state_summary(state),"scientific_decision":None,"generated_at":utc_now()}
    if value["required_control_action"]["code"]=="SCIENTIFIC_DECISION":value["scientific_decision"]={"instruction":"候補、既存Insight、coverage balance、人間指示から次の有限な解析bundleまたはInterpretation移行を選ぶ。","candidates":value["required_control_action"]["candidates"]}
    encoded=json.dumps(value,ensure_ascii=False).encode()
    if len(encoded)>MAX_BRIEF_BYTES:
        value["required_control_action"].pop("candidates",None);value["scientific_decision"]={"instruction":"query candidatesで最大20件を取得して選択する。"};value["truncated"]=True
    if len(json.dumps(value,ensure_ascii=False).encode())>MAX_BRIEF_BYTES:
        value["facts"]["priority_insights"]=value["facts"]["priority_insights"][-5:];value["facts"]["open_next_actions"]=value["facts"]["open_next_actions"][-5:];value["truncated"]=True
    return value
def update_views(path:Path,state:dict[str,Any])->None:
    root=path.parent;summary=state_summary(state);write_json(root/"summaries"/"state_summary.json",summary);write_json(root/"summaries"/"orchestrator_brief.json",brief(state))
    cells=[{"node_id":n["node_id"],"capability_id":n["capability_id"],"stage":n["stage"],"phase":n["phase"],"requested_round_id":n.get("requested_round_id",n["round_id"]),"execution_round_id":execution_round(n),"status":n["status"],"dependencies":n["dependencies"],"scope_mode":n["parameters"].get("scope_mode") or n["parameters"].get("role"),"target_cluster":n["parameters"].get("target_cluster"),"signature":n["analysis_signature"]} for n in state["execution_graph"]["nodes"]]
    write_json(Path(state["indices"]["coverage"]["path"]),{"schema_version":"2.0.0","cells":cells,"updated_at":utc_now()})
def save(path:Path,state:dict[str,Any])->None:
    state["revision"]+=1;state["updated_at"]=utc_now();validate_state(state);write_json(path,state);update_views(path,state)


def create_round(state:dict[str,Any],request:str,wall:int,max_additional:int,iterations:int,parallel_limit:int|None=None)->dict[str,Any]:
    number=state["round_control"]["next_round_number"];rid=f"RND{number:04d}";started=datetime.now(timezone.utc);reserve=max(20,min(90,wall//5))
    selected_parallel=int(parallel_limit if parallel_limit is not None else state["run"]["parallel_limit"])
    if selected_parallel<1:raise ValueError("parallel_limit must be >= 1")
    state["run"]["parallel_limit"]=selected_parallel
    item={"round_id":rid,"status":"active","request":request,"started_at":started.isoformat(),"ended_at":None,"plans":{"basic_compute":False,"initial_global":False,"initial_local":False},"execution_control":{"walltime_minutes":wall,"deadline_at":(started+timedelta(minutes=wall)).isoformat(),"interpretation_reserve_minutes":reserve,"parallel_limit":selected_parallel,"max_additional_nodes":max_additional,"interpretation_iterations":iterations,"additional_nodes_planned":0}}
    state["round_control"]["rounds"].append(item);state["round_control"]["active_round_id"]=rid;state["round_control"]["next_round_number"]+=1;root=Path(state["run"]["run_root"])/"rounds"/rid;root.mkdir(parents=True,exist_ok=True);atomic_text(root/"round_request.md",f"# {rid} Request\n\n{request}\n");write_json(root/"round_manifest.json",item);return item


def cmd_init(a:argparse.Namespace)->int:
    source=Path(a.input).resolve();run_id=a.run_id or stamp();root=Path(a.output_dir).resolve() if a.output_dir else (workspace()/"results"/"CONDUCTOR"/a.project/run_id).resolve()
    if (root/"state.json").exists():raise FileExistsError(root/"state.json")
    import pandas as pd
    frame=pd.read_csv(source);row_count=len(frame)
    if a.endpoint not in frame:raise ValueError(f"Endpoint missing: {a.endpoint}")
    root.mkdir(parents=True,exist_ok=True);indices=index_paths(root)
    for key in ("operator_results","insights","next_actions"):write_jsonl(Path(indices[key]["path"]),[])
    write_csv(Path(indices["clusters"]["registry_path"]),["cluster_id","local_cluster_id","source_node_id","clustering_capability_id","cluster_label","compound_count","membership_path","status","created_at"],[])
    caps=catalog();p=profile();high=[cid for cid in p["basic_compute"].get("high_cost_bundle",[]) if caps[cid]["cost"].get("human_approval_required")]
    state={"schema_version":STATE_SCHEMA,"conductor_version":VERSION,"revision":0,"run":{"run_id":run_id,"project":a.project,"run_root":str(root),"input":str(source),"input_hash":sha_file(source),"endpoint":a.endpoint,"higher_is_better":a.higher_is_better,"parallel_limit":a.parallel_limit,"row_count":row_count,"profile_id":p["profile_id"],"high_cost_bundle":{"status":"not_required" if not high else "pending","capability_ids":high}},"round_control":{"active_round_id":None,"next_round_number":1,"rounds":[]},"orchestration_control":{"lease":{"owner_id":None,"token_hash":None,"expires_at":None,"heartbeat_at":None,"duration_minutes":30},"controller_epoch":0},"counters":{"description_node":0,"clustering_node":0,"analysis_node":0,"interpretation_node":0,"cluster":0,"insight":0,"action":0},"execution_graph":{"nodes":[],"edges":[]},"indices":indices,"history":[],"created_at":utc_now(),"updated_at":utc_now()}
    create_round(state,a.request or "初回の包括的解析を開始する。",a.walltime_minutes,a.max_additional_nodes,a.interpretation_iterations);save(root/"state.json",state);print(root/"state.json");return 0


def recover_commits(path:Path,state:dict[str,Any])->list[str]:
    recovered=[]
    for manifest_path in path.parent.glob("interpretation/*/NI*/attempts/ATT*/commit_manifest.json"):
        manifest=read_json(manifest_path)
        if manifest.get("status")!="prepared":continue
        node=nodes(state).get(manifest["node_id"])
        if not node:continue
        out=manifest_path.parent
        if node.get("committed_attempt_id")==manifest["attempt_id"]:
            manifest["status"]="committed";write_json(manifest_path,manifest);recovered.append(str(manifest_path));continue
        report=manifest.get("report")
        if report and all((out/name).is_file() for name in ("interpretation.json","interpretation.md","interpretation.html")):
            commit_interpretation_records(state,node,report,out,manifest["attempt_id"],write_artifacts=False)
            node["artifacts"]=[{"type":kind,"path":name,"resolved_path":str((out/name).resolve()),"sha256":sha_file(out/name)} for kind,name in (("interpretation","interpretation.json"),("interpretation_markdown","interpretation.md"),("interpretation_html","interpretation.html"),("quality_report","quality_report.json")) if (out/name).is_file()]
            node["commit_manifest_path"]=str(manifest_path.resolve());node["current_attempt_id"]=None
            for attempt in node.get("execution_attempts",[]):
                if attempt.get("attempt_id")==manifest["attempt_id"]:attempt.update({"status":"succeeded","finished_at":node["finished_at"]})
            manifest["status"]="committed";manifest["committed_at"]=utc_now();write_json(manifest_path,manifest);recovered.append(str(manifest_path))
    return recovered


def cmd_bootstrap(a:argparse.Namespace)->int:
    path=Path(a.state).resolve()
    with lock(path):
        state=read_json(path);validate_state(state);recovered=recover_commits(path,state);lease=state["orchestration_control"]["lease"];matches=bool(a.lease_token and token_hash(a.lease_token)==lease.get("token_hash"))
        if lease_live(state) and not matches and not a.force_takeover:
            print(json.dumps({"lease_acquired":False,"reason_code":"LEASE_HELD_BY_OTHER_CONTROLLER","brief":brief(state)},ensure_ascii=False,indent=2));return 0
        if lease_live(state) and a.force_takeover and not a.takeover_reason:raise ValueError("--force-takeover requires --takeover-reason")
        token=a.lease_token if matches else secrets.token_urlsafe(32);now=datetime.now(timezone.utc);minutes=max(5,a.lease_minutes);state["orchestration_control"]["controller_epoch"]+=0 if matches else 1;lease.update({"owner_id":a.owner_id,"token_hash":token_hash(token),"heartbeat_at":now.isoformat(),"expires_at":(now+timedelta(minutes=minutes)).isoformat(),"duration_minutes":minutes});history(state,"bootstrap",owner_id=a.owner_id,recovered_commits=recovered);save(path,state)
    print(json.dumps({"lease_acquired":True,"lease_token":token,"recovered_commits":recovered,"brief":brief(state)},ensure_ascii=False,indent=2));return 0


def mutate(path:Path,a:argparse.Namespace,fn:Any)->Any:
    with lock(path):
        state=read_json(path);validate_state(state);require_writer(state,a);touch_lease(state);result=fn(state);save(path,state);return result
def cmd_heartbeat(a:argparse.Namespace)->int:
    state=mutate(Path(a.state).resolve(),a,lambda s:s);print(json.dumps(brief(state),ensure_ascii=False,indent=2));return 0
def cmd_release(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->None:
        history(state,"lease_released",reason=a.reason);state["orchestration_control"]["lease"].update({"owner_id":None,"token_hash":None,"expires_at":None,"heartbeat_at":None})
    mutate(Path(a.state).resolve(),a,action);return 0
def cmd_plan_basic(a:argparse.Namespace)->int:
    result=mutate(Path(a.state).resolve(),a,plan_basic);print(json.dumps({"planned_node_ids":result},indent=2));return 0
def cmd_approve(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        bundle=state["run"]["high_cost_bundle"];bundle.update({"status":"approved" if a.approve else "rejected","rationale":a.rationale,"decided_at":utc_now()})
        for n in state["execution_graph"]["nodes"]:
            if n["human_approval"]=="bundle_pending":n["human_approval"]="approved" if a.approve else "rejected";n["status"]="skipped" if not a.approve else n["status"]
        return bundle
    print(json.dumps(mutate(Path(a.state).resolve(),a,action),ensure_ascii=False,indent=2));return 0
def cmd_plan_global(a:argparse.Namespace)->int:
    result=mutate(Path(a.state).resolve(),a,plan_initial_global);print(json.dumps({"planned_node_ids":result},indent=2));return 0
def cmd_plan_local(a:argparse.Namespace)->int:
    result=mutate(Path(a.state).resolve(),a,plan_initial_local);print(json.dumps({"planned_node_ids":result},indent=2));return 0
def cmd_plan_additional(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->list[str]:
        item=active_round(state);remaining=int(item["execution_control"]["max_additional_nodes"])-int(item["execution_control"]["additional_nodes_planned"]);count=min(a.count,max(0,remaining));caps=catalog();ids=[]
        for candidate in balanced_candidates(state,count,a.seed):
            node,created=add_node(state,caps,candidate["capability_id"],candidate["dependencies"],"additional_exploration","coverage-balanced seeded exploration",candidate["parameters"])
            if created:ids.append(node["node_id"])
        item["execution_control"]["additional_nodes_planned"]+=len(ids);return ids
    result=mutate(Path(a.state).resolve(),a,action);print(json.dumps({"planned_node_ids":result},indent=2));return 0
def cmd_add(a:argparse.Namespace)->int:
    params=json.loads(a.parameters_json or "{}");deps=[v for v in (a.depends_on or "").split(",") if v]
    result=mutate(Path(a.state).resolve(),a,lambda state:add_node(state,catalog(),a.capability_id,deps,"human_directed",a.reason,params));print(json.dumps({"node":result[0],"created":result[1]},ensure_ascii=False,indent=2));return 0


def command_for(state:dict[str,Any],node:dict[str,Any],attempt_id:str)->list[str]:
    cap=catalog()[node["capability_id"]];root=workspace();launcher=root/".claude"/"skills"/node["skill_name"]/"scripts"/"launch.py";out=Path(node["output_dir"])/"attempts"/attempt_id;argv=["python",str(launcher),"--conductor","--project",state["run"]["project"],"--run-id",state["run"]["run_id"],"--node-id",node["node_id"],"--attempt-id",attempt_id,"--output-dir",str(out)]
    round_id=execution_round(node)
    if not round_id:raise ValueError("Node is not assigned to an execution Round")
    argv += ["--round-id",round_id]
    lookup=nodes(state);deps=[lookup[d] for d in node["dependencies"]]
    if node["stage"]=="description":argv += ["--input",state["run"]["input"]]
    elif node["stage"]=="clustering":
        desc=next((d for d in deps if d["stage"]=="description"),None)
        argv += ["--input",str(primary(desc,catalog()[desc["capability_id"]])) if desc else state["run"]["input"]]
        if desc:argv += ["--input-representation",desc["capability_id"],"--description-manifest",str(promoted_manifest(desc,"description_manifest.json"))]
    elif node["stage"]=="analysis":
        argv += ["--input",state["run"]["input"],"--property-column",state["run"]["endpoint"],"--higher-is-better" if state["run"]["higher_is_better"] else "--no-higher-is-better"]
        descs=[d for d in deps if d["stage"]=="description"];clusters=[d for d in deps if d["stage"]=="clustering"]
        projection=next((d for d in deps if d["stage"]=="analysis" and d["capability_id"] in {"A003","A004"}),None)
        if node["capability_id"]=="A005":
            for desc in descs:argv += ["--description",f"{desc['capability_id']}={primary(desc,catalog()[desc['capability_id']])}","--description-node-id",desc["node_id"]]
            global_model=next((d for d in deps if d["stage"]=="analysis" and d["capability_id"]=="A005"),None)
            if global_model:
                successful=[x for x in global_model["execution_attempts"] if x["status"]=="succeeded"][-1];argv += ["--global-oof",str(Path(global_model["output_dir"])/"attempts"/successful["attempt_id"]/"global_oof_predictions.csv"),"--global-model-node-id",global_model["node_id"]]
        elif descs:argv += ["--description",str(primary(descs[0],catalog()[descs[0]["capability_id"]])),"--description-node-id",descs[0]["node_id"],"--evaluation-representation",descs[0]["capability_id"]]
        if clusters:argv += ["--membership",str(primary(clusters[0],catalog()[clusters[0]["capability_id"]])),"--clustering-node-id",clusters[0]["node_id"],"--clustering-representation",clusters[0]["capability_id"]]
        if projection:argv += ["--projection",str(primary(projection,catalog()[projection["capability_id"]])),"--projection-node-id",projection["node_id"]]
    else:argv += ["--state",state["run"]["run_root"]+os.sep+"state.json","--context",node["parameters"]["context_path"],"--draft",node["parameters"].get("draft_path",str(Path(node["output_dir"])/"interpretation_draft_input.json"))]
    excluded={"context_path","draft_path","scope_mode","focus","reviewed_result_refs","comparison_signatures"}
    mapping={"target_cluster":"--target-cluster","comparison_cluster":"--comparison-cluster"}
    for key,value in node["parameters"].items():
        if key in excluded or value is None:continue
        option=mapping.get(key,"--"+key.replace("_","-"))
        if isinstance(value,bool):argv.append(option if value else "--no-"+option.removeprefix("--"))
        elif isinstance(value,(str,int,float)):argv += [option,str(value)]
    if node["stage"]=="analysis" and node["parameters"].get("scope_mode"):argv += ["--scope-mode",node["parameters"]["scope_mode"]]
    return argv


def cmd_start(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        node=nodes(state).get(a.node_id)
        if not node:raise ValueError("Unknown Node")
        retry=node["status"] in {"failed","unavailable"} and a.retry
        if node["status"] not in {"pending","stale"} and not retry:raise ValueError(f"Node is not startable: {node['status']}")
        error=node_error(state,node)
        if error:raise ValueError(error)
        attempt_id=f"ATT{len(node['execution_attempts'])+1:04d}";attempt={"attempt_id":attempt_id,"status":"running","started_at":utc_now(),"finished_at":None};node["execution_attempts"].append(attempt);node.update({"status":"running","current_attempt_id":attempt_id,"started_at":attempt["started_at"]});command=command_for(state,node,attempt_id);attempt["command_argv"]=command;return {"node_id":node["node_id"],"attempt_id":attempt_id,"command_argv":command,"event_path":str(Path(node["output_dir"])/"attempts"/attempt_id/"execution_event.json")}
    result=mutate(Path(a.state).resolve(),a,action);print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_terminal(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->None:
        node=nodes(state).get(a.node_id)
        if not node:raise ValueError("Unknown Node")
        node.update({"status":a.status,"terminal_reason":a.reason,"finished_at":utc_now()})
        for attempt in reversed(node["execution_attempts"]):
            if attempt["attempt_id"]==node.get("current_attempt_id"):attempt.update({"status":a.status,"finished_at":node["finished_at"],"reason":a.reason});break
        node["current_attempt_id"]=None
    mutate(Path(a.state).resolve(),a,action);return 0


def promote_clusters(state:dict[str,Any],node:dict[str,Any],event_dir:Path,artifacts:list[dict[str,Any]])->None:
    member_art=next((x for x in artifacts if x["type"]=="cluster_membership"),None);registry_art=next((x for x in artifacts if x["type"]=="cluster_registry"),None)
    if not member_art or not registry_art:raise ValueError("Successful Clustering requires membership and registry")
    local_members=read_csv(Path(member_art["resolved_path"]));local_registry=read_json(Path(registry_art["resolved_path"]));mapping={};global_rows=read_csv(Path(state["indices"]["clusters"]["registry_path"]));promoted=[];node_dir=Path(state["run"]["run_root"])/"clusters"/"by_node"/node["node_id"];node_dir.mkdir(parents=True,exist_ok=True)
    for row in local_registry:
        if int(row["compound_count"])<5:raise ValueError("Clustering attempted to register a Cluster smaller than 5")
        cid=allocate(state,"cluster");mapping[row["local_cluster_id"]]=cid;record={"cluster_id":cid,"local_cluster_id":row["local_cluster_id"],"source_node_id":node["node_id"],"clustering_capability_id":node["capability_id"],"cluster_label":row["cluster_label"],"compound_count":row["compound_count"],"membership_path":str((node_dir/"cluster_membership.csv").resolve()),"status":"active","created_at":utc_now()};global_rows.append(record);promoted.append(record)
    for row in local_members:
        if row.get("cluster_id") in mapping:row["cluster_id"]=mapping[row["cluster_id"]]
    write_csv(node_dir/"cluster_membership.csv",["cluster_id","compound_id","membership_value","membership_reason"],local_members);write_json(node_dir/"cluster_registry.json",promoted);write_csv(Path(state["indices"]["clusters"]["registry_path"]),["cluster_id","local_cluster_id","source_node_id","clustering_capability_id","cluster_label","compound_count","membership_path","status","created_at"],global_rows);node["promoted_membership_path"]=str((node_dir/"cluster_membership.csv").resolve());node["cluster_ids"]=[r["cluster_id"] for r in promoted];state["indices"]["clusters"]["cluster_count"]=len(global_rows);rebuild_matrix(state,global_rows)
def rebuild_matrix(state:dict[str,Any],registry:list[dict[str,str]])->None:
    import pandas as pd
    source=pd.read_csv(state["run"]["input"],dtype="string");id_col=next((c for c in source if "id" in str(c).lower()),source.columns[0]);matrix=pd.DataFrame({"compound_id":source[id_col].astype(str)});members={}
    for row in registry:
        for item in read_csv(Path(row["membership_path"])):
            if item.get("cluster_id")==row["cluster_id"] and float(item.get("membership_value") or 0)>0:members.setdefault(row["cluster_id"],set()).add(item["compound_id"])
    for cid in sorted(members):matrix[cid]=matrix["compound_id"].isin(members[cid])
    path=Path(state["run"]["run_root"])/"clusters"/"Cpd_Cluster_matrix_CL000001_099999.csv";matrix.to_csv(path,index=False);state["indices"]["clusters"]["matrix_paths"]=[str(path.resolve())]


def compact_metrics(value:Any,limit:int=16)->dict[str,Any]:
    output:dict[str,Any]={}
    def visit(item:Any,prefix:str="")->None:
        if len(output)>=limit:return
        if isinstance(item,dict):
            for key,child in item.items():
                visit(child,f"{prefix}.{key}".strip("."))
                if len(output)>=limit:break
        elif isinstance(item,(str,int,float,bool)) or item is None:
            text=item if not isinstance(item,str) or len(item)<=180 else item[:177]+"...";output[prefix or "value"]=text
    visit(value);return output
def compact_operator(summary:dict[str,Any],summary_path:Path,round_id:str)->dict[str,Any]:
    primary=summary.get("primary_artifact") or {};primary_path=(summary_path.parent/str(primary.get("path") or "")).resolve()
    report_path=summary_path.parent/"operator_report.html"
    return {key:summary.get(key) for key in ("schema_version","result_ref","node_id","attempt_id","operator_id","run_id","round_id","scope","scope_context","sample_count","endpoint","metric","headline","limitations","warnings","source_nodes","created_at")}|{"round_id":round_id,"key_metrics":compact_metrics(summary.get("key_metrics") or {}),"summary_artifact_path":str(summary_path.resolve()),"artifact_path":str(primary_path),"operator_report_path":str(report_path.resolve()) if report_path.is_file() else None,"artifact_sha256":primary.get("sha256")}
def register_operator(state:dict[str,Any],node:dict[str,Any],artifacts:list[dict[str,Any]])->None:
    item=next((x for x in artifacts if x["type"]=="operator_summary"),None)
    if not item:raise ValueError("Successful Operator requires operator_summary")
    summary_path=Path(item["resolved_path"]);summaries=[(read_json(summary_path),summary_path)];collection=next((x for x in artifacts if x["type"]=="operator_summary_collection"),None)
    if collection:
        collection_path=Path(collection["resolved_path"]);values=read_json(collection_path)
        if not isinstance(values,list):raise ValueError("Operator summary collection must be an array")
        summaries.extend((value,collection_path) for value in values)
    compact=[]
    for summary,source_path in summaries:
        validate(summary,"operator_summary.schema.json")
        if summary["node_id"]!=node["node_id"] or summary["attempt_id"]!=node["current_attempt_id"] or summary["round_id"]!=execution_round(node):raise ValueError("Operator summary provenance mismatch")
        compact.append(compact_operator(summary,source_path,str(execution_round(node))))
    refs=[value["result_ref"] for value in compact]
    if len(refs)!=len(set(refs)):raise ValueError("Duplicate result_ref in Operator summary collection")
    rows=[r for r in read_jsonl(Path(state["indices"]["operator_results"]["path"])) if r.get("result_ref") not in set(refs)];rows.extend(compact);write_jsonl(Path(state["indices"]["operator_results"]["path"]),rows);state["indices"]["operator_results"]["count"]=len(rows);node["result_refs"]=refs


def rebuild_indices(state:dict[str,Any])->dict[str,int]:
    """Rebuild navigation indices from committed Node attempts and artifacts."""
    root=Path(state["run"]["run_root"]);registry=[]
    for node in state["execution_graph"]["nodes"]:
        if node["stage"]!="clustering":continue
        path=root/"clusters"/"by_node"/node["node_id"]/"cluster_registry.json"
        if path.is_file():registry.extend(read_json(path))
    registry.sort(key=lambda row:row["cluster_id"])
    fields=["cluster_id","local_cluster_id","source_node_id","clustering_capability_id","cluster_label","compound_count","membership_path","status","created_at"]
    write_csv(Path(state["indices"]["clusters"]["registry_path"]),fields,registry);state["indices"]["clusters"]["cluster_count"]=len(registry);rebuild_matrix(state,registry)

    operator_by_ref={}
    for node in state["execution_graph"]["nodes"]:
        if node["stage"]!="analysis":continue
        for attempt in node.get("execution_attempts",[]):
            if attempt.get("status")!="succeeded":continue
            base=Path(node["output_dir"])/"attempts"/attempt["attempt_id"];summary_path=base/"operator_summary.json"
            if not summary_path.is_file():continue
            sources=[(read_json(summary_path),summary_path)];collection_path=base/"cluster_operator_summaries.json"
            if collection_path.is_file():
                collection=read_json(collection_path)
                if not isinstance(collection,list):raise ValueError(f"Invalid Operator summary collection: {collection_path}")
                sources.extend((item,collection_path) for item in collection)
            for summary,source_path in sources:
                validate(summary,"operator_summary.schema.json")
                if summary["node_id"]!=node["node_id"] or summary["attempt_id"]!=attempt["attempt_id"]:raise ValueError(f"Operator summary provenance mismatch: {source_path}")
                compact=compact_operator(summary,source_path,summary["round_id"]);ref=compact["result_ref"]
                if ref in operator_by_ref and operator_by_ref[ref]!=compact:raise ValueError(f"Conflicting Operator result_ref: {ref}")
                operator_by_ref[ref]=compact
    operator_rows=[operator_by_ref[key] for key in sorted(operator_by_ref)];write_jsonl(Path(state["indices"]["operator_results"]["path"]),operator_rows);state["indices"]["operator_results"]["count"]=len(operator_rows)

    timeline=[]
    for node in state["execution_graph"]["nodes"]:
        if node["stage"]!="interpretation":continue
        for attempt in node.get("execution_attempts",[]):
            if attempt.get("status")!="succeeded":continue
            report_path=Path(node["output_dir"])/"attempts"/attempt["attempt_id"]/"interpretation.json"
            if report_path.is_file():
                report=read_json(report_path);validate(report,"interpretation.schema.json");timeline.append((str(report.get("created_at") or attempt.get("finished_at") or ""),"report",report))
    for entry in state.get("history",[]):
        if entry.get("action") in {"insight_attention_changed","next_action_status_changed"}:timeline.append((str(entry.get("at") or ""),"human",entry))
    insight_rows=[];action_rows=[];current_insights={};current_actions={}
    for _at,kind,payload in sorted(timeline,key=lambda item:(item[0],item[1])):
        if kind=="report":
            for item in payload["insights"]:
                record={**item,"round_id":payload["round_id"],"interpretation_node_id":payload["node_id"],"updated_at":payload["created_at"]}
                if int(record["revision"])>int(current_insights.get(record["insight_id"],{}).get("revision",0)):insight_rows.append(record);current_insights[record["insight_id"]]=record
            for item in payload["next_actions"]:
                record={**item,"round_id":payload["round_id"],"interpretation_node_id":payload["node_id"],"updated_at":payload["created_at"]}
                if int(record["revision"])>int(current_actions.get(record["action_id"],{}).get("revision",0)):action_rows.append(record);current_actions[record["action_id"]]=record
        elif payload.get("record"):
            record=payload["record"]
            if payload["action"]=="insight_attention_changed" and int(record["revision"])>int(current_insights.get(record["insight_id"],{}).get("revision",0)):insight_rows.append(record);current_insights[record["insight_id"]]=record
            if payload["action"]=="next_action_status_changed" and int(record["revision"])>int(current_actions.get(record["action_id"],{}).get("revision",0)):action_rows.append(record);current_actions[record["action_id"]]=record
    write_jsonl(Path(state["indices"]["insights"]["path"]),insight_rows);write_jsonl(Path(state["indices"]["next_actions"]["path"]),action_rows);state["indices"]["insights"]["count"]=len(current_insights);state["indices"]["next_actions"]["count"]=len(current_actions)
    history(state,"indices_rebuilt",clusters=len(registry),operator_results=len(operator_rows),insights=len(current_insights),next_actions=len(current_actions));return {"clusters":len(registry),"operator_results":len(operator_rows),"insights":len(current_insights),"next_actions":len(current_actions)}


def render_module():
    path=workspace()/"CONDUCTOR_modules"/"tools"/"templates"/"interpretation_render.py";spec=importlib.util.spec_from_file_location("conductor_interpretation_render",path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module);return module
def commit_interpretation_records(state:dict[str,Any],node:dict[str,Any],report:dict[str,Any],out:Path,attempt_id:str,write_artifacts:bool=True)->None:
    insight_path=Path(state["indices"]["insights"]["path"]);action_path=Path(state["indices"]["next_actions"]["path"]);insight_rows=read_jsonl(insight_path);action_rows=read_jsonl(action_path)
    for item in report["insights"]:
        if not any(r.get("insight_id")==item["insight_id"] and int(r.get("revision",1))==item["revision"] for r in insight_rows):insight_rows.append({**item,"round_id":execution_round(node),"interpretation_node_id":node["node_id"],"updated_at":utc_now()})
    for item in report["next_actions"]:
        if not any(r.get("action_id")==item["action_id"] and int(r.get("revision",1))==item["revision"] for r in action_rows):action_rows.append({**item,"round_id":execution_round(node),"interpretation_node_id":node["node_id"],"updated_at":utc_now()})
    write_jsonl(insight_path,insight_rows);write_jsonl(action_path,action_rows)
    state["indices"]["insights"]["count"]=len(latest(insight_rows,"insight_id"));state["indices"]["next_actions"]["count"]=len(latest(action_rows,"action_id"))
    # Recovery may replay a prepared commit after State was not saved.  Advance the
    # monotonic counters to the largest formal ID already present in the report.
    for key,prefix,items,id_key in (("insight","INS",report["insights"],"insight_id"),("action","ACT",report["next_actions"],"action_id")):
        values=[int(str(item[id_key]).removeprefix(prefix)) for item in items if str(item.get(id_key,"" )).startswith(prefix)]
        if values:state["counters"][key]=max(int(state["counters"].get(key,0)),max(values))
    node.update({"status":"succeeded","committed_attempt_id":attempt_id,"final_output_dir":str(out.resolve()),"finished_at":utc_now(),"insight_ids":[i["insight_id"] for i in report["insights"]],"action_ids":[i["action_id"] for i in report["next_actions"]]})
def commit_interpretation(state:dict[str,Any],node:dict[str,Any],event_dir:Path,artifacts:list[dict[str,Any]])->None:
    draft_art=next((x for x in artifacts if x["type"]=="interpretation_draft"),None);context_art=next((x for x in artifacts if x["type"]=="interpretation_context"),None)
    if not draft_art or not context_art:raise ValueError("Interpretation event requires draft and context")
    draft=read_json(Path(draft_art["resolved_path"]));context=read_json(Path(context_art["resolved_path"]));operator_rows=read_jsonl(Path(state["indices"]["operator_results"]["path"]));operator_lookup={r["result_ref"]:r for r in operator_rows};known_refs=set(operator_lookup);allowed=set(context.get("allowed_result_refs") or known_refs);insights=[];tmp_map={};current=latest(read_jsonl(Path(state["indices"]["insights"]["path"])),"insight_id")
    for index,item in enumerate(draft.get("insights") or [],1):
        existing=item.get("existing_insight_id")
        if existing:
            if existing not in current:raise ValueError(f"Unknown existing Insight: {existing}")
            iid=existing;revision=int(current[iid].get("revision",1))+1
        else:iid=allocate(state,"insight");revision=1
        tmp_map[f"TMP-INS{index:04d}"]=iid;support=list(dict.fromkeys(item.get("supporting_results") or []));counter=list(dict.fromkeys(item.get("counter_results") or []))
        if set(support+counter)-allowed:raise ValueError("Insight references Operator results outside its bounded context")
        limitations=[str(v) for v in item.get("limitations") or []]
        if not support:raise ValueError("Each Insight requires at least one supporting Operator result")
        if not limitations:raise ValueError("Each Insight requires a non-empty limitations list")
        if not counter and not any(token in value.lower() for value in limitations for token in ("反証","不一致","counter")):raise ValueError("An Insight without counter_results must document the unsuccessful counterevidence search in limitations")
        insights.append({"insight_id":iid,"revision":revision,"title":str(item["title"]),"observation":str(item["observation"]),"interpretation":str(item["interpretation"]),"attention":item.get("attention","watch"),"scope":item.get("scope") or {},"supporting_results":support,"counter_results":counter,"limitations":limitations})
    actions=[];current_actions=latest(read_jsonl(Path(state["indices"]["next_actions"]["path"])),"action_id")
    for item in draft.get("next_actions") or []:
        existing=item.get("existing_action_id")
        if existing:
            if existing not in current_actions:raise ValueError(f"Unknown existing Next Action: {existing}")
            aid=existing;revision=int(current_actions[aid].get("revision",1))+1
        else:aid=allocate(state,"action");revision=1
        actions.append({"action_id":aid,"revision":revision,"title":str(item["title"]),"rationale":str(item["rationale"]),"status":item.get("status","open"),"source_insights":[tmp_map.get(v,v) for v in item.get("source_insights") or []],"requested_analysis":item.get("requested_analysis") or []})
    referenced=sorted({ref for item in insights for ref in [*item["supporting_results"],*item["counter_results"]]})
    result_catalog=[]
    for ref in referenced:
        row=operator_lookup[ref];result_catalog.append({key:row.get(key) for key in ("result_ref","operator_id","scope","scope_context","sample_count","metric","headline","artifact_path","operator_report_path","summary_artifact_path")})
    report={"schema_version":"2.0.0","run_id":state["run"]["run_id"],"round_id":execution_round(node),"node_id":node["node_id"],"attempt_id":node["current_attempt_id"],"title":str(draft.get("title") or "CONDUCTOR解析結果の解釈"),"executive_summary":str(draft.get("executive_summary") or "今回確認した解析結果の要点を示します。"),"coverage_note":str(draft.get("coverage_note") or "指定されたOperator resultを比較しました。"),"insights":insights,"next_actions":actions,"result_catalog":result_catalog,"created_at":utc_now()};validate(report,"interpretation.schema.json");renderer=render_module();quality=renderer.render_quality(report)
    if quality.get("status")!="pass":raise ValueError(f"Interpretation quality gate failed: {quality.get('issues')}")
    manifest={"schema_version":"1.0.0","status":"prepared","node_id":node["node_id"],"attempt_id":node["current_attempt_id"],"expected_state_revision":state["revision"],"report":report,"prepared_at":utc_now()};manifest_path=event_dir/"commit_manifest.json";write_json(manifest_path,manifest);write_json(event_dir/"interpretation.json",report);atomic_text(event_dir/"interpretation.md",renderer.render_markdown(report));atomic_text(event_dir/"interpretation.html",renderer.render_html(report));write_json(event_dir/"quality_report.json",quality);commit_interpretation_records(state,node,report,event_dir,node["current_attempt_id"])
    node["artifacts"]=[*artifacts,*[{"type":kind,"path":name,"resolved_path":str((event_dir/name).resolve()),"sha256":sha_file(event_dir/name)} for kind,name in (("interpretation","interpretation.json"),("interpretation_markdown","interpretation.md"),("interpretation_html","interpretation.html"),("quality_report","quality_report.json"))]]
    node["commit_manifest_path"]=str(manifest_path.resolve())


def cmd_record(a:argparse.Namespace)->int:
    event_path=Path(a.event).resolve();event=read_json(event_path);validate(event,"execution_event.schema.json")
    def action(state:dict[str,Any])->dict[str,Any]:
        node=nodes(state).get(event["node_id"])
        if not node:raise ValueError("Event Node is not planned")
        for key,expected in (("run_id",state["run"]["run_id"]),("project",state["run"]["project"]),("round_id",execution_round(node)),("capability_id",node["capability_id"]),("skill_name",node["skill_name"]),("attempt_id",node.get("current_attempt_id"))):
            if event.get(key)!=expected:raise ValueError(f"Event {key} does not match current Node attempt; late artifacts remain orphaned")
        if node["status"]!="running":raise ValueError("Only current running attempt can commit")
        artifacts=[]
        for raw in event.get("artifacts") or []:
            item=dict(raw);path=(event_path.parent/item["path"]).resolve()
            if not path.is_file() or sha_file(path)!=item["sha256"]:raise ValueError(f"Artifact missing or hash mismatch: {path}")
            item["resolved_path"]=str(path);artifacts.append(item)
        if event["status"]=="succeeded":
            if node["stage"]=="clustering":promote_clusters(state,node,event_path.parent,artifacts)
            elif node["stage"]=="analysis":register_operator(state,node,artifacts)
            elif node["stage"]=="interpretation":commit_interpretation(state,node,event_path.parent,artifacts)
        if node["stage"]!="interpretation" or event["status"]!="succeeded":node.update({"status":event["status"],"finished_at":event["finished_at"],"artifacts":artifacts,"input_hash":event["input_hash"],"config_hash":event["config_hash"]})
        for attempt in node["execution_attempts"]:
            if attempt["attempt_id"]==event["attempt_id"]:attempt.update({"status":node["status"],"finished_at":event["finished_at"],"event_path":str(event_path)});break
        node["current_attempt_id"]=None;return node
    result=mutate(Path(a.state).resolve(),a,action)
    # The authoritative State is persisted before the prepared manifest is marked
    # committed.  A crash between these writes is repaired deterministically by
    # bootstrap/recover_commits without allocating new IDs.
    manifest_path=result.get("commit_manifest_path") if isinstance(result,dict) else None
    if manifest_path:
        manifest=read_json(Path(manifest_path));manifest["status"]="committed";manifest["committed_at"]=utc_now();write_json(Path(manifest_path),manifest)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def create_context(state:dict[str,Any],max_results:int,focus:str|None)->dict[str,Any]:
    rows=read_jsonl(Path(state["indices"]["operator_results"]["path"]));round_item=active_round(state);rid=round_item["round_id"];iterations=max(1,int(round_item["execution_control"].get("interpretation_iterations") or 1));limit=min(max_results,iterations*20)
    insights=list(latest(read_jsonl(Path(state["indices"]["insights"]["path"])),"insight_id").values());priority_ids={ref for insight in insights if insight.get("attention")=="priority" for ref in [*insight.get("supporting_results",[]),*insight.get("counter_results",[])]}
    current=[r for r in rows if r.get("round_id")==rid];historical=[r for r in rows if r.get("result_ref") in priority_ids and r.get("round_id")!=rid];pool=[];seen=set()
    for item in [*current,*historical]:
        if item["result_ref"] not in seen:pool.append(item);seen.add(item["result_ref"])
    reviewed={ref for node in state["execution_graph"]["nodes"] if node["stage"]=="interpretation" and node["status"]=="succeeded" for ref in node.get("parameters",{}).get("reviewed_result_refs",[])}
    focus_text=(focus or "").lower()
    def focus_rank(item:dict[str,Any])->int:
        if not focus_text:return 0
        searchable=" ".join(str(item.get(key) or "") for key in ("result_ref","operator_id","headline"))+" "+json.dumps(item.get("scope_context") or {},ensure_ascii=False)
        return 0 if focus_text in searchable.lower() else 1
    buckets:dict[tuple[str,str],list[dict[str,Any]]]={}
    for item in pool:
        key=(str(item.get("operator_id") or "unknown"),str((item.get("scope") or {}).get("mode") or "unknown"));buckets.setdefault(key,[]).append(item)
    seed=f"{state['run']['run_id']}:{rid}:{focus or ''}";ordered_keys=sorted(buckets,key=lambda key:value_hash([seed,key]))
    for key in ordered_keys:buckets[key].sort(key=lambda item:(focus_rank(item),item["result_ref"] in reviewed,value_hash([seed,item["result_ref"]])))
    selected=[]
    while len(selected)<limit and any(buckets.values()):
        for key in ordered_keys:
            if buckets[key] and len(selected)<limit:selected.append(buckets[key].pop(0))
    batches=[selected[index:index+20] for index in range(0,len(selected),20)];signatures=[value_hash(sorted(item["result_ref"] for item in batch)) for batch in batches]
    return {"schema_version":"1.0.0","run_id":state["run"]["run_id"],"round_id":rid,"focus":focus,"allowed_result_refs":[r["result_ref"] for r in selected],"operator_results":selected,"comparison_batches":[{"iteration":index+1,"signature":signatures[index],"result_refs":[item["result_ref"] for item in batch]} for index,batch in enumerate(batches)],"existing_priority_insights":[i for i in insights if i.get("attention")=="priority"][-20:],"open_next_actions":[x for x in latest(read_jsonl(Path(state["indices"]["next_actions"]["path"])),"action_id").values() if x.get("status")=="open"][-20:],"comparison_guidance":{"randomized_queue":True,"iteration_budget":iterations,"max_candidates_per_iteration":20,"require_counterevidence_search":True,"avoid_repeated_signatures":True}}
def cmd_add_interpretation(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        if a.defer_pending:
            for n in state["execution_graph"]["nodes"]:
                if n["stage"]!="interpretation" and execution_round(n)==active_round(state)["round_id"] and n["status"]=="pending":n["status"]="deferred";n["execution_round_id"]=None
        nonterminal=[n["node_id"] for n in state["execution_graph"]["nodes"] if execution_round(n)==active_round(state)["round_id"] and n["stage"]!="interpretation" and n["status"] not in TERMINAL|{"deferred"}]
        if nonterminal:raise ValueError(f"Interpretation must be terminal; nonterminal Nodes: {nonterminal[:20]}")
        deps=[n["node_id"] for n in state["execution_graph"]["nodes"] if execution_round(n)==active_round(state)["round_id"] and n["stage"]=="analysis" and n["status"]=="succeeded"]
        existing=next((n for n in reversed(state["execution_graph"]["nodes"]) if execution_round(n)==active_round(state)["round_id"] and n["stage"]=="interpretation"),None);created=False
        if existing:
            node=existing
            if node["status"]=="running":return {"node":node,"created":False,"reused":True,"context_path":node["parameters"].get("context_path"),"draft_path":node["parameters"].get("draft_path")}
            if node["status"]=="succeeded" and interpretation_gate(state)["status"]=="satisfied":return {"node":node,"created":False,"reused":True,"context_path":node["parameters"].get("context_path"),"draft_path":node["parameters"].get("draft_path")}
            if node["status"]=="succeeded":node["status"]="stale";history(state,"interpretation_staled",node_id=node["node_id"],reason="later successful Operator results")
            node["dependencies"]=deps;state["execution_graph"]["edges"]=[edge for edge in state["execution_graph"]["edges"] if edge["target"]!=node["node_id"]]+[{"source":dep,"target":node["node_id"]} for dep in deps];node["analysis_signature"]=signature("I001",deps,{"focus":a.focus} if a.focus else {},"")
        else:
            node,created=add_node(state,catalog(),"I001",deps,a.phase,a.reason,{"focus":a.focus} if a.focus else {})
        context=create_context(state,a.max_results,a.focus);context_path=Path(node["output_dir"])/"interpretation_context.json";context_path.parent.mkdir(parents=True,exist_ok=True);write_json(context_path,context);draft_path=Path(node["output_dir"])/"interpretation_draft_input.json";write_json(draft_path,{"title":"CONDUCTOR解析結果の解釈","executive_summary":"Interpreterが今回のOperator resultを比較して記述する。","coverage_note":"対象resultはinterpretation_context.jsonに記録される。","insights":[],"next_actions":[]});node["parameters"].update({"focus":a.focus,"context_path":str(context_path.resolve()),"draft_path":str(draft_path.resolve()),"reviewed_result_refs":context["allowed_result_refs"],"comparison_signatures":[item["signature"] for item in context["comparison_batches"]]})
        return {"node":node,"created":created,"reused":not created,"context_path":node["parameters"].get("context_path"),"draft_path":node["parameters"].get("draft_path")}
    result=mutate(Path(a.state).resolve(),a,action);print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_insight_attention(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        path=Path(state["indices"]["insights"]["path"]);current=latest(read_jsonl(path),"insight_id").get(a.insight_id)
        if not current:raise ValueError("Unknown Insight")
        revised={**current,"revision":int(current["revision"])+1,"attention":a.attention,"human_note":a.reason,"updated_at":utc_now()};append_jsonl(path,revised);history(state,"insight_attention_changed",insight_id=a.insight_id,record=revised);return revised
    print(json.dumps(mutate(Path(a.state).resolve(),a,action),ensure_ascii=False,indent=2));return 0
def cmd_action_status(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        path=Path(state["indices"]["next_actions"]["path"]);current=latest(read_jsonl(path),"action_id").get(a.action_id)
        if not current:raise ValueError("Unknown Next Action")
        revised={**current,"revision":int(current["revision"])+1,"status":a.status,"human_note":a.reason,"updated_at":utc_now()};append_jsonl(path,revised);history(state,"next_action_status_changed",action_id=a.action_id,record=revised);return revised
    print(json.dumps(mutate(Path(a.state).resolve(),a,action),ensure_ascii=False,indent=2));return 0
def cmd_deprioritize(a:argparse.Namespace)->int:
    ids=set(a.cluster_id.split(","))
    def action(state:dict[str,Any])->None:
        path=Path(state["indices"]["clusters"]["registry_path"]);rows=read_csv(path);known={r["cluster_id"] for r in rows}
        if ids-known:raise ValueError(f"Unknown Cluster IDs: {sorted(ids-known)}")
        for row in rows:
            if row["cluster_id"] in ids:row["status"]="deprioritized";row["deprioritize_reason"]=a.reason
        write_csv(path,list(rows[0]) if rows else [],rows)
    mutate(Path(a.state).resolve(),a,action);return 0


def audit_state(path:Path,state:dict[str,Any],mode:str)->dict[str,Any]:
    checks=[]
    def check(code:str,passed:bool,detail:Any=None,severity:str="error")->None:checks.append({"code":code,"passed":bool(passed),"severity":severity,"detail":detail})
    try:validate_state(state);check("STATE_SCHEMA_AND_DAG",True)
    except Exception as exc:check("STATE_SCHEMA_AND_DAG",False,str(exc))
    ids=[n["node_id"] for n in state["execution_graph"]["nodes"]];check("NODE_IDS_UNIQUE",len(ids)==len(set(ids)))
    sig=[n["analysis_signature"] for n in state["execution_graph"]["nodes"] if n["status"]!="stale"];check("ACTIVE_SIGNATURES_UNIQUE",len(sig)==len(set(sig)))
    running=[n for n in state["execution_graph"]["nodes"] if n["status"]=="running"];check("RUNNING_HAS_CURRENT_ATTEMPT",all(n.get("current_attempt_id") for n in running));check("PARALLEL_LIMIT",len(running)<=state["run"]["parallel_limit"])
    index_files=[Path(state["indices"]["coverage"]["path"]),Path(state["indices"]["clusters"]["registry_path"]),Path(state["indices"]["operator_results"]["path"]),Path(state["indices"]["insights"]["path"]),Path(state["indices"]["next_actions"]["path"]),path.parent/"summaries"/"state_summary.json",path.parent/"summaries"/"orchestrator_brief.json"]
    check("NAVIGATION_INDICES_EXIST",all(item.is_file() for item in index_files),[str(item) for item in index_files if not item.is_file()])
    rows=read_csv(Path(state["indices"]["clusters"]["registry_path"]));check("CLUSTER_MINIMUM_SIZE",all(int(r["compound_count"])>=5 for r in rows));check("CLUSTER_INDEX_COUNT",len(rows)==int(state["indices"]["clusters"].get("cluster_count",0)),{"actual":len(rows),"declared":state["indices"]["clusters"].get("cluster_count")})
    refs=read_jsonl(Path(state["indices"]["operator_results"]["path"]));check("RESULT_REFS_UNIQUE",len(refs)==len({r["result_ref"] for r in refs}));check("OPERATOR_INDEX_COUNT",len(refs)==int(state["indices"]["operator_results"].get("count",0)),{"actual":len(refs),"declared":state["indices"]["operator_results"].get("count")})
    insight_rows=read_jsonl(Path(state["indices"]["insights"]["path"]));insight_count=len(latest(insight_rows,"insight_id"));check("INSIGHT_INDEX_COUNT",insight_count==int(state["indices"]["insights"].get("count",0)),{"actual":insight_count,"declared":state["indices"]["insights"].get("count")})
    action_rows=read_jsonl(Path(state["indices"]["next_actions"]["path"]));action_count=len(latest(action_rows,"action_id"));check("NEXT_ACTION_INDEX_COUNT",action_count==int(state["indices"]["next_actions"].get("count",0)),{"actual":action_count,"declared":state["indices"]["next_actions"].get("count")})
    prepared=list(path.parent.glob("interpretation/*/NI*/attempts/ATT*/commit_manifest.json"));unresolved=[str(p) for p in prepared if read_json(p).get("status")=="prepared"];check("NO_PREPARED_INTERPRETATION_COMMIT",not unresolved,unresolved)
    check("INTERPRETATION_GATE",interpretation_gate(state).get("status") in {"satisfied","not_required"},interpretation_gate(state),"warning")
    if mode=="full":
        missing=[];mismatch=[]
        for n in state["execution_graph"]["nodes"]:
            if n["status"]!="succeeded":continue
            for art in n.get("artifacts") or []:
                p=Path(art.get("resolved_path",""))
                if not p.is_file():missing.append(str(p))
                elif art.get("sha256") and sha_file(p)!=art["sha256"]:mismatch.append(str(p))
        check("SUCCEEDED_ARTIFACTS_EXIST",not missing,missing);check("SUCCEEDED_ARTIFACT_HASHES",not mismatch,mismatch)
    errors=[x for x in checks if not x["passed"] and x["severity"]=="error"];warnings=[x for x in checks if not x["passed"] and x["severity"]=="warning"]
    return {"schema_version":"1.0.0","mode":mode,"run_id":state["run"]["run_id"],"state_revision":state["revision"],"status":"fail" if errors else "warning" if warnings else "pass","error_count":len(errors),"warning_count":len(warnings),"checks":checks,"created_at":utc_now()}
def write_audit(path:Path,result:dict[str,Any])->Path:
    out=path.parent/"audit"/stamp();out.mkdir(parents=True,exist_ok=False);write_json(out/"audit.json",result);lines=[f"# CONDUCTOR {result['mode'].title()} Audit","",f"- Status: {result['status']}",f"- Run: {result['run_id']}",""]+[f"- [{'PASS' if x['passed'] else x['severity'].upper()}] `{x['code']}` — {json.dumps(x.get('detail'),ensure_ascii=False)}" for x in result["checks"]];atomic_text(out/"audit.md","\n".join(lines)+"\n");return out
def cmd_audit(a:argparse.Namespace)->int:
    path=Path(a.state).resolve();state=read_json(path);result=audit_state(path,state,a.mode);out=write_audit(path,result);print(json.dumps({"output_dir":str(out),"audit":result},ensure_ascii=False,indent=2));return 1 if result["status"]=="fail" else 0


def cmd_rebuild_indices(a:argparse.Namespace)->int:
    result=mutate(Path(a.state).resolve(),a,rebuild_indices);print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_round_start(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->dict[str,Any]:
        if active_round(state,False):raise ValueError("A Round is already active")
        expected=f"RND{state['round_control']['next_round_number']:04d}"
        if a.round_id!=expected:raise ValueError(f"Next Round must be {expected}")
        # Deferred Nodes are not silently reactivated. Runtime candidates may select the same signatures explicitly.
        return create_round(state,a.request,a.walltime_minutes,a.max_additional_nodes,a.interpretation_iterations,a.parallel_limit)
    print(json.dumps(mutate(Path(a.state).resolve(),a,action),ensure_ascii=False,indent=2));return 0
def cmd_finish_exploration(a:argparse.Namespace)->int:
    def action(state:dict[str,Any])->None:active_round(state)["finish_requested"]=True;history(state,"finish_exploration_requested",reason=a.reason)
    mutate(Path(a.state).resolve(),a,action);return 0
def cmd_round_end(a:argparse.Namespace)->int:
    path=Path(a.state).resolve()
    def action(state:dict[str,Any])->dict[str,Any]:
        item=active_round(state)
        if item["round_id"]!=a.round_id:raise ValueError("Round ID mismatch")
        if any(n["status"]=="running" for n in state["execution_graph"]["nodes"]):raise ValueError("Running Nodes remain")
        gate=interpretation_gate(state,a.round_id)
        if a.status in {"checkpoint","completed"} and gate["status"] not in {"satisfied","not_required"}:raise ValueError("Interpretation gate is not satisfied")
        audit=audit_latest(state)
        if a.status in {"checkpoint","completed"} and (not audit or audit.get("mode")!="full" or audit.get("status")!="pass"):raise ValueError("A passing Full Audit is required")
        latest_interpretation=max((parse_time(n.get("finished_at")) for n in state["execution_graph"]["nodes"] if execution_round(n)==a.round_id and n["stage"]=="interpretation" and n["status"]=="succeeded"),default=None)
        if a.status in {"checkpoint","completed"} and latest_interpretation and (parse_time(audit.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))<latest_interpretation:raise ValueError("Full Audit must be newer than the final Interpretation")
        item.update({"status":a.status,"ended_at":utc_now(),"end_reason":a.reason,"stop_reason":a.stop_reason});state["round_control"]["active_round_id"]=None if a.status in {"checkpoint","completed"} else item["round_id"]
        summary={"schema_version":"1.0.0","round_id":item["round_id"],"status":item["status"],"node_status":dict(Counter(n["status"] for n in state["execution_graph"]["nodes"] if execution_round(n)==item["round_id"])),"new_insight_ids":[i["insight_id"] for i in latest(read_jsonl(Path(state["indices"]["insights"]["path"])),"insight_id").values() if i.get("round_id")==item["round_id"]],"open_next_actions":[x["action_id"] for x in latest(read_jsonl(Path(state["indices"]["next_actions"]["path"])),"action_id").values() if x.get("status")=="open"],"ended_at":item["ended_at"]};root=path.parent/"rounds"/item["round_id"];write_json(root/"round_summary.json",summary);atomic_text(root/"round_summary.md",f"# {item['round_id']} Summary\n\n- Status: {item['status']}\n- Stop reason: {item['stop_reason']}\n- Insights: {', '.join(summary['new_insight_ids']) or 'none'}\n- Open Next Actions: {', '.join(summary['open_next_actions']) or 'none'}\n");return item
    print(json.dumps(mutate(path,a,action),ensure_ascii=False,indent=2));return 0


def cmd_query(a:argparse.Namespace)->int:
    state=read_json(Path(a.state));ids=[x for x in (a.ids or "").split(",") if x]
    if a.kind=="brief":value=brief(state)
    elif a.kind=="node":value=[nodes(state)[x] for x in ids if x in nodes(state)]
    elif a.kind=="result":
        data={x["result_ref"]:x for x in read_jsonl(Path(state["indices"]["operator_results"]["path"]))};value=[data[x] for x in ids if x in data] if ids else list(data.values())[-a.limit:]
    elif a.kind=="insight":
        data=latest(read_jsonl(Path(state["indices"]["insights"]["path"])),"insight_id");value=[data[x] for x in ids if x in data] if ids else list(data.values())[-a.limit:]
    elif a.kind=="action":
        data=latest(read_jsonl(Path(state["indices"]["next_actions"]["path"])),"action_id");value=[data[x] for x in ids if x in data] if ids else list(data.values())[-a.limit:]
    else:value=balanced_candidates(state,min(a.limit,MAX_CANDIDATES),a.seed)
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0
def cmd_status(a:argparse.Namespace)->int:print(json.dumps(state_summary(read_json(Path(a.state))),ensure_ascii=False,indent=2));return 0
def cmd_runnable(a:argparse.Namespace)->int:print(json.dumps(runnable(read_json(Path(a.state))),ensure_ascii=False,indent=2));return 0


def lease_arg(p:argparse.ArgumentParser)->None:p.add_argument("--lease-token",required=True)
def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Manage a CONDUCTOR 0.1.0 multi-Round State DAG.");sub=p.add_subparsers(dest="command",required=True)
    x=sub.add_parser("init");x.add_argument("--input",required=True);x.add_argument("--endpoint",required=True);x.add_argument("--higher-is-better",action=argparse.BooleanOptionalAction,required=True);x.add_argument("--project",required=True);x.add_argument("--parallel-limit",type=int,required=True);x.add_argument("--run-id");x.add_argument("--output-dir");x.add_argument("--request");x.add_argument("--walltime-minutes",type=int,default=480);x.add_argument("--max-additional-nodes",type=int,default=300);x.add_argument("--interpretation-iterations",type=int,default=3);x.set_defaults(func=cmd_init)
    x=sub.add_parser("bootstrap");x.add_argument("--state",required=True);x.add_argument("--owner-id",required=True);x.add_argument("--lease-token");x.add_argument("--lease-minutes",type=int,default=30);x.add_argument("--force-takeover",action="store_true");x.add_argument("--takeover-reason");x.set_defaults(func=cmd_bootstrap)
    x=sub.add_parser("heartbeat");x.add_argument("--state",required=True);lease_arg(x);x.set_defaults(func=cmd_heartbeat)
    x=sub.add_parser("release-lease");x.add_argument("--state",required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_release)
    for name,func in (("plan-basic",cmd_plan_basic),("plan-initial-global",cmd_plan_global),("plan-initial-local",cmd_plan_local)):
        x=sub.add_parser(name);x.add_argument("--state",required=True);lease_arg(x);x.set_defaults(func=func)
    x=sub.add_parser("approve-basic-bundle");x.add_argument("--state",required=True);choice=x.add_mutually_exclusive_group(required=True);choice.add_argument("--approve",action="store_true");choice.add_argument("--reject",dest="approve",action="store_false");x.add_argument("--rationale",required=True);lease_arg(x);x.set_defaults(func=cmd_approve)
    x=sub.add_parser("plan-additional");x.add_argument("--state",required=True);x.add_argument("--count",type=int,required=True);x.add_argument("--seed",type=int,required=True);lease_arg(x);x.set_defaults(func=cmd_plan_additional)
    x=sub.add_parser("add");x.add_argument("--state",required=True);x.add_argument("--capability-id",required=True);x.add_argument("--depends-on");x.add_argument("--parameters-json");x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_add)
    x=sub.add_parser("start");x.add_argument("--state",required=True);x.add_argument("--node-id",required=True);x.add_argument("--retry",action="store_true");lease_arg(x);x.set_defaults(func=cmd_start)
    x=sub.add_parser("mark-terminal");x.add_argument("--state",required=True);x.add_argument("--node-id",required=True);x.add_argument("--status",choices=sorted(TERMINAL-{"succeeded"}),required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_terminal)
    x=sub.add_parser("record");x.add_argument("--state",required=True);x.add_argument("--event",required=True);lease_arg(x);x.set_defaults(func=cmd_record)
    x=sub.add_parser("add-interpretation");x.add_argument("--state",required=True);x.add_argument("--phase",choices=["initial_local","additional_exploration","deep_dive","human_directed"],default="human_directed");x.add_argument("--reason",required=True);x.add_argument("--focus");x.add_argument("--max-results",type=int,default=200);x.add_argument("--defer-pending",action="store_true");lease_arg(x);x.set_defaults(func=cmd_add_interpretation)
    x=sub.add_parser("insight-set-attention");x.add_argument("--state",required=True);x.add_argument("--insight-id",required=True);x.add_argument("--attention",choices=["priority","watch","background"],required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_insight_attention)
    x=sub.add_parser("next-action-set-status");x.add_argument("--state",required=True);x.add_argument("--action-id",required=True);x.add_argument("--status",choices=["open","closed"],required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_action_status)
    x=sub.add_parser("deprioritize-cluster");x.add_argument("--state",required=True);x.add_argument("--cluster-id",required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_deprioritize)
    x=sub.add_parser("finish-exploration");x.add_argument("--state",required=True);x.add_argument("--reason",required=True);lease_arg(x);x.set_defaults(func=cmd_finish_exploration)
    x=sub.add_parser("round-start");x.add_argument("--state",required=True);x.add_argument("--round-id",required=True);x.add_argument("--request",required=True);x.add_argument("--parallel-limit",type=int);x.add_argument("--walltime-minutes",type=int,default=480);x.add_argument("--max-additional-nodes",type=int,default=300);x.add_argument("--interpretation-iterations",type=int,default=3);lease_arg(x);x.set_defaults(func=cmd_round_start)
    x=sub.add_parser("round-end");x.add_argument("--state",required=True);x.add_argument("--round-id",required=True);x.add_argument("--status",choices=["paused","checkpoint","completed"],required=True);x.add_argument("--reason",required=True);x.add_argument("--stop-reason",choices=["budget_exhausted","no_eligible_work","human_checkpoint","completed_scope","abnormal_interruption","other"],required=True);lease_arg(x);x.set_defaults(func=cmd_round_end)
    x=sub.add_parser("audit");x.add_argument("--state",required=True);x.add_argument("--mode",choices=["quick","full"],default="quick");x.set_defaults(func=cmd_audit)
    x=sub.add_parser("rebuild-indices");x.add_argument("--state",required=True);lease_arg(x);x.set_defaults(func=cmd_rebuild_indices)
    x=sub.add_parser("query");x.add_argument("--state",required=True);x.add_argument("--kind",choices=["brief","node","result","insight","action","candidates"],required=True);x.add_argument("--ids");x.add_argument("--limit",type=int,default=20);x.add_argument("--seed",type=int,default=61453);x.set_defaults(func=cmd_query)
    x=sub.add_parser("status");x.add_argument("--state",required=True);x.set_defaults(func=cmd_status)
    x=sub.add_parser("runnable");x.add_argument("--state",required=True);x.set_defaults(func=cmd_runnable)
    return p


def main()->int:
    parsed=parser().parse_args()
    return parsed.func(parsed)
if __name__=="__main__":
    try:raise SystemExit(main())
    except Exception as exc:print(f"ERROR: {exc}",file=sys.stderr);raise SystemExit(1)
