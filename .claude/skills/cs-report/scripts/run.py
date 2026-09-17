from __future__ import annotations
import argparse,json,os,sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from conductor_report import CitationError,EvidenceRegistry,build_entity_components,validate_component_narrative,validate_finding_tests
from conductor_report.report import component_id
from conductor_stat_core import SchemaValidationError,atomic_write_json,call_local_jsonl,file_sha256,stable_id,validate_instance
from conductor_stat_core.contracts import prepare_output_directory,verify_request_inputs
ROOT=Path(__file__).resolve().parents[4];SCHEMAS=ROOT/"CONDUCTOR_modules"/"schemas"
def _inputs(request:dict[str,Any],role:str)->list[Path]:return [Path(item["path"]).resolve() for item in request["inputs"] if item["role"]==role]
def _one(request:dict[str,Any],role:str)->Path:
    values=_inputs(request,role)
    if len(values)!=1:raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]
def _read_jsonl(path:Path)->list[dict[str,Any]]:return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def _write_jsonl(rows:list[dict[str,Any]],path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent);os.close(fd);temporary=Path(name)
    try:
        with temporary.open("w",encoding="utf-8",newline="\n") as handle:
            for row in rows:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n")
            handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception:temporary.unlink(missing_ok=True);raise
def _artifact(output:Path,role:str,name:str,rows:int|None)->dict[str,Any]:
    digest=file_sha256(output/name);media="text/markdown" if name.endswith(".md") else "application/x-ndjson" if name.endswith(".jsonl") else "application/json";return {"artifact_id":stable_id("ART",{"role":role,"sha256":digest}),"role":role,"path":name,"media_type":media,"schema":f"{role}@0.2.1","rows":rows,"sha256":digest}
