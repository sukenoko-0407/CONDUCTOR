from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
SKILLS_ROOT = PROJECT_ROOT / ".claude" / "skills"
TEMPLATES = MODULE_ROOT / "tools" / "templates"
SCHEMAS = MODULE_ROOT / "schemas"


DESCRIPTIONS = [
    ("D001", "cs-compute-description-rdkit-2d", "RDKit 2D descriptors", "rdkit_2d", "physicochemical", "low", "stable", True),
    ("D002", "cs-compute-description-morgan", "Morgan fingerprint (optional chirality)", "morgan", "2d_fingerprint", "low", "stable", True),
    ("D003", "cs-compute-description-maccs", "MACCS keys", "maccs", "2d_fingerprint", "low", "stable", True),
    ("D004", "cs-compute-description-atom-pair", "Hashed atom-pair fingerprint", "atom_pair", "2d_fingerprint", "low", "stable", True),
    ("D005", "cs-compute-description-topological-torsion", "Hashed topological-torsion fingerprint", "topological_torsion", "2d_fingerprint", "low", "stable", False),
    ("D006", "cs-compute-description-rdkit-fragment", "RDKit fragment counts", "rdkit_fragment", "substructure", "low", "stable", False),
    ("D007", "cs-compute-description-rdkit-path-fingerprint", "RDKit path fingerprint", "rdkit_path", "2d_fingerprint", "low", "stable", True),
    ("D008", "cs-compute-description-rdkit-pattern-fingerprint", "RDKit pattern fingerprint", "rdkit_pattern", "substructure", "low", "stable", False),
    ("D009", "cs-compute-description-rdkit-layered-fingerprint", "RDKit layered fingerprint", "rdkit_layered", "2d_fingerprint", "low", "stable", False),
    ("D010", "cs-compute-description-avalon-fingerprint", "Avalon fingerprint", "avalon", "2d_fingerprint", "low", "stable", False),
    ("D011", "cs-compute-description-gobbi-pharm2d", "Gobbi 2D pharmacophore fingerprint (optional SVD)", "gobbi_pharm2d", "pharmacophore", "medium", "stable", True),
    ("D012", "cs-compute-description-rdkit-3d", "RDKit 3D descriptors", "rdkit_3d", "3d_shape", "medium", "stable", False),
    ("D013", "cs-compute-description-usr-usrcat", "USR and USRCAT", "usr_usrcat", "3d_shape", "medium", "stable", True),
    ("D014", "cs-compute-description-shape", "Basic 3D shape descriptors", "shape", "3d_shape", "medium", "stable", False),
    ("D015", "cs-compute-description-mordred-2d", "Mordred 2D descriptors", "mordred_2d", "physicochemical", "medium", "experimental", False),
    ("D016", "cs-compute-description-mordred-3d", "Mordred 3D descriptors", "mordred_3d", "3d_shape", "high", "experimental", False),
    ("D019", "cs-compute-description-tblite-xtb", "GFN2-xTB quantum descriptors", "tblite_xtb", "quantum", "very_high", "experimental", False),
    ("D020", "cs-compute-description-chemberta-embedding", "ChemBERTa-100M-MLM embedding", "chemberta_embedding", "pretrained_embedding", "high", "experimental", False),
]


CLUSTERINGS = [
    ("C001", "cs-compute-clustering-structure-murcko", "Murcko scaffold clustering", "structure_murcko", "direct_structure", "low", "stable", True),
    ("C002", "cs-compute-clustering-structure-mcs", "MCS clustering", "structure_mcs", "direct_structure", "high", "experimental", True),
    ("C003", "cs-compute-clustering-structure-brics", "BRICS fragment clustering", "structure_brics", "direct_structure", "medium", "stable", True),
    ("C004", "cs-compute-clustering-structure-recap", "RECAP fragment clustering", "structure_recap", "direct_structure", "medium", "stable", False),
    ("C005", "cs-compute-clustering-vector-butina", "Vector Butina clustering", "vector_butina", "description_vector", "medium", "stable", True),
    ("C006", "cs-compute-clustering-vector-hierarchical", "Vector hierarchical clustering", "vector_hierarchical", "description_vector", "medium", "stable", True),
    ("C007", "cs-compute-clustering-vector-dbscan", "Vector DBSCAN clustering", "vector_dbscan", "description_vector", "medium", "stable", True),
    ("C008", "cs-compute-clustering-vector-louvain", "Vector Louvain clustering", "vector_louvain", "description_vector", "medium", "stable", False),
    ("C009", "cs-compute-clustering-vector-leiden", "Vector Leiden clustering", "vector_leiden", "description_vector", "medium", "stable", True),
    ("C010", "cs-compute-clustering-vector-connected-components", "Vector connected-component clustering", "vector_connected_components", "description_vector", "medium", "stable", False),
    ("C011", "cs-compute-clustering-categorical", "Categorical-column clustering", "categorical", "human_context", "low", "stable", False),
    ("C012", "cs-compute-clustering-meta-overlap", "Overlap-based meta clustering", "meta_overlap", "meta", "medium", "experimental", False),
]


OPERATORS = [
    ("A001", "cs-analysis-activity-distribution", "Activity distribution", "activity_distribution", "property_profile", "low", "stable", True, []),
    ("A002", "cs-analysis-descriptor-activity-correlation", "Descriptor-activity correlation", "descriptor_activity_correlation", "interpretable_association", "low", "stable", True, ["description"]),
    ("A003", "cs-analysis-projection-pca", "PCA projection", "projection_pca", "projection", "medium", "stable", True, ["description"]),
    ("A004", "cs-analysis-projection-umap", "UMAP projection", "projection_umap", "projection", "medium", "stable", True, ["description"]),
    ("A005", "cs-analysis-multidescription-feature-model", "Multi-Description feature model", "multidescription_feature_model", "feature_model", "high", "experimental", True, ["description"]),
    ("A006", "cs-analysis-pairwise-structure-similarity", "Pairwise structure similarity", "pairwise_structure_similarity", "feature_space", "medium", "stable", True, []),
    ("A007", "cs-analysis-knn-activity-consistency", "kNN activity consistency", "knn_activity_consistency", "feature_space", "medium", "stable", True, ["description"]),
    ("A008", "cs-analysis-sali", "Extended structure-activity landscape index", "sali", "landscape", "medium", "stable", True, ["description"]),
    ("A009", "cs-analysis-activity-cliff", "Activity cliff detection", "activity_cliff", "landscape", "medium", "stable", True, []),
    ("A010", "cs-analysis-cluster-profile", "Cluster profile", "cluster_profile", "cluster_profile", "low", "stable", True, ["clustering"]),
    ("A011", "cs-analysis-cluster-enrichment", "Cluster activity enrichment", "cluster_enrichment", "cluster_profile", "low", "stable", True, ["clustering"]),
    ("A012", "cs-analysis-cluster-overlap", "Cluster overlap", "cluster_overlap", "cluster_quality", "low", "stable", True, ["clustering"]),
    ("A013", "cs-analysis-cluster-structural-diversity", "Cluster structural diversity", "cluster_structural_diversity", "cluster_quality", "medium", "stable", True, ["clustering"]),
]


