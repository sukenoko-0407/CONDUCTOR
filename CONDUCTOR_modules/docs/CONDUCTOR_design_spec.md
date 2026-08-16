# CONDUCTOR 設計仕様

## Package境界

Claude Codeが直接認識する`.claude/skills/`と`.claude/agents/`をProject直下へ配置し、共有定義、schema、Catalog、Policy、template、検証toolを`CONDUCTOR_modules/`へ配置します。科学Skillは実行codeと`env/pixi.toml`を自分のdirectoryに持ち、単独copy可能です。実行結果は`results/CONDUCTOR/<project>/<run-id>/`だけに書きます。

## 実行主体

- `cs-conductor-orchestrator`: 唯一の人間向けController。科学的候補を選び、Roundを完遂する。
- `cs-conductor-runtime`: Stateの唯一の書込API。ID、DAG、lease、attempt、gate、indexを管理する。
- `cs-conductor-interpreter`: bounded contextを読み、IDなしのInterpretation draftを作る。Stateは変更しない。
- `cs-conductor-run-audit`: Quick／Full監査を行う。Stateは変更しない。
- `cs-conductor-description-migrator`: 0.1.0から成功済みDescriptionだけを新規0.1.1 Runへ決定論的に移す一回限りのAgent。解析は起動しない。

## Stateの階層

`state.json`が正本です。Orchestratorの日常入力は`orchestrator_brief.json`で、全体件数は`state_summary.json`、詳細はRuntime `query`で取得します。外部indexはOperator result、Insight、Next Action、Cluster registry/matrixを保持します。これにより、Roundが増えてもOrchestratorが全Nodeや長文を毎回読む必要はありません。

人間が指定した`parallel_limit`は`round-start`で検証し、現在のRun上限と各Roundの`execution_control`へ記録します。指定を省略した場合だけ直前の値を引き継ぎます。

navigation indexの欠損・件数不一致はAuditで検出します。lease所有者はRuntimeの`rebuild-indices`を使い、成功済attempt artifact、promoted Cluster artifact、State historyから再構築できます。通常運用でindexやledgerを手編集しません。

## DAGとNode

Node prefixはDescription `ND`、Clustering `NC`、Analysis `NA`、Interpretation `NI`です。Edgeは真の入力依存だけを示します。計画上の興味、類似、比較候補はDAG edgeにせずindexやInterpretationで扱います。同一analysis signatureは重複計画しません。

Clustering workerはNode-local Cluster IDを出力し、成功eventのcommit時にRuntimeがRun-global `CL######`へ昇格させます。全compound×ClusterのBoolean matrixとCluster registryを更新します。

## attemptと異常復旧

Node実行のたびに`ATT####`を追加し、出力を`attempts/<attempt-id>/`へ分離します。Runtimeは`running`中のcurrent attemptと一致するeventだけをcommitします。中断時はbootstrapとFull Auditでevent・artifactを照合し、必要なら同じNodeをretryします。

Interpretationは二段階commitです。SkillがIDなしdraftとeventを作り、RuntimeがState lock内でRun-global `INS####`／`ACT####`を割り当てて最終JSON／Markdown／HTMLとledgerを生成します。Operator summaryは短いnavigation indexへ圧縮され、最大20件ずつの多様化した比較batchとしてInterpreterへ渡されます。後発Operatorで再Interpretationが必要になった場合は同じNI Nodeの次attemptを使います。State保存後にcommit manifestを確定し、中間停止はbootstrapで再開します。

## Environment

launcherはLinuxの共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先します。manifest path、binary path、caller working directoryは独立に解決されます。`PIXI_HOME`、Pixi／uv cache、XDG cache、temporary directoryは各Skillの`env/`配下です。lockが未生成の初回だけ`pixi install`を行い、以後は`--locked`で実行します。

## 互換性

alpha版Stateとartifactの汎用的な自動migrationは提供しません。例外として0.1.0から0.1.1へは、成功済みDescription artifactだけを新規RunのRND0001へ移す専用Patchを提供します。旧Clustering、Analysis、Interpretation、IDは引き継がず、RND0002も自動作成しません。
