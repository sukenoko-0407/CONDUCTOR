from __future__ import annotations
import argparse, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from conductor_lens_l7 import run_l7
from conductor_stat_core import SchemaValidationError, atomic_write_json, file_sha256, stable_id, validate_instance
from conductor_stat_core.contracts import prepare_output_directory, verify_request_inputs

ROOT=Path(__file__).resolve().parents[4]; SCHEMAS=ROOT/"CONDUCTOR_modules"/"schemas"
def _input(request:dict[str,Any],role:str)->Path:
    values=[Path(item["path"]).resolve() for item in request["inputs"] if item["role"]==role]
    if len(values)!=1: raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]
def _csv(frame:pd.DataFrame,path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent); os.close(fd); temporary=Path(name)
    try: frame.to_csv(temporary,index=False,lineterminator="\n"); os.replace(temporary,path)
    except Exception: temporary.unlink(missing_ok=True); raise
def _jsonl(rows:tuple[dict[str,Any],...],path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent); os.close(fd); temporary=Path(name)
    try:
        with temporary.open("w",encoding="utf-8",newline="\n") as handle:
            for row in rows: handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception: temporary.unlink(missing_ok=True); raise
def _artifact(output:Path,role:str,name:str,rows:int)->dict[str,Any]:
    digest=file_sha256(output/name); media="application/x-ndjson" if name.endswith(".jsonl") else "text/csv"; return {"artifact_id":stable_id("ART",{"role":role,"sha256":digest}),"role":role,"path":name,"media_type":media,"schema":f"{role}@0.2.1","rows":rows,"sha256":digest}
def execute(args:argparse.Namespace)->dict[str,str]:
    request=json.loads(Path(args.request).resolve().read_text(encoding="utf-8")); validate_instance(request,SCHEMAS/"execution_request.schema.json")
    if request["identity"]["skill_name"]!="cs-lens-l7" or request["parameters"].get("operation")!="l7": raise SchemaValidationError("Request must target cs-lens-l7 operation l7")
    verify_request_inputs(request); config_path=Path(request["config_path"]).resolve(); config=yaml.safe_load(config_path.read_text(encoding="utf-8")); lens=config["lenses"]["l7"]; statistics=config["statistics"]
    result=run_l7(pd.read_csv(_input(request,"fragment_observations")),pd.read_csv(_input(request,"endpoint_table"),dtype={"compound_id":"string"}),request["endpoint_id"],run_seed=int(request["random_seed"]),min_common_r_groups=int(lens["min_common_r_groups"]),min_abs_spearman_rho=float(lens["min_abs_spearman_rho"]),screen_permutations=int(statistics["screen_permutations"]),final_permutations=int(statistics["final_permutations"]),screen_p_max=float(statistics["screen_p_max"]),report_q_max=float(statistics["report_q_max"]))
    output=prepare_output_directory(Path(args.output_dir),args.overwrite); files=[("l7_evidence","l7_evidence.csv",result.evidence),("l7_tests","l7_tests.csv",result.tests),("score_observations","score_observations.csv",result.score_observations)]
    for _,name,frame in files: _csv(frame,output/name)
    _jsonl(result.findings,output/"findings.jsonl")
    for finding in result.findings: validate_instance(finding,SCHEMAS/"finding.schema.json")
    artifacts=[_artifact(output,role,name,len(frame)) for role,name,frame in files]+[_artifact(output,"findings","findings.jsonl",len(result.findings))]
    manifest={"schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":"succeeded","config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],"artifacts":artifacts,"metrics":result.metrics,"warnings":[],"created_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")}; atomic_write_json(output/"artifact_manifest.json",manifest); validate_instance(manifest,SCHEMAS/"artifact_manifest.schema.json"); return {"status":"succeeded","manifest":"artifact_manifest.json","primary":"findings.jsonl"}
def main()->int:
    parser=argparse.ArgumentParser(description="CONDUCTOR 0.2.1 L7 lens"); parser.add_argument("--request",required=True); parser.add_argument("--output-dir",required=True); parser.add_argument("--workers",type=int,default=0); parser.add_argument("--overwrite",action="store_true"); args=parser.parse_args()
    try: response=execute(args)
    except (json.JSONDecodeError,yaml.YAMLError,SchemaValidationError) as exc: print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr); return 2
    except (FileNotFoundError,ValueError,TypeError,KeyError) as exc: print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr); return 3
    except Exception as exc: print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr); return 4
    print(json.dumps(response,separators=(",",":"))); return 0
if __name__=="__main__": raise SystemExit(main())