CAPABILITY_DEFAULTS: dict[str, dict[str, Any]] = {
    "D004": {"default_parameters": {"n_bits": 2048}},
    "D007": {"default_parameters": {"n_bits": 2048}},
    "D013": {"default_parameters": {"num_confs": 20, "random_seed": 61453}},
    "C001": {"default_parameters": {"min_cluster_size": 5}},
    "C002": {"default_parameters": {"min_cluster_size": 5, "max_pairs": 1000, "max_core_clusters": 300, "random_seed": 61453}},
    "C003": {"default_parameters": {"min_cluster_size": 5}},
    "C004": {"default_parameters": {"min_cluster_size": 5}},
    "C005": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto"}},
    "C006": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto"}},
    "C007": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto", "min_samples": 5}},
    "C008": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto", "resolution": 1.0, "random_seed": 61453}},
    "C009": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto", "resolution": 1.0, "random_seed": 61453}},
    "C010": {"default_parameters": {"min_cluster_size": 5, "metric": "auto", "parameter_mode": "auto"}},
    "C011": {"default_parameters": {"min_cluster_size": 5}},
    "C012": {"default_parameters": {"min_cluster_size": 5}},
    "A003": {"default_parameters": {"role": "projection-fit", "random_seed": 61453}},
    "A004": {"default_parameters": {"role": "projection-fit", "random_seed": 61453, "n_neighbors": 15, "min_dist": 0.1, "stability_seeds": 3}},
    "A005": {"default_parameters": {"role": "global-model", "random_seed": 61453, "min_local_samples": 30}},
    "A006": {"default_parameters": {"max_pairs": 200000, "random_seed": 61453}},
    "A007": {"default_parameters": {"k": 10}},
    "A008": {"default_parameters": {"k": 10}},
    "A009": {"default_parameters": {"similarity_threshold": 0.8, "activity_delta_threshold": 1.0, "max_pairs": 200000, "random_seed": 61453}},
    "A010": {"default_parameters": {"high_quantile": 0.8, "low_quantile": 0.2}},
    "A011": {"default_parameters": {"high_quantile": 0.8, "low_quantile": 0.2}},
    "A013": {"default_parameters": {"max_pairs": 200000, "random_seed": 61453}},
}


DESCRIPTION_METADATA: dict[str, dict[str, Any]] = {
    "D001": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D002": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D003": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D004": {"value_semantics": "sparse_count", "natural_metric": "cosine", "allowed_metrics": ["cosine"]},
    "D005": {"value_semantics": "sparse_count", "natural_metric": "cosine", "allowed_metrics": ["cosine"]},
    "D006": {"value_semantics": "sparse_count", "natural_metric": "cosine", "allowed_metrics": ["cosine"]},
    "D007": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D008": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D009": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D010": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto"]},
    "D011": {"value_semantics": "binary_fingerprint", "natural_metric": "tanimoto", "allowed_metrics": ["tanimoto", "cosine"]},
    "D012": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D013": {"value_semantics": "dense_shape_moment", "natural_metric": "manhattan", "allowed_metrics": ["manhattan"]},
    "D014": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D015": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D016": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D019": {"value_semantics": "dense_continuous", "natural_metric": "euclidean", "allowed_metrics": ["euclidean"]},
    "D020": {"value_semantics": "dense_embedding", "natural_metric": "cosine", "allowed_metrics": ["cosine"]},
}


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_capability_defaults(capability: dict[str, Any]) -> None:
    profile = CAPABILITY_DEFAULTS.get(capability["capability_id"])
    if not profile:
        return
    defaults = dict(capability.get("default_parameters") or {})
    defaults.update(profile.get("default_parameters") or {})
    if defaults:
        capability["default_parameters"] = defaults


def pixi_manifest(name: str, kind: str, algorithm: str) -> str:
    deps = {
        "python": ">=3.12,<3.13",
        "pandas": ">=2.2",
        "numpy": ">=1.26",
        "jsonschema": ">=4.21",
    }
    pypi: dict[str, str] = {}
    if kind in {"description", "clustering"} or algorithm in {"pairwise_structure_similarity", "activity_cliff", "cluster_structural_diversity"}:
        deps["rdkit"] = ">=2024.3"
    if kind in {"clustering", "analysis"}:
        deps["scikit-learn"] = ">=1.4"
        deps["scipy"] = ">=1.12"
    if kind == "clustering":
        deps["networkx"] = ">=3.2"
    if "leiden" in algorithm:
        deps["python-igraph"] = ">=0.11"
        deps["leidenalg"] = ">=0.10"
    if algorithm in {"mordred_2d", "mordred_3d"}:
        pypi["mordredcommunity"] = ">=2.0"
    if algorithm == "gobbi_pharm2d":
        deps["scikit-learn"] = ">=1.4"
        deps["scipy"] = ">=1.12"
    if algorithm == "chemberta_embedding":
        deps["pytorch"] = ">=2.3"
        deps["transformers"] = ">=4.41"
    if algorithm == "tblite_xtb":
        deps["tblite-python"] = ">=0.4"
    if kind == "description":
        deps["pyarrow"] = ">=15"
    if algorithm in {"projection_pca", "projection_umap", "multidescription_feature_model"}:
        deps["matplotlib"] = ">=3.8"
    if algorithm == "projection_umap":
        deps["umap-learn"] = ">=0.5.6"
    platforms = '["linux-64", "win-64"]'
    lines = [
        "[workspace]",
        f'name = "{name}"',
        'channels = ["conda-forge"]',
        f"platforms = {platforms}",
        "",
        "[dependencies]",
    ]
    lines.extend(f'{key} = "{value}"' for key, value in sorted(deps.items()))
    if pypi:
        lines.extend(["", "[pypi-dependencies]"])
        lines.extend(f'{key} = "{value}"' for key, value in sorted(pypi.items()))
    lines.extend(["", "[tasks]", 'run = "python ../scripts/run.py"', 'smoke = "python ../scripts/run.py --help"', ""])
    return "\n".join(lines)


