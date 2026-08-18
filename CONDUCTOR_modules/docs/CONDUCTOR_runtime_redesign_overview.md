# CONDUCTOR Runtime抜本改良概要

## 1. 文書の位置づけ

本書は、現行`0.1.1`を起点として、後方互換を設けずにCONDUCTOR `0.1.2`の制御系を再設計するための概要を定める。本改良はDescription、Clustering、Operatorの科学計算kernelを否定するものではなく、Orchestrator、Round、Node、State、Skill出力、Interpretation終端、再開・引継ぎの境界を作り直すものである。作業branchは`0.1.2`とし、旧コードのための新たなArchiveや互換層は作成しない。

CONDUCTORの価値は、多数の専門Skillを疎結合に接続し、GlobalとCluster-localの差、異なるDescription間の一致と矛盾、反証候補を複数Roundにわたって探索する点にある。この価値を維持したまま、Local LLMでも安定して運用できる制御系へ変更する。

## 2. 改良が必要な理由

現行実装では、DAG、実行キュー、Round進行、例外処理、候補管理をNodeの状態へ集約している。Runtimeによる補助は存在するものの、Orchestratorが次の処理を同時に担う場面が残っている。

- 科学的な解析方向の選択
- Node、依存関係、Attemptの把握
- Skillコマンドと引数の組み立て
- 並列実行とEvent収集
- 失敗・適用不能・省略の区別
- Wall TimeとInterpretation reserveの管理
- Interpretation、Audit、Round終了の制御
- セッション中断後の復旧

その結果、次の運用上の問題が確認されている。

- 残り時間と解析候補があるのにRoundを切り上げる
- Nodeを誤って`skipped`等のTerminal状態にする
- Interpretation HTMLが十分に完成する前に作業を終了する
- 元の依頼が未完了でも、新しいRoundをOrchestratorが自律的に開始する
- Main AgentがOrchestrator起動前に巨大な`state.json`を読む
- セッションが変わると、再開に長いStateや複数文書の読解を要する
- Orchestratorが処理をつなぐために一時スクリプトを頻繁に作る
- Skillが多数の管理用ファイルを出力し、科学的成果物との境界が曖昧になる

これらは個別のプロンプト不備だけではなく、Orchestratorへ制御責務を持たせすぎたことに由来する。

## 3. 目標

本改良では次を必須目標とする。

1. Roundを重ねてもOrchestratorが読む情報量を一定範囲に保つ。
2. 別セッション、別Agentへ引き継いでも、同じRoundを安全に再開できる。
3. Roundの開始と確定を人間が管理し、Orchestratorが自律的に次Roundを開始しない。
4. Orchestratorは科学的判断へ集中し、ID、状態遷移、依存関係、時間、終了可否をRuntimeへ委ねる。
5. 誤った操作を手順書だけで防がず、Runtimeが決定論的に拒否する。
6. DAGによる追跡性を維持しつつ、DAGをOrchestratorの直接操作対象にしない。
7. Node状態とSkill出力を簡素化し、必要不可欠な再現性・監査性を失わない。
8. 既存結果をすべて保存しつつ、通常判断では必要な結果だけを読む。
9. InterpretationをRoundの必須Commit成果物とし、未完成での正常終了を構造的に防ぐ。
10. 既存Skillにない探索を試す柔軟性を、管理されたescape hatchとして残す。

## 4. 基本原則

### 4.1 LLMは科学的選択、Runtimeは制御

Orchestratorが担当するのは、候補の優先順位、比較範囲、深掘り方向、人間の観点の反映である。Runtimeが担当するのは、Node ID、依存関係、Attempt、状態遷移、並列数、時間、再試行、Interpretation gate、Audit、Round FSMである。

### 4.2 標準経路とescape hatchを分ける

標準解析は登録済みSkillとRuntimeの正式な実行経路だけで完結させる。Orchestratorが一時PythonやShellを組み立てなくても、候補選択からEvent記録まで進められることを標準とする。

Catalogにない一回限りの確認は許容する。ただし、Runtimeが割り当てたscratch領域、実行manifest、隔離された出力を用い、Stateや正式DAGへ自動登録しない。正式解析へ昇格する場合は、人間が次のRoundで明示する。

### 4.3 候補とNodeを分離する

