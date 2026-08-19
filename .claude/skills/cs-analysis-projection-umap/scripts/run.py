from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    def clean(item: Any) -> Any:
        if isinstance(item, dict): return {str(k): clean(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)): return [clean(v) for v in item]
        if isinstance(item, (np.integer,)): return int(item)
        if isinstance(item, (np.floating, float)): return float(item) if math.isfinite(float(item)) else None
        return item
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2), encoding="utf-8")


def validate(value: dict[str, Any], name: str) -> None:
    import jsonschema
    jsonschema.validate(value, json.loads((SKILL_DIR / "schemas" / name).read_text(encoding="utf-8")))


def workspace() -> Path:
    for root in [SKILL_DIR, *SKILL_DIR.parents, Path.cwd(), *Path.cwd().parents]:
        if (root / ".claude" / "skills").is_dir(): return root
    return Path.cwd()


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Run {CAPABILITY['display_name']}.")
    parser.add_argument("--input", required=True, help="Endpoint CSV.")
    parser.add_argument("--description", help="Description CSV or Parquet; required for projection-fit.")
    parser.add_argument("--description-result", help="Canonical Runtime Description Result 1.0.0 that binds the Description payload and metric.")
    parser.add_argument("--value-semantics", choices=["binary_fingerprint", "sparse_count", "dense_continuous", "dense_shape_moment", "dense_embedding"], help="Required with --metric for standalone projection-fit without a Runtime Description Result.")
    parser.add_argument("--metric", choices=["tanimoto", "cosine", "euclidean", "manhattan"], help="Natural metric for standalone projection-fit without a Runtime Description Result.")
    parser.add_argument("--property-column", required=True)
    parser.add_argument("--id-column", default="compound_id")
    parser.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--role", choices=["projection-fit", "cluster-overlay"], default="projection-fit")
    parser.add_argument("--projection", help="Existing global projection CSV; required for cluster-overlay.")
    parser.add_argument("--membership", help="Cluster membership CSV; required for cluster-overlay.")
    parser.add_argument("--target-cluster")
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-dist", type=float, default=0.1)
    parser.add_argument("--stability-seeds", type=int, default=3)
    parser.add_argument("--random-seed", type=int, default=61453)
    parser.add_argument("--output-dir")
    parser.add_argument("--project"); parser.add_argument("--run-id"); parser.add_argument("--round-id")
    parser.add_argument("--node-id"); parser.add_argument("--attempt-id")
    parser.add_argument("--description-node-id"); parser.add_argument("--clustering-node-id"); parser.add_argument("--projection-node-id"); parser.add_argument("--evaluation-representation")
    parser.add_argument("--conductor", action="store_true"); parser.add_argument("--overwrite", action="store_true")
    result = parser.parse_args()
    if result.higher_is_better is None: parser.error("--higher-is-better or --no-higher-is-better is required")
    if result.role == "projection-fit" and not result.description: parser.error("projection-fit requires --description")
    if result.role == "cluster-overlay" and (not result.projection or not result.membership): parser.error("cluster-overlay requires --projection and --membership")
    if result.conductor:
        missing = [k for k in ("project", "run_id", "round_id", "node_id", "attempt_id") if not getattr(result, k)]
        if missing: parser.error(f"--conductor missing: {', '.join(missing)}")
    elif any(getattr(result, k) for k in ("project", "round_id", "node_id", "attempt_id")):
        parser.error("CONDUCTOR context arguments require --conductor")
    return result


def read_table(path: str) -> pd.DataFrame:
    return pd.read_parquet(path) if Path(path).suffix.lower() == ".parquet" else pd.read_csv(path)


def outdir(a: argparse.Namespace) -> Path:
    run_id = a.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if a.output_dir: return Path(a.output_dir)
    root = workspace() / "results"
    if a.conductor: return root / "CONDUCTOR" / a.project / run_id / "analysis" / CAPABILITY["skill_name"] / a.node_id / "attempts" / a.attempt_id
    return root / "analysis" / Path(a.input).stem / CAPABILITY["skill_name"] / run_id