LAUNCHER = '''from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import json
import hashlib
from pathlib import Path


def prepare_runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache_root = env_dir / "cache"
    pixi_cache = cache_root / "pixi"
    attempt_tmp = Path(os.environ.get("CONDUCTOR_ATTEMPT_TMP", str(env_dir / "tmp"))).resolve()
    locations = {
        "PIXI_HOME": env_dir / "pixi-home",
        "PIXI_CACHE_DIR": pixi_cache,
        "PIXI_CACHE_CONDA_PACKAGES_DIR": pixi_cache / "conda-packages",
        "PIXI_CACHE_REPODATA_DIR": pixi_cache / "repodata",
        "PIXI_CACHE_PYPI_WHEELS_DIR": pixi_cache / "pypi-wheels",
        "PIXI_CACHE_PYPI_MAPPING_DIR": pixi_cache / "pypi-mapping",
        "PIXI_CACHE_EXEC_ENVIRONMENTS_DIR": pixi_cache / "exec-environments",
        "PIXI_CACHE_BUILD_TOOL_ENVIRONMENTS_DIR": pixi_cache / "build-tool-environments",
        "PIXI_CACHE_DETACHED_ENVIRONMENTS_DIR": pixi_cache / "detached-environments",
        "RATTLER_CACHE_DIR": pixi_cache,
        "UV_CACHE_DIR": cache_root / "uv",
        "PIP_CACHE_DIR": cache_root / "pip",
        "XDG_CACHE_HOME": cache_root / "xdg",
        "XDG_CONFIG_HOME": env_dir / "config",
        "XDG_DATA_HOME": env_dir / "data",
        "XDG_STATE_HOME": env_dir / "state",
        "MPLCONFIGDIR": cache_root / "matplotlib",
        "NUMBA_CACHE_DIR": cache_root / "numba",
        "HF_HOME": cache_root / "huggingface",
        "TORCH_HOME": cache_root / "torch",
        "CUDA_CACHE_PATH": cache_root / "cuda",
        "TRITON_CACHE_DIR": cache_root / "triton",
        "TORCHINDUCTOR_CACHE_DIR": cache_root / "torchinductor",
        "JOBLIB_TEMP_FOLDER": attempt_tmp / "joblib",
        "TMPDIR": attempt_tmp,
        "TMP": attempt_tmp,
        "TEMP": attempt_tmp,
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    runtime_env = os.environ.copy()
    runtime_env.update({name: str(path) for name, path in locations.items()})
    runtime_env.update(
        {
            "PIXI_CACHE_NETFS_REDIRECT": "never",
            "PIXI_NO_CONFIG": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return runtime_env


skill_dir = Path(__file__).resolve().parents[1]
arguments = sys.argv[1:]
runner = skill_dir / "scripts" / "run.py"
if arguments and arguments[0] == "render" and (skill_dir / "scripts" / "render.py").is_file():
    runner = skill_dir / "scripts" / "render.py"
    arguments = arguments[1:]
manifest = (skill_dir / "env" / "pixi.toml").resolve()
shared_pixi = Path("/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi")
pixi = str(shared_pixi) if shared_pixi.is_file() and os.access(shared_pixi, os.X_OK) else shutil.which("pixi")
if not pixi:
    print(
        f"ERROR: pixi is required. Shared binary was not executable at {shared_pixi}; "
        "install pixi on PATH and rerun this launcher. "
        "pixi will create or reuse the Skill environment from env/pixi.toml.",
        file=sys.stderr,
    )
    raise SystemExit(127)
runtime_env = prepare_runtime_environment(skill_dir)
capability = json.loads((skill_dir / "capability.json").read_text(encoding="utf-8"))
if capability.get("implementation", {}).get("algorithm") == "chemberta_embedding":
    runtime_env["CUDA_VISIBLE_DEVICES"] = ""
print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
lockfile = manifest.with_name("pixi.lock")
ready_marker = manifest.parent / ".environment-ready"
bootstrap_lock = manifest.parent / ".bootstrap.lock"
lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else "missing"
environment_ready = ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash
if not environment_ready:
    acquired = False
    for _ in range(600):
        try:
            bootstrap_lock.mkdir()
            acquired = True
            break
        except FileExistsError:
            if ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash:
                break
            time.sleep(1)
    if acquired:
        try:
            install = [pixi, "install", "--manifest-path", str(manifest)]
            if lockfile.is_file():
                install.append("--locked")
            completed = subprocess.run(install, env=runtime_env)
            if completed.returncode:
                raise SystemExit(completed.returncode)
            if not lockfile.is_file():
                print(f"ERROR: pixi did not create the expected lock file: {lockfile}", file=sys.stderr)
                raise SystemExit(78)
            lock_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest()
            ready_marker.write_text(lock_hash + "\\n", encoding="utf-8")
        finally:
            bootstrap_lock.rmdir()
    elif not (ready_marker.is_file() and ready_marker.read_text(encoding="utf-8").strip() == lock_hash):
        print("ERROR: timed out waiting for the Skill environment bootstrap lock", file=sys.stderr)
        raise SystemExit(75)
command = [pixi, "run", "--manifest-path", str(manifest), "--locked", "python", str(runner), *arguments]
raise SystemExit(subprocess.call(command, env=runtime_env))
'''