解析候補、適用不能項目、人間が選ばなかった処理はNodeにしない。Nodeは、実行することが正式に決まった一つの科学計算だけを表す。

### 4.4 科学的Negative Resultを失敗にしない

Clusterが得られない、相関がない、モデルが有効でない等は、計算が正しく完了していれば`succeeded`である。下流利用可否と品質flagをResultへ記録し、技術的失敗と区別する。

### 4.5 解析waveと科学的仕様を維持する

基本計算、初期探索、追加探索、深掘り解析の区分は維持する。ただし、これらはNode状態ではなくPlannerの`wave` tagとcoverage contractとして扱う。

- 人間の明示的な省略がない限り、全Description、直接構造Clustering、代表Descriptionに対するVector Clusteringを基本計算で揃える。
- MCSは基本計算に含め、個別の事前承認を要求しない。
- 高コストDescription bundleはRun中に一回だけまとめて人間承認を得る。
- 初期探索ではGlobalに全Operatorを適用し、各Clusteringの代表Clusterへ定められたOperator panelを適用する。
- 追加探索はDescription、Clustering、Operator、scopeへ偏らないseeded balanced selectionとする。
- 深掘り解析はOrchestratorの科学的判断と人間指示を反映する。
- Clusterは5化合物以上だけをRun-global Cluster indexへ登録する。
- Descriptionごとのnatural metric、Vector Clusteringの手法別自動校正、MCSのrandom pair sampling等の現行科学契約を維持する。

一つのRunは一つのendpointを対象とし、`higher_is_better`を必須とする。分子標準化と化合物ID・SMILESの正しさは引き続き人間の責務とする。

## 5. 全体アーキテクチャ

```text
Human
  |
  v
cs-conductor-dispatch
  |  Human authority: Round start / acceptance
  v
cs-conductor-orchestrator
  |  Scientific decision only
  v
Runtime Controller / Round FSM / Planner
  |  validated Task batch
  v
Registered Skills / Executor
  |  minimal scientific artifacts
  v
Event Ledger + Result Index + Artifact Store
  |                         |
  |                         +--> Result Concierge (read-only to analysis state)
  v
Interpreter --> Quality Gate --> Audit --> AWAITING_HUMAN_REVIEW

DAG Snapshot is maintained only by Runtime from committed Node inputs and is transactionally synchronized with Control and Ledger events.
```

## 6. Stateの正本と詳細記録

巨大な`state.json`一つに全責務を持たせない。正本を役割ごとに分ける。

| 対象 | 正式な記録 | 通常の読者 |
|---|---|---|
| 現在何をすべきか | `conductor_control.json` | Main Agent、Orchestrator |
| 実際に何が起きたか | `runtime/event_ledger.jsonl` | Runtime、Audit |
| 科学的依存関係 | `runtime/dag_snapshot.json` | Runtime、State report |
| 検索用の短い結果 | `runtime/result_index.jsonl` | Runtime query、Interpreter |
| Run-global Cluster由来 | `runtime/cluster_registry.jsonl` | Runtime query、Planner |
| 化合物とClusterの所属 | `runtime/cluster_membership*.csv` | Runtime query、Analysis |
| 完全な科学的出力 | stage別Artifact directory | 専門Skill、人間、Concierge |

`conductor_control.json`は単なる集計ではなく、Round制御についての正本である。Node一覧や長いArtifact情報を含めず、次を保持する。

- Run ID、Control revision
- Active RoundとRound state
- 唯一の`required_action`
- State revisionへ結び付いた一回限りのAction token
- 時間、並列数、実行中・待機中件数
- Round Contractの未充足項目
- Interpretation、Audit、closure readiness
- Blockerと人間権限の要否
- 詳細LedgerとSnapshotへのpointer

Main AgentとOrchestratorは詳細DAGを直接読まず、必要なNode、Cluster、Insight、Result CardだけをRuntime queryで取得する。

Analysis ResultのscopeはLLMが自由記述しない。RuntimeがNodeの`scope`、実際に解析へ入ったcompound ID、Cluster registry、入力Descriptionから正規化した`analysis_subject`を生成する。`analysis_subject`は少なくともscope mode、Cluster ID、Cluster生成元、Clustering入力種別（`structure`／`vector`）、母集団数、endpoint有効数、実解析数、除外数、compound set hash、解析用Description Node、Clustering Nodeを持つ。Vector ClusteringではCluster生成元Descriptionを記録し、MCS等の直接構造Clusteringでは生成元Descriptionを空にしたまま入力種別を`structure`と明示する。Operatorの`result.json`、Result Card、個別HTML、Interpretationは同じ値を参照する。