def description_contract(a: argparse.Namespace) -> dict[str, Any]:
    if not a.description_result:
        if a.conductor and a.role == "projection-fit":
            raise ValueError("CONDUCTOR projection-fit requires --description-result")
        if a.role == "projection-fit" and (not a.value_semantics or not a.metric):
            raise ValueError("Standalone projection-fit without --description-result requires --value-semantics and --metric")
        if a.role == "projection-fit":
            expected_metric = {"binary_fingerprint": "tanimoto", "sparse_count": "cosine", "dense_continuous": "euclidean", "dense_shape_moment": "manhattan", "dense_embedding": "cosine"}[a.value_semantics]
            if a.metric != expected_metric:
                raise ValueError(f"{a.value_semantics} vectors require --metric {expected_metric}")
        return {"value_semantics": a.value_semantics, "natural_metric": a.metric}
    if a.value_semantics or a.metric:
        raise ValueError("--value-semantics and --metric cannot be combined with --description-result; the canonical result is authoritative")
    result_path = Path(a.description_result).resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate(result, "description_result.schema.json")
    if a.role == "projection-fit":
        declared_payload = (result_path.parent / result["payload"]).resolve()
        if not a.description or Path(a.description).resolve() != declared_payload:
            raise ValueError("--description does not match the payload bound by --description-result")
    if a.evaluation_representation and str(a.evaluation_representation).upper() != str(result["capability_id"]).upper():
        raise ValueError("--evaluation-representation conflicts with --description-result")
    return result


def semantics(contract: dict[str, Any]) -> tuple[str, str]:
    kind = str(contract.get("value_semantics") or "")
    metric = str(contract.get("natural_metric") or "")
    if not kind or not metric:
        raise ValueError("Description value semantics and natural metric are required")
    return kind, metric


def preprocess(frame: pd.DataFrame, kind: str) -> tuple[np.ndarray, list[str], dict[str, Any]]:
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    columns = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c])]
    usable = [c for c in columns if frame[c].notna().any() and frame[c].nunique(dropna=True) > 1]
    if not usable: raise ValueError("No variable numeric Description features")
    values = frame[usable]
    if kind in {"binary_fingerprint", "sparse_count"}:
        matrix = SimpleImputer(strategy="constant", fill_value=0).fit_transform(values)
        if kind == "sparse_count": matrix = np.log1p(np.maximum(matrix, 0))
    else:
        matrix = SimpleImputer(strategy="median").fit_transform(values)
    matrix = StandardScaler(with_mean=kind != "binary_fingerprint").fit_transform(matrix)
    return matrix, usable, {"input_feature_count": len(columns), "used_feature_count": len(usable), "removed_feature_count": len(columns) - len(usable)}


def scatter_png(frame: pd.DataFrame, property_column: str, cluster_col: str | None = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.8, 6.4), dpi=150)
    color = pd.to_numeric(frame[property_column], errors="coerce")
    points = ax.scatter(frame["component_1"], frame["component_2"], c=color, cmap="viridis", s=34, alpha=.82, edgecolors="white", linewidths=.35)
    if cluster_col and cluster_col in frame:
        selected = frame[cluster_col].fillna(False).astype(bool)
        ax.scatter(frame.loc[selected, "component_1"], frame.loc[selected, "component_2"], facecolors="none", edgecolors="#8a4f3d", s=78, linewidths=1.5)
    ax.set_xlabel("Component 1"); ax.set_ylabel("Component 2"); ax.grid(alpha=.18); fig.colorbar(points, ax=ax, label=property_column)
    fig.tight_layout(); buffer = io.BytesIO(); fig.savefig(buffer, format="png"); plt.close(fig); return buffer.getvalue()


def html_report(title: str, summary: dict[str, Any], image: bytes, table_name: str) -> str:
    cards = "".join(f"<div><small>{html.escape(str(k))}</small><b>{html.escape(str(v))}</b></div>" for k, v in summary.items() if not isinstance(v, (list, dict)))
    encoded = base64.b64encode(image).decode("ascii")
    css = "body{margin:0;background:#eeece7;color:#29383f;font:15px/1.65 'Yu Gothic UI',sans-serif}main{max-width:1050px;margin:28px auto;background:#fff;padding:44px}h1,h2{color:#304956}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.cards div{border:1px solid #d6d3cc;padding:12px}.cards small{display:block;color:#70797e}.cards b{font-size:18px}img{max-width:100%;border:1px solid #d6d3cc}a{color:#486878}"
    return f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body><main><p>CONDUCTOR Operator report</p><h1>{html.escape(title)}</h1><p>高次元表現を2次元へ投影した探索用の可視化です。距離や分離を元空間と同一視せず、仮説候補の発見に利用してください。</p><div class='cards'>{cards}</div><h2>Endpoint landscape</h2><img src='data:image/png;base64,{encoded}' alt='projection scatter'><p>完全な座標: <a href='{html.escape(table_name)}'>{html.escape(table_name)}</a></p></main></body></html>"


