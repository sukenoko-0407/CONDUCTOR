from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".claude" / "skills"
TEMPLATES = ROOT / "tools" / "templates"
SCHEMAS = ROOT / "schemas"


DESCRIPTIONS = [
    ("D001", "cs-compute-description-rdkit-2d", "RDKit 2D descriptors", "rdkit_2d", "physicochemical", "low", "stable", True),
    ("D002", "cs-compute-description-morgan", "Morgan fingerprint (optional chirality)", "morgan", "2d_fingerprint", "low", "stable", True),
    ("D003", "cs-compute-description-maccs", "MACCS keys", "maccs", "2d_fingerprint", "low", "stable", False),
    ("D004", "cs-compute-description-atom-pair", "Hashed atom-pair fingerprint", "atom_pair", "2d_fingerprint", "low", "stable", False),
    ("D005", "cs-compute-description-topological-torsion", "Hashed topological-torsion fingerprint", "topological_torsion", "2d_fingerprint", "low", "stable", False),
    ("D006", "cs-compute-description-rdkit-fragment", "RDKit fragment counts", "rdkit_fragment", "substructure", "low", "stable", False),
    ("D007", "cs-compute-description-rdkit-path-fingerprint", "RDKit path fingerprint", "rdkit_path", "2d_fingerprint", "low", "stable", False),
    ("D008", "cs-compute-description-rdkit-pattern-fingerprint", "RDKit pattern fingerprint", "rdkit_pattern", "substructure", "low", "stable", False),
    ("D009", "cs-compute-description-rdkit-layered-fingerprint", "RDKit layered fingerprint", "rdkit_layered", "2d_fingerprint", "low", "stable", False),
    ("D010", "cs-compute-description-avalon-fingerprint", "Avalon fingerprint", "avalon", "2d_fingerprint", "low", "stable", False),
    ("D012", "cs-compute-description-rdkit-3d", "RDKit 3D descriptors", "rdkit_3d", "3d_shape", "medium", "stable", False),
    ("D013", "cs-compute-description-usr-usrcat", "USR and USRCAT", "usr_usrcat", "3d_shape", "medium", "stable", False),
    ("D014", "cs-compute-description-shape", "Basic 3D shape descriptors", "shape", "3d_shape", "medium", "stable", False),
    ("D015", "cs-compute-description-mordred-2d", "Mordred 2D descriptors", "mordred_2d", "physicochemical", "medium", "experimental", False),
    ("D016", "cs-compute-description-mordred-3d", "Mordred 3D descriptors", "mordred_3d", "3d_shape", "high", "experimental", False),
    ("D017", "cs-compute-description-gobbi-pharm2d", "Gobbi 2D pharmacophore fingerprint (optional SVD)", "gobbi_pharm2d", "pharmacophore", "medium", "stable", False),
    ("D019", "cs-compute-description-pretrained-embedding", "Local pretrained molecular embedding", "pretrained_embedding", "pretrained_embedding", "high", "experimental", False),
    ("D020", "cs-compute-description-tblite-xtb", "GFN2-xTB single-point descriptors", "tblite_xtb", "quantum", "very_high", "experimental", False),
]


CLUSTERINGS = [
    ("C001", "cs-compute-clustering-structure-murcko", "Murcko scaffold clustering", "structure_murcko", "structure_rule", "low", "stable", True),
    ("C002", "cs-compute-clustering-structure-mcs", "MCS clustering", "structure_mcs", "structure_rule", "high", "experimental", False),
    ("C003", "cs-compute-clustering-structure-brics", "BRICS fragment clustering", "structure_brics", "structure_rule", "medium", "stable", False),
    ("C004", "cs-compute-clustering-structure-recap", "RECAP fragment clustering", "structure_recap", "structure_rule", "medium", "stable", False),
    ("C005", "cs-compute-clustering-structure-butina", "Structure Butina clustering", "structure_butina", "structure_similarity", "medium", "stable", True),
    ("C006", "cs-compute-clustering-structure-hierarchical", "Structure hierarchical clustering", "structure_hierarchical", "structure_similarity", "medium", "stable", False),
    ("C007", "cs-compute-clustering-structure-dbscan", "Structure DBSCAN clustering", "structure_dbscan", "structure_similarity", "medium", "stable", False),
    ("C008", "cs-compute-clustering-structure-louvain", "Structure Louvain clustering", "structure_louvain", "structure_similarity", "medium", "stable", False),
    ("C009", "cs-compute-clustering-structure-leiden", "Structure Leiden clustering", "structure_leiden", "structure_similarity", "medium", "stable", False),
    ("C010", "cs-compute-clustering-structure-connected-components", "Structure connected-component clustering", "structure_connected_components", "structure_similarity", "medium", "stable", False),
    ("C011", "cs-compute-clustering-vector-butina", "Vector Butina clustering", "vector_butina", "vector", "medium", "stable", False),
    ("C012", "cs-compute-clustering-vector-hierarchical", "Vector hierarchical clustering", "vector_hierarchical", "vector", "medium", "stable", True),
    ("C013", "cs-compute-clustering-vector-dbscan", "Vector DBSCAN clustering", "vector_dbscan", "vector", "medium", "stable", False),
    ("C014", "cs-compute-clustering-vector-louvain", "Vector Louvain clustering", "vector_louvain", "vector", "medium", "stable", False),
    ("C015", "cs-compute-clustering-vector-leiden", "Vector Leiden clustering", "vector_leiden", "vector", "medium", "stable", False),
    ("C016", "cs-compute-clustering-vector-connected-components", "Vector connected-component clustering", "vector_connected_components", "vector", "medium", "stable", False),
    ("C017", "cs-compute-clustering-categorical", "Categorical-column clustering", "categorical", "human_context", "low", "stable", False),
    ("C018", "cs-compute-clustering-meta-overlap", "Overlap-based meta clustering", "meta_overlap", "meta", "medium", "experimental", False),
]


