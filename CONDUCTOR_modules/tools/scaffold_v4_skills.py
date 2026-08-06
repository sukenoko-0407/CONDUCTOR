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
    ("D012", "cs-compute-description-rdkit-3d", "RDKit 3D descriptors", "rdkit_3d", "3d_shape", "medium", "stable", False),
    ("D013", "cs-compute-description-usr-usrcat", "USR and USRCAT", "usr_usrcat", "3d_shape", "medium", "stable", True),
    ("D014", "cs-compute-description-shape", "Basic 3D shape descriptors", "shape", "3d_shape", "medium", "stable", False),
    ("D015", "cs-compute-description-mordred-2d", "Mordred 2D descriptors", "mordred_2d", "physicochemical", "medium", "experimental", False),
    ("D016", "cs-compute-description-mordred-3d", "Mordred 3D descriptors", "mordred_3d", "3d_shape", "high", "experimental", False),
    ("D017", "cs-compute-description-gobbi-pharm2d", "Gobbi 2D pharmacophore fingerprint (optional SVD)", "gobbi_pharm2d", "pharmacophore", "medium", "stable", True),
    ("D019", "cs-compute-description-pretrained-embedding", "Local pretrained molecular embedding", "pretrained_embedding", "pretrained_embedding", "high", "experimental", False),
    ("D020", "cs-compute-description-tblite-xtb", "GFN2-xTB single-point descriptors", "tblite_xtb", "quantum", "very_high", "experimental", False),
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
    ("A001", "cs-analysis-group-profile", "Group profile", "group_profile", "group_profile", "low", "stable", True, ["grouping"]),
    ("A002", "cs-analysis-activity-distribution", "Activity distribution", "activity_distribution", "property_profile", "low", "stable", True, []),
    ("A003", "cs-analysis-pairwise-structure-similarity", "Pairwise structure similarity", "pairwise_structure_similarity", "feature_space", "medium", "stable", True, []),
    ("A004", "cs-analysis-descriptor-activity-correlation", "Descriptor-activity correlation", "descriptor_activity_correlation", "interpretable_association", "low", "stable", True, ["description"]),
    ("A005", "cs-analysis-knn-activity-consistency", "kNN activity consistency", "knn_activity_consistency", "feature_space", "medium", "stable", True, ["description"]),
    ("A006", "cs-analysis-sali", "Extended structure-activity landscape index", "sali", "landscape", "medium", "stable", True, ["description"]),
    ("A007", "cs-analysis-activity-cliff", "Activity cliff detection", "activity_cliff", "landscape", "medium", "stable", True, []),
    ("A008", "cs-analysis-group-enrichment", "Group activity enrichment", "group_enrichment", "group_profile", "low", "stable", True, ["grouping"]),
    ("A009", "cs-analysis-group-overlap", "Group overlap", "group_overlap", "group_quality", "low", "stable", True, ["grouping"]),
    ("A010", "cs-analysis-group-structural-diversity", "Group structural diversity", "group_structural_diversity", "group_quality", "medium", "stable", True, ["grouping"]),
]


