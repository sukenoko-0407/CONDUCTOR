from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))
PANEL = tuple(CAPABILITY.get("fixed_description_panel") or ["D001", "D002", "D006", "D013", "D016", "D019"])


def now() -> str: return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str: return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def clean(value: Any) -> Any:
    if isinstance(value,dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [clean(v) for v in value]
    if isinstance(value,(np.integer,)): return int(value)
    if isinstance(value,(np.floating,float)): return float(value) if math.isfinite(float(value)) else None
    return value


def write_json(path: Path,value: Any)->None: path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2),encoding="utf-8")


def validate(value:dict[str,Any],name:str)->None:
    import jsonschema
    jsonschema.validate(value,json.loads((SKILL_DIR/"schemas"/name).read_text(encoding="utf-8")))


def workspace()->Path:
    for root in [SKILL_DIR,*SKILL_DIR.parents,Path.cwd(),*Path.cwd().parents]:
        if (root/".claude"/"skills").is_dir(): return root
    return Path.cwd()


def parse_description(values:list[str])->dict[str,Path]:
    result:dict[str,Path]={}
    for item in values:
        if "=" not in item: raise ValueError("--description requires D###=/path/to/table")
        key,path=item.split("=",1); result[key.upper()]=Path(path)
    missing=set(PANEL)-set(result); extra=set(result)-set(PANEL)
    if missing or extra: raise ValueError(f"Fixed Description panel mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    return result


def args()->argparse.Namespace:
    parser=argparse.ArgumentParser(description=f"Run {CAPABILITY['display_name']}.")
    parser.add_argument("--input",required=True); parser.add_argument("--property-column",required=True); parser.add_argument("--id-column",default="compound_id")
    parser.add_argument("--higher-is-better",action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument("--description",action="append",required=True,help="Repeat exactly six times: D001=path ... D019=path")
    parser.add_argument("--role",choices=["global-model","cluster-survey","within-cluster"],default="global-model")
    parser.add_argument("--membership"); parser.add_argument("--target-cluster"); parser.add_argument("--global-oof")
    parser.add_argument("--min-local-samples",type=int,default=30); parser.add_argument("--outer-folds",type=int,default=5); parser.add_argument("--random-seed",type=int,default=61453)
    parser.add_argument("--output-dir"); parser.add_argument("--project"); parser.add_argument("--run-id"); parser.add_argument("--round-id"); parser.add_argument("--node-id"); parser.add_argument("--attempt-id")
    parser.add_argument("--description-node-id",action="append",default=[]); parser.add_argument("--clustering-node-id"); parser.add_argument("--global-model-node-id")
    parser.add_argument("--conductor",action="store_true"); parser.add_argument("--overwrite",action="store_true")
    result=parser.parse_args(); result.description_paths=parse_description(result.description)
    if result.higher_is_better is None: parser.error("--higher-is-better or --no-higher-is-better is required")
    if result.min_local_samples<30: parser.error("--min-local-samples must be >= 30")
    if result.role != "global-model" and not result.membership: parser.error("Local model roles require --membership")
    if result.role=="within-cluster" and not result.target_cluster: parser.error("within-cluster requires --target-cluster")
    if result.role=="cluster-survey" and not result.global_oof: parser.error("cluster-survey requires --global-oof from the Global A005 Node")
    if result.conductor:
        missing=[k for k in ("project","run_id","round_id","node_id","attempt_id") if not getattr(result,k)]
        if missing: parser.error(f"--conductor missing: {', '.join(missing)}")
    elif any(getattr(result,k) for k in ("project","round_id","node_id","attempt_id")): parser.error("CONDUCTOR context requires --conductor")
    return result


def table(path:Path)->pd.DataFrame: return pd.read_parquet(path) if path.suffix.lower()==".parquet" else pd.read_csv(path)


def load(a:argparse.Namespace)->tuple[pd.DataFrame,dict[str,list[str]]]:
    endpoint=pd.read_csv(a.input,dtype={a.id_column:"string"})
    if a.id_column not in endpoint or a.property_column not in endpoint: raise ValueError("ID/property column missing")
    data=endpoint[[a.id_column,a.property_column]].rename(columns={a.id_column:"compound_id"}); data[a.property_column]=pd.to_numeric(data[a.property_column],errors="coerce"); data=data.dropna(subset=[a.property_column])
    blocks:dict[str,list[str]]={}
    for block in PANEL:
        frame=table(a.description_paths[block])
        if "compound_id" not in frame: raise ValueError(f"{block} lacks compound_id")
        columns=[c for c in frame if c not in {"compound_id","input_smiles","mol_parse_ok","description_error"} and pd.api.types.is_numeric_dtype(frame[c])]
        if not columns: raise ValueError(f"{block} has no numeric features")
        if block=="D006":
            frame[columns]=frame[columns].clip(lower=0).apply(np.log1p)
        elif block=="D002":
            values=frame[columns].stack().dropna()
            if len(values) and not values.isin([0,1]).all(): raise ValueError("D002 must be a binary Morgan fingerprint")
        renamed={c:f"{block}::{c}" for c in columns}; frame=frame[["compound_id",*columns]].rename(columns=renamed); data=data.merge(frame,on="compound_id",how="inner"); blocks[block]=list(renamed.values())
    if len(data)<10: raise ValueError("Too few complete panel rows")
    return data,blocks


def folds(ids:pd.Series,count:int,seed:int)->np.ndarray:
    return np.array([int(hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()[:8],16)%count for value in ids.astype(str)])


def vip_select(train:pd.DataFrame,y:np.ndarray,blocks:dict[str,list[str]])->tuple[list[str],dict[str,float]]:
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    scores:dict[str,float]={}
    n=len(train)
    for block,columns in blocks.items():
        usable=[c for c in columns if train[c].notna().any() and train[c].nunique(dropna=True)>1]
        if not usable: continue
        matrix=SimpleImputer(strategy="median").fit_transform(train[usable]); variances=np.var(matrix,axis=0); usable=[c for c,v in zip(usable,variances) if v>1e-12]
        if not usable: continue
        matrix=SimpleImputer(strategy="median").fit_transform(train[usable]); matrix=StandardScaler().fit_transform(matrix)
        corr=np.nan_to_num([abs(np.corrcoef(matrix[:,i],y)[0,1]) for i in range(matrix.shape[1])]); limit=min(len(usable),256,max(5,5*n)); keep=np.argsort(corr)[::-1][:limit]; matrix=matrix[:,keep]; names=[usable[i] for i in keep]
        comp=max(1,min(2,matrix.shape[0]-1,matrix.shape[1]))
        try:
            model=PLSRegression(n_components=comp,scale=False).fit(matrix,y)
            weights=np.asarray(model.x_weights_); q=np.asarray(model.y_loadings_).reshape(-1); strength=np.sum((np.asarray(model.x_scores_)**2),axis=0)*(q[:comp]**2); denom=max(float(np.sum(strength)),1e-12)
            vip=np.sqrt(matrix.shape[1]*np.sum((weights[:,:comp]**2)*strength[:comp],axis=1)/denom)
            if not np.isfinite(vip).all():raise ValueError("non-finite VIP")
        except Exception:
            # Degenerate/collinear blocks cannot support a stable PLS solution.
            # Retain a deterministic training-fold-only univariate fallback.
            vip=np.asarray(corr,dtype=float)[keep]
        for name,value in zip(names,vip): scores[name]=float(value)
    selected=[]
    for block in PANEL:
        selected.extend([name for name,_ in sorted(((n,s) for n,s in scores.items() if n.startswith(block+"::")),key=lambda x:-x[1])[:5]])
    cap=min(30,max(6,len(train)//3)); selected=sorted(selected,key=lambda name:-scores[name])[:cap]
    return selected,scores


def fit_predict(train:pd.DataFrame,test:pd.DataFrame,y_train:np.ndarray,features:list[str])->dict[str,np.ndarray]:
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if not features: return {"constant":np.repeat(float(np.mean(y_train)),len(test))}
    xtr=train[features]; xte=test[features]; predictions={"constant":np.repeat(float(np.mean(y_train)),len(test))}
    ridge=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),Ridge(alpha=1.0)); ridge.fit(xtr,y_train); predictions["ridge"]=ridge.predict(xte)
    components=max(1,min(2,len(features),len(train)-1)); pls=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),PLSRegression(n_components=components))
    try:
        pls.fit(xtr,y_train); values=pls.predict(xte).reshape(-1)
        if np.isfinite(values).all():predictions["pls"]=values
    except Exception:
        pass
    if len(train)>=60 and len(features)<=12:
        from sklearn.preprocessing import SplineTransformer
        spline=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),SplineTransformer(n_knots=3,degree=2),Ridge(alpha=1.0)); spline.fit(xtr,y_train); predictions["spline_ridge"]=spline.predict(xte)
    return predictions


