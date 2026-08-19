# CONDUCTOR 0.1.3 Main Agent Orchestration 実装計画書

## 1. 目的

本計画は、[CONDUCTOR_0.1.3_main_orchestrator_overview.md](CONDUCTOR_0.1.3_main_orchestrator_overview.md)を実装するための作業順序、変更境界、試験、cutover条件を定める。

`0.1.3`では、Main AgentをOrchestratorとし、Tool callの多い処理を短命なExecutor Subagentへ隔離する。`0.1.2`のRuntime基盤を利用するが、`0.1.2`の実運用評価を前提にせず、機能を`0.1.3`統合試験で再確認する。

実装branchは`0.1.3`とする。現行コードはGitに保持されているため、新しいArchiveを作成しない。

## 2. 優先順位

1. Main Agent contextをTool call失敗と再試行から隔離する。
2. Claude CodeのSubagent制約と一致する起動構造にする。
3. 人間によるRound開始・継続・確定権限を維持する。
4. Runtime単一Writerと状態遷移の頑健性を維持する。
5. InterpretationとAuditを必須終端とする。
6. Skill引数不備等へ対応できる監査可能な柔軟性を残す。
7. Description、Clustering、Operatorの科学計算kernelを維持する。
8. 既存projectの`CLAUDE.md`と共存する。

## 3. 変更境界

### 3.1 大幅に変更するもの

- Main Agent用Orchestration Skill
- 既存Dispatcher SkillとOrchestrator Agentの役割
- Executor Subagentと実行packet
- Runtime CLIの応答形式
- lease、Action token、Executor capabilityの境界
- Tool call failure分類、回復budget、recovery manifest
- Interpreterの起動主体
- Agent／SkillのPackage install構成
- Orchestration関連tests、文書、prompt

### 3.2 原則維持するもの

- Description、Clustering、Operatorの科学計算kernel
- 各Skill内のPixi環境
- Capability Catalogの科学的収載内容
- `conductor_control.json`、Event Ledger、DAG Snapshot、Result Index
- Node 5状態とRun-global Node ID
- Round FSMと人間権限
- bounded Working Set
- canonical `analysis_subject`
- Interpretation schema、固定HTML template、Quality gate
- Concierge、Node Review、State Report
- 一般利用時のSkill I/O

### 3.3 実施しないもの

- Agent Teams依存
- Subagentのnested spawn
- Stage別LLM Subagentの大量追加
- 0.1.1 Run migration
- 0.1.2互換wrapper
- 科学計算kernelの一括改変
- project既存`CLAUDE.md`の自動編集
- Run中のSkill source自動修正

## 4. 目標構成

```text
.claude/
├── agents/
│   ├── cs-conductor-executor.md
│   └── cs-conductor-interpreter.md
└── skills/
    ├── cs-conductor-orchestrator/
    ├── cs-conductor-runtime/
    ├── cs-conductor-run-audit/
    ├── cs-conductor-node-review/
    ├── cs-conductor-state-report/
    └── cs-conductor-result-concierge/
```

削除対象は次のとおりである。

- `.claude/agents/cs-conductor-orchestrator.md`
- `.claude/skills/cs-conductor-dispatch/`

`cs-conductor-dispatch`の必要機能は`cs-conductor-orchestrator` Skillへ統合する。名称重複を避けるため、`cs-conductor-orchestrator`はSkillとしてのみ存在させる。

`cs-conductor-orchestrator`には、AI向け`SKILL.md`に加えて人間向け`README.md`、`capability.json`、薄いcontrol client、必要最小限のPixi定義を置く。既存DispatcherのCapability IDは可能な限り維持し、単なる名称変更で新しい管理IDを増やさない。

## 5. 実装Phase

### Phase 0: Baselineとinventory

- branchが`0.1.3`であることを確認する。
- worktreeがcleanであることを確認する。
- `0.1.2`のunit test、package verification、Catalog validation結果をbaselineとして取得する。
- Runtime command、required action、response size、agent起動箇所をinventory化する。
- Runtimeから完全Controlを返しているcommandを列挙する。
- 既存Orchestratorが直接行うBash／Skill callを分類する。
- Tool call failure、引数不一致、retry、Interpretation起動のfixtureを準備する。
- 対象projectの`CLAUDE.md`とpermissionがSubagent起動、Run Root書込み、Runtime実行と競合しないかを確認するpreflight項目を定義する。
- 同期filesystem、Linux共有filesystem、長時間processについて現行`execute-batch`の挙動をbaseline化する。