def skill_md(capability: dict[str, Any], kind: str) -> str:
    name = capability["skill_name"]
    display = capability["display_name"]
    boundary_extra = ""
    if capability.get("approval_policy") == "preauthorized_initial":
        approval_boundary = "- このcapabilityはCatalogで`approval_policy=preauthorized_initial`とされた必須初手であり、`high` costでもrunごとの人間承認を待たない。人間指定の並列上限とStateの実行制御には従う。"
    else:
        approval_boundary = "- 高コストcapabilityは人間が計算資源を明示承認するまで実行しない。CONDUCTORではOrchestratorの承認手順に従う。"
    if kind == "description":
        purpose = f"CSVまたは1件以上のSMILESから{display}を計算する。"
        inputs = "`--input CSV`または反復可能な`--smiles`を使う。CSVではcompound ID列とSMILES列を推定するが、曖昧なら`--id-column`と`--smiles-column`を指定する。個別SMILESへIDを与える場合は`--compound-id`を同じ回数指定する。"
        base_args = "--input compounds.csv"
        if capability["implementation"]["algorithm"] == "chemberta_embedding":
            base_args += " --model-dir /shared/models/ChemBERTa-100M-MLM"
            inputs += " ChemBERTa-100M-MLMのローカルmodel weightを`--model-dir`または`CONDUCTOR_CHEMBERTA_MODEL_DIR`で指定する。外部からmodelを自動downloadせずCPUで実行する。"
        algorithm = capability["implementation"]["algorithm"]
        description_options = {
            "rdkit_2d": "RDKitが提供する2D descriptor集合を固定仕様で計算する。algorithm固有optionはない。",
            "morgan": "`--radius`、`--n-bits`、`--encoding bit|count`、`--use-features`を指定できる。chiralityを含めない`--no-include-chirality`がdefaultで、chiralityを含める場合だけ`--include-chirality`を指定する。",
            "maccs": "固定長MACCS keysを計算する。algorithm固有optionはない。",
            "atom_pair": "`--n-bits`でhashed count fingerprintの次元を指定する。",
            "topological_torsion": "`--n-bits`でhashed count fingerprintの次元を指定する。",
            "rdkit_fragment": "RDKit fragment count集合を固定仕様で計算する。algorithm固有optionはない。",
            "rdkit_path": "`--n-bits`でfingerprintの次元を指定する。",
            "rdkit_pattern": "`--n-bits`でfingerprintの次元を指定する。",
            "rdkit_layered": "`--n-bits`でfingerprintの次元を指定する。",
            "avalon": "`--n-bits`でfingerprintの次元を指定する。",
            "rdkit_3d": "`--num-confs`と`--random-seed`でconformer探索を制御する。入力SMILESから3D conformerを生成するため、2D手法より計算量が大きい。",
            "usr_usrcat": "`--num-confs`と`--random-seed`でconformer探索を制御する。",
            "shape": "`--num-confs`と`--random-seed`でconformer探索を制御する。",
            "mordred_2d": "Mordred 2D descriptor集合を固定仕様で計算する。algorithm固有optionはない。",
            "mordred_3d": "`--num-confs`と`--random-seed`でconformer探索を制御する。高コストのため人間承認後に実行する。",
            "gobbi_pharm2d": "folded fingerprintは`--reduction none --n-bits N`、dataset単位の低次元表現は`--reduction svd --svd-dim N`を使う。SVDはvalid moleculeが2件以上必要で、`--random-seed`を記録する。",
            "chemberta_embedding": "`--model-dir`、環境変数、Skill-local設定の順でChemBERTa-100M-MLM weightを解決する。CPU batch推論と非special-token mean poolingに固定し、外部modelを自動downloadしない。",
            "tblite_xtb": "`--num-confs`、`--random-seed`、必要に応じて`--charge`と`--uhf`を指定する。非常に高コストのため人間承認後に実行する。",
        }
        option_guidance = description_options[algorithm]
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id N000001 --attempt-id ATT0001'
        output_contract = f'''- 通常モード: `results/description/<input>/<skill>/<run-id>/`へ`{capability["output"]["basename"]}.csv`（または`--format parquet`）だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/description/<skill>/<node-id-safe>/attempts/<attempt-id>/`へ主成果物、`description_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    elif kind == "clustering":
        algorithm = capability["implementation"]["algorithm"]
        if algorithm.startswith("structure_"):
            purpose = f"compound IDとSMILESを含むCSVを{display}により直接Cluster化し、Clustering artifactを生成する。"
            inputs = "compound IDとSMILESを持つCSVを`--input`へ必ず指定する。inlineの`--smiles`と`--compound-id`は受け付けない。Description CSVを入力とせず、fingerprint vectorを内部生成して距離clusteringへ置き換えない。列が曖昧なら`--id-column`と`--smiles-column`を指定する。"
            boundary_extra = "- 一般利用・CONDUCTOR利用ともcompound ID・SMILES CSVを入力とし、inline SMILESは受け付けない。\n- Description vectorを入力とせず、CSV内のSMILESを宣言された構造規則で直接処理する。\n"
        elif algorithm.startswith("vector_"):
            purpose = f"Description Skillが生成した数値vectorへ{display}を適用し、Clustering artifactを生成する。"
            inputs = "compound IDと数値featureを持つDescription CSVを必須入力とする。raw SMILESは受け付けず、fingerprintやdescriptorを内部生成しない。SMILES列やstatus列はfeatureから除外し、Description値がない行は未割当として保持する。"
            boundary_extra = "- raw SMILESからDescriptionを内部生成しない。先に適切なDescription Skillを実行する。\n"
        else:
            purpose = f"{display}を単独実行し、Clustering artifactを生成する。"
            inputs = "algorithmに対応するmembershipまたはcategorical CSVを使う。"
        base_args = "--input compounds.csv"
        if algorithm.startswith("vector_"):
            base_args = "--input path/to/description.csv --input-representation D001"
        elif capability["implementation"]["algorithm"] == "categorical":
            base_args += " --columns assay"
            inputs = "compound IDと一つ以上のカテゴリ列を持つCSVを使い、`--columns assay,series`のようにClusteringへ使用する列を必ず指定する。"
        elif capability["implementation"]["algorithm"] == "meta_overlap":
            base_args = "--input path/to/cluster_membership.csv"
            inputs = "long形式の`cluster_id,compound_id,membership_value`、または行がcompound、列がCluster IDのBoolean wide形式membership CSVを使う。long形式と複数shardでは同一compound IDの反復を許可する。"
        clustering_options = {
            "structure_murcko": "`--min-cluster-size`未満のscaffold Clusterを登録しない。",
            "structure_mcs": "`--min-cluster-size`（既定・下限5）、`--max-pairs`（既定・上限1000）、`--max-core-clusters`（既定300）で探索量を制限する。pair上限を適用する場合は`--random-seed`に基づく一様ランダム非復元抽出を行う。C002は構造Clusteringの中心的な初手であり、runごとの事前承認なしで実行する。",
            "structure_brics": "`--min-cluster-size`未満のfragment Clusterを登録しない。",
            "structure_recap": "`--min-cluster-size`未満のfragment Clusterを登録しない。",
            "categorical": "`--columns`を必須とし、`--min-cluster-size`未満のClusterを登録しない。",
            "meta_overlap": "`--similarity-threshold`でsource Cluster間Jaccard graphのedgeを定義し、`--min-cluster-size`未満の統合Clusterを登録しない。",
        }
        if algorithm.startswith(("structure_", "vector_")) and algorithm.split("_", 1)[1] not in {"murcko", "mcs", "brics", "recap"}:
            method = algorithm.split("_", 1)[1]
            source_options = "`--metric auto`でDescription manifestに固定されたMetricを使用する。`--parameter-mode auto`を既定とし、Clustering Skill自身がactivityを使わず距離・近傍構造から手法固有parameterを選ぶ。人間が再現条件を固定する場合だけ`--parameter-mode fixed`を使う。"
            method_options = {
                "butina": "autoではk近傍距離からnative-distance cutoffを選ぶ。fixedでは`--distance-cutoff`を指定する。",
                "hierarchical": "autoではaverage-linkage距離gapから切断候補を選ぶ。fixedでは`--n-clusters`または`--distance-threshold`を指定する。",
                "dbscan": "autoではk-distance分布から`eps`を選び、`min_samples=5`を既定とする。fixedでは`--eps`を指定する。",
                "louvain": "autoではweighted mutual-kNN graphを構築し、boundedなkと`resolution`候補を評価する。fixedでは`--n-neighbors`と`--resolution`を指定する。",
                "leiden": "autoではweighted mutual-kNN graphを構築し、boundedなkと`resolution`候補を評価する。fixedでは`--n-neighbors`と`--resolution`を指定する。",
                "connected_components": "autoではk近傍距離とpercolation傾向からnative-distance cutoffを選ぶ。fixedでは`--distance-cutoff`を指定する。",
            }[method]
            option_guidance = f"`--min-cluster-size`未満のClusterを登録しない。{source_options}{method_options}"
        else:
            option_guidance = clustering_options[algorithm]
        conductor_args = base_args
        if algorithm.startswith("vector_"):
            conductor_args += " --description-manifest path/to/description_manifest.json"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {conductor_args} --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id N000001 --attempt-id ATT0001'
        output_contract = '''- 通常モード: `results/clustering/<input>/<skill>/<run-id>/`へ`cluster_membership.csv`、`cluster_summary.csv`、`clustering_diagnostics.csv`を生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/clustering/<skill>/<node-id-safe>/attempts/<attempt-id>/`へ通常成果物、Vector Clusteringでは`distance_profile.json`、さらに`clustering_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    elif kind == "analysis":
        purpose = f"{display}を実行し、客観的な数値結果とCONDUCTOR Operator summaryを生成する。"
        extra = ""
        dependency_text = ""
        if "description" in capability.get("dependencies", []):
            extra += " --description path/to/description.csv"
            dependency_text += " `--description`で数値Description artifactを必ず指定する。"
        if "clustering" in capability.get("dependencies", []):
            extra += " --membership path/to/cluster_membership.csv"
            dependency_text += " `--membership`でClustering membershipを必ず指定する。"
        base_args = f"--input compounds.csv --property-column pIC50 --higher-is-better{extra}"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --conductor --project PROJECT --run-id RUN_ID --node-id N000001 --round-id RND0001 --attempt-id ATT0001'
        inputs = f"元CSV、endpoint列、`--higher-is-better`または`--no-higher-is-better`を必ず指定する。{dependency_text}"
        operator = capability["implementation"]["operator"]
        if operator == "sali":
            purpose = "Description空間の局所的なproperty勾配をSALIで評価し、高SALI cliff pairとlandscape分布の平滑性をCONDUCTOR Operator resultとして生成する。"
        analysis_options = {
            "activity_distribution": "全体分布をdefaultとし、任意の`--membership`と`--target-cluster`でCluster別に限定できる。",
            "descriptor_activity_correlation": "`--description`の全数値featureについてPearson/Spearman相関を計算する。任意のCluster内scopeへ限定できる。",
            "projection_pca": "`--role projection-fit|cluster-overlay`を使う。overlayはGlobal座標を再利用し、再fitしない。",
            "projection_umap": "`--role projection-fit|cluster-overlay`を使う。metricはDescription semanticsで固定し、複数seedの近傍安定性をreportする。",
            "multidescription_feature_model": "固定panel D001,D002,D006,D013,D016,D019を使う。Global modelまたは30化合物以上のCluster surveyを、各outer training fold内で特徴量選択してOOF評価する。",
            "pairwise_structure_similarity": "SMILES列を使い、`--max-pairs`でpair数を制限する。上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。Cluster内／二Cluster間scopeを指定できる。",
            "knn_activity_consistency": "`--description`と`--k`を指定する。metricはDescription manifestのsemanticsから拘束する。",
            "sali": "`--description`と`--k`を指定する。binaryはTanimoto、USR/USRCATはManhattan、embedding／疎countはCosine、その他の連続descriptorはEuclideanとする。高SALI cliff pairとlandscape分布の平滑性をともにsummaryへ残す。",
            "activity_cliff": "`--similarity-threshold`、`--activity-delta-threshold`、`--max-pairs`を指定する。pair上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。Cluster内／二Cluster間scopeを指定できる。",
            "cluster_profile": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`、任意の`--target-cluster`を指定できる。",
            "cluster_enrichment": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`を指定する。",
            "cluster_overlap": "`--membership`を必須とし、Cluster間の重複を評価する。",
            "cluster_structural_diversity": "`--membership`を必須とし、SMILES列と`--max-pairs`を使う。pair上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。",
        }
        option_guidance = analysis_options[operator]
        if operator in {"projection_pca","projection_umap"}:
            general_outputs=f'`{capability["output"]["filename"]}`と`projection.png`'
        elif operator=="multidescription_feature_model":
            general_outputs=f'`{capability["output"]["filename"]}`、OOF予測、`operator_report.html`'
        else:
            general_outputs=f'`{capability["output"]["filename"]}`'
        output_contract = f'''- 通常モード: `results/analysis/<input>/<skill>/<run-id>/`へ{general_outputs}を生成する。State用summary、manifest、execution eventは生成しない。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/analysis/<skill>/<node-id-safe>/attempts/<attempt-id>/`へ主成果物、`operator_report.html`、`operator_summary.json`、`analysis_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    else:
        purpose = "専用Interpretation Policyに従い、複数Operator result、Cluster局所性、依存関係、失敗を読み取り専用で比較する。"
        inputs = "`--context`、Interpreterが作成したID未付与の`--draft`、新規の`--output-dir`を指定する。Runtimeが対象result、scope、正式IDを管理する。"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json --output-dir path/to/preview'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --context path/to/context.json --draft path/to/draft.json --output-dir path/to/preview'
        output_contract = '''- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`へID未付与の検証済みpreview JSON／Markdown／HTMLを生成する。
- CONDUCTORではInterpreterがこのSkillでdraftを事前検査できる。正式ID、scope、Markdown／HTML、Ledger commitは0.1.3 Runtimeだけが確定する。'''
        option_guidance = "`references/interpretation_policy.md`を完全に読む。summaryはnavigationにだけ使い、保持するInsightは原数値artifactを確認する。矛盾、negative result、反証探索を記録し、State更新とOperator実行はRuntime／Orchestratorへ委ねる。"
    if kind == "description":
        workflow_input = "入力形式、compound ID列、SMILES列を確認し、曖昧な列だけを明示指定する。"
    elif kind == "clustering" and capability["implementation"]["algorithm"].startswith("vector_"):
        workflow_input = "Description CSVのrepresentationを確認する。CONDUCTORモードではStateが束縛した`--input-representation`と`--description-manifest`を必ず渡す。"
    elif kind == "clustering":
        workflow_input = "入力列とClustering固有の上流artifactを確認し、曖昧な列だけを明示指定する。"
    elif kind == "analysis":
        workflow_input = "Stateが束縛したDescription／Clustering Capabilityとsource Node IDを、対応する上流artifactとともに渡す。"
    else:
        workflow_input = "Runtimeが作成したcontextとdraftを確認し、許可されたOperator resultだけを扱う。"
    if kind == "interpretation":
        mode_section = '''## Mode selection

このSkillはID未付与draftの検査専用で、`--conductor`を受け付けない。正式なCONDUCTOR InterpretationはRuntimeがscopeとIDを確定してcommitする。一般利用でも既存の解析結果を読むだけでStateは作らない。'''
    else:
        mode_section = '''## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORでの実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードではCONDUCTOR context引数を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001`をすべて指定する。CLIもこの組合せを検証する。