def evaluate(data:pd.DataFrame,blocks:dict[str,list[str]],property_column:str,fold:np.ndarray)->tuple[pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    rows=[]; selection=Counter(); valid_folds=0
    for label in sorted(set(fold)):
        test_mask=fold==label; train=data.loc[~test_mask]; test=data.loc[test_mask]
        if len(train)<8 or not len(test): continue
        y=train[property_column].to_numpy(float); features,scores=vip_select(train,y,blocks)
        if not features: continue
        valid_folds+=1; selection.update(features); predictions=fit_predict(train,test,y,features)
        for model,values in predictions.items():
            for cid,actual,pred in zip(test["compound_id"],test[property_column],values): rows.append({"compound_id":cid,"fold":int(label),"model":model,"actual":actual,"predicted":float(pred),"residual":float(actual-pred)})
    prediction=pd.DataFrame(rows)
    metrics=[]
    for model,frame in prediction.groupby("model"):
        actual=frame["actual"].to_numpy(float); pred=frame["predicted"].to_numpy(float); rmse=float(np.sqrt(np.mean((actual-pred)**2))); mae=float(np.mean(np.abs(actual-pred))); r2=float(1-np.sum((actual-pred)**2)/max(np.sum((actual-np.mean(actual))**2),1e-12)); metrics.append({"model":model,"oof_n":len(frame),"rmse":rmse,"mae":mae,"r2":r2})
    metric_frame=pd.DataFrame(metrics).sort_values(["rmse","model"]) if metrics else pd.DataFrame(columns=["model","oof_n","rmse","mae","r2"])
    return prediction,metric_frame,{"valid_fold_count":valid_folds,"selection_frequency":dict(selection),"selected_feature_count":len(selection)}


def memberships(path:str)->dict[str,set[str]]:
    frame=pd.read_csv(path,dtype={"compound_id":"string"}); active=frame["membership_value"].fillna(0).astype(float)>0 if "membership_value" in frame else pd.Series(True,index=frame.index)
    return {str(cid):set(part["compound_id"].astype(str)) for cid,part in frame.loc[active].groupby("cluster_id")}


def output_dir(a:argparse.Namespace)->Path:
    run=a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if a.output_dir:return Path(a.output_dir)
    root=workspace()/"results"
    if a.conductor:return root/"CONDUCTOR"/a.project/run/"analysis"/CAPABILITY["skill_name"]/a.node_id/"attempts"/a.attempt_id
    return root/"analysis"/Path(a.input).stem/CAPABILITY["skill_name"]/run


def report(rows:pd.DataFrame,headline:str)->str:
    table_html=rows.to_html(index=False,escape=True) if len(rows) else "<p>適用可能な結果はありません。</p>"
    css="body{margin:0;background:#efede8;color:#293840;font:15px/1.65 'Yu Gothic UI',sans-serif}main{max-width:1100px;margin:28px auto;background:white;padding:44px}h1,h2{color:#304957}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d9d5cc;padding:8px}th{background:#e9ecea}"
    return f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>{css}</style></head><body><main><p>CONDUCTOR Operator report</p><h1>{html.escape(CAPABILITY['display_name'])}</h1><p>{html.escape(headline)}</p><h2>モデル比較</h2>{table_html}<h2>解釈上の注意</h2><p>これは予測製品ではなく、単変量相関では埋没し得る複数Description由来signalを探索する機能です。OOF baselineとの差、fold間変動、特徴量選択安定性を確認してください。</p></main></body></html>"


def run()->int:
    started=now(); a=args(); data,blocks=load(a); fold=folds(data["compound_id"],a.outer_folds,a.random_seed); data["outer_fold"]=fold; out=output_dir(a)
    if out.exists() and any(out.iterdir()) and not a.overwrite: raise FileExistsError(f"Output directory is not empty: {out}")
    out.mkdir(parents=True,exist_ok=True); rows=[]; prediction_paths=[]; details={"role":a.role,"panel":list(PANEL),"block_preprocessing":{"D001":"median+scale","D002":"binary median+scale","D006":"log1p+median+scale","D013":"median+scale","D016":"median+scale","D019":"median+scale"},"selection_scope":"outer-training-fold-only","cluster_results":[]}
    if a.role=="global-model":
        pred,metrics,extra=evaluate(data,blocks,a.property_column,fold); pred_path=out/"global_oof_predictions.csv"; pred.to_csv(pred_path,index=False); prediction_paths.append(pred_path); rows=metrics.assign(cluster_id="GLOBAL").to_dict("records"); details.update(extra)
    else:
        cluster_map=memberships(a.membership); selected={a.target_cluster:cluster_map.get(a.target_cluster,set())} if a.role=="within-cluster" else cluster_map
        global_oof=pd.read_csv(a.global_oof) if a.global_oof else None
        for cluster_id,members in sorted(selected.items()):
            subset=data[data["compound_id"].astype(str).isin(members)].copy(); entry={"cluster_id":cluster_id,"sample_count":len(subset)}
            if len(subset)<a.min_local_samples or subset[a.property_column].nunique()<3: entry.update({"status":"not_applicable","reason":"minimum sample count or endpoint variation not met"}); details["cluster_results"].append(entry); continue
            pred,metrics,extra=evaluate(subset,blocks,a.property_column,subset["outer_fold"].to_numpy()); valid_fold_count=extra["valid_fold_count"]
            if valid_fold_count<3: entry.update({"status":"not_applicable","reason":"fewer than three valid shared folds"}); details["cluster_results"].append(entry); continue
            cluster_dir=out/"clusters"/str(cluster_id); cluster_dir.mkdir(parents=True,exist_ok=True); pred_path=cluster_dir/"oof_predictions.csv"; pred.to_csv(pred_path,index=False); metrics.to_csv(cluster_dir/"model_comparison.csv",index=False); prediction_paths.append(pred_path)
            baseline_rmse=None
            if global_oof is not None:
                common=global_oof[global_oof["compound_id"].astype(str).isin(set(subset["compound_id"].astype(str)))].copy()
                if len(common):
                    candidates=common[common["model"]!="constant"] if "model" in common else common
                    by_model=[]
                    for model_name,model_rows in candidates.groupby("model",dropna=False):
                        by_model.append((float(np.sqrt(np.mean((model_rows["actual"]-model_rows["predicted"])**2))),str(model_name)))
                    if by_model:baseline_rmse=min(by_model)[0]
            for row in metrics.to_dict("records"): row.update({"cluster_id":cluster_id,"global_context_rmse":baseline_rmse,"rmse_delta_vs_global":None if baseline_rmse is None else row["rmse"]-baseline_rmse}); rows.append(row)
            entry.update({"status":"succeeded","valid_fold_count":valid_fold_count,"best_model":metrics.iloc[0]["model"] if len(metrics) else None,"best_rmse":metrics.iloc[0]["rmse"] if len(metrics) else None}); details["cluster_results"].append(entry)
    result=pd.DataFrame(rows); result_path=out/CAPABILITY["output"]["filename"]; result.to_csv(result_path,index=False)
    headline=f"固定panel {', '.join(PANEL)}をfold内で選択し、{a.role}としてbaseline・Ridge・PLS・条件付きSpline-Ridgeを比較しました。"
    (out/"operator_report.html").write_text(report(result,headline),encoding="utf-8")
    input_components=[sha(Path(a.input)),*[sha(path) for path in a.description_paths.values()],*[sha(Path(v)) for v in (a.membership,a.global_oof) if v]]; input_hash=value_hash(input_components)
    scope_mode=a.role; source_nodes=[*a.description_node_id,*([a.clustering_node_id] if a.clustering_node_id else []),*([a.global_model_node_id] if a.global_model_node_id else [])]; base_ref=f"{a.node_id}@{a.attempt_id}" if a.conductor else "standalone"
    result_ref=base_ref+f"/{a.target_cluster}" if a.conductor and a.role=="within-cluster" and a.target_cluster else base_ref
    context={"description_node_ids":list(a.description_node_id),"clustering_node_ids":[a.clustering_node_id] if a.clustering_node_id else [],"cluster_ids":[a.target_cluster] if a.target_cluster else []}
    limitations=["探索的モデル比較であり予測モデルの採用を推奨するものではない。","小標本では性能差と特徴量選択が不安定になり得る。"]
    summary={"schema_version":"1.0.0","result_ref":result_ref,"node_id":a.node_id,"attempt_id":a.attempt_id,"operator_id":CAPABILITY["operator_id"],"run_id":a.run_id or "standalone","round_id":a.round_id or "RND0000","scope":{"mode":scope_mode,"target_cluster_id":a.target_cluster},"scope_context":context,"sample_count":len(data),"endpoint":{"column":a.property_column,"higher_is_better":bool(a.higher_is_better)},"metric":"rmse","headline":headline,"key_metrics":details,"top_records":result.head(100).to_dict("records"),"limitations":limitations,"warnings":[],"source_nodes":source_nodes,"primary_artifact":{"path":result_path.name,"sha256":sha(result_path)},"created_at":now()}
    cluster_summaries=[]
    if a.conductor and a.role=="cluster-survey":
        for entry in details["cluster_results"]:
            if entry.get("status")!="succeeded":continue
            cluster_id=str(entry["cluster_id"]);comparison_path=out/"clusters"/cluster_id/"model_comparison.csv";cluster_rows=result[result.get("cluster_id",pd.Series(dtype=str)).astype(str)==cluster_id] if "cluster_id" in result else pd.DataFrame()
            local_headline=f"{cluster_id}（N={entry['sample_count']}）のLocal modelをGlobal OOF contextと比較しました。best RMSE={entry.get('best_rmse')}。"
            cluster_summary={"schema_version":"1.0.0","result_ref":f"{base_ref}/{cluster_id}","node_id":a.node_id,"attempt_id":a.attempt_id,"operator_id":CAPABILITY["operator_id"],"run_id":a.run_id,"round_id":a.round_id,"scope":{"mode":"within-cluster","target_cluster_id":cluster_id},"scope_context":{"description_node_ids":list(a.description_node_id),"clustering_node_ids":[a.clustering_node_id] if a.clustering_node_id else [],"cluster_ids":[cluster_id]},"sample_count":int(entry["sample_count"]),"endpoint":{"column":a.property_column,"higher_is_better":bool(a.higher_is_better)},"metric":"rmse","headline":local_headline,"key_metrics":entry,"top_records":cluster_rows.head(20).to_dict("records"),"limitations":limitations,"warnings":[],"source_nodes":source_nodes,"primary_artifact":{"path":str(comparison_path.relative_to(out)),"sha256":sha(comparison_path)},"created_at":now()}
            validate(cluster_summary,"operator_summary.schema.json");cluster_summaries.append(cluster_summary)
    config={k:v for k,v in vars(a).items() if k!="description_paths"}; manifest={"schema_version":"2.0.0","conductor_version":"0.1.1","artifact_stage":"analysis","run_id":a.run_id or "standalone","node_id":a.node_id,"attempt_id":a.attempt_id,"capability_id":CAPABILITY["capability_id"],"skill_name":CAPABILITY["skill_name"],"skill_version":CAPABILITY["version"],"input":a.input,"input_hash":input_hash,"value_semantics":"model_evaluation","natural_metric":None,"warnings":[],"created_at":now(),"configuration":config,"fixed_description_panel":list(PANEL)}
    if a.conductor:
        validate(summary,"operator_summary.schema.json"); write_json(out/"operator_summary.json",summary); validate(manifest,"artifact_manifest.schema.json"); write_json(out/"analysis_manifest.json",manifest)
        artifacts=[]
        for kind,name in [("operator_result",result_path.name),("operator_report","operator_report.html"),("operator_summary","operator_summary.json"),("manifest","analysis_manifest.json")]: artifacts.append({"type":kind,"path":name,"sha256":sha(out/name)})
        if cluster_summaries:
            write_json(out/"cluster_operator_summaries.json",cluster_summaries);artifacts.append({"type":"operator_summary_collection","path":"cluster_operator_summaries.json","sha256":sha(out/"cluster_operator_summaries.json")})
        for path in prediction_paths: artifacts.append({"type":"oof_predictions","path":str(path.relative_to(out)),"sha256":sha(path)})
        event={"schema_version":"2.0.0","project":a.project,"run_id":a.run_id,"round_id":a.round_id,"node_id":a.node_id,"attempt_id":a.attempt_id,"capability_id":CAPABILITY["capability_id"],"skill_name":CAPABILITY["skill_name"],"status":"succeeded","input_hash":input_hash,"config_hash":value_hash(config),"configuration":config,"artifacts":artifacts,"warnings":[],"started_at":started,"finished_at":now()}; validate(event,"execution_event.schema.json"); write_json(out/"execution_event.json",event)
    print(out); return 0


if __name__=="__main__":
    try: raise SystemExit(run())
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(1)
