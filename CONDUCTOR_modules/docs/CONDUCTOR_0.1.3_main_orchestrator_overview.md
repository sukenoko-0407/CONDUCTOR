# CONDUCTOR 0.1.3 Main Agent Orchestration 仕様概要

## 1. 文書の位置づけ

本書は、CONDUCTOR `0.1.3`で採用するMain Agent中心のOrchestration仕様を定める。`0.1.2`で導入した小さいControl State、Runtime単一Writer、5状態Node、bounded Working Set、Interpretation終端gateを基盤として維持し、Claude Code上の役割配置を変更する。

`0.1.2`は実運用評価を省略し、`0.1.3`を次の評価対象とする。ただし、`0.1.2`で実装したRuntime機能を無検証で引き継ぐのではなく、`0.1.3`の統合試験で再検証する。

本改良ではDescription、Clustering、Operatorの科学計算kernelを原則変更しない。主対象はMain Agent、Skill、Subagent、Runtime応答、Tool call回復、Interpretation起動、Package導入、文書、試験である。

本変更は、CONDUCTORの科学的設計思想を置き換えるものではない。疎結合な専門Skill、Runtime単一Writer、人間管理のRound、GlobalとCluster-localの比較、多角的Interpretationは維持する。大きく変わるのは、制御責務を一つの長寿命Orchestrator Subagentへ集める構成から、Main Agentの判断、短命Executorの実行、Interpreterの解釈へ分離する実行トポロジーである。

## 2. 改良理由

`0.1.2`までの標準構成では、Main AgentはDispatcherとして一つのOrchestrator Subagentを起動し、その終了を待つ。Orchestrator SubagentはRound全体を通して次の処理を担う。

- 科学的な解析方向の選択
- Description、Clustering、Operatorの実行制御
- Tool call失敗の診断と再試行
- Runtime actionの反復
- InterpretationとAuditへの移行

専門Skillの生出力をlogへ逃がしても、失敗したTool call、再試行、引数修正、状態確認の履歴は長時間生存するOrchestratorのcontextへ蓄積する。さらに、通常のClaude Code Subagentは別のSubagentを起動できないため、Orchestrator SubagentからInterpreter Subagentを起動する既存手順は実行環境の制約と一致しない。

`0.1.3`ではMain AgentをOrchestratorとし、Main Agentだけが短命な専門Subagentを起動する。科学的判断は人間との会話を保持するMain Agentに残し、Tool callの多い処理はExecutorへ隔離する。

### 2.1 0.1.2との比較

| 観点 | 0.1.2 | 0.1.3 |
|---|---|---|
| Main Agent | Dispatcherとして待機 | OrchestratorとしてRoundを統括 |
| 科学的判断 | 長寿命Orchestrator Subagent | Main Agent |
| Skill実行 | Orchestrator contextからRuntimeを反復 | 短命Executor contextへ隔離 |
| Interpretation | Orchestratorからの起動を想定 | Mainから兄弟Interpreterを直接起動 |
| Tool call失敗 | Orchestrator contextへ蓄積し得る | ExecutorとRuntime回復へ限定 |
| State正本 | Runtime／Control／Ledger | 維持 |
| DAGとNode | Runtime管理 | 維持 |
| 科学的探索方針 | 多角的・複数Round | 維持 |

したがって、0.1.3は科学システムの方向転換ではなく、Claude Codeの実行制約と長時間contextに合わせた責務再配置である。Mainが計算まで抱える、Executorが科学判断を始める、回復scriptが算法を代替する、という境界崩れが起きた場合は0.1.2より改悪になるため、Runtime契約と受入試験で防止する。

## 3. 基本原則

### 3.1 Main Agentは指揮者であり、計算workerではない

Main Agentは、Round権限、科学的選択、human priority、最終成果物の確認を担当する。Description、Clustering、Operatorのprocess実行、長いlog、回復用Tool callは担当しない。

### 3.2 Skillで役割を有効化する

Main AgentのOrchestrator役は、projectの`CLAUDE.md`へ常時記載せず、手動起動型`cs-conductor-orchestrator` SkillをMain conversationへinlineで読み込むことで有効化する。