完了条件は、Mainへ残す処理、Executorへ移す処理、Runtimeへ移す処理が表で確定していることである。

### Phase 1: Role contractの固定

- Main Agent、Executor、Interpreter、Runtime、人間の権限表を作る。
- Main Agentが実行できるRuntime actionを限定する。
- Executorへ渡すaction-scoped capabilityを定義する。
- Interpreterへ渡すID-free draft contractを再確認する。
- Main Agentのcompact result envelope schemaを定義する。
- execution packet、failure packet、recovery manifest schemaを定義する。
- Main AgentとExecutorの同時書込みが起きない遷移表を作る。
- 一時fileを許可する条件、配置、記録、破棄、正式昇格禁止を固定する。
- execution packet、failure packet、compact envelopeを正本Stateにしないことを固定する。
- Node状態、Round状態、global ID体系を本改良で増やさないことを固定する。

権限の目安は次のとおりとする。

| 操作 | Human | Main | Executor | Interpreter | Runtime |
|---|---:|---:|---:|---:|---:|
| 新Round開始指示 | Yes | 受付 | No | No | 検証・適用 |
| 科学候補選択 | priority | Yes | No | No | 適用条件検証 |
| Skill process実行 | No | No | Yes | No | command生成・監視 |
| 回復用一時file | No | No | scratch内 | No | 記録・検証 |
| Interpretation draft | review | No | No | Yes | context固定・commit |
| Node ID／Status更新 | No | No | No | No | Yes |
| Round終了判定 | accept | No | No | No | gate判定 |

### Phase 2: Runtime compact API

- Main Agent向けRuntime応答をcompact envelopeへ変更する。
- 完全Controlを各mutation responseへ埋め込まない。
- `required_action`、revision、件数、closure gate、detail pointerだけを標準応答にする。
- 詳細取得は明示的なbounded queryへ分離する。
- compact responseのserialized size上限を定めてtestする。
- 既存Action tokenのsingle-use、revision binding、Round bindingを維持する。
- Main sessionをlease ownerとし、Executorへleaseそのものを渡さない方式を実装する。
- Executor用のaction-scoped tokenまたは署名済execution packetを実装する。
- stale Executor、重複Executor、別Round packetを拒否する。
- compact envelopeへ`protocol_version`、required Skill、current revisionを含める。
- Orchestrator Skill内のcontrol clientでpath解決、CLI escape、control authority注入、compact JSON出力を行う。
- mutation応答喪失時は自動再送せず、Control revisionと`verify-return`で照合して二重適用を避ける。

MainがRuntime commandのraw stdoutを受け取らないよう、CLIはmachine-readable compact JSONと詳細log fileを分離する。

### Phase 3: Execution packetとExecutor

- `.claude/agents/cs-conductor-executor.md`を追加する。
- Executorのtool allowlistを必要最小限にする。
- ExecutorからAgent toolを除外し、Subagent起動を試みないようにする。
- Runtimeがexecution packetを生成する。
- packetにcommand、cwd、env、input、expected output、validation、timeout、recovery budgetを含める。
- Executorは一packetまたは一batchを実行したら終了する。
- Runtime内部process poolで`parallel_limit`を実現し、複数Executorを並列起動しない。
- stdout／stderrをNode scratchのlogへredirectする。
- Executor final responseをcompact result envelopeへ固定する。
- envelopeはRuntimeが生成・schema検証し、Executorの自由記述を正本にしない。
- envelopeが上限を超える場合はdetail pointerへ置き換える。
- execution packet作成時にCapability、入力Node、入力Artifact、launcher、共通CONDUCTOR引数、出力先を固定する。
- packet構築failureではExecutorを起動せず、実行時のCapability固有CLI不整合はExecutor内の有限回復へ隔離する。
- process recordを実行前に永続化し、Executor／Tool call中断後に同じNodeとAttemptをreconcileできるようにする。
- Runtimeが`still_running`とprocess IDを返し、Main instructionで短間隔pollと重複Executorを防ぐ。

Executorが独自に全State、Catalog全体、過去Reportを探索しないことをinstructionとtestで確認する。

### Phase 4: 適応的実行回復

- failureを少なくとも次へ分類する。
  - transient process failure
  - environment initialization failure
  - argument contract mismatch
  - path／working-directory mismatch
  - input format／column mismatch
  - payload validation failure
  - scientific negative result
  - non-recoverable implementation failure
