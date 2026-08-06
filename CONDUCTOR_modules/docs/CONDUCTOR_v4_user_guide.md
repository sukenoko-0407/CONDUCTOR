# CONDUCTOR v4 利用手順

## 1. 前提

- Claude Codeをリポジトリ直下で起動する。
- Pythonは3.12を標準とする。
- Linux x86_64を主対象、Windows x86_64を副対象とする。
- Linux/HPCでは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を実行可能にする。各Skillのlauncherがこのパスを優先する。共有パスがないWindowsではPATH上の`pixi`を利用できるようにする。
- 入力分子の標準化は事前に人間が行う。
- 1 runにつきendpointは一つとし、活性の向き`higher_is_better`を必ず指定する。

既存Projectへ組み込む場合は、Project直下に`.claude/agents/`、`.claude/skills/`、`CONDUCTOR_modules/`を配置する。導入手順と配置検証は`CONDUCTOR_modules/README.md`を参照する。

`CONDUCTOR_modules/pyproject.toml`と`CONDUCTOR_modules/uv.lock`は開発・受入試験用であり、Skillの実行時依存ではない。各Skillはフォルダ単位でコピーして利用できる。

各SkillのPixi workspace rootは`<skill>/env/`である。manifestは`<skill>/env/pixi.toml`、lock fileは`<skill>/env/pixi.lock`、環境実体は`<skill>/env/.pixi/envs/default/`となる。バイナリの設置場所、manifestの場所、呼出し時のworking directoryは一致している必要がない。launcherがSkill directoryを基準に絶対パス化するため、環境構築のために`cd`しない。

環境の構築とSkillの実行には必ず`scripts/launch.py`を使い、共有Pixiを直接呼び出さない。launcherは起動前に次の書込み先を作成し、親processに同名変数があってもSkill-local値で上書きしてPixiへ渡す。

- Pixi cache: `<skill>/env/cache/pixi/`
- uv cache: `<skill>/env/cache/uv/`
- pip/XDG/library cache: `<skill>/env/cache/`以下
- Pixi global data: `<skill>/env/pixi-home/`
- XDG config/data/state: `<skill>/env/config/`、`env/data/`、`env/state/`
- 一時file: `<skill>/env/tmp/`

対象には`PIXI_HOME`、`PIXI_CACHE_DIR`、Pixiの全cache-kind変数、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、`XDG_*`、`TMPDIR`/`TMP`/`TEMP`、Matplotlib、Numba、Hugging Face、PyTorch、CUDA/Triton等のcache変数を含む。`PIXI_CACHE_NETFS_REDIRECT=never`を設定するため、NFS上でもcacheを`$SLURM_TMPDIR`等へ移さない。`PIXI_NO_CONFIG=1`によりsystem/user Pixi configを読み込まず、外部の`detached-environments`設定やcache pathを継承しない。HPC固有のmirror、proxy、認証が必要なら、Skillのmanifestまたは実行環境変数として明示する。

## 2. Claude Codeで全体を実行する

Claude Codeの新しいsessionでは、追加したSubagentを認識させるため必要に応じて`/agents`を開くかsessionを再起動する。その後、次のように依頼する。

```text
@cs-conductor-orchestrator
path/to/compounds.csvを入力とし、endpoint=<列名>、higher_is_better=true、
project=jak2、parallel_limit=8でCONDUCTOR v4解析を開始してください。
広く浅い解析後、深掘り候補と承認が必要な計算を報告してください。
```

OrchestratorはPolicy、Catalog、Stateを読み、allowlistに収載されたSkillだけでDAGを計画する。初手の`representative-family-wide-v1`は、3Dを含むDescription 7 node、Grouping 9 node、Operator 36 nodeの計52 nodeを基本とする。GroupingはSMILES直接型3 nodeと、Description artifact入力型6 nodeから成る。A009はC002 MCSとC003 BRICSの重複Groupを評価する。assay条件が複数なら関連nodeを追加する。初期結果の一部に信号がなくても残りを打ち切らない。MCSは高コストでも必須初手として事前許可されており、Stateでrunnableになり次第、runごとの承認待ちなしで実行する。

## 3. Stateを手動操作する

以下の例ではOrchestrator Skillのlauncherを使う。共有Pixiを優先し、Skill-local cacheを設定してから`pixi run`する。未作成なら`<skill>/env/.pixi/envs/default/`を構築し、以後は同じ環境を再利用する。

Catalogの読み取り専用検証:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py catalog --check
```

`CONDUCTOR_modules/`は通常runでは読み取り専用である。人間が収載内容を変更したpackage保守時だけ`catalog --write`を使用する。

run初期化:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state init \
  --input chemble_jak2.csv \
  --endpoint pIC50 \
  --higher-is-better \
  --project jak2 \
  --parallel-limit 8
```