- Skillは`disable-model-invocation: true`とし、人間が明示的に呼び出した場合だけ有効化する。
- Skillに`context: fork`を指定しない。Subagentとして起動してはならない。
- project既存の`CLAUDE.md`を置換、切替、上書きしない。
- 既存`CLAUDE.md`には、必要なら「CONDUCTORは明示起動時のみ開始する」という短いrouting規則だけを人間が追加できる。必須とはしない。
- Skill本文はMain contextへ残るため、長時間または自律実行するCONDUCTOR Roundでは専用Claude Code sessionを標準運用とする。通常作業との同一session内切替は、状態確認や短い操作に限定する。
- Claude Code Skillの`allowed-tools`は実行許可を補助するものであり、Main Agentのtoolを制限するsecurity boundaryとはみなさない。状態保護はRuntime token、command allowlist、schema、single writerで保証する。

### 3.3 Subagentは短命かつ単機能とする

標準Subagentは次の二種類だけとする。

- `cs-conductor-executor`: 一つのRuntime required actionまたは一つの実行batchを処理する。
- `cs-conductor-interpreter`: Runtimeが固定した対象集合からInterpretation draftを作る。

Description用、Clustering用、Operator用のLLM Subagentは作らない。科学的専門性は各Skillが持ち、ExecutorはRuntimeが作成した実行packetを処理する汎用workerとする。

### 3.4 Runtimeだけが状態を確定する

Main Agent、Executor、InterpreterはいずれもNode ID、Status、Edge、Round番号を直接編集しない。RuntimeだけがControl、Event Ledger、DAG Snapshot、Result Index、Cluster Registry、canonical Artifactを更新する。

### 3.5 柔軟性は隔離して残す

一時的なPython、Shell、補助設定fileの利用を全面禁止しない。標準実行がSkillの引数不備、path差、format差等で失敗した場合、ExecutorはRuntimeが割り当てたscratch内で限定的な回復処理を行える。

回復処理は、正式Stateの直接編集、Skill sourceの実行中改変、scratch外への書込みを許可しない。成功結果は標準validationを通過した場合だけRuntimeがcommitする。

回復処理は機械的な呼出し補正に限定し、Description、Clustering、Operatorのアルゴリズムを一時scriptで再実装しない。科学parameter、対象化合物集合、endpoint、metric、Cluster scope、乱数seed等の意味が変わる可能性がある場合は自動回復せず、明示的な技術的失敗または人間確認へ移す。

## 4. 全体アーキテクチャ

```text
Human
  |
  | manual invocation + Round instruction
  v
cs-conductor-orchestrator Skill
  |
  v
Main Agent = Orchestrator
  |-- scientific decision from bounded Working Set
  |-- human-authorized Round control
  |
  +--> cs-conductor-executor Subagent
  |      |-- Runtime action packet
  |      |-- registered Skill execution
  |      |-- bounded recovery in Node scratch
  |      `-- compact result envelope
  |
  +--> cs-conductor-interpreter Subagent
  |      `-- ID-free structured draft
  |
  `--> Runtime Controller
         |-- single writer / tokens / lease
         |-- Node / Attempt / DAG / Artifact commit
         |-- validation / retry budget / audit
         `-- Interpretation and Round closure gates
```

Runtime内部の科学Skill processは`parallel_limit`まで並列実行できるが、同じRunに対するExecutor Subagentは一時点で一つだけとする。さらに`available_cpu_cores`（未指定時8）をCPU総予算として独立管理し、実効同時Node数と内部thread数を予算以下に保つ。C002 MCSは最大8個の単一thread worker、D019 xTBは原則4コア/化合物で内部並列化し、いずれも単独packetとする。複数ExecutorによるState競合を避け、並列性はRuntimeのprocess管理へ集約する。

Runtimeは一つのRoundへ割り当てるAnalysis Nodeを最大200件に制限し、初期Global／Local候補を最大50件ずつ層化してNode化する。初期Globalは最大100件で区切り、Local解析用に少なくとも100件分の容量を残す。未Node化候補を巨大なqueueとしてDAGへ保存せず、次の人間承認Roundで成功済みsignatureを除外して再構成する。長いWall Timeはprocessを完了させる余裕であり、計画件数を増やす指定ではない。Description／Clusteringの基本計算はこのAnalysis上限の対象外とする。