## 7. Roundの定義と人間権限

Roundは、人間の指示から始まり、人間の確認待ちへ戻る一つの解析契約である。

```text
ACTIVE
  -> FINALIZING
  -> AWAITING_HUMAN_REVIEW
  -> CLOSED

AWAITING_HUMAN_REVIEW
  -- human continue --> ACTIVE
  -- human report revision --> FINALIZING
```

- `ACTIVE`: 解析を実行する。
- `FINALIZING`: 新規科学Taskを停止し、InterpretationとAuditを完成させる。
- `AWAITING_HUMAN_REVIEW`: 成果物と未完了項目を人間へ提示する。
- `CLOSED`: 人間が結果を確認して確定した。

Orchestratorは`AWAITING_HUMAN_REVIEW`まで進められるが、そこから先の遷移は行えない。人間は、同じRoundの未完了作業を継続する、Interpretationだけを修正する、Roundを確定する、確定して次Roundを開始する、のいずれかを選ぶ。新Roundは人間の明示指示を受けた`cs-conductor-dispatch`だけが開始する。ここでの`accept`はworkflow上の確定であり、全Insightへの科学的同意を意味しない。

セッション中断後にActive Roundを再開することと、新Roundを開始することを明確に分ける。前者は復旧であり自動化可能、後者は人間権限である。

### 7.1 Round Contract

Round開始時に人間の依頼を短い契約へ固定する。

- objective
- required deliverables
- optional directions
- human priorities
- walltime、parallel limit、その他の予算
- 明示的な省略条件

必須成果物は、可能な限り`capability_coverage`、`artifact_exists`、`comparison_completed`、`interpretation_completed`等の機械検証可能な型で記録する。自由記述の科学的目的はOrchestratorが根拠Nodeを添えて充足を提案できるが、Runtimeが意味を推測して完了扱いにはしない。最終的な受理は人間が行う。

Runtimeは必須成果物の充足状況を管理する。予算終了時に未完了なら、Interpretationを作成したうえで`partial`または`blocked`として人間へ返す。未完了作業を理由にOrchestratorが次Roundを作ることは禁止する。

`complete`、`partial`、`blocked`はRound Outcomeの分類であり、Round FSMの状態ではない。たとえば`partial`な成果であっても、InterpretationとAuditを完了して`AWAITING_HUMAN_REVIEW`で人間へ返す。Node状態、Round状態、成果の充足度を一つのstatusへ混在させない。

## 8. Orchestrator起動Skill

Main Agent用に`cs-conductor-dispatch`を設ける。Orchestrator Agentと同名にせず、入口と実行主体を混同させない。

Dispatcherは次だけを担当する。

1. 指定Run Rootの`conductor_control.json`を確認する。
2. 人間の依頼を、新Round開始、Active Round再開、状態確認のいずれかへ分類する。
3. `prepare-round`でRound Contract案を作る。これはStateを変更しない。
4. Active Roundがあれば新Roundを作らず、同じRoundを再開する。
5. 人間の最新依頼に明示的な開始指示があり、Contractがその依頼と一致する場合だけ`authorize-round`する。意味のある補完が必要なら人間確認を求める。人間確認待ちでは、同一Round継続、Report修正、accept、acceptと次Round開始の各操作を明示的に分ける。
6. Dispatcher authorityでRoundを作成した後、開始権限を含まないRound-scoped leaseとAction tokenだけを一つのOrchestratorへ渡す。
7. Orchestrator終了後にControl Stateを再確認し、実際の状態だけを報告する。

Dispatcherは科学的候補を選ばず、詳細Stateを読まず、未完了Roundから次Roundを自動生成しない。

Main AgentはOrchestratorを直接起動せず、常にDispatcherを入口とする。Orchestratorが予期せず停止した場合、Dispatcherはlease、process、heartbeat、Control revisionを照合する。live leaseがあれば二重起動せず、leaseが失効し同じActive Roundが残る場合だけ同じRoundを再開する。状態進捗のない停止が連続した場合は自動再起動を打ち切って人間へblockerを返し、別Roundを作らない。

