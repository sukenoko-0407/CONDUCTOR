from __future__ import annotations
import argparse,json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from conductor_deepdive import ArtifactRegistry,build_chemical_axes,run_deep_dive
from conductor_stat_core import SchemaValidationError,atomic_write_json,call_local_jsonl,file_sha256,stable_id,validate_instance
from conductor_stat_core.contracts import prepare_output_directory,verify_request_inputs
ROOT=Path(__file__).resolve().parents[4];SKILL=Path(__file__).resolve().parents[1];SCHEMAS=ROOT/"CONDUCTOR_modules"/"schemas"
def _inputs(request:dict[str,Any],role:str)->list[Path]:return [Path(item["path"]).resolve() for item in request["inputs"] if item["role"]==role]
def _one(request:dict[str,Any],role:str)->Path:
    values=_inputs(request,role)
    if len(values)!=1:raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]
def _optional_csv(request:dict[str,Any],role:str)->pd.DataFrame:
    values=_inputs(request,role)
    if len(values)>1:raise ValueError(f"At most one {role!r} input is allowed")
    return pd.read_csv(values[0]) if values else pd.DataFrame()
def _read_jsonl(path:Path)->list[dict[str,Any]]:return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def _write_jsonl(rows:tuple[dict[str,Any],...],path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent);os.close(fd);temporary=Path(name)
    try:
        with temporary.open("w",encoding="utf-8",newline="\n") as handle:
            for row in rows:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n")
            handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception:temporary.unlink(missing_ok=True);raise
def _csv(frame:pd.DataFrame,path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent);os.close(fd);temporary=Path(name)
    try:frame.to_csv(temporary,index=False,lineterminator="\n");os.replace(temporary,path)
    except Exception:temporary.unlink(missing_ok=True);raise
def _artifact(output:Path,role:str,name:str,rows:int|None)->dict[str,Any]:
    digest=file_sha256(output/name);media="application/json" if name.endswith(".json") else "application/x-ndjson" if name.endswith(".jsonl") else "text/csv";return {"artifact_id":stable_id("ART",{"role":role,"sha256":digest}),"role":role,"path":name,"media_type":media,"schema":f"{role}@0.2.1","rows":rows,"sha256":digest}