## 5. Main Agent Orchestrator Skill

### 5.1 配置

```text
.claude/skills/cs-conductor-orchestrator/
├── SKILL.md
├── README.md
├── capability.json
├── env/pixi.toml
└── scripts/
```

既存`cs-conductor-dispatch`の入口機能を統合し、`.claude/agents/cs-conductor-orchestrator.md`は廃止する。同じ名称のSkillとSubagentを併存させない。

### 5.2 起動

人間はClaude Code Main sessionで次の形式により明示起動する。

```text
/cs-conductor-orchestrator

run_root: /path/to/run_root
request: RND0002を開始し、F012を重視しつつ追加探索も実施する
walltime: 8h
parallel_limit: 8
available_cpu_cores: 64
```

Skill呼出しだけでは新Round開始の意味にしない。`request`に新Round開始、同一Round継続、Report修正、状態確認のいずれかが明示されていることをRuntime APIで区別する。曖昧な場合はStateを変更せず人間へ確認する。

### 5.3 Main Agentの責務

Main Agentは次を担当する。

1. `conductor_control.json`と短いRuntime inspection結果を読む。
2. 人間の依頼を状態確認、新Round開始、Active Round再開、同一Round継続、Report修正、acceptへ分類する。
3. 新RoundではRound Contract案と人間依頼の一致を確認する。
4. `SCIENTIFIC_DECISION`ではbounded Working Setから次の解析を選ぶ。
5. RuntimeへNode候補を提出し、RuntimeがRound上限内で割り当てたNode IDを受け取る。
6. 実行actionでは一つのExecutorを起動し、compact resultだけを受け取る。
7. Interpretation actionではInterpreterを直接起動する。
8. Interpretation commit、Quality gate、Full Audit、`AWAITING_HUMAN_REVIEW`到達を確認する。
9. 人間の明示指示なしに次Roundを開始しない。

Main AgentはRuntime CLIを自由に組み立てない。Orchestrator Skill内の薄いcontrol clientと固定command mappingを使用し、run root解決、引数escape、control authority注入、compact JSON出力を決定論的に行う。mutation応答を失った場合は自動再送せず、Control revisionと`verify-return`で照合する。Mainの推論対象はRuntime commandの構文ではなく、科学候補と人間依頼である。

### 5.4 Main Agentが行わないこと

- 専門Skillの`launch.py`や`run.py`を直接実行しない。
- Skill引数をその場で組み立て直さない。
- raw stdout、stderr、完全Ledger、全DAGを通常は読まない。
- Node、Attempt、Cluster、Insight IDを生成しない。
- StatusやControl JSONを直接編集しない。
- Executorが失敗したことだけを理由に、別Nodeや次Roundを作らない。

## 6. Executor Subagent

### 6.1 実行単位

Executorは一つのRuntime required actionまたは一つのbatchだけを処理して終了する。Main Agentから受け取る情報は次に限定する。

- `run_root`
- packetに固定されたRound IDとControl revision
- Runtime生成のexecution packet path
- packet専用のExecutor token

Mainのlease tokenとAction tokenそのものはExecutorへ渡さない。packet内部には、それらと同一時点のControlへ結び付けるhashだけを署名対象として保持する。

Executorは全Stateや過去Interpretationを読まない。execution packetにない科学的判断を追加しない。

### 6.2 Tool callの隔離

専門Skill実行、環境構築、引数検査、log確認、回復用Tool callはExecutor context内で行う。Main Agentへ返すのは固定構造のcompact result envelopeだけとする。Envelope本文はExecutorの自由記述ではなくRuntimeが生成・schema検証し、Executorはそのpathと最小statusだけを返す。

```json
{
  "round_id": "RND0002",
  "control_revision": 42,
  "action": "EXECUTE_RUNNABLE_BATCH",
  "succeeded": 12,
  "failed": 1,
  "recovered": 2,
  "affected_node_ids": ["N000101", "N000102"],
  "failure_codes": ["skill_argument_contract_mismatch"],
  "next_required_action": "SCIENTIFIC_DECISION",
  "detail_pointer": "runtime/logs/..."
}
```

