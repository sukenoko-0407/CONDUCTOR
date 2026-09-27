from __future__ import annotations
import argparse,json,os,sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from conductor_report import CitationError,EvidenceRegistry,build_entity_components,render_finding_html,render_html_report,validate_component_response,validate_finding_tests
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
def _score_observations(paths:list[Path])->dict[str,list[dict[str,Any]]]:
    result:dict[str,list[dict[str,Any]]]={}
    for path in paths:
        try:frame=pd.read_csv(path)
        except pd.errors.EmptyDataError:continue
        if frame.empty:continue
        if "finding_key" not in frame.columns:raise ValueError(f"score_observations is missing finding_key: {path}")
        for row in frame.to_dict(orient="records"):result.setdefault(str(row["finding_key"]),[]).append(row)
    return result
def _fragment_smiles(connection:sqlite3.Connection)->dict[str,str]:
    result:dict[str,str]={}
    for transform_class,variable_smiles in connection.execute(
        'SELECT DISTINCT "class",variable_smiles FROM fragmentations '
        "WHERE status='accepted' ORDER BY \"class\",variable_smiles"
    ):
        fragment_id=stable_id("FRAG",{"schema_version":"0.2.1","class":str(transform_class),"variable_smiles":str(variable_smiles)})
        previous=result.setdefault(fragment_id,str(variable_smiles))
        if previous!=str(variable_smiles):raise ValueError(f"Conflicting fragment structure for {fragment_id}")
    return result
def _artifact(output:Path,role:str,name:str,rows:int|None)->dict[str,Any]:
    digest=file_sha256(output/name);media="text/html" if name.endswith(".html") else "text/markdown" if name.endswith(".md") else "application/x-ndjson" if name.endswith(".jsonl") else "application/json";return {"artifact_id":stable_id("ART",{"role":role,"sha256":digest}),"role":role,"path":name,"media_type":media,"schema":f"{role}@0.2.1","rows":rows,"sha256":digest}
def _lens_telemetry(manifests:list[dict[str,Any]])->list[dict[str,Any]]:
    rows=[]
    for manifest in manifests:
        producer=manifest.get("producer") or {};metrics=manifest.get("metrics") or {};work=metrics.get("work_estimate")
        if not isinstance(work,dict):continue
        node_id=str(producer.get("node_id",""));actual=metrics.get("actual_wall_seconds");estimated=work.get("estimated_seconds");ratio=metrics.get("estimate_actual_ratio");observed=metrics.get("observed_units_per_second");detail=work.get("detail") or {}
        if ratio is None and isinstance(actual,(int,float)) and actual>0 and isinstance(estimated,(int,float)):ratio=float(estimated)/float(actual)
        if observed is None and isinstance(actual,(int,float)) and actual>0 and isinstance(work.get("unit_count"),(int,float)):observed=float(work["unit_count"])/float(actual)
        evaluation="not_measured" if ratio is None else "unsafe_underestimate" if float(ratio)<1.0 else "conservative" if float(ratio)>3.0 else "within_band"
        rows.append({"node_id":node_id,"lens":node_id.removeprefix("P03-") or node_id,"engine":detail.get("engine") or detail.get("correlation_engine"),"cost_model_version":detail.get("cost_model_version"),"unit_count":work.get("unit_count"),"estimated_seconds":estimated,"actual_wall_seconds":actual,"estimate_actual_ratio":ratio,"observed_units_per_second":observed,"configured_units_per_second":detail.get("configured_units_per_second"),"evaluation":evaluation})
    return sorted(rows,key=lambda item:(str(item["lens"]),str(item["node_id"])))