- Runtimeが回復可能分類にだけ有限のrecovery budgetを発行する。
- Executorが該当Skillの必要最小限のdocument、metadata、launcher help、実装箇所を確認できるようにする。
- 回復用directoryをNode Attempt scratch配下へ作る。
- 一時Python、Shell、設定fileを許容する。
- command、理由、入力hash、一時file hash、出力hashを`recovery_manifest.json`へ保存する。
- 回復後も通常のArtifact schema、行数、ID、hash、analysis subject validationを必須にする。
- 回復成功時は`execution_mode: adaptive_recovery`をResultまたはLedgerへ記録する。
- 反復する引数不備はfailure分類とAttempt監査記録からSkill保守課題として人間へ報告する。
- Run中にSkill sourceを自動patchしない。
- 一時scriptによる専門アルゴリズム再実装を拒否する。
- compound ID、endpoint、metric、scope、Cluster、科学parameter、seedのinvariantを検証する。
- 科学的意味が変わり得る補正は自動実行せず人間へ返す。
- 回復manifestをAttemptごとに検証し、過去の補正を後続Nodeへ暗黙適用しない。
- execution／failure packetは標準成功後に削除可能で、正本file数を増やさない。

既定回復budget候補を「標準実行一回＋最大二回の補正実行」とし、同一Nodeの最大三Attemptとして記録する。補正ごとに別Nodeや新しいStatusを作らない。診断read／help callはAttemptに数えないがExecutor内部budgetで制限する。Fault-injection結果を見て最終固定し、回復budget終了後にMain Agentが同じTool callを手動反復しないようRuntime required actionを制御する。

### Phase 5: Main Agent Orchestrator Skill

- `cs-conductor-dispatch`を基に`.claude/skills/cs-conductor-orchestrator/`を作る。
- 人間向け`README.md`を追加し、目的、手動起動、専用session、制約、Version履歴を簡潔に記載する。
- `disable-model-invocation: true`を設定する。
- `context: fork`を設定せず、Main conversationで実行する。
- project既存`CLAUDE.md`へ依存しないinstructionにする。
- SKILL.mdを短い固定loopにし、詳細科学policyは必要時に参照する。
- 状態確認、新Round、Active Round再開、同一Round継続、Report修正、acceptを区別する。
- 曖昧な人間依頼ではStateを変更しない。
- `SCIENTIFIC_DECISION`だけをMainの推論責務とする。
- execution actionでは`cs-conductor-executor`を一つだけ起動する。
- Interpreter actionでは`cs-conductor-interpreter`をMainから直接起動する。
- Subagent帰還後は発言ではなくRuntime revisionとrequired actionを確認する。
- 無進捗の自動再起動回数を限定し、人間へblockerを返す。
- 人間の許可なしに次Roundを作らない。
- `allowed-tools`を状態保護の手段と誤認せず、Runtime tokenとcommand allowlistを実際の境界にする。
- compact envelopeのprotocol versionが不一致または不明な場合はStateを変更せず、Skill再起動を要求する。
- 長時間RoundではCONDUCTOR専用Main sessionを標準とし、通常project作業との同一session混在を避ける。

Skill本文はMain contextへ残るため、手順、禁止事項、action mappingだけを置く。長いschema、科学背景、failure一覧はreferencesまたはRuntime packetへ移す。

### Phase 6: InterpreterとFinalization

- `.claude/agents/cs-conductor-interpreter.md`からOrchestrator Subagent前提の記載を除く。
- Main AgentがInterpreterを直接起動する手順へ変更する。
- RuntimeがInterpretation contextとNodeを先に固定する。
- InterpreterはID-free draftだけをscratchへ出す。
- Runtimeがscope、Result参照、sample数、content lintを検証する。
- draft拒否時はMainへ短い修正summaryとdraft pointerだけを返す。
- 同一Interpretation Nodeを新しいInterpreterで修正できるようにする。
- Interpreter retryを有限にし、超過時は`FINALIZING`でblockerを返す。
- JSON、Markdown、HTML、Quality report、後続Full Auditが揃うまで`AWAITING_HUMAN_REVIEW`へ進めない。
- Auditの長い出力はfileへ保存し、MainへPASS／FAILと主要codeだけを返す。

### Phase 7: Package、Catalog、installer