raw log、traceback、Skill出力表、長いwarning一覧をMain Agentの返却本文へ含めない。Main Agentが科学判断に必要と認めた場合だけ、Runtimeのbounded queryで該当Result Cardまたはfailure summaryを取得する。

### 6.3 標準実行

RuntimeはCapability metadataとCatalogから次を確定する。

- executableとSkill path
- 引数名、入力Artifact、出力scratch
- working directory
- Pixi、UV、XDG cache
- `TMPDIR`、`TMP`、`TEMP`
- timeout、parallel limit、Available CPU Cores
- expected Artifactとvalidation

ExecutorはRuntime生成packetを一度だけRuntime launcherへ渡し、packet内の科学Skill commandを自身で再構築または直接実行しない。

Runtimeはexecution packetを作る際に、登録Capability、入力Node、入力Artifact、launcher path、CONDUCTOR共通引数、出力先を決定論的に組み立てる。署名・hash対象は実行環境固有のPython絶対pathではなく`<CONDUCTOR_RUNTIME_PYTHON>`を先頭に置いた論理commandとし、packet検証後に実行側Runtimeが自身の`sys.executable`へ一度だけ解決する。Attempt rootはRuntime管理file用、`output/`はSkill成果物専用に分離し、Skill起動前には`output/`を作らない。OrchestratorのControl commandも薄いclientからRuntime SkillのPixi環境へ委譲し、packet作成と実行でRuntime依存関係を一元化する。packet作成に失敗した場合はExecutorを起動しない。Pixi環境の実初期化やCapability固有CLIの実行時不整合はExecutor内でfailure分類し、有限回の回復対象とする。独立したpreflight用Statusやrequired actionは増やさない。

### 6.4 適応的実行回復

標準実行に失敗した場合、Runtimeが回復可能と分類したときだけExecutorへ回復budgetを与える。対象例は次のとおりである。

- Skill documentとlauncher実装の引数名不一致
- optional引数のDefault不備
- WindowsとLinuxのpath表現差
- input column aliasやformat adapterの不足
- launcherが期待するworking directoryとの差
- subprocessの一時的な環境初期化失敗

Executorは次の順で回復する。

1. failure packet、該当Skillの`SKILL.md`、`capability.json`、launcher help、必要箇所の実装だけを確認する。
2. 正式引数の置換、path補正、format adapter等の最小修正を選ぶ。
3. 必要なら割当scratch内に一時Python、Shell、設定fileを作る。
4. command、引数、入力hash、一時file hash、理由を`recovery_manifest.json`へ記録する。
5. 同じNodeの次AttemptとしてRuntimeへ結果を返す。補正のために別Nodeを作らない。
6. canonical Artifact validationに合格した場合だけcommitする。

validationにはfile存在やschemaだけでなく、回復前後で変えてはならない次のinvariantを含める。

- compound ID集合と行対応
- endpoint列と`higher_is_better`
- Description／Clustering／Operator capability
- metric、scope、Cluster ID、入力Node
- 科学parameterとseed
- expected feature／membership／result semantics

一時fileは次に限定する。

```text
run_root/runtime/scratch/<round>/<node>/<attempt>/recovery/
```

`/tmp`やproject任意位置の利用を一律禁止はしないが、標準では割当scratchを使用する。外部toolがOS tempを必須とする場合、Runtimeが環境変数で割当scratchへredirectする。redirect不能な例外は実行manifestへ記録し、正式Stateへ直接触れない。

回復処理では次を禁止する。

- `conductor_control.json`、Ledger、DAG、registryの直接編集
- 実行中のSkill source、Catalog、schemaの恒久修正
- 入力科学dataの意味を変える暗黙変換
- 専門Skillのアルゴリズムを一時scriptで代替実装すること
- validationを迂回した成功扱い
- 同じcommandの無制限な反復

既定回復budgetは、標準実行一回と最大二回の補正実行、すなわち同一Nodeで最大三Attemptに固定する。診断のためのread／help callはAttemptに数えないが、対象fileをExecutor契約で限定する。無制限retryは認めない。budgetを使い切った場合はNodeを技術的失敗として明示し、Main Agentへ短いfailure codeを返す。Node状態やglobal ID体系は増やさない。

