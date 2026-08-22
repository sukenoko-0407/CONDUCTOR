---
name: cs-compute-clustering-structure-mcs
description: Cluster compounds directly from SMILES by maximum common substructure as a mandatory initial CONDUCTOR axis, without generating a hidden descriptor vector or requiring per-run human approval. General mode is the default; use CONDUCTOR mode only as an explicit opt-in with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# MCS clustering

## Purpose

compound IDとSMILESを含むCSVをMCS clusteringにより直接Cluster化し、Clustering artifactを生成する。

## Input

compound IDとSMILESを持つCSVを`--input`へ必ず指定する。inlineの`--smiles`と`--compound-id`は受け付けない。Description CSVを入力とせず、fingerprint vectorを内部生成して距離clusteringへ置き換えない。列が曖昧なら`--id-column`と`--smiles-column`を指定する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. 入力列とClustering固有の上流artifactを確認し、曖昧な列だけを明示指定する。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

`--min-cluster-size`（既定・下限5）、`--max-pairs`（既定・上限1000）、`--max-core-clusters`（既定300）で探索量を制限する。pair上限を適用する場合は`--random-seed`に基づく一様ランダム非復元抽出を行う。MCS pair探索は割当CPU数の範囲で最大8個の単一thread workerを使い、同一SMARTSを重複排除してから全化合物への部分構造照合を最大8 threadで行う。C002は構造Clusteringの中心的な初手であり、runごとの事前承認なしで実行する。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORでの実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードではCONDUCTOR context引数を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001`をすべて指定する。CLIもこの組合せを検証する。

Runtime経由ではSkillのCONDUCTOR出力はattempt scratchとして検証され、成功時に0.1.5の最小正本artifactへ昇格される。

## Output contract

- 通常モード: `results/clustering/<input>/<skill>/<run-id>/`へ`cluster_membership.csv`、`cluster_summary.csv`、`clustering_diagnostics.csv`を生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/clustering/<skill>/<node-id-safe>/attempts/<attempt-id>/`へ通常成果物、Vector Clusteringでは`distance_profile.json`、さらに`clustering_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。

`<node-id-safe>`はnode IDの`:`を`-`へ置換したdirectory名であり、同一Skillの複数node間の出力衝突を防ぐ。

`--output-dir`は両モードの既定出力先より優先するが、モード自体は変更しない。

## Environment

`scripts/launch.py`を使用し、`pixi`を直接実行しない。launcherは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上の`pixi`を使う。Skill directoryからmanifest、lock、runnerの絶対パスを作るため、呼出し元のworking directoryに依存しない。起動前に`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、一時領域、主要な実行時cacheを`<skill>/env/`配下へ強制し、system/user Pixi configを読み込まない。`pixi.lock`がない初回だけ`pixi install`でlockと環境を作成し、以後は`--locked`で再利用する。環境実体は`<skill>/env/.pixi/envs/default/`へ置く。

## General mode command

CONDUCTOR利用が明示されていない場合はこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input compounds.csv --run-id general-001
```

## CONDUCTOR mode command

明示的なCONDUCTOR利用で、project、run、nodeが確定している場合だけこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id N000001 --attempt-id ATT0001
```

## Boundaries

- 一般利用・CONDUCTOR利用ともcompound ID・SMILES CSVを入力とし、inline SMILESは受け付けない。
- Description vectorを入力とせず、CSV内のSMILESを宣言された構造規則で直接処理する。
- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- このcapabilityはCatalogで`approval_policy=preauthorized_initial`とされた必須初手であり、`high` costでもrunごとの人間承認を待たない。人間指定の並列上限とStateの実行制御には従う。
- CONDUCTOR RuntimeではC002を単独Nodeとして実行し、最大8 CPUを他Nodeと競合させない。一般利用でも利用可能CPUを超えず、最大8 Workerとする。
