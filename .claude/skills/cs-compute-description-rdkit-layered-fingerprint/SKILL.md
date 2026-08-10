---
name: cs-compute-description-rdkit-layered-fingerprint
description: Use when Claude Code needs to run RDKit layered fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. General mode is the default; use CONDUCTOR mode only as an explicit opt-in with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# RDKit layered fingerprint

## Purpose

CSVまたは1件以上のSMILESからRDKit layered fingerprintを計算する。

## Input

`--input CSV`または反復可能な`--smiles`を使う。CSVではcompound ID列とSMILES列を推定するが、曖昧なら`--id-column`と`--smiles-column`を指定する。個別SMILESへIDを与える場合は`--compound-id`を同じ回数指定する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. 入力列と必要な上流artifactを確認し、不明な列は明示指定する。OperatorのCONDUCTOR実行では、Stateが束縛したDescription／Clustering Capabilityとsource Node IDを表す`--evaluation-representation`、`--description-node-id`、`--clustering-representation`、`--clustering-node-id`を該当する上流入力とともに渡す。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

`--n-bits`でfingerprintの次元を指定する。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORでの実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードではCONDUCTOR context引数を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001`をすべて指定する。CLIもこの組合せを検証する。

## Output contract

- 通常モード: `results/description/<input>/<skill>/<run-id>/`へ`D009_rdkit_layered.csv`（または`--format parquet`）だけを生成する。
- CONDUCTORモード: `results/CONDUCTOR/<project>/<run-id>/description/<skill>/<node-id-safe>/attempts/<attempt-id>/`へ主成果物、`description_manifest.json`、`warnings.json`、`execution_event.json`を生成しschema検証する。

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
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id ND000001 --attempt-id ATT0001
```

## Boundaries

- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- 高コストcapabilityは人間が計算資源を明示承認するまで実行しない。CONDUCTORではOrchestratorの承認手順に従う。