## 9. NodeとAttempt

### 9.1 Node

NodeはRun-globalな`N######`で統一する。種別は`kind`で表す。

```json
{
  "node_id": "N000123",
  "kind": "analysis",
  "capability_id": "A003",
  "input_nodes": ["N000021"],
  "scope": {"mode": "single_cluster", "cluster_ids": ["C000018"]},
  "parameters": {},
  "status": "succeeded",
  "created_in_round": "RND0003",
  "output_ref": "analysis/N000123"
}
```

Edgeは`input_nodes`から生成し、Cluster ID等のscope参照をDAG dependencyと混同しない。Edgeは独立した編集対象にしない。

### 9.2 Node状態

Node状態は次の5種類だけとする。

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

現行の`skipped`、`waived`、`not_applicable`、`unavailable`、`deferred`、`stale`はNode状態から除く。

- 選ばれなかった候補、適用不能、明示省略はDecision Logへ記録する。
- 未実行の正式Taskは`pending`のままBacklogへ残す。
- 技術的利用不能は最終的に`failed`とし、理由codeを持つ。
- 入力や仕様が変わる場合は新Nodeを作り、旧Nodeは履歴として保持する。

`pending` NodeはRun-global Backlogへ残せるが、現在Roundが`FINALIZING`へ入る時点で`assigned_round`を解除する。次Roundでの実行には、人間が開始した新しいRound Contractによる明示的な再採用が必要であり、RuntimeやOrchestratorが自動的に持ち越して実行しない。

### 9.3 Attempt

AttemptはRuntime内部で管理し、Node状態の種類を増やさない。最初の技術的失敗は`failed`として記録した上で、Runtimeの単一`required_action`により同じNodeへ一回だけ再試行できる。二回目の失敗は`failed`のまま残す。セッション中断でEventが未確定なら、Runtimeがprocess、heartbeat、artifactを照合し、同じAttemptを成功または失敗へ確定する。

## 10. Skill出力の簡素化

Skillは科学計算を担当し、Runtimeから渡されたNode／Round／Attempt identityをscratchのExecution Eventへ返す。lease、DAG登録、ID発行、状態遷移、canonical Artifactの確定はRuntimeだけが担当する。

| Stage | 基本成果物 |
|---|---|
| Description | feature payload + canonical `result.json` |
| Clustering | `membership.csv` + canonical `result.json` |
| Analysis | analysis payload + `result.json` + `report.html` |
| Interpretation | `interpretation.json` + `interpretation.md` + `interpretation.html` + quality report |

手法固有の追加Payloadは許容するが、canonical `result.json`から明示的に参照する。Skillがscratchへ出すmanifest、warning、Execution EventはRuntime検証後にLedgerまたはcanonical resultへ集約し、Run Rootの成功Node directoryへ重複昇格しない。

成功成果物はNode directoryへ一度だけcommitする。Attemptごとの同一成果物copyは作らず、失敗AttemptはLedgerと必要最小限のlogだけを保持する。DescriptionとClusteringの計算kernelは原則維持し、I/O adapterとCONDUCTOR連携を変更する。

一般利用とCONDUCTOR利用で科学的Payloadを可能な限り共通化する。CONDUCTOR固有管理情報はRuntimeが外側から付与し、専門SkillにState管理を持たせない。

一般利用時のCSVまたはSMILES入力、構造ClusteringのCSV入力、Vector ClusteringのDescription Vector入力という現行の入力責務は維持する。Runtimeは、共有Pixi binaryを優先し、`PIXI_CACHE_DIR`、`UV_CACHE_DIR`、Pixi home、XDG cacheを各Skillの`env/`内へ、実行時の`TMPDIR`、`TMP`、`TEMP`をNode専用scratchへ設定する。

## 11. Result Card、Working Set、取捨選択

解析結果は削除しない。ただし、Orchestratorが全Artifactを読むことも避ける。

各成功Analysisから短いResult Cardを作成し、次を記録する。

- Node、Operator、Description、Cluster scope
- sample count、metric、短いheadline
- validation結果、quality flags、下流利用可否
- Artifact pointer
- 関連InsightとRound