def execute(args:argparse.Namespace)->dict[str,str]:
    request=json.loads(Path(args.request).resolve().read_text(encoding="utf-8"));validate_instance(request,SCHEMAS/"execution_request.schema.json")
    if request["identity"]["skill_name"]!="cs-report" or request["parameters"].get("operation")!="report":raise SchemaValidationError("Request must target cs-report operation report")
    verify_request_inputs(request);config_path=Path(request["config_path"]).resolve();config=yaml.safe_load(config_path.read_text(encoding="utf-8"));llm=config["llm"];findings=_read_jsonl(_one(request,"findings_deep_dived"));table_paths=_inputs(request,"evidence_table");manifests=[json.loads(path.read_text(encoding="utf-8")) for path in _inputs(request,"artifact_manifest")];hashes={Path(item["path"]).name:str(item["sha256"]) for manifest in manifests for item in manifest.get("artifacts",[])};run_root=Path(request["parameters"].get("run_root",ROOT)).resolve();registry=EvidenceRegistry.load(run_root,table_paths,hashes);compounds=pd.read_csv(_one(request,"compounds"),dtype={"compound_id":"string"});entity_ids=set(compounds["compound_id"].astype(str));database_inputs=_inputs(request,"mmp_database")
    if len(database_inputs)>1:raise ValueError("At most one mmp_database input is allowed")
    pair_ids=None
    if database_inputs:
        with sqlite3.connect(f"file:{database_inputs[0].as_posix()}?mode=ro",uri=True) as connection:pair_ids={str(row[0]) for row in connection.execute("SELECT pair_id FROM pairs")}
    validation_errors=[]
    try:validate_finding_tests(findings,registry,entity_ids,pair_ids)
    except CitationError as exc:validation_errors.append(str(exc))
    by_id={item["finding_id"]:item for item in findings};components=build_entity_components(findings);drafts=[];logical_calls=0;failed_calls=0;warnings=[]
    for identifiers in components:
        component_findings=[by_id[value] for value in identifiers];available={citation["citation_id"]:citation["table_ref"] for finding in component_findings for citation in finding["citations"]}
        test_ids={test["test_id"] for finding in component_findings for test in finding["tests"]}
        for name,frame in registry.tables.items():
            if "test_id" not in frame:continue
            for row in frame.loc[frame["test_id"].astype(str).isin(test_ids)].to_dict(orient="records"):
                citation_id=stable_id("CIT",{"table":name,"row_id":str(row["row_id"])});available[citation_id]=f"{name}#row_id={row['row_id']}"
        evidence=[{"citation_id":citation_id,"table_ref":reference,"row":registry.row(reference)} for citation_id,reference in sorted(available.items())];identifier=component_id(identifiers);payload={"schema_version":"0.2.1","request_id":stable_id("LLMREQ",{"task":"compose_component_narrative","component":identifier}),"task":"compose_component_narrative","finding_ids":identifiers,"allowed_templates":[],"evidence":[{"findings":component_findings,"citeable_rows":evidence}],"output_schema":{"type":"object"}}
        try:
            response,_=call_local_jsonl(str(llm["command"] or ""),payload,timeout_seconds=int(llm["timeout_seconds"]),schema_retries=int(llm["schema_retries"]),response_schema=SCHEMAS/"llm_response.schema.json");logical_calls+=1;text=response["narrative"];citations=response["citations"]
        except Exception as exc:
            logical_calls+=1;failed_calls+=1;text=None;citations=[];warnings.append(f"{identifier}: Local LLM failed: {exc}")
        draft={"component_id":identifier,"finding_ids":identifiers,"narrative":text,"citations":citations};drafts.append(draft)
        if text is not None:
            try:warnings.extend(f"{identifier}: unused citation {value}" for value in validate_component_narrative(identifier,text,citations,available,registry))
            except CitationError as exc:validation_errors.append(str(exc))
    failure_fraction=failed_calls/logical_calls if logical_calls else 0.0
    if failure_fraction>float(llm["max_failure_fraction"]):validation_errors.append(f"Local LLM logical-call failure fraction {failure_fraction:.6f} exceeds {llm['max_failure_fraction']}")
    status="failed" if validation_errors else "succeeded";report={"schema_version":"0.2.1","status":status,"endpoint_id":request["endpoint_id"],"components":drafts,"finding_count":len(findings)};validation={"status":status,"errors":validation_errors,"warnings":warnings,"logical_calls":logical_calls,"failed_logical_calls":failed_calls,"failure_fraction":failure_fraction}
    output=prepare_output_directory(Path(args.output_dir),args.overwrite);_write_jsonl(findings,output/"final_findings.jsonl");_write_jsonl(drafts,output/"narrative_drafts.jsonl");atomic_write_json(output/"citation_validation.json",validation);atomic_write_json(output/"report.json",report)
    markdown=["# CONDUCTOR 0.2.1 Report",""]
    for draft in drafts:
        if draft["narrative"] is not None:markdown.extend([f"## {draft['component_id']}","",str(draft["narrative"]),""])
    (output/"report.md").write_text("\n".join(markdown),encoding="utf-8",newline="\n")
    files=[("final_findings","final_findings.jsonl",len(findings)),("narrative_drafts","narrative_drafts.jsonl",len(drafts)),("citation_validation","citation_validation.json",None),("report_json","report.json",None),("report_markdown","report.md",None)];artifacts=[_artifact(output,*item) for item in files];metrics={"finding_count":len(findings),"component_count":len(components),"citation_error_count":len(validation_errors),"logical_calls":logical_calls,"failed_logical_calls":failed_calls};manifest={"schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":status,"config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],"artifacts":artifacts,"metrics":metrics,"warnings":warnings,"created_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")};atomic_write_json(output/"artifact_manifest.json",manifest);validate_instance(manifest,SCHEMAS/"artifact_manifest.schema.json");return {"status":status,"manifest":"artifact_manifest.json","primary":"report.md"}
def main()->int:
    parser=argparse.ArgumentParser(description="CONDUCTOR 0.2.1 report");parser.add_argument("--request",required=True);parser.add_argument("--output-dir",required=True);parser.add_argument("--workers",type=int,default=0);parser.add_argument("--overwrite",action="store_true");args=parser.parse_args()
    try:response=execute(args)
    except (json.JSONDecodeError,yaml.YAMLError,SchemaValidationError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 2
    except (FileNotFoundError,ValueError,TypeError,KeyError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 3
    except Exception as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 4
    print(json.dumps(response,separators=(",",":")));return 5 if response["status"]=="failed" else 0
if __name__=="__main__":raise SystemExit(main())