Runtime経由ではSkillのCONDUCTOR出力はattempt scratchとして検証され、成功時に0.1.3の最小正本artifactへ昇格される。'''
    return f'''---
name: {name}
description: {capability["description"]} General mode is the default; use CONDUCTOR mode only as an explicit opt-in with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# {display}

## Purpose

{purpose}

## Input

{inputs} 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. {workflow_input}
3. algorithm固有optionが必要なら`python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

{option_guidance}

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

{mode_section}

## Output contract

{output_contract}

`<node-id-safe>`はnode IDの`:`を`-`へ置換したdirectory名であり、同一Skillの複数node間の出力衝突を防ぐ。

`--output-dir`は両モードの既定出力先より優先するが、モード自体は変更しない。

## Environment

`scripts/launch.py`を使用し、`pixi`を直接実行しない。launcherは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上の`pixi`を使う。Skill directoryからmanifest、lock、runnerの絶対パスを作るため、呼出し元のworking directoryに依存しない。起動前に`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、一時領域、主要な実行時cacheを`<skill>/env/`配下へ強制し、system/user Pixi configを読み込まない。`pixi.lock`がない初回だけ`pixi install`でlockと環境を作成し、以後は`--locked`で再利用する。環境実体は`<skill>/env/.pixi/envs/default/`へ置く。

