---
name: cs-compute-clustering-categorical
description: Use when Claude Code needs to run Categorical-column clustering from CSV or compatible CONDUCTOR v4 artifacts with a self-contained Pixi environment. General mode is the default; use CONDUCTOR mode only as an explicit opt-in with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Categorical-column clustering

## Purpose

Categorical-column clusteringを単独実行し、一般利用ではClustering、CONDUCTOR内ではGrouping artifactを生成する。

## Input

compound IDと一つ以上のカテゴリ列を持つCSVを使い、`--columns assay,series`のようにGroupingへ使用する列を必ず指定する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. 入力列と必要な上流artifactを確認し、不明な列は明示指定する。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

`--columns`を必須とし、`--min-cluster-size`未満のgroupを出力しない。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORまたはCONDUCTOR v4での実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードでは`--project`と`--node-id`を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID`をすべて指定する。CLIもこの組合せを検証する。

## Output contract

- 通常モード: `results/clustering/<input>/<skill>/<run-id>/`へ`cluster_membership.csv`と`cluster_summary.csv`だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/grouping/<skill>/`へ通常成果物、`group_registry.json`、`grouping_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。

`--output-dir`は両モードの既定出力先より優先するが、モード自体は変更しない。

## Environment

`scripts/launch.py`を使用し、`pixi`を直接実行しない。launcherは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上の`pixi`を使う。Skill directoryからmanifestとrunnerの絶対パスを作るため、呼出し元のworking directoryに依存しない。起動前に`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、一時領域、主要な実行時cacheを`<skill>/env/`配下へ強制し、system/user Pixi configを読み込まない。環境実体は`<skill>/env/.pixi/envs/default/`へ作成または再利用する。

## General mode command

CONDUCTOR利用が明示されていない場合はこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input compounds.csv --columns assay --run-id general-001
```

## CONDUCTOR mode command

明示的なCONDUCTOR利用で、project、run、nodeが確定している場合だけこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input compounds.csv --columns assay --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## Boundaries

- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- 高コストcapabilityは人間が計算資源を明示承認するまで実行しない。CONDUCTORではOrchestratorの承認手順に従う。
