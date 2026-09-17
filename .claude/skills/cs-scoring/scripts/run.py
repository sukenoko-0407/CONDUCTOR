from __future__ import annotations
import argparse,json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from conductor_scoring import score_findings
from conductor_stat_core import SchemaValidationError,atomic_write_json,file_sha256,stable_id,validate_instance
from conductor_stat_core.contracts import prepare_output_directory,verify_request_inputs
ROOT=Path(__file__).resolve().parents[4];SCHEMAS=ROOT/"CONDUCTOR_modules"/"schemas"
def _inputs(request:dict[str,Any],role:str)->list[Path]:return [Path(item["path"]).resolve() for item in request["inputs"] if item["role"]==role]
def _one(request:dict[str,Any],role:str)->Path:
    values=_inputs(request,role)
    if len(values)!=1:raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]
def _jsonl_read(paths:list[Path])->list[dict[str,Any]]:
    return [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def _csv(frame:pd.DataFrame,path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent);os.close(fd);temporary=Path(name)
    try:frame.to_csv(temporary,index=False,lineterminator="\n");os.replace(temporary,path)
    except Exception:temporary.unlink(missing_ok=True);raise
def _jsonl(rows:tuple[dict[str,Any],...],path:Path)->None:
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent);os.close(fd);temporary=Path(name)
    try:
        with temporary.open("w",encoding="utf-8",newline="\n") as handle:
            for row in rows:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n")
            handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception:temporary.unlink(missing_ok=True);raise
def _artifact(output:Path,role:str,name:str,rows:int|None)->dict[str,Any]:
    digest=file_sha256(output/name);media="application/json" if name.endswith(".json") else "application/x-ndjson" if name.endswith(".jsonl") else "text/csv";return {"artifact_id":stable_id("ART",{"role":role,"sha256":digest}),"role":role,"path":name,"media_type":media,"schema":f"{role}@0.2.1","rows":rows,"sha256":digest}
def _table(path:Path)->pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower()==".parquet" else pd.read_csv(path,dtype={"compound_id":"string"})
def _confounders(request:dict[str,Any])->pd.DataFrame:
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold
    registry_paths=_inputs(request,"feature_spaces")
    if len(registry_paths)!=1: raise ValueError("Exactly one feature_spaces input is required for confounder adjustment")
    payloads:list[Path]=[]
    registry=json.loads(registry_paths[0].read_text(encoding="utf-8")); observed=next((item for item in registry["spaces"] if str(item["space_id"])=="D001"),None)
    if observed is None: raise ValueError("D001 is required for MW/cLogP/TPSA adjustment")
    payloads.append(Path(observed["path"]).resolve())
    for registry_path in _inputs(request,"candidate_feature_spaces"):
        candidate_registry=json.loads(registry_path.read_text(encoding="utf-8")); candidate=next((item for item in candidate_registry["spaces"] if str(item["space_id"])=="D001"),None)
        if candidate is not None: payloads.append(Path(candidate["candidate_path"]).resolve())
    frames=[]
    for payload in payloads:
        frame=_table(payload); required={"compound_id","input_smiles","rdkit2d__MolWt","rdkit2d__MolLogP","rdkit2d__TPSA"}; missing=required-set(frame.columns)
        if missing: raise ValueError(f"D001 payload is missing confounder columns: {sorted(missing)}")
        frames.append(frame[list(required)].copy())
    merged=pd.concat(frames,ignore_index=True); merged["compound_id"]=merged["compound_id"].astype(str)
    duplicate=merged.groupby("compound_id",sort=False).filter(lambda group:len(group)>1)
    if not duplicate.empty:
        for _,group in duplicate.groupby("compound_id",sort=False):
            for column in required-{"compound_id"}:
                if group[column].astype(str).nunique(dropna=False)>1: raise ValueError(f"Conflicting D001 rows for {group.iloc[0]['compound_id']}")
        merged=merged.drop_duplicates("compound_id",keep="first")
    scaffolds=[]
    for row in merged.itertuples(index=False):
        molecule=Chem.MolFromSmiles(str(row.input_smiles))
        if molecule is None: raise ValueError(f"Invalid D001 input_smiles for {row.compound_id}")
        scaffold=MurckoScaffold.GetScaffoldForMol(molecule); key=Chem.MolToSmiles(scaffold,canonical=True) if scaffold.GetNumAtoms() else ""; scaffolds.append(key or f"ACYCLIC:{Chem.MolToSmiles(molecule,canonical=True)}")
    return pd.DataFrame({"compound_id":merged["compound_id"].tolist(),"mw":pd.to_numeric(merged["rdkit2d__MolWt"],errors="coerce"),"clogp":pd.to_numeric(merged["rdkit2d__MolLogP"],errors="coerce"),"tpsa":pd.to_numeric(merged["rdkit2d__TPSA"],errors="coerce"),"scaffold_id":scaffolds})