Insightは可変のattentionを持つ。

- `pinned`: 人間が常に保持する。
- `active`: 現在の深掘り対象。
- `watch`: 関連結果が増えたら再評価する。
- `background`: 通常は読み込まない。

`pinned`への変更は人間専用とする。InterpreterとOrchestratorは`active`、`watch`、`background`を提案できるが、Runtimeが履歴として記録する。永続的なNext Action ledgerは廃止し、Interpretationの各Insightへ短い`recommended_followups`を内包する。人間が採用したfollow-upだけを次Round Contractへ移し、未採用提案のOpen／Close状態を増やさない。

Runtimeは各科学Decisionでbounded Working Setを生成する。対象はRound Contract、未充足成果物、human priority、pinned／active Insight、直接関係するResult Card、未解決の矛盾、coverage balanceを満たす候補に限定する。過去全Roundの長文Interpretationを通常入力にしない。

## 12. InterpretationとRound Commit

Interpretationは単なる終端Nodeではなく、Roundを人間確認待ちへ移すCommit成果物である。当該Roundで成功したAnalysis Nodeと、人間が明示的に再検討対象へ加えた過去Resultだけを対象集合として固定する。次をすべて満たさない限り`AWAITING_HUMAN_REVIEW`へ進めない。

- Interpretation JSON、Markdown、HTMLが存在する。
- JSON schemaと内容品質検査が成功する。
- 対象集合に含まれる最新Analysisより後に生成されている。
- ReportとQuality検査がhashで結び付く。
- Full AuditがInterpretationより後に成功する。
- Round Contractの充足・未充足が明示される。
- `review_manifest`に、詳細確認、集約確認、未確認のResultと理由が列挙される。

### 12.1 Scopeと表示の正確性

Insightの対象scopeはInterpreterが独自に記述せず、支持・反証Resultの`analysis_subject`からRuntimeが次のいずれかへ正規化する。

- Global
- 単一Cluster
- Global対Cluster
- Cluster間比較
- 複数scopeの横断比較

単一ClusterのResultをGlobalと表示する、異なるClusterを一つのClusterとして表示する、Cluster IDが不明なままGlobalへfallbackする、のいずれもQuality gateで失敗させる。scopeが欠落または矛盾する場合は「未指定」と表示して通過させず、Report commitを拒否する。

各Insight cardには、人間が解析内容を一読で確認できるよう、次を固定順で表示する。

- 対象scopeとCluster ID
- Cluster生成に使ったClustering、入力種別、Vector Clusteringの場合の生成元Description
- Operator解析に使ったDescription、metric、endpoint
- Cluster母集団数と実解析数
- Global比較または比較対象Cluster
- 支持Result、反証Result、主要数値
- 観察、解釈、限界、recommended follow-up
- 個別Operator HTMLと数値Artifactへの参照

同じClusterでも欠損値等により実解析数がCluster母集団数より小さくなることがあるため、母集団数、endpoint有効数、実解析数、除外理由を別項目として表示する。Cluster間比較では、Cluster同士の重複数と重複率を示し、重複可能な構造Clustering等を排他的Cluster比較として扱わない。比較を主張するInsightは、比較対象となるResultを必ず引用し、単一scopeの結果だけからGlobal対ClusterやCluster間の差を断定しない。

Insight title、観察、解釈等の自由記述は、Runtimeが確定した事実欄を上書きできない。自由記述にはscopeを再定義させず、`Global`、`Cluster`、Cluster ID、Operator、Description、sample count等の事実語が引用Resultと矛盾しないかをcontent lintで検査する。矛盾を安全に自動修正できない場合はReport commitを拒否し、Interpreterへ修正対象を返す。

Report全体にはRun／Round、endpoint、`higher_is_better`、単位・変換が提供されている場合はその内容、scope／Operator／Description別のreview件数、未確認範囲を示す。MarkdownとHTMLは同じ構造化Reportから生成し、HTMLは日本語の固定template、落ち着いた低彩度の配色、安定したsection順、存在確認済みのArtifact linkを用いる。固定templateは、識別を色だけに依存せず、印刷時にも読めるcontrastとlabelを持つ。Figureを掲載する場合はHTMLへ埋め込み、大きな数値Artifactと個別Operator HTMLは相対linkにする。外部CDN、外部font、network取得を必要としない。Insightの表示順もattention、scope種別、Insight IDによって決定論的に固定する。