WIDE_PROFILE: dict[str, dict[str, Any]] = {
    "D001": {"wide_shallow_axis": "physicochemical_2d"},
    "D002": {"wide_shallow_axis": "local_circular_graph"},
    "D003": {"wide_shallow_axis": "curated_substructure_keys"},
    "D004": {"wide_shallow_axis": "topological_atom_pairs", "default_parameters": {"n_bits": 2048}},
    "D007": {"wide_shallow_axis": "topological_paths", "default_parameters": {"n_bits": 2048}},
    "D013": {"wide_shallow_axis": "shape_and_3d_pharmacophore", "default_parameters": {"num_confs": 20, "random_seed": 61453}},
    "D017": {"wide_shallow_axis": "pharmacophore_2d"},
    "C001": {"wide_shallow_axis": "scaffold_rule", "default_parameters": {"min_cluster_size": 3}},
    "C002": {"wide_shallow_axis": "maximum_common_substructure", "default_parameters": {"min_cluster_size": 3, "max_pairs": 1000, "max_core_groups": 300, "random_seed": 61453}},
    "C003": {"wide_shallow_axis": "fragment_decomposition", "default_parameters": {"min_cluster_size": 3}},
    "C005": {"wide_shallow_axis": "vector_similarity_partition", "wide_shallow_sources": {"description": ["D002"]}, "default_parameters": {"min_cluster_size": 3, "metric": "auto", "similarity_threshold": 0.55}},
    "C006": {"wide_shallow_axis": "vector_hierarchical", "wide_shallow_sources": {"description": ["D001", "D013", "D017"]}, "default_parameters": {"min_cluster_size": 3, "metric": "auto", "distance_threshold": 0.7}},
    "C007": {"wide_shallow_axis": "vector_density_clustering", "wide_shallow_sources": {"description": ["D001"]}, "default_parameters": {"min_cluster_size": 3, "metric": "auto", "eps": 0.5, "min_samples": 3}},
    "C008": {"default_parameters": {"min_cluster_size": 3, "metric": "auto", "similarity_threshold": 0.55, "resolution": 1.0, "random_seed": 61453}},
    "C009": {"wide_shallow_axis": "vector_graph_community", "wide_shallow_sources": {"description": ["D002"]}, "default_parameters": {"min_cluster_size": 3, "metric": "auto", "similarity_threshold": 0.55, "resolution": 1.0, "random_seed": 61453}},
    "C010": {"default_parameters": {"min_cluster_size": 3, "metric": "auto", "similarity_threshold": 0.55}},
    "C011": {"wide_shallow_axis": "assay_context_groups"},
    "A001": {"wide_shallow_axis": "group_activity_profile", "wide_shallow_sources": {"grouping": ["*"]}, "default_parameters": {"high_quantile": 0.8, "low_quantile": 0.2}},
    "A002": {"wide_shallow_axis": "endpoint_distribution"},
    "A003": {"wide_shallow_axis": "pairwise_structure_space", "default_parameters": {"max_pairs": 200000, "random_seed": 61453}},
    "A004": {"wide_shallow_axis": "descriptor_activity_association", "wide_shallow_sources": {"description": ["D001", "D013"]}},
    "A005": {"wide_shallow_axis": "neighborhood_activity_consistency", "wide_shallow_sources": {"description": ["D004", "D007"]}, "wide_shallow_parameter_overrides": {"description": {"D004": {"metric": "cosine"}, "D007": {"metric": "tanimoto"}}}, "default_parameters": {"k": 10}},
    "A006": {"wide_shallow_axis": "representation_specific_activity_cliffs", "wide_shallow_sources": {"description": ["D002", "D013", "D017"]}, "wide_shallow_parameter_overrides": {"description": {"D002": {"metric": "tanimoto"}, "D013": {"metric": "manhattan"}, "D017": {"metric": "tanimoto"}}}, "default_parameters": {"k": 10}},
    "A007": {"wide_shallow_axis": "structure_activity_cliffs", "default_parameters": {"similarity_threshold": 0.8, "activity_delta_threshold": 1.0, "max_pairs": 200000, "random_seed": 61453}},
    "A008": {"wide_shallow_axis": "group_activity_enrichment", "wide_shallow_sources": {"grouping": ["*"]}, "default_parameters": {"high_quantile": 0.8, "low_quantile": 0.2}},
    "A009": {"wide_shallow_axis": "overlapping_group_structure", "wide_shallow_sources": {"grouping": ["C002", "C003"]}},
    "A010": {"wide_shallow_axis": "group_structural_diversity", "wide_shallow_sources": {"grouping": ["C001", "C002", "C003", "C006"]}, "default_parameters": {"max_pairs": 200000, "random_seed": 61453}},
}


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_wide_profile(capability: dict[str, Any]) -> None:
    profile = WIDE_PROFILE.get(capability["capability_id"])
    if not profile:
        return
    defaults = dict(capability.get("default_parameters") or {})
    defaults.update(profile.get("default_parameters") or {})
    capability.update({key: value for key, value in profile.items() if key != "default_parameters"})
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
    if kind in {"description", "clustering"} or algorithm in {"pairwise_structure_similarity", "activity_cliff", "group_structural_diversity"}:
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
    if algorithm == "pretrained_embedding":
        deps["pytorch-gpu"] = ">=2.3"
        deps["cuda-version"] = ">=12,<13"
        deps["transformers"] = ">=4.41"
    if algorithm == "tblite_xtb":
        deps["tblite-python"] = ">=0.4"
    if kind == "description":
        deps["pyarrow"] = ">=15"
    platforms = '[{ platform = "linux-64", cuda = "12" }, { platform = "win-64", cuda = "12" }]' if algorithm == "pretrained_embedding" else '["linux-64", "win-64"]'
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
from pathlib import Path