def execute(args:argparse.Namespace)->dict[str,str]:
    request=json.loads(Path(args.request).resolve().read_text(encoding="utf-8"));validate_instance(request,SCHEMAS/"execution_request.schema.json")
    if request["identity"]["skill_name"]!="cs-scoring" or request["parameters"].get("operation")!="score":raise SchemaValidationError("Request must target cs-scoring operation score")
    verify_request_inputs(request);finding_paths=_inputs(request,"findings");observation_paths=_inputs(request,"score_observations")
    if not finding_paths or not observation_paths:raise ValueError("At least one findings and score_observations input is required")
    config_path=Path(request["config_path"]).resolve();config=yaml.safe_load(config_path.read_text(encoding="utf-8"));observations=pd.concat([pd.read_csv(path) for path in observation_paths],ignore_index=True);scoring=config["scoring"]
    result=score_findings(_jsonl_read(finding_paths),observations,pd.read_csv(_one(request,"endpoint_table")),request["endpoint_id"],run_seed=int(request["random_seed"]),confounders=_confounders(request),bootstrap_iterations=int(config["statistics"]["bootstrap_iterations"]),statistical_strength_min=float(scoring["statistical_strength_min"]),robustness_min=float(scoring["robustness_min"]),display_k=int(scoring["display_k"]))
    output=prepare_output_directory(Path(args.output_dir),args.overwrite);_jsonl(result.findings,output/"findings_scored.jsonl");_csv(result.scores,output/"scores.csv");atomic_write_json(output/"scoring_gate.json",result.gate)
    for finding in result.findings:validate_instance(finding,SCHEMAS/"finding.schema.json")
    artifacts=[_artifact(output,"findings_scored","findings_scored.jsonl",len(result.findings)),_artifact(output,"scores","scores.csv",len(result.scores)),_artifact(output,"scoring_gate","scoring_gate.json",None)];status=result.gate["status"];manifest={"schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":status,"config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],"artifacts":artifacts,"metrics":result.gate,"warnings":[] if status=="succeeded" else ["Fewer than display_k Findings passed fixed scoring gates"],"created_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")};atomic_write_json(output/"artifact_manifest.json",manifest);validate_instance(manifest,SCHEMAS/"artifact_manifest.schema.json");return {"status":status,"manifest":"artifact_manifest.json","primary":"findings_scored.jsonl"}
def main()->int:
    parser=argparse.ArgumentParser(description="CONDUCTOR 0.2.1 scoring");parser.add_argument("--request",required=True);parser.add_argument("--output-dir",required=True);parser.add_argument("--workers",type=int,default=0);parser.add_argument("--overwrite",action="store_true");args=parser.parse_args()
    try:response=execute(args)
    except (json.JSONDecodeError,yaml.YAMLError,SchemaValidationError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 2
    except (FileNotFoundError,ValueError,TypeError,KeyError) as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 3
    except Exception as exc:print(json.dumps({"status":"failed","error":str(exc)}),file=sys.stderr);return 4
    print(json.dumps(response,separators=(",",":")));return 0
if __name__=="__main__":raise SystemExit(main())