Insightが0件でもよいが、その場合は、確認したOperator結果数、注目Insightが得られなかった理由、未確認範囲を必須とする。次に検討可能な方向は根拠がある場合だけ記載し、無理にInsightを作らない。

Agentが途中停止した場合は`FINALIZING`のまま残り、次AgentにはInterpretation再開が唯一の`required_action`として提示される。人間確認後にReport修正が必要な場合、旧Interpretationは履歴として保持し、新しいInterpretation Nodeを`supersedes`関係で作成してcurrent pointerを更新する。

## 13. Concierge

`cs-conductor-result-concierge`は既存Runの理解を助ける読み取り中心の機能として強化する。出力先は人間の指定どおりRun Root内とする。

```text
run_root/
└── concierge/
    └── REQ000001/
        ├── request.json
        ├── report.md
        ├── report.html
        └── figures/
```

Conciergeが書き込めるのは`run_root/concierge/`配下だけである。次の領域は保護し、変更前後のControl revisionと主要hashを検証する。

- `conductor_control.json`
- `runtime/`
- `rounds/`
- `description/`
- `clustering/`
- `analysis/`
- `interpretation/`

ConciergeはNode、DAG、Insight Registry、Round、Result Cardを変更しない。Focused explanation、根拠追跡、Global／Cluster比較、Description横断比較、表、Figure、翻訳、追加の読み取り型集計を実行できる。追加計算は`ad hoc explanation`として明示し、正式Evidenceへ自動昇格しない。正式解析へ反映する場合は、人間が次RoundのRound Contractへ記載する。

## 14. Node Review

異常Nodeへ対応するため、人間専用の`cs-conductor-node-review`を設ける。Orchestratorの通常Skillには含めず、人間が明示した場合だけMain Agentが利用する。

Node Reviewは、NodeとArtifactの検証、orphaned Attemptの照合、失敗Nodeの再試行提案、成功結果の下流利用停止、Pending Nodeのcancel、影響を受ける下流Nodeの列挙を行う。

任意Statusへの直接変更は提供しない。処理順序は、検査、変更案、影響範囲、人間確認、Runtime適用、Auditとする。すべての補正をEvent Ledgerへ追記し、State JSONを直接編集しない。

科学的に有用でない正常結果は`succeeded`のまま、次のようにResult側で扱う。

```json
{
  "validation_passed": true,
  "eligible_for_downstream": false,
  "quality_flags": ["no_usable_clusters"]
}
```

## 15. Scratchと柔軟性

一時スクリプトを全面禁止しない。標準経路では不要にし、例外探索として隔離・記録する。

```text
run_root/runtime/scratch/RND0003/N000123/ATT0001/
```

Runtimeはworking directory、環境、入力、コマンド、出力を記録する。scratchは一時作業領域であり、例外的な補助処理も正式Stateを直接変更できない。再利用価値が確認された処理は独立Skillへ昇格し、正式Nodeとして改めて実行する。実験用の永続ID体系は増やさない。

## 16. 後方互換性と切替

現行`0.1.1` Runの再開互換性は提供しない。必要な旧Runの参照にはGit上の`0.1.1`実装を用い、`0.1.2` repository内へ旧コードをArchiveしない。新仕様では新しいRunを開始し、暗黙変換や部分的互換層を設けない。

実装途中の旧新混在状態を配布しない。Runtime、schema、Dispatcher、Orchestrator、Interpreter、Audit、Skill adapter、文書、testsが揃った時点で一括切替する。

## 17. 改良後の最小運用

初回または次Round開始時、人間はMain AgentへRun Root、Roundの目的、予算を伝える。Main AgentはDispatcherを使う。Active Roundのセッション引継ぎではRun Rootだけでよい。

```text
Human -> Dispatcher -> Orchestrator -> Runtime required_action loop
      -> Interpretation -> Audit -> AWAITING_HUMAN_REVIEW
      -> Human review -> close or explicitly start next Round
```

Orchestratorが読む情報は`conductor_control.json`と、Runtimeがその時点用に生成したWorking Setだけである。詳細Ledger、全DAG、全Artifact、過去の長文Reportは必要時に限定して取得する。
