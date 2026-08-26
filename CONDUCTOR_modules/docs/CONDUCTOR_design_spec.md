# CONDUCTOR 0.2.0 design spec

## 権限境界

| Component | 担当 | 禁止 |
|---|---|---|
| Human | Round開始・継続・改訂・受理、資源承認 | なし |
| Main Orchestrator | 人間依頼の契約化、科学的選択、Runtime呼び出し、Interpreter起動 | Skill直接実行、State直接編集、自動新Round開始 |
| Runtime Worker | 署名済packetのclaim、科学processの実行・待機・回収 | 科学的候補選択、引数の即席修正、新Round開始 |
| Compatibility Executor | 人間が明示起動したときのみ、packet一つをRuntimeへ中継 | 通常計算、候補選択、引数修正、別Subagent起動 |
| Runtime | ID、FSM、lease、DAG、Request、packet、Attempt、commit、audit | 科学的価値判断 |
| Interpreter | 少数Review Bundleの絶対評価または選抜evidenceのID-free Synthesis draft | scope／ID／Candidate class発行、新規計算、State変更 |

Main Orchestratorは手動Skillで一時的に有効化し、Projectの`CLAUDE.md`へ常駐させません。通常の科学計算はLLM Subagentではなく決定論的なOS Runtime Workerが所有します。InterpreterだけをMainが必要時に短命Subagentとして起動します。Compatibility Executorは通常フローに含めません。

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

Capability metadataがadapter profileとdefault parameterを宣言し、Skill内adapterが既存CLIへ変換します。RuntimeはRequest／command hashをpacketへ署名し、初回claimだけが独立OS Runtime Workerを起動します。packet実行直前には、Requestに記録した入力・上流成果物のSHA-256を現在のfile内容と照合し、不一致なら科学process起動前にfail closedとします。one-use Action tokenとExecutor tokenは使わず、単一Writer lease、Control revision、packet署名、Packet IDとAttemptのatomic結合で二重実行を防ぎます。同じPacketの再投入は既存Workerへの再接続です。

各Skillのlauncherは`env/pixi.toml`とRelease時に配布する`env/pixi.lock`を使います。ready markerは`pixi.toml + pixi.lock + platform`のfingerprintで検証します。同一Skillが同時に初回起動されても、Skill-local bootstrap lockに記録したowner PID・host・作成時刻により環境構築は一回だけ行い、死んだownerのlockは安全に回収します。cacheと一時fileはGit管理外の`env/`内へ限定し、再現性の正本である`pixi.lock`はGit管理対象です。

Attempt rootはRuntime管理file、`skill_output/`は科学成果物へ分離します。Skill起動前の`skill_output/`は存在させません。stdout/stderrはAttempt logへ逐次書き込み、timeout時はPOSIX process groupまたはWindows process treeを停止します。失敗時の即席CLI修正は廃止し、timeout等の一時障害だけを同一Requestで最大3回再試行します。argument、column、path、schema等の決定論的エラーは人間修正待ちとし、修正後も同じNode IDへ新Attemptを追加します。

## 探索Planner

基本計算はDescription／Clusteringを揃える決定論的段階です。Operator探索は`exploration`一種類です。人間指定予算を最大25 NodeのSliceへ分け、各Sliceの成功Resultを既定4 Review BundleずつScreeningしてから次へ進みます。profile安全上限は500、既定予算は50です。

通常Roundの自動Screeningは1 batchずつ進めます。人間が明示した再Screeningだけは、小batchを最大4件のwaveへまとめ、独立した短命Interpreterで並列評価できます。Runtime State、Assessment revision、索引、CSVの更新は従来どおりwriter lock下で一件ずつcommitするため、並列評価がDAGやRound Stateを直接変更することはありません。

Plannerは成功済みsignatureを除外し、過去のCapability、Global／Local scope、入力Description／Clusteringの成功数が少ない候補を優先します。Failed Nodeは成功履歴へ数えません。同点は固定seed hashで決めます。Globalを優先し、概ね`Global, Global, Local`の比率で選びます。全候補queueをStateへ保存せず、次Roundで同じ規則から再構成します。

Local候補は対応するGlobal comparatorが存在するときだけ作ります。A014だけは定型PlannerがGlobal DB一件だけを作り、Local Nodeを自動計画しません。Clustering連携は人間起動のread-only MMP InterpretationがGlobal DBとcanonical membershipから派生集計します。

## ArtifactとInterpretation

Skill outputはRuntimeがschema、identity、hash、scope、科学的不変条件を検証してから正本へatomic promotionします。Result Cardのartifact linkはRun Root相対pathへ一度だけ正規化し、Result Index、Interpretation、Full Auditでも同じ形式を使います。Description metadataはCanonical Resultだけを下流へ渡します。

A014 Globalは全詳細CSV、正規化SQLite、集約CSV、reference card、HTML、storage profileを一括commitします。native work DBとParquetを正本にしません。通常Result CardはMMP候補の入れ子を持たず、coverageと専用Skillへのpointerだけを保持します。

RuntimeはResult Card v2をcomparison familyへ登録し、Global、Global–Local、sibling ClusterのReview Bundleを決定論的に作ります。InterpreterはOperator固有anchorで0～3の複数絶対軸を評価し、Runtimeが信頼性とCandidate classを確定して`runtime/result_assessment_index.jsonl`へcommitします。合計点は作りません。正式Synthesisでは`design_lead`と`contextual_anomaly`から最大50 Resultだけを渡し、支持・反証・negative resultは主候補を限定するために使います。RuntimeがInsight ID、scope、sample factsを確定して固定templateからJSON／Markdown／HTMLを生成します。

`screening` RoundはScreening summaryとFull Audit、`full` RoundはさらにInterpretationが合格しない限りhandoffしません。

CLOSED Roundの一次評価を修正する場合も元Roundは再開しません。人間承認されたhistorical re-Screening Roundが、保存済みReview Bundle集合をhash固定し、Operator予算0で小batch評価、Summary、Auditだけを実行します。Assessmentの実行RoundとSource Roundを分離して記録し、通常Contextには最新revisionだけを載せます。