同じ回復が複数Nodeで再発した場合は、Runtime Auditへ`skill_contract_defect`として集約する。Run中にSkill sourceを自動修正せず、保守課題として人間へ提示する。

回復manifestはNode Attemptごとに検証し、過去の補正を後続Nodeへ暗黙適用しない。繰り返す契約不備はfailure分類と監査記録からSkill保守課題として扱う。これにより状態管理を増やさず、古い補正recipeが別入力へ誤適用されることを避ける。

### 6.5 長時間実行と中断

Executor contextが長時間processの正本になってはならない。Runtimeはprocess ID、論理command hash、解決済みcommand hash、実行Python path、開始時刻、heartbeat、timeout、scratch、expected Artifactを実行開始前に記録する。ExecutorまたはClaude Code tool callが中断しても、新しいExecutorはprocessとArtifactを照合し、同じNode／Attemptをreconcileする。

実行中Nodeがある場合、Runtimeは`still_running`とprocess IDをcompactに返す。Main Agentは短い間隔でpollしたり、別Nodeや別Executorを重複起動したりしない。processが親session終了等で停止した場合は、Runtimeが同じNode／AttemptのArtifactとprocess recordを照合し、正常終了したように扱わない。

## 7. Interpreter Subagent

InterpreterはMain Agentが直接起動する兄弟Subagentであり、Executorや別Subagentから起動しない。

RuntimeはInterpretation対象Node、canonical `analysis_subject`、Result Card、過去Insightの必要部分、human priority、review manifestを固定したcontextを作る。InterpreterはID-free draftを作り、RuntimeがID割当、scope検証、content lint、Markdown／HTML render、commitを行う。

Quality gateでdraftが拒否された場合、Main Agentへは修正対象を短く返す。Main Agentは同じInterpretation Nodeに対して新しいInterpreterを起動できる。無制限に繰り返さず、規定回数を超えた場合は`FINALIZING`のまま人間へblockerを返す。

## 8. Runtimeとの境界

### 8.1 維持するもの

- `conductor_control.json`をRound制御の正本とする。
- RuntimeをStateのsingle writerとする。
- Node状態を`pending`、`running`、`succeeded`、`failed`、`cancelled`へ限定する。
- leaseと一回限りAction tokenで二重処理を拒否する。
- Active Round再開と新Round開始を別APIとする。
- InterpretationとFull AuditをRound終端の必須gateとする。
- DAGを追跡記録として維持し、LLMに直接操作させない。

### 8.2 変更するもの

- Runtime action応答をMain Agent向けcompact envelopeと詳細pointerへ分ける。
- Executor向けexecution packetとfailure packetを追加する。
- Tool call回復budget、recovery manifest、failure分類をRuntime管理へ加える。
- Orchestrator lease ownerをMain sessionとし、Executorにはaction-scoped capabilityだけを渡す。
- Main AgentとExecutorへ同じ権限tokenを渡さない。
- Interpreter起動待ちをMain Agentが処理できるaction contractへ変更する。

execution packet、failure packet、compact envelope、recovery用fileは新しい正本Stateではない。Node Attempt scratch内の一時情報とし、標準成功時は削除可能とする。回復を使用した場合だけ、短いrecovery summaryとmanifest hashをLedgerへ残す。新しい永続Status、global ID、packet indexは追加しない。

Control全体を各Tool call応答へ繰り返し埋め込まない。Main Agent向け応答は、current revision、required action、closure gate、件数、pointerを中心とし、serialized sizeへ上限を設ける。

## 9. Round進行

```text
Human invokes Skill
  -> Main inspects Control
  -> human-authorized start or same-Round resume
  -> Main scientific decision
  -> Runtime plans Nodes
  -> Main launches one Executor
  -> Executor executes and returns compact result
  -> repeat decision/execution within budget
  -> Runtime enters FINALIZING
  -> Main launches Interpreter
  -> Runtime validates and commits Interpretation
  -> Executor or Runtime runs Full Audit
  -> AWAITING_HUMAN_REVIEW
  -> stop and return to Human
```