OPERATORS = [
    ("A001", "cs-analysis-group-profile", "Group profile", "group_profile", "group_profile", "low", "stable", True, ["grouping"]),
    ("A002", "cs-analysis-activity-distribution", "Activity distribution", "activity_distribution", "property_profile", "low", "stable", True, []),
    ("A003", "cs-analysis-pairwise-structure-similarity", "Pairwise structure similarity", "pairwise_structure_similarity", "feature_space", "medium", "stable", False, []),
    ("A004", "cs-analysis-descriptor-activity-correlation", "Descriptor-activity correlation", "descriptor_activity_correlation", "interpretable_association", "low", "stable", True, ["description"]),
    ("A005", "cs-analysis-knn-activity-consistency", "kNN activity consistency", "knn_activity_consistency", "feature_space", "medium", "stable", True, ["description"]),
    ("A006", "cs-analysis-sali", "Structure-activity landscape index", "sali", "landscape", "medium", "stable", True, ["description"]),
    ("A007", "cs-analysis-activity-cliff", "Activity cliff detection", "activity_cliff", "landscape", "medium", "stable", True, []),
    ("A008", "cs-analysis-group-enrichment", "Group activity enrichment", "group_enrichment", "group_profile", "low", "stable", True, ["grouping"]),
    ("A009", "cs-analysis-group-overlap", "Group overlap", "group_overlap", "group_quality", "low", "stable", False, ["grouping"]),
    ("A010", "cs-analysis-group-structural-diversity", "Group structural diversity", "group_structural_diversity", "group_quality", "medium", "stable", False, ["grouping"]),
]


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/description/<skill>/`へ主成果物、`description_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    elif kind == "clustering":
        purpose = f"{display}を単独実行し、一般利用ではClustering、CONDUCTOR内ではGrouping artifactを生成する。"
        algorithm = capability["implementation"]["algorithm"]
        if algorithm.startswith("structure_"):
            inputs = "compound IDとSMILESを持つCSV、または反復可能な`--smiles`を使う。列が曖昧なら`--id-column`と`--smiles-column`を指定する。"
        elif algorithm.startswith("vector_"):
            inputs = "compound IDと数値featureを持つDescription CSVを使う。SMILES列やstatus列はfeatureから自動除外する。"
        else:
            inputs = "algorithmに対応するmembershipまたはcategorical CSVを使う。"
        base_args = "--input compounds.csv"
        if capability["implementation"]["algorithm"] == "categorical":
            base_args += " --columns assay"
            inputs = "compound IDと一つ以上のカテゴリ列を持つCSVを使い、`--columns assay,series`のようにGroupingへ使用する列を必ず指定する。"
        elif capability["implementation"]["algorithm"] == "meta_overlap":
            base_args = "--input path/to/cluster_membership.csv"
            inputs = "long形式の`cluster_id,compound_id`またはIDとgroup列を持つwide形式のmembership CSVを使う。long形式ではoverlapを表す同一compound IDの反復を許可する。"
        clustering_options = {
            "structure_murcko": "`--min-cluster-size`未満のscaffold groupを出力しない。",
            "structure_mcs": "`--min-cluster-size`、`--max-pairs`、`--max-core-groups`で探索量を制限する。高コストのため人間承認後に実行する。",
            "structure_brics": "`--min-cluster-size`未満のfragment groupを出力しない。",
            "structure_recap": "`--min-cluster-size`未満のfragment groupを出力しない。",
            "categorical": "`--columns`を必須とし、`--min-cluster-size`未満のgroupを出力しない。",
            "meta_overlap": "`--similarity-threshold`でsource group間Jaccard graphのedgeを定義し、`--min-cluster-size`未満の統合groupを出力しない。",
        }
        if algorithm.startswith(("structure_", "vector_")) and algorithm.split("_", 1)[1] not in {"murcko", "mcs", "brics", "recap"}:
            method = algorithm.split("_", 1)[1]
            source_options = "`--radius`と`--n-bits`を指定できる。" if algorithm.startswith("structure_") else "`--metric`を指定できる。"
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
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/grouping/<skill>/`へ通常成果物、`group_registry.json`、`grouping_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
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
        analysis_options = {
            "group_profile": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`、任意の`--target-group`を指定できる。",
            "activity_distribution": "全体分布をdefaultとし、任意の`--membership`と`--target-group`でgroup別に限定できる。",
            "pairwise_structure_similarity": "SMILES列を使い、`--max-pairs`でpair列挙を制限する。",
            "descriptor_activity_correlation": "`--description`の全数値featureについてPearson/Spearman相関を計算する。algorithm固有optionはない。",
            "knn_activity_consistency": "`--description`、`--k`、`--metric`を指定する。",
            "sali": "`--description`、`--k`、`--metric`を指定し、近傍edge上でSALIを計算する。",
            "activity_cliff": "`--similarity-threshold`、`--activity-delta-threshold`、`--max-pairs`を指定する。",
            "group_enrichment": "`--membership`を必須とし、`--high-quantile`、`--low-quantile`を指定する。",
            "group_overlap": "`--membership`を必須とする。algorithm固有optionはない。",
            "group_structural_diversity": "`--membership`を必須とし、SMILES列と`--max-pairs`を使う。",
        }
        option_guidance = analysis_options[operator]
        output_contract = f'''- 通常モード: `results/analysis/<input>/<skill>/<run-id>/`へ`{capability["output"]["filename"]}`だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/analysis/<skill>/`へ主成果物、`evidence.json`、`analysis_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。'''
    else:
        purpose = "複数Operator evidenceを統合し、agent向けJSONと人間向けMarkdown/HTMLを生成する。"
        inputs = "`--evidence`または`--evidence-dir`で一つ以上のevidence JSONを指定する。"
        general_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --evidence-dir path/to/evidence --run-id general-001'
        conductor_example = f'python "${{CLAUDE_SKILL_DIR}}/scripts/launch.py" --evidence-dir results/CONDUCTOR/PROJECT/RUN_ID/analysis --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID'
        output_contract = '''- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`へ`interpretation.json`、`interpretation.md`、`interpretation.html`を生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/interpretation/<skill>/`へ同じ三成果物とschema検証済み`execution_event.json`を生成する。'''
        option_guidance = "`--evidence`は反復可能で、`--evidence-dir`も反復可能である。異なるrun IDのevidenceは混在させない。"
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

- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- 高コストcapabilityは人間が計算資源を明示承認するまで実行しない。CONDUCTORではOrchestratorの承認手順に従う。
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
        created += create_skill(capability, "description", TEMPLATES / "description_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, algorithm, family, cost, status, wide in CLUSTERINGS:
        capability = base_capability(identifier, name, display, "grouping", family, cost, status, wide)
        dependency = ["description"] if algorithm.startswith("vector_") else (["grouping"] if algorithm == "meta_overlap" else [])
        input_contract = ["description_csv"] if algorithm.startswith("vector_") else (["group_membership_csv"] if algorithm == "meta_overlap" else (["categorical_csv"] if algorithm == "categorical" else ["csv_or_smiles"]))
        capability.update({"clustering_id": identifier, "dependencies": dependency, "input_contract": input_contract, "output": {"membership": "cluster_membership.csv", "summary": "cluster_summary.csv"}, "implementation": {"algorithm": algorithm}})
        created += create_skill(capability, "clustering", TEMPLATES / "clustering_run.py", ["execution_event.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    for identifier, name, display, operator, family, cost, status, wide, dependencies in OPERATORS:
        capability = base_capability(identifier, name, display, "analysis", family, cost, status, wide)
        capability.update({"operator_id": identifier, "dependencies": dependencies, "input_contract": ["endpoint_csv", *dependencies], "output": {"filename": f"{identifier}_{operator}.csv", "evidence": "evidence.json"}, "implementation": {"operator": operator}})
        created += create_skill(capability, "analysis", TEMPLATES / "operator_run.py", ["execution_event.schema.json", "evidence.schema.json", "artifact_manifest.schema.json"], args.force)
        included.append(name)
    interpretation = base_capability("I001", "cs-analysis-interpret-evidence", "SAR evidence interpretation", "interpretation", "evidence_integration", "low", "stable", True)
    interpretation.update({"interpretation_id": "I001", "dependencies": ["evidence"], "input_contract": ["evidence_json"], "output": {"json": "interpretation.json", "markdown": "interpretation.md", "html": "interpretation.html"}, "implementation": {"purpose": "evidence_interpretation"}})
    created += create_skill(interpretation, "interpretation", TEMPLATES / "interpretation_run.py", ["execution_event.schema.json", "interpretation.schema.json", "evidence.schema.json"], args.force)
    included.append(interpretation["skill_name"])
    selection_path = ROOT / "catalog" / "included_skills.json"
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