広く浅い初期DAGの作成と実行可能nodeの確認:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state plan-wide \
  --state results/CONDUCTOR/jak2/<run_id>/state.json

python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state runnable \
  --state results/CONDUCTOR/jak2/<run_id>/state.json

python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state status \
  --state results/CONDUCTOR/jak2/<run_id>/state.json
```

`status`の`wide_shallow_coverage`には、Description、Grouping、Operatorの軸別状態が表示される。「ヒントなし」と判断する前に、未実行、失敗、skipと代替の要否を確認する。

人間がDAGを視覚確認したい場合だけ、State JSONを明示して読み取り専用reportを生成する。通常のOrchestration中に自動実行したり、DAG nodeとして登録したりしない。

```bash
python .claude/skills/cs-conductor-state-report/scripts/launch.py \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --explicit-request
```

成果物はStateと同じ場所の`state/<UTC timestamp>/`へ保存される。`state_report.html`は進捗、stage別集計、実行可能node、Group件数、Node詳細をまとめ、`state_dag.svg`は円形Nodeの色とEdgeの線種で実行済み、未実行、失敗、blocked、Interpretation履歴を区別する。`state_nodes.csv`と`state_summary.json`は監査・二次利用向けである。

Groupの詳細は常時Stateへ展開せず、必要なときだけrun共通indexを読む。`groups`は由来と状態を表示し、`discard-group`は低価値領域を自動探索対象から外すが、所属列と履歴は削除しない。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state groups \
  --state results/CONDUCTOR/jak2/<run_id>/state.json --status active

python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state discard-group \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --group-id G_G002_4A91C2D0870FB6E3 --reason "独立表現で支持されず、十分に検討済み"
```

Skill実行後は、Skillが返した`execution_event.json`をStateへ記録する。Capability IDは手法、Node IDはrun内の個別実行を表す。新規Nodeは段階別にDescription=`D###`、Grouping=`G###`、Operator=`O###`、Interpretation=`I###`として自動採番される。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state start \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --node-id D001

# 対応するSkillを実行した後
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state record \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --event results/CONDUCTOR/jak2/<run_id>/description/<skill>/D001/execution_event.json
```

初手nodeは同じSkillを異なる上流sourceへ適用する場合がある。Stateの`input_bindings`、source別`parameters`、`output_dir`をそのまま使用し、最初に見つかったDescriptionやGrouping artifact、共通metricへ置き換えない。特に`cs-compute-clustering-vector-*`へ元のSMILES CSVを渡さず、bindingされたDescription CSVを渡す。A006 SALIではD002=`tanimoto`、D013=`manhattan`、D017=`tanimoto`を使用する。旧形式Node IDに`:`が含まれる場合だけdirectory名で`-`へ変換する。

同一algorithmのvariantを比較する場合はcapabilityを増やさず、parameterを持つ別nodeを追加する。JSON keyはCLIの内部名（hyphenをunderscoreへ変換）を使う。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state add \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --capability-id D002 \
  --parameters-json '{"include_chirality":true}' \
  --reason "stereochemistryを含めた表現で局所矛盾を再評価する"
```

Stateはeventの`configuration`がnodeの`parameters`と一致することを確認する。default variantもCatalogの`default_parameters`からnodeへ記録される。

Skillがeventを生成せず異常終了した場合は、実際のエラーを記録して終了する。`failed` nodeは自動的な再試行対象にならず、再試行が必要なら理由を付けて新しいnodeを計画する。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state fail \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --node-id D001 \
  --reason "Skill process exited before producing execution_event.json"
```

人間が部分的なDescription、Grouping、Operatorを指定する場合も、個別Skillを直接実行しない。Capability、上流Node、parameter、指示理由をStateへ登録してから通常どおりstart・実行・recordする。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state add \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --capability-id A006 --depends-on D002 \
  --human-request \
  --reason "Morgan空間に限定して指定Groupのlandscapeを再評価する"
```

GroupingがDescription-vector型なら対応するDescription Node、Operatorなら必要なDescription/Grouping Nodeを`--depends-on`へ指定する。StateはCatalogの入力契約と重複signatureを検証し、`phase=human_directed`と人間の理由を履歴へ残す。

再開時は入力hashを再確認する。変更がなければ完了nodeを再実行せず、変更があれば影響する下流nodeを`stale`にする。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state resume \
  --state results/CONDUCTOR/jak2/<run_id>/state.json
