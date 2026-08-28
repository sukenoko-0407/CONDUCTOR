---
name: cs-compute-clustering-vector-hierarchical
description: Apply Vector hierarchical clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. General mode is the default; use CONDUCTOR mode only as an explicit opt-in with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Vector hierarchical clustering

## Purpose

Description Skillが生成した数値vectorへVector hierarchical clusteringを適用し、Clustering artifactを生成する。

## Input

compound IDと数値featureを持つDescription CSVを必須入力とする。raw SMILESは受け付けず、fingerprintやdescriptorを内部生成しない。SMILES列やstatus列はfeatureから除外し、Description値がない行は未割当として保持する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. Description CSVのrepresentationを確認する。CONDUCTORモードではStateが束縛した`--input-representation`とCanonical Description Result 1.0.0を`--description-result`で必ず渡す。一般利用でResultがない場合は`--value-semantics`と非autoの`--metric`を明示する。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. 出力先が既存の場合は上書きせず、意図的な再計算に限って`--overwrite`を使う。
5. 実行後に主成果物を確認する。CONDUCTORモードではmanifest、warnings、execution eventも確認し、Orchestratorへ渡す。

## Algorithm-specific options

`--min-cluster-size`未満のClusterを登録しない。`--metric auto`でCanonical Description Resultに固定されたMetricを使用する。`--parameter-mode auto`を既定とし、Clustering Skill自身がactivityを使わず距離・近傍構造から手法固有parameterを選ぶ。人間が再現条件を固定する場合だけ`--parameter-mode fixed`を使う。autoではaverage-linkage距離gapから切断候補を選ぶ。fixedでは`--n-clusters`または`--distance-threshold`を指定する。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection: mandatory

- 通常モードをdefaultとする。ユーザーが単にこの計算・解析を依頼した場合は`--conductor`を付けない。
- `--conductor`を付けるのは、ユーザーがCONDUCTORでの実行を明示した場合、OrchestratorがDAG nodeとして呼び出した場合、または既存CONDUCTOR runへの接続が明示され完全なrun contextが与えられた場合だけとする。
- CONDUCTOR利用は明示されているがproject、run ID、node IDが未確定なら実行しない。Orchestratorでrun/nodeを初期化するか不足情報を確認し、IDを捏造したり通常モードへ黙って降格したりしない。
- repository名、利用可能なCONDUCTOR artifact、Catalog収載、`results/CONDUCTOR/`形式の`--output-dir`だけを根拠にCONDUCTORモードを推測しない。
- 意図が曖昧なら、出力契約が変わることを示して実行前に確認する。確認できない場合は通常モードとして`--conductor`を省略する。
- 通常モードではCONDUCTOR context引数を指定しない。CONDUCTORモードでは`--conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001`をすべて指定する。CLIもこの組合せを検証する。

Runtime経由ではSkillのCONDUCTOR出力はattempt scratchとして検証され、成功時に現行CONDUCTORの最小正本artifactへ昇格される。

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
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input path/to/description.csv --input-representation D001 --value-semantics dense_continuous --metric euclidean --run-id general-001
```

## CONDUCTOR mode command

明示的なCONDUCTOR利用で、project、run、nodeが確定している場合だけこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --input path/to/description.csv --input-representation D001 --description-result path/to/run_root/description/N000001/result.json --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id N000001 --attempt-id ATT0001
```

## Boundaries

- raw SMILESからDescriptionを内部生成しない。先に適切なDescription Skillを実行する。
- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- 高コストcapabilityは人間が計算資源を明示承認するまで実行しない。CONDUCTORではOrchestratorの承認手順に従う。