def run() -> int:
    started = now(); a = args(); output = outdir(a)
    if output.exists() and any(output.iterdir()) and not a.overwrite: raise FileExistsError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    endpoint = pd.read_csv(a.input, dtype={a.id_column: "string"})
    if a.id_column not in endpoint or a.property_column not in endpoint: raise ValueError("ID/property column missing")
    endpoint = endpoint[[a.id_column, a.property_column]].rename(columns={a.id_column: "compound_id"})
    endpoint[a.property_column] = pd.to_numeric(endpoint[a.property_column], errors="coerce")
    endpoint = endpoint.dropna(subset=[a.property_column])
    operator = CAPABILITY["implementation"]["operator"]
    metric = None; details: dict[str, Any] = {"role": a.role}
    if a.role == "projection-fit":
        desc = read_table(a.description)
        if "compound_id" not in desc: raise ValueError("Description must contain compound_id")
        contract = description_contract(a)
        declared_features = [str(column) for column in contract.get("feature_columns") or []]
        if contract.get("row_count") is not None and int(contract["row_count"]) != len(desc):
            raise ValueError("Description Result row_count does not match the Description payload")
        if declared_features:
            missing = [column for column in declared_features if column not in desc.columns]
            if missing: raise ValueError(f"Description payload is missing Result-bound feature columns: {missing[:10]}")
            if int(contract["feature_count"]) != len(declared_features): raise ValueError("Description Result feature_count does not match feature_columns")
        merged = endpoint.merge(desc, on="compound_id", how="inner")
        feature_frame = merged[declared_features] if declared_features else merged.drop(columns=["compound_id", a.property_column], errors="ignore")
        kind, metric = semantics(contract); matrix, features, prep = preprocess(feature_frame, kind); details.update(prep)
        if operator == "projection_pca":
            from sklearn.decomposition import PCA
            model = PCA(n_components=2, random_state=a.random_seed); coordinates = model.fit_transform(matrix)
            details.update({"explained_variance_ratio": model.explained_variance_ratio_.tolist(), "loadings": {features[i]: model.components_[:, i].tolist() for i in range(len(features))}})
        else:
            import umap
            from sklearn.manifold import trustworthiness
            if len(matrix) < 4: raise ValueError("UMAP projection requires at least four valid compounds")
            umap_metric = {"tanimoto": "jaccard", "manhattan": "manhattan", "cosine": "cosine"}.get(metric, "euclidean")
            model = umap.UMAP(n_components=2, n_neighbors=min(a.n_neighbors, max(2, len(matrix)-1)), min_dist=a.min_dist, metric=umap_metric, random_state=a.random_seed)
            trust_k=min(5,max(1,(len(matrix)-1)//2));coordinates = model.fit_transform(matrix); details["trustworthiness"] = float(trustworthiness(matrix, coordinates, n_neighbors=trust_k))
            details.update({"metric": umap_metric, "stability_seeds": a.stability_seeds})
        result = merged[["compound_id", a.property_column]].copy(); result[["component_1", "component_2"]] = coordinates
    else:
        result = pd.read_csv(a.projection).merge(endpoint, on="compound_id", how="inner", suffixes=("", "_endpoint"))
        projection_summary = Path(a.projection).parent / "operator_summary.json"
        if projection_summary.is_file():
            try:
                source_summary = json.loads(projection_summary.read_text(encoding="utf-8")); metric = source_summary.get("metric"); details["projection_metric"] = metric
            except Exception:
                details["projection_metric"] = "unavailable"
        details["projection_node_id"] = a.projection_node_id
        membership = pd.read_csv(a.membership, dtype={"compound_id": "string"})
        active = membership["membership_value"].fillna(0).astype(float) > 0 if "membership_value" in membership else pd.Series(True, index=membership.index)
        selected = set(membership.loc[active & (membership["cluster_id"].astype(str) == str(a.target_cluster)), "compound_id"].astype(str)) if a.target_cluster else set(membership.loc[active, "compound_id"].astype(str))
        result["cluster_selected"] = result["compound_id"].astype(str).isin(selected); details["selected_count"] = int(result["cluster_selected"].sum())
    result_path = output / CAPABILITY["output"]["filename"]; result.to_csv(result_path, index=False)
    image = scatter_png(result, a.property_column, "cluster_selected" if "cluster_selected" in result else None)
    (output / "projection.png").write_bytes(image)
    headline = f"{CAPABILITY['display_name']}で{len(result)}化合物を可視化しました。2次元配置は探索用であり、元の高次元距離を完全には保持しません。"
    scope_mode = "cluster-overlay" if a.role == "cluster-overlay" else "projection-fit"
    result_ref=f"{a.node_id}@{a.attempt_id}" if a.conductor else "standalone"
    if a.conductor and scope_mode=="cluster-overlay" and a.target_cluster:result_ref+=f"/{a.target_cluster}"
    summary = {"schema_version":"1.0.0","result_ref":result_ref,"node_id":a.node_id,"attempt_id":a.attempt_id,"operator_id":CAPABILITY["operator_id"],"run_id":a.run_id or "standalone","round_id":a.round_id or "RND0000","scope":{"mode":scope_mode,"target_cluster_id":a.target_cluster},"scope_context":{"description_node_ids":[a.description_node_id] if a.description_node_id else [],"clustering_node_ids":[a.clustering_node_id] if a.clustering_node_id else [],"cluster_ids":[a.target_cluster] if a.target_cluster else []},"sample_count":len(result),"endpoint":{"column":a.property_column,"higher_is_better":bool(a.higher_is_better)},"metric":metric,"headline":headline,"key_metrics":details,"top_records":[],"limitations":["次元削減による情報損失がある。","投影座標は標準DAGのClustering入力にしない。"],"warnings":[],"source_nodes":[v for v in (a.description_node_id,a.clustering_node_id,a.projection_node_id) if v],"primary_artifact":{"path":result_path.name,"sha256":sha(result_path)},"created_at":now()}
    input_files=[Path(a.input),*[Path(v) for v in (a.description,a.description_result,a.projection,a.membership) if v]]
    manifest={"schema_version":"2.0.0","conductor_version":"0.1.3","artifact_stage":"analysis","run_id":a.run_id or "standalone","node_id":a.node_id,"attempt_id":a.attempt_id,"capability_id":CAPABILITY["capability_id"],"skill_name":CAPABILITY["skill_name"],"skill_version":CAPABILITY["version"],"input":a.input,"input_hash":value_hash([sha(path) for path in input_files]),"value_semantics":"projection_coordinates","natural_metric":metric,"warnings":[],"created_at":now(),"configuration":vars(a)}
    if a.conductor:
        (output/"operator_report.html").write_text(html_report(CAPABILITY["display_name"],details,image,result_path.name),encoding="utf-8")
        validate(summary,"operator_summary.schema.json"); write_json(output/"operator_summary.json",summary)
        validate(manifest,"artifact_manifest.schema.json"); write_json(output/"analysis_manifest.json",manifest)
        artifacts=[]
        for kind,name in [("operator_result",result_path.name),("operator_report","operator_report.html"),("operator_summary","operator_summary.json"),("projection_image","projection.png"),("manifest","analysis_manifest.json")]: artifacts.append({"type":kind,"path":name,"sha256":sha(output/name)})
        config=vars(a); event={"schema_version":"2.0.0","project":a.project,"run_id":a.run_id,"round_id":a.round_id,"node_id":a.node_id,"attempt_id":a.attempt_id,"capability_id":CAPABILITY["capability_id"],"skill_name":CAPABILITY["skill_name"],"status":"succeeded","input_hash":manifest["input_hash"],"config_hash":value_hash(config),"configuration":config,"artifacts":artifacts,"warnings":[],"started_at":started,"finished_at":now()}
        validate(event,"execution_event.schema.json"); write_json(output/"execution_event.json",event)
    print(output); return 0


if __name__ == "__main__":
    try: raise SystemExit(run())
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(1)