def execute(args:argparse.Namespace)->dict[str,str]:
    request=json.loads(Path(args.request).resolve().read_text(encoding="utf-8"));validate_instance(request,SCHEMAS/"execution_request.schema.json")
    if request["identity"]["skill_name"]!="cs-deepdive" or request["parameters"].get("operation")!="deep_dive":raise SchemaValidationError("Request must target cs-deepdive operation deep_dive")
    verify_request_inputs(request);config_path=Path(request["config_path"]).resolve();config=yaml.safe_load(config_path.read_text(encoding="utf-8"));llm=config["llm"];deep=config["deep_dive"]
    findings=_read_jsonl(_one(request,"findings_scored"));observations=pd.concat([pd.read_csv(path) for path in _inputs(request,"score_observations")],ignore_index=True);compounds=pd.read_csv(_one(request,"compounds"),dtype={"compound_id":"string"});candidate_compounds=_optional_csv(request,"l4_candidates")
    if not candidate_compounds.empty:
        required={"compound_id","canonical_smiles"};missing=required-set(candidate_compounds)
        if missing:raise ValueError(f"l4_candidates is missing columns: {sorted(missing)}")
        compounds=pd.concat([compounds,candidate_compounds[["compound_id","canonical_smiles"]]],ignore_index=True).drop_duplicates("compound_id",keep="last")
    hammett=SKILL/"resources"/"hammett_constants.tsv";axes=build_chemical_axes(compounds,hammett)
    registry=ArtifactRegistry(observations,axes,_optional_csv(request,"deep_dive_candidates"),_optional_csv(request,"context_membership"),int(request["random_seed"]),int(deep["min_group_n"]))
    counter={"value":0}
    def invoke(task:str,finding:dict[str,Any],allowed:list[str],evidence:list[dict[str,Any]])->dict[str,Any]:
        counter["value"]+=1;payload={"schema_version":"0.2.1","request_id":stable_id("LLMREQ",{"task":task,"finding":finding["finding_id"],"call":counter["value"]}),"task":task,"finding_ids":[finding["finding_id"]],"allowed_templates":allowed,"evidence":evidence,"output_schema":{"type":"object"}};validate_instance(payload,SCHEMAS/"llm_request.schema.json");response,_=call_local_jsonl(str(llm["command"] or ""),payload,timeout_seconds=int(llm["timeout_seconds"]),schema_retries=int(llm["schema_retries"]),response_schema=SCHEMAS/"llm_response.schema.json");return response
    def selector(finding:dict[str,Any],allowed:list[str],tree:list[dict[str,Any]])->list[dict[str,Any]]:return invoke("select_deep_dive",finding,allowed,[{"finding":finding,"tree":tree}])["selections"]
    def summarizer(finding:dict[str,Any],tree:list[dict[str,Any]])->dict[str,Any]:
        response=invoke("summarize_deep_dive",finding,[],[{"finding":finding,"tree":tree}]);return {"narrative":response["narrative"],"citations":response["citations"]}
    result=run_deep_dive(findings,registry,selector,summarizer,max_depth=int(deep["max_depth"]),max_children=int(deep["max_children"]),max_tests_per_finding=int(deep["max_tests_per_finding"]),stop_after_consecutive_inconclusive=int(deep["stop_after_consecutive_inconclusive"]))
    output=prepare_output_directory(Path(args.output_dir),args.overwrite);_write_jsonl(result.nodes,output/"deep_dive_nodes.jsonl");_write_jsonl(result.summaries,output/"deep_dive_summaries.jsonl");_write_jsonl(result.updated_findings,output/"findings_deep_dived.jsonl");_csv(axes,output/"chemical_axes.csv")
    hammett_manifest={"version":"0.2.1","source":"Hansch-Leo-Taft 1991 compilation","license":"factual-data","sha256":file_sha256(hammett)};atomic_write_json(output/"hammett_manifest.json",hammett_manifest)
    for node in result.nodes:validate_instance(node,SCHEMAS/"deep_dive_node.schema.json")
    for finding in result.updated_findings:validate_instance(finding,SCHEMAS/"finding.schema.json")
    failure_fraction=result.failed_logical_calls/result.logical_calls if result.logical_calls else 0.0;status="failed" if failure_fraction>float(llm["max_failure_fraction"]) else "succeeded";files=[("deep_dive_nodes","deep_dive_nodes.jsonl",len(result.nodes)),("deep_dive_summaries","deep_dive_summaries.jsonl",len(result.summaries)),("findings_deep_dived","findings_deep_dived.jsonl",len(result.updated_findings)),("chemical_axes","chemical_axes.csv",len(axes)),("hammett_manifest","hammett_manifest.json",None)];artifacts=[_artifact(output,*item) for item in files];metrics={"finding_count":len(findings),"node_count":len(result.nodes),"logical_calls":result.logical_calls,"failed_logical_calls":result.failed_logical_calls,"failure_fraction":failure_fraction};manifest={"schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":status,"config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],"artifacts":artifacts,"metrics":metrics,"warnings":[] if status=="succeeded" else ["Local LLM logical-call failure fraction exceeded configured maximum"],"created_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")};atomic_write_json(output/"artifact_manifest.json",manifest);validate_instance(manifest,SCHEMAS/"artifact_manifest.schema.json");return {"status":status,"manifest":"artifact_manifest.json","primary":"findings_deep_dived.jsonl"}
def main()->int:
    parser=argparse.ArgumentParser(description="CONDUCTOR 0.2.1 deep dive");parser.add_argument("--request",required=True);parser.add_argument("--output-dir",required=True);parser.add_argument("--workers",type=int,default=0);parser.add_argument("--overwrite",action="store_true");args=parser.parse_args()
    try:response=execute(args)
    except (json.JSONDecodeError,yaml.YAMLError,SchemaValidationError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 2
    except (FileNotFoundError,ValueError,TypeError,KeyError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 3
    except Exception as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 4
    print(json.dumps(response,separators=(",",":")));return 4 if response["status"]=="failed" else 0
if __name__=="__main__":raise SystemExit(main())