def prepare_runtime_environment(skill_dir: Path) -> dict[str, str]:
    env_dir = (skill_dir / "env").resolve()
    cache_root = env_dir / "cache"
    pixi_cache = cache_root / "pixi"
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
        "JOBLIB_TEMP_FOLDER": env_dir / "tmp" / "joblib",
        "TMPDIR": env_dir / "tmp",
        "TMP": env_dir / "tmp",
        "TEMP": env_dir / "tmp",
    }
    for path in set(locations.values()):
        path.mkdir(parents=True, exist_ok=True)
    runtime_env = os.environ.copy()
    runtime_env.update({name: str(path) for name, path in locations.items()})
    runtime_env.update(
        {
            "PIXI_CACHE_NETFS_REDIRECT": "never",
            "PIXI_NO_CONFIG": "1",
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
print(f"INFO: Using Pixi executable: {pixi}", file=sys.stderr)
print(f"INFO: Skill-local cache root: {skill_dir / 'env' / 'cache'}", file=sys.stderr)
command = [pixi, "run", "--manifest-path", str(manifest), "python", str(runner), *arguments]
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
        if capability["implementation"]["algorithm"] == "pretrained_embedding":
            base_args += " --model-dir /shared/models/molecular-model --device cuda"
            inputs += " ローカルmodel weightを`--model-dir`で指定するか、`embed_smiles(smiles, model_dir)`を公開するローカルPython fileを`--adapter`で指定する。外部からmodelを自動downloadしない。"
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
            "pretrained_embedding": "`--model-dir`または`--adapter`を必須とし、`--device cpu|cuda`と`--batch-size`を指定する。built-in loaderはbatch単位で推論し、外部modelを自動downloadしない。",
            "tblite_xtb": "`--num-confs`、`--random-seed`、必要に応じて`--charge`と`--uhf`を指定する。非常に高コストのため人間承認後に実行する。",
        }
        option_guidance = description_options[algorithm]
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID'
        output_contract = f'''- 通常モード: `results/description/<input>/<skill>/<run-id>/`へ`{capability["output"]["basename"]}.csv`（または`--format parquet`）だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/description/<skill>/<node-id-safe>/`へ主成果物、`description_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    elif kind == "clustering":
        algorithm = capability["implementation"]["algorithm"]
        if algorithm.startswith("structure_"):
            purpose = f"compound IDとSMILESを含むCSVを{display}により直接group化し、一般利用ではClustering、CONDUCTOR内ではGrouping artifactを生成する。"
            inputs = "compound IDとSMILESを持つCSVを`--input`へ必ず指定する。inlineの`--smiles`と`--compound-id`は受け付けない。Description CSVを入力とせず、fingerprint vectorを内部生成して距離clusteringへ置き換えない。列が曖昧なら`--id-column`と`--smiles-column`を指定する。"
            boundary_extra = "- 一般利用・CONDUCTOR利用ともcompound ID・SMILES CSVを入力とし、inline SMILESは受け付けない。\n- Description vectorを入力とせず、CSV内のSMILESを宣言された構造規則で直接処理する。\n"
        elif algorithm.startswith("vector_"):
            purpose = f"Description Skillが生成した数値vectorへ{display}を適用し、一般利用ではClustering、CONDUCTOR内ではGrouping artifactを生成する。"
            inputs = "compound IDと数値featureを持つDescription CSVを必須入力とする。raw SMILESは受け付けず、fingerprintやdescriptorを内部生成しない。SMILES列やstatus列はfeatureから除外し、Description値がない行は未割当として保持する。"
            boundary_extra = "- raw SMILESからDescriptionを内部生成しない。先に適切なDescription Skillを実行する。\n"
        else:
            purpose = f"{display}を単独実行し、一般利用ではClustering、CONDUCTOR内ではGrouping artifactを生成する。"
            inputs = "algorithmに対応するmembershipまたはcategorical CSVを使う。"
        base_args = "--input compounds.csv"
        if capability["implementation"]["algorithm"] == "categorical":
            base_args += " --columns assay"
            inputs = "compound IDと一つ以上のカテゴリ列を持つCSVを使い、`--columns assay,series`のようにGroupingへ使用する列を必ず指定する。"
        elif capability["implementation"]["algorithm"] == "meta_overlap":
            base_args = "--input path/to/cluster_membership.csv"
            inputs = "long形式の`cluster_id,compound_id,membership_value`または`group_id,compound_id,membership_value`、もしくは行がcompound、列がGroup IDのBoolean wide形式のmembership CSVを使う。long形式と複数shardでは同一compound IDの反復を許可する。"
        clustering_options = {
            "structure_murcko": "`--min-cluster-size`未満のscaffold groupを出力しない。",
            "structure_mcs": "`--min-cluster-size`（既定3）、`--max-pairs`（既定・上限1000）、`--max-core-groups`（既定300）で探索量を制限する。pair上限を適用する場合は`--random-seed`に基づく一様ランダム非復元抽出を行う。C002は構造Groupingの中心的な初手であり、CONDUCTOR v4ではrunごとの事前承認なしで実行する。",
            "structure_brics": "`--min-cluster-size`未満のfragment groupを出力しない。",
            "structure_recap": "`--min-cluster-size`未満のfragment groupを出力しない。",
            "categorical": "`--columns`を必須とし、`--min-cluster-size`未満のgroupを出力しない。",
            "meta_overlap": "`--similarity-threshold`でsource group間Jaccard graphのedgeを定義し、`--min-cluster-size`未満の統合groupを出力しない。",
        }
        if algorithm.startswith(("structure_", "vector_")) and algorithm.split("_", 1)[1] not in {"murcko", "mcs", "brics", "recap"}:
            method = algorithm.split("_", 1)[1]
            source_options = "`--metric auto`を既定とし、`--input-representation`と実VectorからMetricを決定する。binaryおよびMorganはTanimoto、USR/USRCATはManhattan、疎countとembedding/SVDはCosine、その他の連続値は標準化Euclideanを用いる。binaryまたは既知のbit fingerprintへTanimoto以外を明示すると停止する。"
            method_options = {
                "butina": "`--similarity-threshold`でcluster cutoffを指定する。",
                "hierarchical": "`--n-clusters`または`--distance-threshold`で切断条件を指定する。",
                "dbscan": "`--eps`と`--min-samples`を指定する。",
                "louvain": "`--similarity-threshold`、`--resolution`、`--random-seed`を指定する。",
                "leiden": "`--similarity-threshold`、`--resolution`、`--random-seed`を指定する。",
                "connected_components": "`--similarity-threshold`でgraph edgeを定義する。",
            }[method]
            option_guidance = f"`--min-cluster-size`未満のgroupを出力しない。{source_options}{method_options}"
        else:
            option_guidance = clustering_options[algorithm]
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID'
        output_contract = '''- 通常モード: `results/clustering/<input>/<skill>/<run-id>/`へ`cluster_membership.csv`と`cluster_summary.csv`だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/grouping/<skill>/<node-id-safe>/`へ通常成果物、`group_registry.json`、`grouping_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    elif kind == "analysis":
        purpose = f"{display}を実行し、客観的な数値結果とCONDUCTOR evidenceを生成する。"
        extra = ""
        dependency_text = ""
        if "description" in capability.get("dependencies", []):
            extra += " --description path/to/description.csv"
            dependency_text += " `--description`で数値Description artifactを必ず指定する。"
        if "grouping" in capability.get("dependencies", []):
            extra += " --membership path/to/cluster_membership.csv"
            dependency_text += " `--membership`でGrouping membershipを必ず指定する。"
        base_args = f"--input compounds.csv --property-column pIC50 --higher-is-better{extra}"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" {base_args} --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID'
        inputs = f"元CSV、endpoint列、`--higher-is-better`または`--no-higher-is-better`を必ず指定する。{dependency_text}"
        operator = capability["implementation"]["operator"]
        if operator == "sali":
            purpose = "Description空間の局所的なproperty勾配をSALIで評価し、高SALI cliff pairとlandscape分布の平滑性をCONDUCTOR evidenceとして生成する。"
        analysis_options = {
            "group_profile": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`、任意の`--target-group`を指定できる。",
            "activity_distribution": "全体分布をdefaultとし、任意の`--membership`と`--target-group`でgroup別に限定できる。",
            "pairwise_structure_similarity": "SMILES列を使い、`--max-pairs`でpair数を制限する。上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。Group内／二Group間scopeを指定できる。",
            "descriptor_activity_correlation": "`--description`の全数値featureについてPearson/Spearman相関を計算する。任意のGroup内scopeへ限定できる。",
            "knn_activity_consistency": "`--description`と`--k`を指定する。`--metric auto`はfeature特性から距離を選び、CONDUCTOR初手ではsource別metricをStateへ明示記録する。Group内／二Group間scopeではglobal前処理基準を既定とする。",
            "sali": "`--description`と`--k`を指定する。`--metric auto`はMorgan/binaryへTanimoto、USR/USRCATへManhattan、embedding/SVDまたは疎なcountへcosine、その他の連続descriptorへEuclideanを選ぶ。Group内／二Group間scopeとglobal前処理基準に対応し、高SALI cliff pairとlandscape分布の平滑性をともにevidenceへ残す。",
            "activity_cliff": "`--similarity-threshold`、`--activity-delta-threshold`、`--max-pairs`を指定する。pair上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。Group内／二Group間scopeを指定できる。",
            "group_enrichment": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`を指定する。",
            "group_overlap": "`--membership`を必須とする。初手ではC002 MCSとC003 BRICSを評価する。",
            "group_structural_diversity": "`--membership`を必須とし、SMILES列と`--max-pairs`を使う。pair上限超過時は`--random-seed`による一様ランダム非復元抽出を行う。",
        }
        option_guidance = analysis_options[operator]
        output_contract = f'''- 通常モード: `results/analysis/<input>/<skill>/<run-id>/`へ`{capability["output"]["filename"]}`だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/analysis/<skill>/<node-id-safe>/`へ主成果物、`evidence.json`、`analysis_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    else:
        purpose = "専用Interpretation Policyに従うClaude Code Agent向けに、複数Operator evidence、Group局所性、依存関係、失敗を読み取り専用で整理する。"
        inputs = "`--evidence`または`--evidence-dir`で同一runのevidenceを指定する。CONDUCTORでは`--state`を必ず指定する。"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --evidence-dir path/to/evidence --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --evidence-dir results/CONDUCTOR/PROJECT/RUN_ID/analysis --state results/CONDUCTOR/PROJECT/RUN_ID/state.json --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID'
        output_contract = '''- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`へ`interpretation.json`、`interpretation_context.json`、`interpretation.md`、`interpretation.html`を生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/interpretation/<skill>/<node-id-safe>/`へ同じ成果物とschema検証済み`execution_event.json`を生成する。専用Agentは必要に応じて`exploration_plan.json`を追加する。'''
        option_guidance = "`references/interpretation_policy.md`を完全に読む。`--state`から失敗、skip、依存性、探索ledgerを読み、矛盾とnegative resultを保持する。全discoveryに反証要求を付ける。既存Groupingにないrandom、matched random、交差、差分、boundaryはPlanの`scope`へcompound IDと選択法を記録し、membership生成とOperator実行はOrchestratorへ委ねる。"
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
2. 入力列と必要な上流artifactを確認し、不明な列は明示指定する。
3. algorithm固有optionが必要なら`python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

{option_guidance}

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORまたはCONDUCTOR v4での実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードでは`--project`と`--node-id`を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID`をすべて指定する。CLIもこの組合せを検証する。

## Output contract

{output_contract}

`<node-id-safe>`はnode IDの`:`を`-`へ置換したdirectory名であり、同一Skillの複数node間の出力衝突を防ぐ。

`--output-dir`は両モードの既定出力先より優先するが、モード自体は変更しない。

## Environment

`scripts/launch.py`を使用し、`pixi`を直接実行しない。launcherは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上の`pixi`を使う。Skill directoryからmanifestとrunnerの絶対パスを作るため、呼出し元のworking directoryに依存しない。起動前に`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、一時領域、主要な実行時cacheを`<skill>/env/`配下へ強制し、system/user Pixi configを読み込まない。環境実体は`<skill>/env/.pixi/envs/default/`へ作成または再利用する。

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
    conductor_args = "--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID"

    if kind == "description":
        algorithm = capability["implementation"]["algorithm"]
        family_scenes = {
            "physicochemical": "物性傾向の把握、活性との相関確認、解釈可能な特徴量の作成。",
            "2d_fingerprint": "構造類似性評価、クラスタリング、近傍解析に使う2D表現の作成。",
            "substructure": "部分構造や官能基パターンに基づく比較、Grouping、SAR解析。",
            "3d_shape": "3D形状や立体配置を使った比較、2D表現と異なる観点での深掘り。",
            "pharmacophore": "2D pharmacophore配置に基づく類似性評価やクラスタリング。",
            "pretrained_embedding": "ローカルに配置した事前学習modelから分子embeddingを抽出する場合。",
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
        elif algorithm == "pretrained_embedding":
            general_args += " --model-dir /shared/models/molecular-model --device cuda"
        constraints = ["入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。"]
        if algorithm == "gobbi_pharm2d":
            constraints.append("SVD表現は入力datasetに依存する座標系であり、2件以上のvalid moleculeが必要。")
        if algorithm == "pretrained_embedding":
            constraints.append("model weightを自動downloadしない。`--model-dir`またはlocal adapterが必要。")
        if algorithm in {"rdkit_3d", "usr_usrcat", "shape", "mordred_3d", "tblite_xtb"}:
            constraints.append("入力SMILESからconformerを生成するため、結果と計算時間は3D生成条件の影響を受ける。")
        if approval:
            constraints.append("高コスト計算として、CONDUCTORでは実行前に人間の承認が必要。")
        elif capability.get("approval_policy") == "preauthorized_initial":
            constraints.append("高コストだが、CONDUCTOR v4の必須初手として方針上事前許可されており、runごとの人間承認は不要。人間指定の並列上限には従う。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
    elif kind == "clustering":
        algorithm = capability["implementation"]["algorithm"]
        if algorithm.startswith("structure_"):
            purpose = f"compound IDとSMILESを{display}で直接group化し、cluster membershipとsummaryを生成する。"
            scenes = "SMILESを直接扱うseries分割やscaffold/fragment解析を行い、Description vector由来のClusteringと比較する場合。"
            general_args = "--input compounds.csv"
        elif algorithm.startswith("vector_"):
            purpose = f"Description Skillが生成した数値vectorへ{display}を適用し、cluster membershipとsummaryを生成する。"
            scenes = "descriptor、fingerprint、embedding空間で化合物をgroup化し、SMILESを直接扱う構造Groupingと比較する場合。"
            general_args = "--input description.csv"
        elif algorithm == "categorical":
            purpose = "CSVのカテゴリ列からgroupを作り、cluster membershipとsummaryを生成する。"
            scenes = "assay条件、既知series、sourceなど、人間が付与したカテゴリで化合物を分ける場合。"
            general_args = "--input compounds.csv --columns assay"
        else:
            purpose = "long形式のGrouping結果またはBoolean wide matrix shardにあるcompound重複を使ってmeta groupを生成する。"
            scenes = "複数Groupingの重複関係を要約し、上位のgroup構造を確認する場合。"
            general_args = "--input cluster_membership.csv"
        constraints = ["一般利用ではClustering、CONDUCTOR内ではGroupingとして扱う。入力分子やfeature値は変更しない。"]
        if algorithm.startswith("structure_"):
            constraints.append("Description vectorは入力にせず、fingerprint生成を内部に隠した距離clusteringも行わない。")
            constraints.append("一般利用・CONDUCTOR利用ともcompound IDとSMILESを含むCSVを必須入力とし、CLIへのSMILES直接指定は受け付けない。")
            constraints.append("invalid SMILESは未割当として保持する。分子標準化は行わない。")
        if algorithm == "structure_mcs":
            constraints.append("`--max-pairs`は1～1000に制限し、`--max-core-groups`の既定値は300とする。")
        if algorithm.startswith("vector_"):
            constraints.append("raw SMILESは入力にできず、Descriptionを内部生成しない。`--metric auto`は表現に応じてTanimoto、Manhattan、Cosine、標準化Euclideanを選び、binaryまたは既知のbit fingerprintではTanimoto以外を許可しない。")
            constraints.append("結果は入力feature、距離metric、thresholdまたはcluster数に依存する。")
        if approval:
            constraints.append("高コスト計算として、CONDUCTORでは実行前に人間の承認が必要。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
        extra_example = ""
    elif kind == "analysis":
        operator = capability["implementation"]["operator"]
        operator_scenes = {
            "group_profile": "各groupの活性分布とhigh/low activity比率を比較する場合。",
            "activity_distribution": "endpoint全体または指定groupの分布を最初に把握する場合。",
            "pairwise_structure_similarity": "構造類似度と活性差をpair単位で確認する場合。",
            "descriptor_activity_correlation": "各Description featureと活性の単変量関連を確認する場合。",
            "knn_activity_consistency": "近傍化合物間で活性がどの程度一貫するか評価する場合。",
            "sali": "近い表現を持つ化合物間の大きな活性差を優先順位付けする場合。",
            "activity_cliff": "高い構造類似性と大きな活性差を同時に満たすpairを抽出する場合。",
            "group_enrichment": "特定groupにhigh activity化合物が濃縮されているか評価する場合。",
            "group_overlap": "Grouping内のgroup同士がどの程度重複するか評価する場合。",
            "group_structural_diversity": "各group内の構造的な多様性を評価する場合。",
        }
        purpose = f"{display}を実行し、一般利用向け数値結果とCONDUCTOR向けevidenceを生成する。"
        scenes = operator_scenes[operator]
        general_args = "--input compounds.csv --property-column pIC50 --higher-is-better"
        if "description" in capability.get("dependencies", []):
            general_args += " --description description.csv"
        if "grouping" in capability.get("dependencies", []):
            general_args += " --membership cluster_membership.csv"
        constraints = ["endpoint列と`--higher-is-better`または`--no-higher-is-better`の指定が必要。"]
        constraints.append("数値的観察を出力するOperatorであり、SAR機序や因果関係を確定しない。")
        if operator in {"knn_activity_consistency", "sali"}:
            constraints.append("`--metric auto`はfeature特性から距離を選び、Morgan表現にはTanimoto以外を使用しない。")
        if operator == "sali":
            constraints.append("高SALI pairと、中心・upper tailが示すlandscape平滑性をともに評価し、異なるmetricのraw SALI値を直接比較しない。")
        if approval:
            constraints.append("dataset規模によって高コストになる場合は、CONDUCTORで人間の承認を得る。")
        primary_example = f"python .claude/skills/{name}/scripts/launch.py {general_args}"
        extra_example = ""
    else:
        purpose = "専用Interpretation Agent向けにOperator evidence、Group局所性、依存関係、失敗を読み取り専用で整理し、agent JSONと人間向けreportを生成する。"
        scenes = "異なるDescription・Grouping・Operator間の一致、矛盾、例外、global/local差を比較し、反証を伴う探索要求を作る場合。"
        constraints = ["専用Policyを読み、Interpretation nodeを読み取り専用の終端として扱う。", "全discoveryに反証要求を付け、同じanalysis signatureを再要求しない。", "多重探索結果、negative result、矛盾を削除しない。", "State更新、Operator実行、approval判断、新規SMILES生成は行わない。"]
        primary_example = f"python .claude/skills/{name}/scripts/launch.py --evidence-dir path/to/evidence"
        general_args = "--evidence-dir path/to/evidence --state path/to/state.json"
        extra_example = ""

    constraint_text = "\n".join(f"- {item}" for item in constraints) if constraints else "- 特になし。"
    conductor_example = f"python .claude/skills/{name}/scripts/launch.py {general_args} {conductor_args}"
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


def base_capability(identifier: str, name: str, display: str, stage: str, family: str, cost: str, status: str, wide: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "capability_id": identifier,
        "skill_name": name,
        "display_name": display,
        "version": "4.0.0",
        "stage": stage,
        "family": family,
        "description": f"Use when Claude Code needs to run {display} from CSV or compatible CONDUCTOR v4 artifacts with a self-contained Pixi environment.",
        "cost": {"class": cost, "human_approval_required": cost in {"high", "very_high"}, "hpc_profile": "cpu64" if cost not in {"very_high"} else "a100_cpu8"},
        "applicability": {"status": status, "platforms": ["linux-64", "win-64"], "molecule_standardization": "out_of_scope"},
        "default_wide_shallow": wide,
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
    for schema in schemas:
        shutil.copy2(SCHEMAS / schema, skill_dir / "schemas" / schema)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Create missing CONDUCTOR v4 Skill folders from the development templates.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated Skill files. Manual customizations may be lost.")
    args = parser.parse_args()
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    created = 0
    for identifier, name, display, algorithm, family, cost, status, wide in DESCRIPTIONS:
        capability = base_capability(identifier, name, display, "description", family, cost, status, wide)
        if identifier == "D019":
            capability["cost"]["hpc_profile"] = "a100_cpu8"
        elif identifier == "D020":
            capability["cost"]["hpc_profile"] = "cpu64"
        capability.update({"representation_id": identifier, "dependencies": [], "input_contract": ["csv_or_smiles"], "output": {"basename": f"{identifier}_{algorithm}"}, "implementation": {"algorithm": algorithm}})
        if identifier == "D002":
            capability.update({
                "default_variant": "standard",
                "default_parameters": {"include_chirality": False, "radius": 2, "n_bits": 2048, "encoding": "bit", "use_features": False},
                "variants": [
                    {"id": "standard", "cli": "--no-include-chirality", "description": "Morgan fingerprint without chirality invariants."},
                    {"id": "chiral", "cli": "--include-chirality", "description": "The same Morgan algorithm with chirality invariants enabled."},
                ],
            })
        elif identifier == "D017":
            capability.update({
                "default_variant": "folded",
                "default_parameters": {"reduction": "none", "n_bits": 2048},
                "variants": [
                    {"id": "folded", "cli": "--reduction none --n-bits 2048", "description": "Fold the sparse Gobbi Pharm2D signature into a fixed-width bit vector."},
                    {"id": "svd", "cli": "--reduction svd --svd-dim 256", "description": "Fit TruncatedSVD to the run cohort's raw Gobbi Pharm2D signature matrix."},
                ],
            })
        apply_wide_profile(capability)
        created += create_skill(capability, "description", TEMPLATES / "description_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, algorithm, family, cost, status, wide in CLUSTERINGS:
        capability = base_capability(identifier, name, display, "grouping", family, cost, status, wide)
        if identifier == "C002":
            capability["cost"]["human_approval_required"] = False
            capability["approval_policy"] = "preauthorized_initial"
        if algorithm.startswith("structure_"):
            grouping_kind, dependency, input_contract = "direct_structure", [], ["compound_id_smiles_csv"]
            description = f"Group compounds from a compound-ID/SMILES CSV with {display}, without generating a hidden descriptor vector."
        elif algorithm.startswith("vector_"):
            grouping_kind, dependency, input_contract = "description_vector", ["description"], ["description_vector_csv"]
            description = f"Apply {display} to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally."
        elif algorithm == "meta_overlap":
            grouping_kind, dependency, input_contract = "meta", ["grouping"], ["group_membership_csv"]
            description = capability["description"]
        else:
            grouping_kind, dependency, input_contract = "categorical", [], ["categorical_csv"]
            description = capability["description"]
        capability.update({"grouping_kind": grouping_kind, "description": description, "clustering_id": identifier, "dependencies": dependency, "input_contract": input_contract, "output": {"membership": "cluster_membership.csv", "summary": "cluster_summary.csv"}, "implementation": {"algorithm": algorithm}})
        if identifier == "C002":
            capability["description"] = "Group compounds directly from SMILES by maximum common substructure as a mandatory initial CONDUCTOR v4 Grouping axis, without generating a hidden descriptor vector or requiring per-run human approval."
        apply_wide_profile(capability)
        created += create_skill(capability, "clustering", TEMPLATES / "clustering_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, operator, family, cost, status, wide, dependencies in OPERATORS:
        capability = base_capability(identifier, name, display, "analysis", family, cost, status, wide)
        capability.update({"operator_id": identifier, "dependencies": dependencies, "input_contract": ["endpoint_csv", *dependencies], "output": {"filename": f"{identifier}_{operator}.csv", "evidence": "evidence.json"}, "implementation": {"operator": operator}})
        capability["scope_support"] = {
            "A001": ["global", "within-group"],
            "A002": ["global", "within-group"],
            "A003": ["global", "within-group", "between-groups"],
            "A004": ["global", "within-group"],
            "A005": ["global", "within-group", "between-groups"],
            "A006": ["global", "within-group", "between-groups"],
            "A007": ["global", "within-group", "between-groups"],
            "A008": ["global", "within-group"],
            "A009": ["global"],
            "A010": ["global", "within-group"],
        }[identifier]
        if identifier == "A006":
            capability["description"] = "Use when Claude Code needs to evaluate local property-landscape roughness and smoothness with representation-aware SALI, preserve high-SALI cliff pairs for interpretation, and generate CONDUCTOR v4 evidence."
        apply_wide_profile(capability)
        created += create_skill(capability, "analysis", TEMPLATES / "operator_run.py", ["execution_event.schema.json", "evidence.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    interpretation = base_capability("I001", "cs-analysis-interpret-evidence", "SAR evidence interpretation", "interpretation", "evidence_integration", "low", "stable", False)
    interpretation.update({
        "description": "Use when the dedicated Claude Code Interpretation Agent must explore CONDUCTOR v4 evidence across representations, groups, scopes, and Operators under a read-only Policy, preserve contradictions, and prepare falsification-oriented exploration requests and human reports.",
        "interpretation_id": "I001",
        "dependencies": ["evidence"],
        "input_contract": ["evidence_json", "optional_state_json_read_only", "interpretation_policy_markdown"],
        "output": {"json": "interpretation.json", "markdown": "interpretation.md", "html": "interpretation.html", "context": "interpretation_context.json", "exploration_plan": "exploration_plan.json"},
        "implementation": {"purpose": "policy_guided_iterative_evidence_exploration", "state_access": "read_only", "execution_authority": "orchestrator_only"},
    })
    interpretation_created = create_skill(interpretation, "interpretation", TEMPLATES / "interpretation_run.py", ["execution_event.schema.json", "interpretation.schema.json", "interpretation_exploration_plan.schema.json", "evidence.schema.json"], args.force)
    created += interpretation_created
    if interpretation_created:
        references = SKILLS_ROOT / interpretation["skill_name"] / "references"
        references.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MODULE_ROOT / "docs" / "CONDUCTOR_v4_interpretation_policy.md", references / "interpretation_policy.md")
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