## General mode command

CONDUCTOR利用が明示されていない場合はこちらを使う。

```bash
{general_example}
```

## CONDUCTOR mode command

明示的なCONDUCTOR利用で、project、run、nodeが確定している場合だけこちらを使う。

```bash
{conductor_example}
```

## Boundaries

{boundary_extra}- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
{approval_boundary}
'''


def readme_md(capability: dict[str, Any], kind: str) -> str:
    name = capability["skill_name"]
    display = capability["display_name"]
    approval = capability["cost"]["human_approval_required"]
    environment = (
        "`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。"
        "Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。"
    )
    conductor_args = "--conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001"
    readme_conductor_extra = ""

    if kind == "description":
        algorithm = capability["implementation"]["algorithm"]
        family_scenes = {
            "physicochemical": "物性傾向の把握、活性との相関確認、解釈可能な特徴量の作成。",
            "2d_fingerprint": "構造類似性評価、クラスタリング、近傍解析に使う2D表現の作成。",
            "substructure": "部分構造や官能基パターンに基づく比較、Clustering、SAR解析。",
            "3d_shape": "3D形状や立体配置を使った比較、2D表現と異なる観点での深掘り。",
            "pharmacophore": "2D pharmacophore配置に基づく類似性評価やクラスタリング。",
            "pretrained_embedding": "ローカルに配置したChemBERTa modelからCPUで分子embeddingを抽出する場合。",
            "quantum": "電子エネルギーや原子電荷など、量子化学由来の特徴量が必要な場合。",
        }
        purpose = f"CSVまたは1件以上のSMILESから{display}を計算し、Description表を生成する。"
        scenes = family_scenes[capability["family"]]
        general_args = "--input compounds.csv"
        extra_example = ""
        if algorithm == "morgan":
            extra_example = f'''\nchiralityを含める例:\n\n```bash\npython .claude/skills/{name}/scripts/launch.py --input compounds.csv --include-chirality\n```'''
        elif algorithm == "gobbi_pharm2d":
            extra_example = f'''\nSVD表現を作る例:\n\n```bash\npython .claude/skills/{name}/scripts/launch.py --input compounds.csv --reduction svd --svd-dim 128\n```'''
        elif algorithm == "chemberta_embedding":
            general_args += " --model-dir /shared/models/ChemBERTa-100M-MLM"
        constraints = ["入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。"]
        if algorithm == "gobbi_pharm2d":
            constraints.append("SVD表現は入力datasetに依存する座標系であり、2件以上のvalid moleculeが必要。")
        if algorithm == "chemberta_embedding":
            constraints.append("model weightを自動downloadしない。`--model-dir`で完全なlocal model directoryを指定し、CPUだけを使用する。")
        if algorithm in {"rdkit_3d", "usr_usrcat", "shape", "mordred_3d", "tblite_xtb"}:
            constraints.append("入力SMILESからconformerを生成するため、結果と計算時間は3D生成条件の影響を受ける。")
        if approval:
            constraints.append("高コスト計算として、CONDUCTORでは実行前に人間の承認が必要。")
        elif capability.get("approval_policy") == "preauthorized_initial":
            constraints.append("高コストだが、CONDUCTORの必須初手として方針上事前許可されており、runごとの人間承認は不要。人間指定の並列上限には従う。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
    elif kind == "clustering":
        algorithm = capability["implementation"]["algorithm"]
        if algorithm.startswith("structure_"):
            purpose = f"compound IDとSMILESを{display}で直接Cluster化し、cluster membershipとsummaryを生成する。"
            scenes = "SMILESを直接扱うseries分割やscaffold/fragment解析を行い、Description vector由来のClusteringと比較する場合。"
            general_args = "--input compounds.csv"
        elif algorithm.startswith("vector_"):
            purpose = f"Description Skillが生成した数値vectorへ{display}を適用し、cluster membershipとsummaryを生成する。"
            scenes = "descriptor、fingerprint、embedding空間で化合物をCluster化し、SMILESを直接扱う構造Clusteringと比較する場合。"
            general_args = "--input description.csv --input-representation D001"
            readme_conductor_extra = " --description-manifest path/to/description_manifest.json"
        elif algorithm == "categorical":
            purpose = "CSVのカテゴリ列からClusterを作り、cluster membershipとsummaryを生成する。"
            scenes = "assay条件、既知series、sourceなど、人間が付与したカテゴリで化合物を分ける場合。"
            general_args = "--input compounds.csv --columns assay"
        else:
            purpose = "long形式のClustering結果またはBoolean wide matrix shardにあるcompound重複を使ってmeta Clusterを生成する。"
            scenes = "複数Clusteringの重複関係を要約し、上位のCluster構造を確認する場合。"
            general_args = "--input cluster_membership.csv"
        constraints = ["一般利用とCONDUCTORの両方でClustering／Clusterと呼ぶ。入力分子やfeature値は変更しない。", "5化合物未満のClusterは出力・登録しない。"]
        if algorithm.startswith("structure_"):
            constraints.append("Description vectorは入力にせず、fingerprint生成を内部に隠した距離clusteringも行わない。")
            constraints.append("一般利用・CONDUCTOR利用ともcompound IDとSMILESを含むCSVを必須入力とし、CLIへのSMILES直接指定は受け付けない。")
            constraints.append("invalid SMILESは未割当として保持する。分子標準化は行わない。")
        if algorithm == "structure_mcs":
            constraints.append("`--max-pairs`は1～1000に制限し、`--max-core-clusters`の既定値は300とする。")
        if algorithm.startswith("vector_"):
            constraints.append("raw SMILESは入力にできず、Descriptionを内部生成しない。MetricはDescription表現に固定し、`--parameter-mode auto`ではactivityを使わず手法固有の距離・近傍parameterを決定する。")
            constraints.append("自動候補がすべて断片化または崩壊する場合は、Clusterを強制せず`no_usable_partition`を返す。")
        if approval:
            constraints.append("高コスト計算として、CONDUCTORでは実行前に人間の承認が必要。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
        extra_example = ""
    elif kind == "analysis":
        operator = capability["implementation"]["operator"]
        operator_scenes = {
            "activity_distribution": "endpoint全体または指定Clusterの分布を最初に把握する場合。",
            "descriptor_activity_correlation": "各Description featureと活性の単変量関連を確認する場合。",
            "projection_pca": "Description空間をPCAで2次元投影し、endpoint勾配やCluster配置を可視化する場合。",
            "projection_umap": "Description空間をUMAPで2次元投影し、非線形な局所構造を可視化する場合。",
            "multidescription_feature_model": "固定した6種類のDescriptionからfold内で特徴量を選び、globalまたは30化合物以上のClusterで簡潔なモデルを比較する場合。",
            "pairwise_structure_similarity": "構造類似度と活性差をpair単位で確認する場合。",
            "knn_activity_consistency": "近傍化合物間で活性がどの程度一貫するか評価する場合。",
            "sali": "近い表現を持つ化合物間の大きな活性差を優先順位付けする場合。",
            "activity_cliff": "高い構造類似性と大きな活性差を同時に満たすpairを抽出する場合。",
            "cluster_profile": "各Clusterの活性分布とhigh/low activity比率を比較する場合。",
            "cluster_enrichment": "特定Clusterにhigh activity化合物が濃縮されているか評価する場合。",
            "cluster_overlap": "Clustering内のCluster同士がどの程度重複するか評価する場合。",
            "cluster_structural_diversity": "各Cluster内の構造的な多様性を評価する場合。",
        }
        purpose = f"{display}を実行し、一般利用向け数値結果とCONDUCTOR向けOperator resultを生成する。"
        scenes = operator_scenes[operator]
        general_args = "--input compounds.csv --property-column pIC50 --higher-is-better"
        if "description" in capability.get("dependencies", []):
            general_args += " --description description.csv"
        if "clustering" in capability.get("dependencies", []):
            general_args += " --membership cluster_membership.csv"
        constraints = ["endpoint列と`--higher-is-better`または`--no-higher-is-better`の指定が必要。"]
        constraints.append("数値的観察を出力するOperatorであり、SAR機序や因果関係を確定しない。")
        constraints.append("CONDUCTORモードではState由来のDescription／Clustering Capabilityとsource Node IDを保持し、scope、主要結果、上位個別結果とともに`operator_report.html`へ示す。完全な数値はCSVに保持する。")
        if operator in {"knn_activity_consistency", "sali"}:
            constraints.append("`--metric auto`はfeature特性から距離を選び、Morgan表現にはTanimoto以外を使用しない。")
        if operator == "sali":
            constraints.append("高SALI pairと、中心・upper tailが示すlandscape平滑性をともに評価し、異なるmetricのraw SALI値を直接比較しない。")
        if approval:
            constraints.append("dataset規模によって高コストになる場合は、CONDUCTORで人間の承認を得る。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
        extra_example = ""
    else:
        purpose = "専用Interpretation Agentが作成したInsight案を検証し、Runtimeによる正式なscope・通しID付与と人間向け固定report生成へ引き渡す。"
        scenes = "異なるDescription・Clustering・Operator間の一致、矛盾、例外、global/local差を比較し、反証を伴う次の解析候補を作る場合。"
        constraints = ["専用Policyを読み、Interpretation nodeを読み取り専用のRound commitとして扱う。", "全Insight候補で反証を探索し、同じanalysis signatureを再要求しない。", "多重探索結果、negative result、矛盾を削除しない。", "scope・Insight正式ID付与、State更新、Operator実行、approval判断、新規SMILES生成は行わない。"]
        primary_example = f"python .claude/skills/{name}/scripts/launch.py --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json"
        general_args = "--context path/to/context.json --draft path/to/draft.json --output-dir path/to/preview"
        extra_example = ""

    constraint_text = "\n".join(f"- {item}" for item in constraints) if constraints else "- 特になし。"
    conductor_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}{readme_conductor_extra} {conductor_args}"
    return f'''# {display}

