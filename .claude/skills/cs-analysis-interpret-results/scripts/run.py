from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from render import render_html, render_markdown, render_quality


SKILL_DIR=Path(__file__).resolve().parents[1]
CAPABILITY=json.loads((SKILL_DIR/"capability.json").read_text(encoding="utf-8"))


def now()->str:return datetime.now(timezone.utc).isoformat()
def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def value_hash(value:Any)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
def write_json(path:Path,value:Any)->None:path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
def validate(value:dict[str,Any],name:str)->None:
    import jsonschema
    jsonschema.validate(value,json.loads((SKILL_DIR/"schemas"/name).read_text(encoding="utf-8")))


def workspace()->Path:
    for root in [SKILL_DIR,*SKILL_DIR.parents,Path.cwd(),*Path.cwd().parents]:
        if (root/".claude"/"skills").is_dir():return root
    return Path.cwd()


def args()->argparse.Namespace:
    p=argparse.ArgumentParser(description="Validate an Interpreter draft and create deterministic preview reports.")
    p.add_argument("--context",required=True);p.add_argument("--draft",required=True,help="Interpreter-authored JSON without formal INS/ACT IDs")
    p.add_argument("--state");p.add_argument("--output-dir");p.add_argument("--project");p.add_argument("--run-id");p.add_argument("--round-id");p.add_argument("--node-id");p.add_argument("--attempt-id")
    p.add_argument("--conductor",action="store_true");p.add_argument("--overwrite",action="store_true")
    a=p.parse_args()
    if a.conductor:
        missing=[k for k in ("project","run_id","round_id","node_id","attempt_id","state") if not getattr(a,k)]
        if missing:p.error(f"--conductor missing: {', '.join(missing)}")
    elif any(getattr(a,k) for k in ("project","round_id","node_id","attempt_id")):p.error("CONDUCTOR context requires --conductor")
    return a


def output(a:argparse.Namespace)->Path:
    run=a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if a.output_dir:return Path(a.output_dir)
    root=workspace()/"results"
    if a.conductor:return root/"CONDUCTOR"/a.project/run/"interpretation"/CAPABILITY["skill_name"]/a.node_id/"attempts"/a.attempt_id
    return root/"interpretation"/"standalone"/CAPABILITY["skill_name"]/run


def normalize_draft(draft:dict[str,Any],a:argparse.Namespace)->dict[str,Any]:
    insights=[]
    for index,item in enumerate(draft.get("insights") or [],1):
        insights.append({"insight_id":f"TMP-INS{index:04d}","revision":1,"title":str(item["title"]),"observation":str(item["observation"]),"interpretation":str(item["interpretation"]),"attention":item.get("attention","watch"),"scope":item.get("scope") or {},"supporting_results":list(dict.fromkeys(item.get("supporting_results") or [])),"counter_results":list(dict.fromkeys(item.get("counter_results") or [])),"limitations":[str(v) for v in item.get("limitations") or []]})
    actions=[]
    for index,item in enumerate(draft.get("next_actions") or [],1):
        actions.append({"action_id":f"TMP-ACT{index:04d}","revision":1,"title":str(item["title"]),"rationale":str(item["rationale"]),"status":item.get("status","open"),"source_insights":[str(v) for v in item.get("source_insights") or []],"requested_analysis":item.get("requested_analysis") or []})
    return {"schema_version":"2.0.0","run_id":a.run_id or "standalone","round_id":a.round_id or "RND0000","node_id":a.node_id or "NI000000","attempt_id":a.attempt_id or "ATT0000","title":str(draft.get("title") or "CONDUCTOR解析結果の解釈"),"executive_summary":str(draft.get("executive_summary") or "今回確認した解析結果の要点を示します。"),"coverage_note":str(draft.get("coverage_note") or "指定されたInterpretation contextを対象に比較しました。"),"insights":insights,"next_actions":actions,"created_at":now()}


def run()->int:
    started=now();a=args();out=output(a)
    if out.exists() and any(out.iterdir()) and not a.overwrite:raise FileExistsError(f"Output directory is not empty: {out}")
    out.mkdir(parents=True,exist_ok=True);context=json.loads(Path(a.context).read_text(encoding="utf-8"));draft=json.loads(Path(a.draft).read_text(encoding="utf-8"));preview=normalize_draft(draft,a)
    known=set(context.get("allowed_result_refs") or [])
    referenced={ref for item in preview["insights"] for ref in [*item["supporting_results"],*item["counter_results"]]}
    if known and referenced-known:raise ValueError(f"Draft references results outside context: {sorted(referenced-known)}")
    result_lookup={item.get("result_ref"):item for item in context.get("operator_results") or [] if item.get("result_ref")}
    preview["result_catalog"]=[{key:result_lookup.get(ref,{}).get(key) for key in ("result_ref","operator_id","scope","scope_context","sample_count","metric","headline","artifact_path","operator_report_path","summary_artifact_path")} | {"result_ref":ref} for ref in sorted(referenced)]
    for item in preview["insights"]:
        if not item["supporting_results"]:raise ValueError(f"{item['insight_id']}: at least one supporting Operator result is required")
        if not item["limitations"]:raise ValueError(f"{item['insight_id']}: limitations must not be empty")
        if not item["counter_results"] and not any(token in value.lower() for value in item["limitations"] for token in ("反証","不一致","counter")):raise ValueError(f"{item['insight_id']}: record the unsuccessful counterevidence search in limitations")
    write_json(out/"interpretation_draft.json",draft);write_json(out/"interpretation_context.json",context)
    # TMP IDs make these preview files. Runtime replaces IDs, validates schema, and renders final files atomically at commit.
    (out/"interpretation_preview.md").write_text(render_markdown(preview),encoding="utf-8")
    (out/"interpretation_preview.html").write_text(render_html(preview),encoding="utf-8")
    write_json(out/"quality_report.json",render_quality(preview))
    if a.conductor:
        config=vars(a); artifacts=[]
        for kind,name in [("interpretation_draft","interpretation_draft.json"),("interpretation_context","interpretation_context.json"),("interpretation_preview","interpretation_preview.md"),("interpretation_preview","interpretation_preview.html"),("quality_report","quality_report.json")]:artifacts.append({"type":kind,"path":name,"sha256":sha(out/name)})
        event={"schema_version":"2.0.0","project":a.project,"run_id":a.run_id,"round_id":a.round_id,"node_id":a.node_id,"attempt_id":a.attempt_id,"capability_id":CAPABILITY["capability_id"],"skill_name":CAPABILITY["skill_name"],"status":"succeeded","input_hash":value_hash([sha(Path(a.context)),sha(Path(a.draft))]),"config_hash":value_hash(config),"configuration":config,"artifacts":artifacts,"warnings":[],"started_at":started,"finished_at":now()};validate(event,"execution_event.schema.json");write_json(out/"execution_event.json",event)
    print(out);return 0


if __name__=="__main__":
    try:raise SystemExit(run())
    except Exception as exc:print(f"ERROR: {exc}",file=sys.stderr);raise SystemExit(1)
