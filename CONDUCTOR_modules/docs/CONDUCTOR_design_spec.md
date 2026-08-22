# CONDUCTOR 0.1.5 design spec

## 権限境界

| Component | 担当 | 禁止 |
|---|---|---|
| Human | Round開始・継続・改訂・受理、資源承認 | なし |
| Main Orchestrator | 人間依頼の契約化、科学的選択、Executor／Interpreter起動 | Skill直接実行、State直接編集、自動新Round開始 |
| Executor | 署名済packet一つの実行 | 候補選択、引数修正、別Subagent起動 |
| Runtime | ID、FSM、lease、DAG、Request、packet、Attempt、commit、audit | 科学的価値判断 |
| Interpreter | bounded evidenceの個別・横断解釈、ID-free draft | scope／ID発行、新規計算、State変更 |

Main Orchestratorは手動Skillで一時的に有効化し、Projectの`CLAUDE.md`へ常駐させません。ExecutorとInterpreterはMainが直接起動する短命な兄弟Subagentです。

## State階層

`conductor_control.json`は小さい運用正本です。Run設定、active Round、FSM、lease、件数、単一`required_action`、closure gate、詳細file pointerだけを持ちます。再開時は最初にこれだけを読みます。

`runtime/dag_snapshot.json`はRuntime専用の詳細Node表現、`runtime/event_ledger.jsonl`はchecksum chain付き監査履歴です。Control、DAG、Eventはtransaction journalで同期します。LLMは直接編集しません。

Round FSMは`ACTIVE -> FINALIZING -> AWAITING_HUMAN_REVIEW -> CLOSED`です。`CLOSED`から新Roundへ進むには人間の明示指示が必要です。

Node IDはRun全体で`N######`、状態は`pending / running / succeeded / failed / cancelled`だけです。再試行は同じNodeの新Attemptで、最大3回です。成功済み同一signatureは再実行せず、現在Roundの`reused_node_ids`へ参照します。

## 実行契約

各科学NodeにはRuntimeが`execution_request.json`を生成します。構造は次の固定10領域です。

- `identity`
- `inputs`
- `columns`
- `endpoint`
- `subject`
- `parameters`
- `resources`
- `output`
- `created_at`
- `schema_version`

Runtime commandは全Skillで次の形だけです。

```text
<CONDUCTOR_RUNTIME_PYTHON> <skill>/scripts/launch.py --conductor-request <request.json>
```

Capability metadataがadapter profileとdefault parameterを宣言し、Skill内adapterが既存CLIへ変換します。RuntimeはRequest／command hashをpacketへ署名し、Executorはpacketを一回だけ実行します。packet実行直前には、Requestに記録した入力・上流成果物のSHA-256を現在のfile内容と照合し、不一致なら科学process起動前にfail closedとします。one-use Action tokenとExecutor tokenは使わず、単一Writer lease、Control revision、packet署名、一回のatomic state transitionで二重実行を防ぎます。

各Skillのlauncherは`env/pixi.toml`とRelease時に配布する`env/pixi.lock`を使います。ready markerは`pixi.toml + pixi.lock + platform`のfingerprintで検証します。同一Skillが同時に初回起動されても、Skill-local bootstrap lockに記録したowner PID・host・作成時刻により環境構築は一回だけ行い、死んだownerのlockは安全に回収します。cacheと一時fileはGit管理外の`env/`内へ限定し、再現性の正本である`pixi.lock`はGit管理対象です。

Attempt rootはRuntime管理file、`skill_output/`は科学成果物へ分離します。Skill起動前の`skill_output/`は存在させません。stdout/stderrはAttempt logへ逐次書き込み、timeout時はPOSIX process groupまたはWindows process treeを停止します。失敗時の即席CLI修正は廃止し、timeout等の一時障害だけを同一Requestで最大3回再試行します。argument、column、path、schema等の決定論的エラーは人間修正待ちとし、修正後も同じNode IDへ新Attemptを追加します。

## 探索Planner

基本計算はDescription／Clusteringを揃える決定論的段階です。Operator探索は`exploration`一種類で、一Round最大100 Analysis Nodeです。

Plannerは成功済みsignatureを除外し、過去のCapability、Global／Local scope、入力Description／Clusteringの成功数が少ない候補を優先します。Failed Nodeは成功履歴へ数えません。同点は固定seed hashで決めます。Globalを優先し、概ね`Global, Global, Local`の比率で選びます。全候補queueをStateへ保存せず、次Roundで同じ規則から再構成します。

Local候補は対応するGlobal comparatorが存在するときだけ作ります。Global MMP DBは一件、全Cluster screeningは一件、Local detailは代表Clusterに限定し、通常Operatorの全直積へ混ぜません。

## ArtifactとInterpretation

Skill outputはRuntimeがschema、identity、hash、scope、科学的不変条件を検証してから正本へatomic promotionします。Result Cardのartifact linkはRun Root相対pathへ一度だけ正規化し、Result Index、Interpretation、Full Auditでも同じ形式を使います。Description metadataはCanonical Resultだけを下流へ渡します。

A014は全詳細CSV、正規化SQLite、集約CSV、reference card、HTML、storage profileを一括commitします。native work DBとParquetを正本にしません。

RuntimeはInterpretation対象、canonical scope、Result Card、比較batch、未確認範囲、人間focusを固定します。Interpreterは個別確認後にGlobal／Cluster、兄弟Cluster、独立Description family、Operator間、Round間、矛盾、反証、negative resultを比較します。RuntimeがInsight ID、scope、sample factsを確定して固定templateからJSON／Markdown／HTMLを生成します。

InterpretationとFull Auditが合格しない限りRoundをhandoffしません。