- `CONDUCTOR_modules/VERSION`をcutover時に`0.1.3`へ更新する。
- `catalog/included_skills.json`へOrchestrator Skillを登録する。
- `catalog.json`と人間向けSkill Catalogを再生成する。
- `install_into_project.py`のAgent／Skill配置を更新する。
- 旧`.claude/agents/cs-conductor-orchestrator.md`と旧`cs-conductor-dispatch`をobsolete componentとして検出する。
- obsolete componentを削除する場合はCONDUCTOR固有marker、既知path、期待Capability IDを検証し、同名の利用者fileを無条件削除しない。
- installerは既存projectの`CLAUDE.md`を変更しないことをtestする。
- 既存projectに同名の非CONDUCTOR componentがある場合は上書きせず明示的に停止する。
- package verificationの必須AgentをExecutorとInterpreterへ変更する。
- すべての参照、prompt、READMEから旧起動経路を除去する。

### Phase 8: 文書更新と整理

- `CONDUCTOR_design_spec.md`をMain Agent方式へ更新する。
- `CONDUCTOR_overview.md`と`CONDUCTOR_user_guide.md`の起動例を手動Skill呼出しへ変更する。
- `CONDUCTOR_policy.md`のOrchestratorをMain Agentとして定義する。
- prompt集を`/cs-conductor-orchestrator`起動形式へ更新する。
- session handoffを「新Main sessionで同じSkillとRun Rootを指定」に変更する。
- Executor回復、scratch、maintenance defectの監査方法を記載する。
- 0.1.3正本文書への切替後、重複する0.1.2設計文書を削除または統合する。新しいArchiveは作らない。
- Version表記を一括検索し、現役文書を`0.1.3`へ統一する。

### Phase 9: 自動試験

#### 9.1 Main Agent起動

- OrchestratorがAgentではなくSkillとしてのみ存在する。
- Orchestrator Skillが手動起動専用である。
- Skillがfork contextを要求しない。
- 通常作業promptでOrchestrator Skillが自動発動しない。
- installerが既存`CLAUDE.md`を変更しない。

#### 9.2 Subagent境界

- ExecutorとInterpreterをMainから起動できる。
- Executorが別Subagentを起動できないtool構成である。
- Executorが一batch後に終了する。
- 二つのExecutorが同じpacketをcommitできない。
- Interpreterが同じInterpretation Nodeを再開できる。

#### 9.3 Context上限

- Main向けRuntime応答が設定sizeを超えない。
- Executor final responseへraw logが混入しない。
- Executorの自由記述ではなくRuntime生成envelopeがMainへ渡る。
- 20 Round、5,000 Node fixtureでもMain入力がboundedである。
- Tool callが複数回失敗してもMainへ返るfailure summaryが一定size以内である。
- 詳細logをpointerから明示取得できる。

#### 9.4 回復処理

- 誤ったDefault引数をscratch adapterで補正できる。
- renamed CLI optionをlauncher helpから解決できる。
- Windows／Linux path差を補正できる。
- format adapter成功後にcanonical validationを通過する。
- validation失敗結果を成功commitしない。
- recovery manifestがcommandとhashを保持する。
- scratch外への回復file書込みを拒否する。
- recovery budget超過後に無限retryしない。
- 同一Nodeのfailure分類とAttempt履歴をAuditで追跡できる。
- 科学的Negative Resultを技術的failureとしてretryしない。
- packet作成時の共通実行契約不一致ではExecutorを起動しない。
- 回復処理が専門アルゴリズムを再実装しない。
- 科学parameter、seed、metric、scope、対象compoundが変わる補正を拒否する。
- adaptive recoveryごとにinvariant検査を通る。
- packetと標準成功scratchをpruneした後もAuditと再現性に必要なsummaryが残る。

#### 9.5 RoundとInterpretation

- 人間の明示指示なしに新Roundを開始しない。
- Active Round再開でRound IDを増やさない。
- Main session中断後に別Main sessionが同じactionを再開する。
- Main context compaction後、protocol不明時にStateを変更せずSkill再起動へ戻れる。
- Executor停止後も同じNodeとAttemptを照合する。
- Interpretationなしにfinalizeできない。
- InterpreterをMainから起動する。
- Interpretation Quality失敗時に同じNodeを修正する。
- Full Auditなしに`AWAITING_HUMAN_REVIEW`へ進まない。

#### 9.6 科学回帰

- Description fixtureが許容差内で一致する。
- Clustering membershipが固定seed条件で一致する。
- Operator resultと個別HTMLが一致する。
- Metric、Cluster scope、analysis subjectが維持される。
- 一般利用CLIがRuntimeなしで動作する。

### Phase 10: Fault-injectionと実運用smoke