## SKILLの目的

{purpose}

## 想定利用シーン

{scenes}

## 環境構築

{environment}

## 利用例

一般利用（主成果物のみ）:

```bash
{primary_example}
```
{extra_example}

CONDUCTORのState nodeとして利用する場合:

```bash
{conductor_example}
```

## 制約事項

{constraint_text}

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
'''


def base_capability(identifier: str, name: str, display: str, stage: str, family: str, cost: str, status: str, _legacy_wide: bool) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "capability_id": identifier,
        "skill_name": name,
        "display_name": display,
        "version": "0.1.3",
        "stage": stage,
        "family": family,
        "description": f"Use when Claude Code needs to run {display} from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment.",
        "cost": {"class": cost, "human_approval_required": cost in {"high", "very_high"}, "hpc_profile": "cpu64" if cost not in {"very_high"} else "a100_cpu8"},
        "applicability": {"status": status, "platforms": ["linux-64", "win-64"], "molecule_standardization": "out_of_scope"},
    }


def create_skill(capability: dict[str, Any], kind: str, template: Path, schemas: list[str], force: bool) -> bool:
    skill_dir = SKILLS_ROOT / capability["skill_name"]
    if skill_dir.exists() and not force:
        return False
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "schemas").mkdir(parents=True, exist_ok=True)
    (skill_dir / "env").mkdir(parents=True, exist_ok=True)
    dump_json(skill_dir / "capability.json", capability)
    (skill_dir / "SKILL.md").write_text(skill_md(capability, kind), encoding="utf-8")
    (skill_dir / "README.md").write_text(readme_md(capability, kind), encoding="utf-8")
    shutil.copy2(template, skill_dir / "scripts" / "run.py")
    (skill_dir / "scripts" / "launch.py").write_text(LAUNCHER, encoding="utf-8")
    implementation = capability["implementation"].get("algorithm") or capability["implementation"].get("operator") or capability["implementation"].get("purpose")
    (skill_dir / "env" / "pixi.toml").write_text(pixi_manifest(capability["skill_name"], kind, str(implementation)), encoding="utf-8")
    if capability["skill_name"] == "cs-compute-description-chemberta-embedding":
        (skill_dir / "env" / "model_path.txt").write_text(
            "C:\\Users\\kimot\\OneDrive\\TAKAHIRO\\coding_workspace\\embed_model\\ChemBERTa-100M-MLM\n",
            encoding="utf-8",
        )
    for schema in schemas:
        shutil.copy2(SCHEMAS / schema, skill_dir / "schemas" / schema)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or refresh CONDUCTOR 0.1.3 Skill folders from canonical templates.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated Skill files. Manual customizations may be lost.")
    parser.add_argument("--only", action="append", help="Refresh only the named Skill; repeat for multiple Skills.")
    args = parser.parse_args()
    selected = set(args.only or [])
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    created = 0
    for identifier, name, display, algorithm, family, cost, status, wide in DESCRIPTIONS:
        capability = base_capability(identifier, name, display, "description", family, cost, status, wide)
        if identifier in {"D019", "D020"}:
            capability["cost"]["hpc_profile"] = "cpu64"
        capability.update({"representation_id": identifier, "dependencies": [], "input_contract": ["csv_or_smiles"], "output": {"basename": f"{identifier}_{algorithm}"}, "implementation": {"algorithm": algorithm}, **DESCRIPTION_METADATA[identifier]})
        if identifier == "D002":
            capability.update({
                "default_variant": "standard",
                "default_parameters": {"include_chirality": False, "radius": 2, "n_bits": 2048, "encoding": "bit", "use_features": False},
                "variants": [
                    {"id": "standard", "cli": "--no-include-chirality", "description": "Morgan fingerprint without chirality invariants."},
                    {"id": "chiral", "cli": "--include-chirality", "description": "The same Morgan algorithm with chirality invariants enabled."},
                ],
            })
        elif identifier == "D011":
            capability.update({
                "default_variant": "folded",
                "default_parameters": {"reduction": "none", "n_bits": 2048},
                "variants": [
                    {"id": "folded", "cli": "--reduction none --n-bits 2048", "description": "Fold the sparse Gobbi Pharm2D signature into a fixed-width bit vector."},
                    {"id": "svd", "cli": "--reduction svd --svd-dim 256", "description": "Fit TruncatedSVD to the run cohort's raw Gobbi Pharm2D signature matrix."},
                ],
            })
        apply_capability_defaults(capability)
        if not selected or name in selected:
            created += create_skill(capability, "description", TEMPLATES / "description_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, algorithm, family, cost, status, wide in CLUSTERINGS:
        capability = base_capability(identifier, name, display, "clustering", family, cost, status, wide)
        if identifier == "C002":
            capability["cost"]["human_approval_required"] = False
            capability["approval_policy"] = "preauthorized_initial"
        if algorithm.startswith("structure_"):
            clustering_kind, dependency, input_contract = "direct_structure", [], ["compound_id_smiles_csv"]
            description = f"Cluster compounds from a compound-ID/SMILES CSV with {display}, without generating a hidden descriptor vector."
        elif algorithm.startswith("vector_"):
            clustering_kind, dependency, input_contract = "description_vector", ["description"], ["description_vector_csv"]
            description = f"Apply {display} to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally."
        elif algorithm == "meta_overlap":
            clustering_kind, dependency, input_contract = "meta", ["clustering"], ["cluster_membership_csv"]
            description = capability["description"]
        else:
            clustering_kind, dependency, input_contract = "categorical", [], ["categorical_csv"]
            description = capability["description"]
        capability.update({"clustering_kind": clustering_kind, "description": description, "clustering_id": identifier, "dependencies": dependency, "input_contract": input_contract, "output": {"membership": "cluster_membership.csv", "summary": "cluster_summary.csv", "manifest": "clustering_manifest.json"}, "implementation": {"algorithm": algorithm}, "analysis_role": "clustering"})
        if identifier == "C002":
            capability["description"] = "Cluster compounds directly from SMILES by maximum common substructure as a mandatory initial CONDUCTOR axis, without generating a hidden descriptor vector or requiring per-run human approval."
        apply_capability_defaults(capability)
        if not selected or name in selected:
            created += create_skill(capability, "clustering", TEMPLATES / "clustering_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, operator, family, cost, status, wide, dependencies in OPERATORS:
        capability = base_capability(identifier, name, display, "analysis", family, cost, status, wide)
        capability.update({"operator_id": identifier, "dependencies": dependencies, "input_contract": ["endpoint_csv", *dependencies], "output": {"filename": f"{identifier}_{operator}.csv", "report": "operator_report.html", "summary": "operator_summary.json", "manifest": "analysis_manifest.json"}, "implementation": {"operator": operator}, "analysis_role": operator})
        capability["scope_support"] = {
            "A001": ["global", "within-cluster"],
            "A002": ["global", "within-cluster"],
            "A003": ["projection-fit", "cluster-overlay"],
            "A004": ["projection-fit", "cluster-overlay"],
            "A005": ["global-model", "cluster-survey", "within-cluster"],
            "A006": ["global", "within-cluster", "between-clusters"],
            "A007": ["global", "within-cluster", "between-clusters"],
            "A008": ["global", "within-cluster", "between-clusters"],
            "A009": ["global", "within-cluster", "between-clusters"],
            "A010": ["global", "within-cluster"],
            "A011": ["global", "within-cluster"],
            "A012": ["global"],
            "A013": ["global", "within-cluster"],
        }[identifier]
        if identifier == "A008":
            capability["description"] = "Use when Claude Code needs to evaluate local property-landscape roughness and smoothness with representation-aware SALI and preserve high-SALI cliff pairs for CONDUCTOR Interpretation."
        if identifier in {"A006", "A009", "A013"}:
            capability["internal_representation"] = {"kind": "morgan", "radius": 2, "n_bits": 2048, "metric": "tanimoto"}
        if identifier in {"A003", "A004"}:
            capability["input_contract"] = ["endpoint_csv", "description", "optional_clustering", "optional_projection"]
        if identifier == "A005":
            capability["cost"]["human_approval_required"] = False
            capability["approval_policy"] = "preauthorized_initial"
            capability["fixed_description_panel"] = ["D001", "D002", "D006", "D013", "D016", "D019"]
            capability["input_contract"] = ["endpoint_csv", "six_description_artifacts", "optional_clustering", "optional_global_model"]
        apply_capability_defaults(capability)
        template = TEMPLATES / ("projection_run.py" if identifier in {"A003", "A004"} else "multidescription_model_run.py" if identifier == "A005" else "operator_run.py")
        analysis_created = create_skill(capability, "analysis", template, ["execution_event.schema.json", "operator_summary.schema.json", "artifact_manifest.schema.json"], args.force) if not selected or name in selected else False
        created += analysis_created
        if analysis_created:
            shutil.copy2(TEMPLATES / "operator_report.py", SKILLS_ROOT / name / "scripts" / "operator_report.py")
        included.append(name)
    interpretation = base_capability("I001", "cs-analysis-interpret-results", "SAR result interpretation", "interpretation", "result_integration", "low", "stable", False)
    interpretation.update({
        "description": "Use when the dedicated Claude Code Interpreter must compare CONDUCTOR Operator results across representations, Clusters, scopes, and Rounds, preserve contradictions, and prepare Japanese human reports under a read-only Policy.",
        "interpretation_id": "I001",
        "dependencies": ["analysis"],
        "input_contract": ["runtime_interpretation_context", "selected_result_artifacts", "interpretation_policy_markdown"],
        "output": {"json": "interpretation.json", "markdown": "interpretation.md", "html": "interpretation.html", "context": "interpretation_context.json", "quality": "report_quality.json", "draft": "interpretation_draft.json"},
        "implementation": {"purpose": "policy_guided_iterative_result_exploration", "state_access": "read_only", "execution_authority": "runtime_commit_only", "requires_dedicated_agent_review": True},
    })
    interpretation_created = create_skill(interpretation, "interpretation", TEMPLATES / "interpretation_run.py", ["interpretation.schema.json", "result_card.schema.json", "analysis_subject.schema.json", "working_set.schema.json"], args.force) if not selected or interpretation["skill_name"] in selected else False
    created += interpretation_created
    if interpretation_created:
        references = SKILLS_ROOT / interpretation["skill_name"] / "references"
        references.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MODULE_ROOT / "docs" / "CONDUCTOR_interpretation_policy.md", references / "interpretation_policy.md")
        shutil.copy2(TEMPLATES / "interpretation_render.py", SKILLS_ROOT / interpretation["skill_name"] / "scripts" / "render.py")
    included.append(interpretation["skill_name"])
    selection_path = MODULE_ROOT / "catalog" / "included_skills.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if not selection.get("included_skills"):
        selection["included_skills"] = included
        dump_json(selection_path, selection)
    else:
        print("Human-managed Catalog allowlist already contains entries; it was not modified.")
    print(f"Created or updated {created} of {len(included)} defined self-contained Skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