Main Agentが途中停止した場合、新しいClaude Code Main sessionで同じSkillを明示起動し、同じRun Rootを指定する。RuntimeはActive Roundと失効leaseを照合し、同じrequired actionを再発行する。新Roundは作らない。

## 10. Context管理

Main Agentが通常読む情報を次に限定する。

- 人間の現在依頼
- compact Control envelope
- bounded Working Set
- Executorのcompact result
- Interpreterのcommit結果とQuality summary
- Audit summary

通常は読まないものは次のとおりである。

- ExecutorのTool call transcript
- raw stdout／stderr
- 全Event Ledger
- 全DAG Snapshot
- 全Result Card
- 過去全RoundのInterpretation本文
- recovery用一時fileの内容

詳細はpointerで保持し、Main Agentが特定の失敗や科学結果を判断するために必要な場合だけ取得する。

Compact envelopeには`protocol_version`、Skill名、current revisionを持たせる。Main Agentが自動compaction、session再開、別session引継ぎ等によりOrchestration手順を確信できない場合、推測で続行せず、同じRun Rootで`/cs-conductor-orchestrator`を再度明示起動する。Runtime Stateは変えず、同じrequired actionから再開する。

## 11. 既存projectとの共存

- Package installerは既存projectの`CLAUDE.md`を変更しない。
- `.claude/skills/`と`.claude/agents/`へCONDUCTOR componentだけを配置する。
- Orchestrator Skillは手動起動専用とし、通常のClaude Code作業中に自動発動しない。
- 同じprojectで通常作業とCONDUCTORを行える。
- Context混在を避けるため、通常作業sessionとCONDUCTOR Round sessionの分離を推奨する。
- 起動preflightで既存`CLAUDE.md`とproject permissionに、Subagent起動、Run Root書込み、Runtime commandを明示的に禁じる規則がないか確認する。競合時は自動上書きせず、人間へ提示する。

## 12. 保持する科学仕様

本改良で次を変更しない。

- 基本計算、初期探索、追加探索、深掘り解析
- GlobalとCluster-localの比較
- Description横断、Cluster間、Operator横断の探索
- MCSを含む基本計算範囲
- Descriptionごとのnatural metric
- Vector Clusteringの手法別校正
- Cluster最小登録サイズ5
- Interpretationの比較、矛盾、反証探索
- 一Run一endpointと`higher_is_better`必須
- Description、Clustering、Operator Skillの一般利用

## 13. 非目標

- Agent Teamsを必須機能にしない。
- Subagentの入れ子を前提にしない。
- Main Agentへ全Stateを読ませない。
- Stageごとに多数のLLM worker定義を作らない。
- Tool call失敗をLLMの無制限な試行錯誤で解決しない。
- 一時fileを全面禁止しないが、非監査の恒久成果物にはしない。
- 0.1.1 Runのmigrationを実装しない。
- 0.1.2用の新たな互換層やArchiveを作らない。0.1.3の受入は新規Runで行い、旧Control versionを暗黙変換しない。

## 14. 受入状態

`0.1.3`は少なくとも次を満たした時点で受入候補とする。

1. 人間の明示起動時だけMain AgentがOrchestratorになる。
2. Main AgentがExecutorとInterpreterを直接起動できる。
3. Orchestrator Subagentへの依存がない。
4. Tool call失敗と回復履歴がMain contextへ流入しない。
5. 引数不備をscratch内の監査可能な回復で吸収できる。
6. 回復処理がStateとSkill sourceを汚さない。
7. 別Main sessionが同じActive Roundを再開できる。
8. InterpretationとAuditなしにRoundが正常終了しない。
9. 人間の指示なしに次Roundが開始されない。
10. Description、Clustering、Operatorの科学計算結果が回帰試験で維持される。
11. packet作成時に共通実行契約を固定し、実行時CLI不一致はExecutor内の有限回復へ隔離する。
12. 回復処理が科学parameterや対象集合を変えない。
13. 一時packet追加により正本Stateや通常Artifact数が再肥大化しない。
14. 長時間Tool call中断後も同じNodeを照合できる。