```

## 4. 高コストnodeの承認

Catalogで`high`または`very_high`のSkill、およびデータ規模のため実行時に高コスト化したnodeは原則として承認が必要である。例外はCatalogで`approval_policy=preauthorized_initial`と明記されたC002 MCSであり、必須初手としてrunごとの承認を求めない。それ以外はOrchestratorの説明で目的、対象、期待情報、CPU/GPU、並列数、代替案を確認してから承認する。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state approve \
  --state results/CONDUCTOR/jak2/<run_id>/state.json \
  --node-id <承認対象のNode-ID> \
  --approve \
  --rationale "Mordred 3D記述子で立体的な仮説を検証する"
```

承認しない場合は`--reject`を使う。拒否されたnodeと、その出力だけに依存する未開始下流nodeは理由付き`skipped`となる。沈黙や過去runの承認を現在runの承認として扱わない。

## 5. Skillを一般用途で単独実行する

DescriptionをCSVから実行:

```bash
python .claude/skills/cs-compute-description-morgan/scripts/launch.py \
  --input compounds.csv --n-bits 2048
```

Morganのchirality variantとGobbi Pharm2DのSVD variantは、それぞれ同じalgorithm Skill内のoptionとして選ぶ。一般利用で複数variantを比較するときは出力衝突を避けるためrun IDまたは`--output-dir`を分ける。

```bash
python .claude/skills/cs-compute-description-morgan/scripts/launch.py \
  --input compounds.csv --include-chirality --run-id chiral-morgan

python .claude/skills/cs-compute-description-gobbi-pharm2d/scripts/launch.py \
  --input compounds.csv --reduction svd --svd-dim 128 --run-id pharm2d-svd
```

複数SMILESから実行:

```bash
python .claude/skills/cs-compute-description-rdkit-2d/scripts/launch.py \
  --smiles "CCO" --smiles "c1ccccc1"
```

Groupingには入力契約が異なる二系統がある。Murcko、MCS、BRICS、RECAPは、compound IDとSMILESを含むCSVを必須入力とし、そのCSV内のSMILESを直接処理する。CLIへのinline `--smiles`入力は受け付けない。

```bash
python .claude/skills/cs-compute-clustering-structure-murcko/scripts/launch.py \
  --input compounds.csv
```

Butina、hierarchical、DBSCAN、Louvain、Leiden、connected-componentsはDescription Skillの数値CSVを処理する。raw SMILESを直接渡してはならない。既定の`--metric auto`はbinaryおよびMorganへTanimoto、USR/USRCATへManhattan、疎な非負countとembedding/SVDへCosine、その他の連続値へ標準化Euclideanを選ぶ。Morgan fingerprintを明示的にTanimotoで処理する例:

```bash
python .claude/skills/cs-compute-description-morgan/scripts/launch.py \
  --input compounds.csv --output-dir results/example/morgan

python .claude/skills/cs-compute-clustering-vector-butina/scripts/launch.py \
  --input results/example/morgan/D002_morgan.csv \
  --input-representation D002 --metric tanimoto
```

MCSでpair数を制限する場合は先頭から抽出せず、再現可能な一様ランダム抽出を行う。`--max-pairs`の上限は1000、`--random-seed`の既定値は61453である。

一般利用はdefaultであり、`--conductor`、`--project`、`--node-id`を指定しない。Description、Clustering、Operatorは主成果物だけを出力する。既定出力は`results/description|clustering|analysis/...`であり、`--output-dir`が常に優先されるが、出力先を`results/CONDUCTOR/`配下にしてもモードは変わらない。

CONDUCTOR artifactとして実行するのは、ユーザーがCONDUCTOR利用を明示した場合、OrchestratorがState DAG nodeを実行する場合、または既存runへの接続が明示された場合に限る。次の4引数を必ず一組として渡す。

```bash
python .claude/skills/cs-compute-description-morgan/scripts/launch.py \
  --input compounds.csv \
  --conductor --project project_name --run-id RUN_ID --node-id D002
```

`--conductor`は主結果に加え、schema検証済みmanifest、warnings、execution eventを生成する。Operatorは`evidence.json`と自己完結`operator_report.html`、Groupingは`group_registry.json`も生成する。Operator reportにはDescription／GroupingのCapabilityとsource Node、対象scope・Group、主要指標、上位明細、制約、parameterを記載し、Interpretationから個別結果を掘り下げる入口とする。

OperatorをGroup局所へ再適用する例:

```bash
python .claude/skills/cs-analysis-sali/scripts/launch.py \
  --input compounds.csv --property-column pIC50 --higher-is-better \
  --description morgan.csv --membership cluster_membership.csv \
  --target-group G_G002_4A91C2D0870FB6E3 --scope-mode within-group \
  --reference-scope global
```

A003、A005、A006、A007は`--comparison-group`と`--scope-mode between-groups`にも対応する。scope比較では同じendpoint、表現、Metricとglobal前処理基準を維持する。