- Skill process nonzero終了
- launcher option mismatch
- optional引数Default不備
- Pixi環境初期化失敗
- Node scratch書込み失敗
- Executor process強制停止
- Main session停止
- 長時間process中のExecutor／Tool call停止
- stale action packet再送
- Artifact欠損と壊れたJSON
- recovery adapter自体の失敗
- Interpreter途中停止
- HTML生成後、Audit前停止
- Mainが早期終了または次Round開始を要求

いずれもState破損、ID重複、無限retry、Interpretationなし正常終了、自動新Roundを起こさないことを確認する。

実環境smokeでは、少なくとも小規模入力でDescription、Clustering、Global Operator、Cluster-local Operator、Interpretation、Auditまで一Roundを通す。`0.1.2`の実運用評価を省略するため、`0.1.3`の配布前smokeは省略しない。

## 6. 実装順序上の依存関係

```text
Role contract
  -> Runtime compact API
  -> execution packet / Executor
  -> recovery mechanism
  -> Main Orchestrator Skill
  -> Interpreter handoff
  -> installer / catalog / docs
  -> integration and fault-injection tests
```

Main Orchestrator Skillを先に書き換えて旧Runtimeへ接続すると、旧新経路が混在する。Runtime packetとExecutor contractを先に完成させ、最後に入口をatomicに切り替える。

## 7. リスクと抑制策

| リスク | 影響 | 抑制策 |
|---|---|---|
| Main contextがRound中に増える | 科学判断品質低下 | compact envelope、bounded Working Set、Round専用session |
| Subagent起動回数が増える | latency、token消費 | 一Nodeでなく一batch、一action単位で起動 |
| Executorが独自判断を広げる | 再現性低下 | execution packet、有限recovery budget、scratch、manifest |
| 一時fileが恒久仕様化する | 保守不能 | 再発をAudit集計し、Run外でSkill修正 |
| Runtimeが複雑化する | 実装不具合 | schema、単一Writer、fault-injection、責務表 |
| MainとExecutorのtoken競合 | 二重commit | action-scoped token、revision binding、単一Executor |
| Skill Default不備が多発する | retry増加 | preflight、launcher help検査、contract defect集計 |
| Main Agentが通常作業中に起動する | 意図しないRun変更 | manual-only Skill、既存CLAUDE.md非依存 |
| Interpreter修正loop | Round未完了 | finite retry、同一Node、blocker返却 |
| 0.1.2未評価の欠陥を継承する | 0.1.3不安定化 | 全Runtime回帰、統合smoke、fault-injection |
| Mainの小さい制御Tool callが失敗する | 二重mutation、再試行履歴 | idempotent control client、compact response、有限transport retry |
| 回復scriptが科学的意味を変える | 誤った成功結果 | mechanical correction限定、invariant検査、algorithm再実装禁止 |
| packetとscratchが再肥大化する | 状態把握と保守性低下 | 非正本扱い、成功後prune、Ledgerへhashと短いsummaryのみ |
| 長時間processがSubagent終了に巻き込まれる | Nodeがrunningのまま残る | process record、heartbeat、reconcile、process-kill fault test |
| 既存CLAUDE.mdと権限が競合する | SubagentやRuntimeが起動不能 | 起動preflight、非破壊の競合報告、既存file非上書き |

## 8. Cutover条件

次をすべて満たすまで`0.1.3`へVersionを切り替えない。

1. Runtime compact APIとexecution packetが完成している。
2. ExecutorとInterpreterをMainから起動できる。
3. 旧Orchestrator AgentとDispatcher Skillの参照が残っていない。
4. Tool call failure、回復、停止、再開の試験が成功している。
5. Interpretation、HTML、Auditの終端試験が成功している。
6. package installerが既存`CLAUDE.md`を変更しない。
7. Catalog、Version、schema、docs、promptが一致している。
8. Description、Clustering、Operatorの科学回帰が成功している。
9. package verificationと全自動試験が成功している。
10. 実環境の一Round smokeが成功している。
11. preflightがSkill呼出し契約の不一致を検出できる。
12. adaptive recoveryが科学invariantを維持する。
13. 一時packetとscratchが正本Stateを肥大化させない。
14. 長時間processの中断・再開試験が成功している。

CutoverはAgent、Skill、Runtime、schema、installer、Catalog、文書、testを一括で行う。旧新混在状態を配布しない。

`0.1.3`の受入は新規Runで行う。`0.1.1`または`0.1.2` Control Stateを暗黙変換して開かず、Version mismatchを明示する。

## 9. 実装後の標準運用

### 新Round