def execute(args:argparse.Namespace)->dict[str,str]:
    request=json.loads(Path(args.request).resolve().read_text(encoding="utf-8"));validate_instance(request,SCHEMAS/"execution_request.schema.json")
    if request["identity"]["skill_name"]!="cs-report" or request["parameters"].get("operation")!="report":raise SchemaValidationError("Request must target cs-report operation report")
    verify_request_inputs(request);config_path=Path(request["config_path"]).resolve();config=yaml.safe_load(config_path.read_text(encoding="utf-8"));llm=config["llm"];findings=_read_jsonl(_one(request,"findings_deep_dived"));table_paths=_inputs(request,"evidence_table");manifests=[json.loads(path.read_text(encoding="utf-8")) for path in _inputs(request,"artifact_manifest")];hashes={Path(item["path"]).name:str(item["sha256"]) for manifest in manifests for item in manifest.get("artifacts",[])};run_root=Path(request["parameters"].get("run_root",ROOT)).resolve();registry=EvidenceRegistry.load(run_root,table_paths,hashes);compounds=pd.read_csv(_one(request,"compounds"),dtype={"compound_id":"string"});entity_ids=set(compounds["compound_id"].astype(str));compound_smiles=dict(zip(compounds["compound_id"].astype(str),compounds["canonical_smiles"].astype(str),strict=True));observations_by_finding=_score_observations(_inputs(request,"score_observations"));database_inputs=_inputs(request,"mmp_database")
    if len(database_inputs)>1:raise ValueError("At most one mmp_database input is allowed")
    pair_ids=None;fragment_smiles={}
    if database_inputs:
        with sqlite3.connect(f"file:{database_inputs[0].as_posix()}?mode=ro",uri=True) as connection:
            pair_ids={str(row[0]) for row in connection.execute("SELECT pair_id FROM pairs")};fragment_smiles=_fragment_smiles(connection)
    validation_errors=[]
    try:validate_finding_tests(findings,registry,entity_ids,pair_ids)
    except CitationError as exc:validation_errors.append(str(exc))
    by_id={item["finding_id"]:item for item in findings};components=build_entity_components(findings);drafts=[];logical_calls=0;failed_calls=0;warnings=[];narrative_failures=[];semantic_retry_count=0;provider_attempt_count=0
    for identifiers in components:
        component_findings=[by_id[value] for value in identifiers];available={citation["citation_id"]:citation["table_ref"] for finding in component_findings for citation in finding["citations"]}
        test_ids={test["test_id"] for finding in component_findings for test in finding["tests"]}
        for name,frame in registry.tables.items():
            if "test_id" not in frame:continue
            for row in frame.loc[frame["test_id"].astype(str).isin(test_ids)].to_dict(orient="records"):
                citation_id=stable_id("CIT",{"table":name,"row_id":str(row["row_id"])});available[citation_id]=f"{name}#row_id={row['row_id']}"
        evidence=[{"citation_id":citation_id,"table_ref":reference,"row":registry.row(reference)} for citation_id,reference in sorted(available.items())];identifier=component_id(identifiers);logical_calls+=1;text=None;citations=[];accepted=False;feedback=None
        for semantic_attempt in range(1,int(llm["schema_retries"])+2):
            request_evidence=[{"findings":component_findings,"citeable_rows":evidence},{"generation_constraints":{"uncited_numeric_tokens":"forbidden","connected_component_phrase":"この連結成分","forbidden_examples":["1連結成分","一つ目","第1"]}}]
            if feedback is not None:request_evidence.append({"validation_feedback":{"previous_response_rejected":True,"reason":feedback,"required_action":"引用行に存在しない数値を全て除く。安全に書けなければnarrativeをnull、citationsを空配列にする。"}})
            payload={"schema_version":"0.2.1","request_id":stable_id("LLMREQ",{"task":"compose_component_narrative","component":identifier,"semantic_attempt":semantic_attempt}),"task":"compose_component_narrative","finding_ids":identifiers,"allowed_templates":[],"evidence":request_evidence,"output_schema":{"type":"object"}}
            try:
                response,provider_attempts=call_local_jsonl(str(llm["command"] or ""),payload,timeout_seconds=int(llm["timeout_seconds"]),schema_retries=int(llm["schema_retries"]),response_schema=SCHEMAS/"llm_response.schema.json");provider_attempt_count+=provider_attempts
                unused=validate_component_response(identifier,response,available,registry);text=response["narrative"];citations=response["citations"];warnings.extend(f"{identifier}: unused citation {value}" for value in unused);accepted=True;break
            except CitationError as exc:
                feedback=str(exc);semantic_retry_count+=1;narrative_failures.append({"component_id":identifier,"finding_ids":identifiers,"task":"compose_component_narrative","stage":"citation_validation","semantic_attempt":semantic_attempt,"error_type":type(exc).__name__,"error":str(exc),"final":semantic_attempt==int(llm["schema_retries"])+1});warnings.append(f"{identifier}: rejected narrative attempt {semantic_attempt}: {exc}")
            except Exception as exc:
                attempts=int(getattr(exc,"attempts",1));provider_attempt_count+=attempts;narrative_failures.append({"component_id":identifier,"finding_ids":identifiers,"task":"compose_component_narrative","stage":"provider_or_schema","semantic_attempt":semantic_attempt,"error_type":type(exc).__name__,"error":str(exc),"attempt_errors":list(getattr(exc,"errors",())),"final":True});warnings.append(f"{identifier}: Local LLM failed: {exc}");break
        if not accepted:
            failed_calls+=1;text=None;citations=[];warnings.append(f"{identifier}: narrative was replaced by fail-closed null")
        drafts.append({"component_id":identifier,"finding_ids":identifiers,"narrative":text,"citations":citations,"citation_refs":[{"citation_id":value,"table_ref":available[value]} for value in citations]})
    failure_fraction=failed_calls/logical_calls if logical_calls else 0.0
    if failure_fraction>float(llm["max_failure_fraction"]):validation_errors.append(f"Local LLM logical-call failure fraction {failure_fraction:.6f} exceeds {llm['max_failure_fraction']}")
    rejected_narrative_count=sum(item["stage"]=="citation_validation" for item in narrative_failures);provider_failure_event_count=sum(item["stage"]=="provider_or_schema" for item in narrative_failures)
    status="failed" if validation_errors else "succeeded";created_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");telemetry=_lens_telemetry(manifests);display_k=int((config.get("scoring") or {}).get("display_k",10));visualization={"version":"lens_svg_v1","structure_engine":"rdkit-2026.3.4","score_observation_count":sum(len(rows) for rows in observations_by_finding.values()),"compound_structure_count":len(compound_smiles),"fragment_structure_count":len(fragment_smiles)};report={"schema_version":"0.2.1","status":status,"run_id":request["identity"]["run_id"],"endpoint_id":request["endpoint_id"],"created_at":created_at,"components":drafts,"finding_count":len(findings),"display_k":display_k,"lens_telemetry":telemetry,"visualization":visualization};validation={"status":status,"errors":validation_errors,"warnings":warnings,"logical_calls":logical_calls,"failed_logical_calls":failed_calls,"failure_fraction":failure_fraction,"semantic_retry_count":semantic_retry_count,"rejected_narrative_count":rejected_narrative_count,"provider_failure_event_count":provider_failure_event_count}
    output=prepare_output_directory(Path(args.output_dir),args.overwrite);_write_jsonl(findings,output/"final_findings.jsonl");_write_jsonl(drafts,output/"narrative_drafts.jsonl");_write_jsonl(narrative_failures,output/"llm_narrative_failures.jsonl");atomic_write_json(output/"citation_validation.json",validation);atomic_write_json(output/"report.json",report)
    markdown=["# CONDUCTOR 0.2.1 Report",""]
    for draft in drafts:
        if draft["narrative"] is not None:markdown.extend([f"## {draft['component_id']}","",str(draft["narrative"]),""])
    (output/"report.md").write_text("\n".join(markdown),encoding="utf-8",newline="\n")
    reportable=sorted((item for item in findings if (item.get("state") or {}).get("pipeline")=="reportable"),key=lambda item:(int((item.get("scores") or {}).get("rank") or 2**31-1),-float((item.get("scores") or {}).get("composite") or 0.0),str(item.get("finding_id",""))))
    important=reportable[:max(0,display_k)];evidence_by_ref={}
    for finding in important:
        for citation in finding.get("citations") or []:
            reference=str(citation.get("table_ref",""))
            if reference and reference not in evidence_by_ref:evidence_by_ref[reference]=registry.row(reference)
    detail_dir=output/"finding_reports";detail_dir.mkdir(parents=True,exist_ok=True);detail_paths={}
    for finding in important:
        finding_id=str(finding["finding_id"])
        if not finding_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in finding_id):raise ValueError(f"Unsafe finding_id for HTML path: {finding_id!r}")
        relative=f"finding_reports/{finding_id}.html";detail_paths[finding_id]=relative
        (output/relative).write_text(render_finding_html(finding,validation,run_id=request["identity"]["run_id"],endpoint_id=request["endpoint_id"],created_at=created_at,evidence_by_ref=evidence_by_ref,observations_by_finding=observations_by_finding,compound_smiles=compound_smiles,fragment_smiles=fragment_smiles,overview_href="../report.html"),encoding="utf-8",newline="\n")
    (output/"report.html").write_text(render_html_report(report,findings,validation,run_id=request["identity"]["run_id"],created_at=created_at,evidence_by_ref=evidence_by_ref,observations_by_finding=observations_by_finding,compound_smiles=compound_smiles,fragment_smiles=fragment_smiles,finding_report_paths=detail_paths),encoding="utf-8",newline="\n")
    files=[("final_findings","final_findings.jsonl",len(findings)),("narrative_drafts","narrative_drafts.jsonl",len(drafts)),("llm_narrative_failures","llm_narrative_failures.jsonl",len(narrative_failures)),("citation_validation","citation_validation.json",None),("report_json","report.json",None),("report_markdown","report.md",None),("report_html","report.html",None)]+[("finding_report_html",detail_paths[str(finding["finding_id"])],None) for finding in important];artifacts=[_artifact(output,*item) for item in files];metrics={"finding_count":len(findings),"finding_report_count":len(important),"finding_visual_count":len(important),"visualization_version":"lens_svg_v1","component_count":len(components),"citation_error_count":len(validation_errors),"logical_calls":logical_calls,"failed_logical_calls":failed_calls,"failure_fraction":failure_fraction,"semantic_retry_count":semantic_retry_count,"rejected_narrative_count":rejected_narrative_count,"provider_failure_event_count":provider_failure_event_count,"provider_attempt_count":provider_attempt_count,"lens_telemetry_count":len(telemetry),"unsafe_underestimate_count":sum(item["evaluation"]=="unsafe_underestimate" for item in telemetry)};manifest={"schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":status,"config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],"artifacts":artifacts,"metrics":metrics,"warnings":warnings,"created_at":created_at};atomic_write_json(output/"artifact_manifest.json",manifest);validate_instance(manifest,SCHEMAS/"artifact_manifest.schema.json");return {"status":status,"manifest":"artifact_manifest.json","primary":"report.html"}
def main()->int:
    parser=argparse.ArgumentParser(description="CONDUCTOR 0.2.1 report");parser.add_argument("--request",required=True);parser.add_argument("--output-dir",required=True);parser.add_argument("--workers",type=int,default=0);parser.add_argument("--overwrite",action="store_true");args=parser.parse_args()
    try:response=execute(args)
    except (json.JSONDecodeError,yaml.YAMLError,SchemaValidationError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 2
    except (FileNotFoundError,ValueError,TypeError,KeyError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 3
    except Exception as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 4
    print(json.dumps(response,separators=(",",":")));return 5 if response["status"]=="failed" else 0
if __name__=="__main__":raise SystemExit(main())