repository名、Catalog収載、CONDUCTOR互換入力、出力先だけからCONDUCTOR利用を推測しない。意図が曖昧なら、出力内容と保存先が変わることを説明して実行前に確認する。確認できない場合は通常モードで実行する。CLIは不完全なCONDUCTOR contextと、通常モードへの`--project`／`--node-id`混入をerrorにする。

CONDUCTOR利用が明示されているのにproject、run ID、node IDが未確定の場合は、通常モードへ降格せず、Orchestratorでrun/nodeを初期化するか不足情報を確認する。Agentが識別子を捏造して実行してはならない。

## 6. Catalogの管理

1. 収載したいSkill名だけを`CONDUCTOR_modules/catalog/included_skills.json`へ人間が追加または削除する。
2. Orchestratorの`catalog`コマンドを実行する。
3. `CONDUCTOR_modules/catalog/catalog.json`と`CONDUCTOR_modules/docs/CONDUCTOR_v4_skill_catalog.md`の差分を確認する。

生成scriptはSkill metadataを検証するが、allowlist自体は変更しない。Skill directoryを作成しただけではCONDUCTORから利用されない。

## 7. Interpretation

専用`cs-conductor-interpreter` Agentは`CONDUCTOR_modules/docs/CONDUCTOR_v4_interpretation_policy.md`に従い、Stateと全evidenceを読み取り専用で比較する。Interpretation nodeは終端であり、State変更やOperator直接実行を行わない。

反復探索前に、人間が探索budgetを設定する。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state configure-exploration \
  --state results/CONDUCTOR/PROJECT/RUN_ID/state.json \
  --max-iterations 5 --max-additional-nodes 40 \
  --walltime-minutes 240 --seed 61453
```

Interpreterには`evidence.json`だけでなく`state.json`を渡す。Capability I001のrunnerは`draft`の`interpretation.json`、`interpretation_context.json`、Markdown、自己完結HTMLを準備する。専用Agentは元artifactを確認し、何を解析し、何を観察し、どう解釈し、なぜ注目するかを具体化して`agent_interpreted`へ最終化する。HはHypothesisの追跡IDであり、Evidence一件ごとには生成しない。Agentが追加解析を必要と判断した場合は、各discoveryに反証要求を持つ`exploration_plan.json`を作る。Interpretation HTMLの「個別解析」linkから対応するOperator HTMLを開き、集約された解釈の根拠となる表現、Group、scope、数値明細を確認できる。

Interpretationだけを再実行する場合もOrchestratorへ依頼する。既存のOperator NodeをEvidence依存として新しいInterpretation Nodeを登録する。最初のNodeが`I001`なら次は自動的に`I002`となるが、Capabilityはどちらも`I001`である。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state add \
  --state results/CONDUCTOR/PROJECT/RUN_ID/state.json \
  --capability-id I001 --depends-on O001,O004,O017 \
  --previous-interpretation-node I001 --human-request \
  --reason "前回結果を踏まえ、指定された観点だけでEvidenceを再比較する"
```

前回Interpretationはread-only contextであり実行依存Nodeではない。`I001`のdirectoryやartifactは上書きせず、`I002`へ新しいreportとeventを保存する。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state register-exploration \
  --state results/CONDUCTOR/PROJECT/RUN_ID/state.json \
  --plan path/to/exploration_plan.json
```

登録時にbudget、seed、Catalog、上流node、Orchestrator指定のGroup/Description/Grouping/Operator bounds、重複・参照不明ID、同一analysis signatureの再実行、Interpretation nodeへの依存、反証要求を検証する。Plan requestに`scope`がある場合は、random、matched random、交差、差分などの選択法とcompound IDを検証し、`interpretation/scopes/`のcontent-addressed membership CSVへ自動変換する。許可された低コストnodeは通常の並列上限内で実行し、高コストnodeは人間承認を求める。結果が多い場合は削除せず、Orchestratorが識別力のある追加Description–Grouping–Operator branchを作り、別のInterpretation nodeで比較する。

## 8. 解析Roundとセッション引継ぎ

同じInput、endpoint、`higher_is_better`について解析を積み重ねる場合は、新しいrunを作らず同じ`state.json`を継続する。追加budgetは消費済みledgerをresetせず、新しい累積上限として設定する。Orchestratorは各人間確認時またはInterpretation Round完了時にrun rootの`session_handoff.md`を更新する。

新しいClaude Codeセッションでは、最初にPolicy、Catalog、`state.json`、`state status`を確認し、その後handoff、最新Interpretation、参照されたevidenceを読む。handoffは現在地とartifactへの索引であり、Stateやevidenceの代替ではない。推奨依頼文とhandoff様式は`CONDUCTOR_modules/docs/prompt/`に収載する。

## 9. 開発者向け確認

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
```

高コストSkillの実計算は通常の受入試験へ含めず、承認されたHPC runで個別に検証する。