1. 人間が専用Claude Code Main sessionで`/cs-conductor-orchestrator`を呼ぶ。
2. Run Root、Round目的、予算、human priorityを指定する。
3. Main AgentがContractを確認し、Runtimeへ開始を依頼する。
4. Mainが科学候補を選び、Executorへbatchを委任する。
5. ExecutorのTool call履歴はMainへ返さず、compact resultだけを返す。
6. Mainが必要な追加解析を判断する。
7. MainがInterpreterを起動する。
8. RuntimeがQuality gateとAuditを通し、人間確認待ちへ進める。

### Active Roundの引継ぎ

1. 新しいMain sessionでOrchestrator Skillを呼ぶ。
2. 同じRun Rootと「Active Roundを再開」と指定する。
3. Runtimeがlease、revision、orphaned Attemptを照合する。
4. Mainは同じrequired actionから再開する。
5. 新Roundを作らない。

### Skill実行不備

1. Executorが標準commandの失敗をlogへ保存する。
2. Runtimeが回復可能性とbudgetを返す。
3. Executorがscratch内で最小補正を行う。
4. validation成功時だけ同じNodeへcommitする。
5. Mainは回復件数とfailure codeだけを受け取る。
6. 再発する不備はAuditからSkill保守課題へ移す。

## 10. 実装開始前の確認結果

- branch `0.1.3`への移行は確認済みである。
- 文書作成時点のworktreeはcleanであった。
- Main AgentをOrchestratorにする方式はClaude CodeのMain／Subagent階層と一致する。
- Orchestratorをmanual-only inline Skillとすることで既存`CLAUDE.md`と共存できる。
- Tool call失敗をExecutorへ隔離するだけでなく、Runtimeの有限回復とscratch監査を組み合わせる必要がある。
- 一時実行fileの全面禁止は採用せず、回復目的の限定利用を正式仕様とする。
- 回復は機械的な呼出し補正に限定し、科学計算の代替実装には使わない。
- Main側の制御Tool callも薄いidempotent clientで吸収し、LLMのCLI試行錯誤へ任せない。
- transient packetやscratchを新しいState正本にせず、状態管理の単純さを維持する。
- 変更規模はOrchestration層では大きいが、科学計算kernelの全面改変は不要である。

## 11. 実装結果

### 11.1 完了した中核項目

- Main Agentでのみ手動起動する`cs-conductor-orchestrator` Skillを追加した。
- 旧Orchestrator Agentと`cs-conductor-dispatch` Skillを廃止し、名称と起動責務の競合を解消した。
- 短命Executorと短命InterpreterをMainの兄弟Subagentとして分離した。
- Runtime応答を16 KiB上限のcompact protocolへ変更した。
- leaseをExecutorへ渡さない署名済み・Action-scoped・期限付きexecution packetを実装した。科学Skill commandは環境非依存の論理commandとして署名し、検証後に実行側RuntimeのPythonへ解決する。
- 標準実行一回と最大二回の同一Node retry、failure分類、failure packet、scratch限定adaptive recovery、科学引数不変検査を実装した。
- Interpretation quality failureを同一Interpretation Nodeの有限Attemptとして記録し、上限到達時は人間停止にした。
- Interpretation、固定HTML、Full Auditが揃わなければRoundを人間確認待ちへ移せないgateを維持・検証した。
- Package installer、Catalog、prompt、正本文書を0.1.3構成へ更新した。
- Description、Clustering、Operatorの科学計算kernelにはVersion契約以外の一括変更を加えていない。

### 11.2 単純化のため独立機能にしなかった項目

- `preflight-capabilities`という新しい状態遷移commandは追加しなかった。packet作成時のCapability／入力／command構築と、実行後のArtifact validationを既存遷移へ統合し、状態とrequired actionを増やさない方を選んだ。
- adaptive recovery recipeの自動再利用は追加しなかった。回復は各Attemptの署名済みcontractとmanifestに対して個別検証し、過去の補正を暗黙適用しない。再発はfailure分類と監査記録から人間がSkill保守へ戻す。
- Main側のmutation自動再送は追加しなかった。応答喪失時は同じmutationを再送せず、Control revisionと`verify-return`で照合する。これにより二重適用を避ける。

### 11.3 検証結果

- Windows開発環境の全自動test: 35件合格、Leidenの専用依存関係test 1件skip
- Package layout、47 allowlisted capabilities、installer dry-run／実copy: PASS
- Python compile、全JSON Schema parse、`git diff --check`: PASS
- Linux共有filesystem上の一Round end-to-end smoke: 配布先受入試験として未実施
