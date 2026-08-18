# CONDUCTOR 0.1.2 Runtime抜本改良 作業計画書

## 1. 目的と前提

本計画は、`0.1.1`をbaselineとしてCONDUCTOR `0.1.2`の制御系を後方互換なしで再構築した作業を定める。目標仕様は[CONDUCTOR_runtime_redesign_overview.md](CONDUCTOR_runtime_redesign_overview.md)を正とする。実装後のcutoverではpackage Version、Catalog、Skill、Agent、schema、文書を同時に`0.1.2`へ更新する。

> 実装状態: 0.1.2 Runtime、Dispatcher、5状態DAG、bounded Working Set、固定Interpretation gate、Node Review、Concierge write boundaryを実装済み。受入試験結果は本書末尾と`CONDUCTOR_verification.md`で管理する。

本改良の優先順位は次の順とする。

1. Local LLMでも誤りにくい制御境界
2. 複数Roundと別Agent引継ぎの安定性
3. 人間によるRound開始・確定権限
4. Interpretationを必須とするRound終端
5. 状態、Node、Artifactの簡素化
6. 科学的探索の柔軟性
7. 人間と開発者の監査性

## 2. 変更境界

### 2.1 大幅に変更するもの

- `state.json`中心のState管理
- Round lifecycleと開始・確定権限
- Orchestrator Agentの制御loop
- Runtime CLI、Planner、Executor、Reducer、Audit
- Node ID、Node状態、Attempt管理
- DAGの生成・利用方法
- Result index、Working Set、query interface
- Interpretation commit、quality、closure gate
- SkillのCONDUCTOR出力adapter
- Main Agent用Dispatcher Skill
- Conciergeの出力隔離と機能
- 人間用Node Review Skill
- State report、schema、tests、正本文書

### 2.2 原則維持するもの

- Description、Clustering、Operatorの科学計算kernel
- Capability Catalogの科学的な収載内容
- Description Vectorに応じたMetric選択
- Clusteringの手法別parameter校正
- GlobalとCluster-local解析
- 複数Roundで解析を深める基本思想
- Interpretationの比較、矛盾、反証探索
- 各Skillの独立利用可能性とSkill内Pixi環境
- Linux/HPCを主対象としWindowsでも構築・検証可能とする方針
- 一Run一endpoint、`higher_is_better`必須、endpointが異なる場合は別Runとする契約
- 分子標準化、化合物ID、SMILESの正しさを人間の責務とする境界
- 基本計算、初期探索、追加探索、深掘り解析の科学的範囲
- 全Description、MCSを含む直接構造Clustering、代表Vector Clusteringを基本計算で揃える原則
- 初期Globalの全Operatorと代表Cluster-local panel
- Cluster登録の最小サイズ5、MCSのrandom pair sampling、Descriptionごとのnatural metric

### 2.3 実施しないもの

- 現行Runの自動migration
- 旧State schemaとの互換wrapper
- 旧コードの新規Archive作成
- 科学計算kernelの一括書き直し
- 外部Workflow engineや外部Graph DBの導入
- Concierge結果の自動Evidence化
- Orchestratorへの汎用State編集権限

## 3. 設計成果物

実装前に次のschemaと契約を確定する。

1. `conductor_control.schema.json`
2. `round_contract.schema.json`
3. `runtime_event.schema.json`
4. `node_record.schema.json`
5. `result_card.schema.json`
6. `working_set.schema.json`
7. `interpretation.schema.json`
8. `round_outcome.schema.json`
9. `description_result.schema.json`
10. `clustering_result.schema.json`
11. `analysis_result.schema.json`
12. `analysis_subject.schema.json`
13. `interpretation_review_manifest.schema.json`
14. stage別の最小Skill output contract
15. Action token、lease、Control revisionの遷移規則

Schemaは責務を重複させない。Node recordにRound FSMやInterpretation品質を持たせず、Control Stateに全Node詳細を持たせない。

## 4. 目標directory

```text
run_root/
├── conductor_control.json
├── rounds/
│   └── RND0001/
│       ├── round_contract.json
│       ├── round_outcome.json
│       └── interpretation_ref.json
├── runtime/
│   ├── event_ledger.jsonl
│   ├── dag_snapshot.json
│   ├── result_index.jsonl
│   ├── cluster_registry.jsonl
│   ├── cluster_membership.csv
│   ├── logs/
│   └── scratch/
├── description/
│   └── N######/
├── clustering/
│   └── N######/
├── analysis/
│   └── N######/
├── interpretation/
│   └── N######/
└── concierge/
    └── REQ######/
```

`concierge/`はRun Root内に置くが、Control、Ledger、DAG、科学Artifactから独立させる。Runtime AuditはConciergeの存在をNode数やArtifact countへ含めない。

## 5. 実装Phase

### Phase 0: baseline、inventory、切替条件

- 現行test、package verification、主要Skill smokeを実行しbaselineを保存する。
- 現行Runtimeが管理する状態、schema、file、CLI、Agent責務をinventory化する。
- Description、Clustering、Analysis、Interpretationごとの実出力fileをfixtureで収集する。
- 科学計算kernelと管理wrapperの境界を特定する。
- branchと`CONDUCTOR_modules/VERSION`が`0.1.2`で一致することを確認する。
- 旧新混在を防ぐcutover checklistを作る。
- Git管理外の`CONDUCTOR_modules/Archive/`を0.1.2 packageへ持ち込まず、新しいArchiveを作成しないことを確認する。

完了条件は、変更対象、維持対象、削除候補、生成元templateが一覧化されることである。

### Phase 1: Control State、Ledger、Round FSM

- 小さい`conductor_control.json`を実装する。
- append-only Event Ledgerとdeterministic reducerを実装する。
- Ledgerは単一WriterのJSONLを既定とし、sequence、record checksum、flush、fsyncを必須とする。末尾の不完全recordはbootstrapで検出し、最後の完全recordまでを正として復旧する。
- Control fileは一時fileへの書込み、flush、atomic replaceで更新する。
- Eventには単調増加sequence、Control revision、event type、payload hashを持たせる。
- 起動時にLedger末尾とControl revisionを照合し、中断したcommitを再構築する。
- Round状態を`ACTIVE`、`FINALIZING`、`AWAITING_HUMAN_REVIEW`、`CLOSED`へ限定する。
- `AWAITING_HUMAN_REVIEW`からは、人間権限による同一Round継続で`ACTIVE`、Report修正で`FINALIZING`、acceptで`CLOSED`へ遷移できる。Orchestratorはこれらの遷移を起こせない。
- Round ContractとRound Outcomeを導入する。
- Round Contractのrequired deliverableを、機械検証可能な型と自由記述の科学的目的へ分ける。自由記述項目はOrchestratorが根拠を提示できるが、Runtimeだけで完了確定しない。
- Active Round再開と新Round開始を別APIにする。

Round開始APIはDispatcher用authorityを要求し、Orchestrator用Round-scoped tokenでは呼び出せない設計にする。

### Phase 2: Node、Attempt、DAG

- Run-globalな`N######`カウンタへ統一する。
- Node状態を`pending`、`running`、`succeeded`、`failed`、`cancelled`へ限定する。
- Candidate、Decision、Node、Attemptを別recordにする。
- `skipped`、`waived`、`not_applicable`、`unavailable`、`deferred`、`stale`をNode状態から削除する。
- Node dependencyを`input_nodes`、解析範囲を`scope`へ分け、Cluster IDをNode dependencyと混同しない。
- EdgeをNodeの`input_nodes`から生成する。
- 同一Node retry、orphan reconciliation、最終failureの規則を実装する。
- 下流利用可否、validation、quality flagをResult Cardへ移す。
- `pending` NodeがRound終了時に残る場合は`assigned_round`を解除し、次Round Contractによる明示的な再採用なしに実行しない。
- Run-global Cluster registryと化合物×Cluster Boolean membership indexをReducerで更新する。Cluster数がCSV上限へ近づく場合だけID範囲で分割する。
- DAG SnapshotをControlとEvent Ledgerへtransactionally同期する。Ledger単体へ全Node recordを複製する完全event-sourcingは、履歴肥大化を避けるため採用しない。

Runtime以外からNode ID、Status、Edgeを直接更新できないことをtestする。

### Phase 3: DispatcherとMain Agent境界

- `.claude/skills/cs-conductor-dispatch/`を追加する。
- Dispatcher用CLIは`inspect`、`prepare-round`、`authorize-round`、`resume-round`、`continue-round`、`revise-report`、`accept-round`、`verify-return`に限定する。
- `prepare-round`はStateを変更せず、人間の最新依頼からRound Contract案とrequest hashを作る。
- `authorize-round`は明示的な開始指示と一致する未使用request hashを要求し、Round作成後に使用済みにする。
- Active Round存在時の新Round開始を拒否する。
- `AWAITING_HUMAN_REVIEW`からの自動新Round開始を拒否する。
- 人間が明示的に次Round開始を指示した場合は、前Roundのworkflow上のacceptと新Round作成を監査可能な二つのEventとして同一Dispatcher操作内で実施する。
- 同時Orchestrator起動をleaseとAction tokenで拒否する。
- Dispatcher authorityをOrchestratorへ渡さず、Orchestrator tokenのscopeからRound作成・acceptを除外する。
- Orchestrator帰還後、発言ではなくControl Stateを検証してMain Agentへ返す。
- Main AgentからOrchestratorを直接起動せず、Dispatcherを唯一の入口にする。
- `verify-return`はlease、process、heartbeat、Control revisionを照合し、live leaseがある場合は二重起動を拒否する。
- Orchestratorの予期しない停止時は、失効leaseを回収した後に同じActive Roundと同じ`required_action`を再開する。新Roundや代替Nodeを作らない。
- 同じControl revisionのまま停止が連続した場合は自動再開を打ち切り、診断情報を添えたblockerとして人間へ返す。
- 推奨promptとsession handoff文書をDispatcher中心に更新する。

Dispatcher自身は詳細DAG、全State、科学Artifactを読まない。

### Phase 4: Runtime Planner、Executor、Action API

- Runtimeが各時点で一つだけ`required_action`を発行する。
- Action tokenをControl revision、Round ID、lease ownerへ結び付ける。
- stale token、重複実行、別Round tokenを拒否する。
- Plannerが適用条件を判定し、不適用候補をNode化しないようにする。
- RuntimeがSkill command、working directory、環境、一時領域を生成する。
- Runtimeは共有Pixi binaryを優先し、Pixi／UV／XDG cacheを各Skillの`env/`配下へ、`TMPDIR`／`TMP`／`TEMP`をNode専用scratchへ固定する。
- `execute-batch`がstart、専門Skill実行、Event検証、commitを一つの標準経路として扱う。
- Wall Time、Interpretation reserve、parallel limitをRuntimeが管理する。
- `soft_stop_at = deadline - interpretation_reserve`をRuntimeが計算し、soft stop後は新規科学Taskを開始しない。各Taskへtimeoutを設定し、予想外に長いTaskはRoundを自動延長せず、結果を照合して`partial`として人間へ返せるようにする。
- 時間と候補が残る状態での自律的な早期finalizeを拒否する。
- 人間checkpoint、候補なし、予算終了、Round Contract完遂を明示的に区別する。

Orchestratorへ汎用`mark-terminal`や直接`round-start`を提供しない。

### Phase 5: Skill出力adapter

- 共通launcherからCONDUCTOR固有State更新を除く。
- Runtimeが一般利用Skillを呼び、外側からNodeとEventを管理するadapterを実装する。
- Descriptionはfeature payloadと`result.json`を基本とする。
- Clusteringは`membership.csv`と`result.json`を基本とする。
- Analysisは`result.json`と`report.html`を基本とする。
- Runtimeが実際のcompound setとNode scopeからcanonical `analysis_subject`を作り、Result Cardと個別HTMLへ注入する。SkillやLLMがGlobal／Cluster labelを独自生成しない。
- `analysis_subject`にscope mode、Cluster ID、Cluster生成元、Clustering入力種別、population count、endpoint-valid count、analyzed count、excluded count、compound set hash、解析用Description Node、Clustering Nodeを持たせる。
- Vector ClusteringのCluster生成元Descriptionは必須、MCS等の直接構造Clusteringでは生成元Descriptionをnullとし、入力種別`structure`を必須とする。
- 手法固有Payloadを`result.json`の明示参照へ統一する。
- warning、manifest、config、validationを重複fileにせず、ResultまたはLedgerへ集約する。
- 成功成果物はNode directoryへatomicに一度だけcommitする。
- 失敗AttemptはLedgerと必要なlogだけを保持する。
- dense、sparse、binary、3D、embedding等のpayload形式をCapability metadataで宣言する。
- 一般利用のCSV／SMILES入力、構造ClusteringのCSV入力、Vector ClusteringのDescription Vector入力を回帰testする。

各Skillの科学計算結果を現行fixtureと比較し、管理wrapper変更による数値差がないことを確認する。

### Phase 6: Result Card、Working Set、検索

- Analysis成功時にResult Cardを生成する。
- Result CardをOperator、Description、Cluster、scope、Round、quality flagで索引化する。
- Insight attentionを`pinned`、`active`、`watch`、`background`で管理する。
- `pinned`への変更は人間専用とする。
- attentionは後から変更可能とし、元Resultを削除しない。
- 永続的なNext Action ledgerを廃止し、各Insightの`recommended_followups`へ統合する。人間が採用したfollow-upだけを次Round Contractへ移す。
- Working Set builderを実装する。
- 人間priority、Round Contract、未充足項目、関連Insight、矛盾、coverage balanceを選択規則へ含める。
- Working Setの件数とserialized sizeに上限を設ける。
- `conductor_control.json`は32 KiB、Working Setは64 KiB、候補は20件を既定上限とし、超過情報は切り捨てずquery pointerへ置き換える。
- `query node|cluster|result|insight|candidates`をbounded responseにする。
- 全Ledgerや全Interpretationを通常queryで返さない。

20 Round、数千Nodeのsynthetic fixtureでもControl StateとWorking Setの大きさが増え続けないことを確認する。

### Phase 7: Orchestrator Agent

- Orchestratorのinstructionを短い固定loopへ書き直す。
- 通常入力を`conductor_control.json`とWorking Setだけに限定する。
- deterministic actionはRuntimeへそのまま返す。
- 科学的推論が必要な時だけ候補選択、比較、深掘り提案を行う。
- Node ID、Status、Edge、Round番号を生成しない。
- 新Round開始、Round close確定、任意State修正を禁止する。
- 一時scriptがなくても標準Roundを完了できるようRuntime APIを整える。
- escape hatchは隔離scratchに限定し、再利用する処理は独立Skillへ昇格させる。
- Agentが停止しても次Agentが同じ`required_action`から再開できるようにする。

Agent instructionには特定のLLM製品名を記載せず、短いcontextでも動作するmodel-agnosticな設計とする。

### Phase 8: Interpretation、Audit、Round Commit

- Interpreter contextをWorking Setと選択済Result Cardから生成する。
- 当該Roundで成功したAnalysisと、人間が明示的に再検討へ指定した過去ResultをInterpretation対象集合として固定する。
- `review_manifest`へ詳細確認、集約確認、未確認のResultと理由を記録する。
- Insightのscopeを支持・反証Resultのcanonical `analysis_subject`からRuntimeが導出し、Interpreter draftの自由記述scopeを正式Reportへ採用しない。
- 単一Cluster、Global対Cluster、Cluster間、複数scope横断を型として区別する。
- Result間のscope、Cluster ID、compound set hashがInsightの対象表示と一致しなければcommitを拒否する。
- draft、preview、contextをscratchへ置き、正式出力は最終3fileへ限定する。
- Interpretation JSON、Markdown、HTMLを同一Reportから決定論的にrenderする。
- HTMLは固定templateで、Executive Summary、解析範囲、Insight、支持・反証・限界、Cluster／Global比較、推奨follow-up、参照Operatorを常に同じ順序で表示する。作業記録ではなく人間向け解釈Reportとする。
- 各Insightにscope、Cluster生成元、解析Description、Operator、metric、endpoint、population count、analyzed count、主要数値、Artifact linkを固定表示する。
- population count、endpoint有効数、実解析数、除外理由を分離し、sample数の意味を曖昧にしない。
- Cluster間比較ではcompound ID集合から重複数と重複率を算出し、重複可能なClusterを排他的集団のように表示しない。
- 比較を述べるInsightには、比較各側のResult参照を必須とする。単一scopeのResultだけによるGlobal対ClusterまたはCluster間の比較主張を拒否する。
- LLM自由記述がcanonical scope、Cluster ID、Operator、Description、sample countと矛盾しないかをcontent lintで検査する。
- 欠落scopeをGlobalへfallbackせず、Quality errorとする。
- MarkdownとHTMLを同一Report modelから生成し、表示内容の一致を検証する。
- HTMLは色だけに依存しないlabel、印刷可能なcontrast、決定論的なInsight順序を持たせる。
- HTMLは低彩度の固定paletteとprint CSSを用い、外部CDN／font／scriptに依存しない。小さいFigureは埋込み、大きなArtifactと個別Operator reportは存在検証済みの相対linkにする。
- Report headerにRun、Round、endpoint、`higher_is_better`、任意の単位・変換、review対象数、Outcomeを固定表示する。
- 空Insight Reportにもreview count、比較、negative conclusion、未確認範囲を要求する。
- Report hashとQuality結果をLedgerへcommitする。
- Full AuditにControl/Ledger整合、Node transition、Artifact hash、Interpretation freshness、Round Contract outcomeを追加する。
- `FINALIZING`からInterpretationを飛ばして進む経路をなくす。
- Audit成功後は`AWAITING_HUMAN_REVIEW`へ進め、`CLOSED`にはしない。
- 人間のacceptまたは明示的な次Round開始時だけ前Roundを`CLOSED`にする。
- 人間がInterpretation修正を求めた場合は旧Reportを保持し、新Interpretation Nodeへ`supersedes`を記録してcurrent pointerを更新する。

Interpreter中断時は同じInterpretation Nodeを再開し、別Nodeや別Roundを生成しない。

### Phase 9: Concierge強化

- 出力を`run_root/concierge/REQ######/`へ固定する。
- path validationで`concierge/`外への書込みを拒否する。
- protected scopeのControl revisionとhashを処理前後で検証する。
- Node、DAG、Round、Insight Registry、Result Cardを変更しない。
- Insight根拠追跡、Global／Cluster比較、Description横断比較、表、Figure、翻訳、Focused HTMLを実装する。
- ad hoc集計を正式CONDUCTOR Evidenceと区別するlabelを付ける。
- 入力Node／Artifact hashと使用した処理を`request.json`またはprovenanceへ記録する。
- Conciergeの追加がFull AuditやNode countに影響しないことを確認する。

### Phase 10: Node Review

- `.claude/skills/cs-conductor-node-review/`を追加する。
- `inspect`、`propose`、`apply-confirmed`、`verify`の段階に分ける。
- 人間の明示指示がないapplyを拒否する。
- 任意Status setterを実装しない。
- failed Nodeのretry、orphan reconciliation、pending cancel、成功結果の下流利用停止を限定操作として実装する。
- 変更前に影響を受ける下流Nodeを表示する。
- 補正EventをLedgerへ追記し、DAG SnapshotとResult IndexをReducerで更新する。
- 適用後にFull Auditまたは対象限定Auditを必須とする。

Node Review SkillをOrchestrator Agentの常設Skill一覧へ含めない。

### Phase 11: State report、文書、Package切替

- State reportをControl Stateと派生DAG Snapshot対応へ更新する。
- State reportの出力は`run_root/state/<UTC timestamp>/`とし、明示的な人間依頼時だけ生成する。
- 人間向けDAG図はNode状態5種類とResult qualityを分けて表示する。
- Catalog、Policy、Design Spec、Output Contract、Identifier Reference、User Guide、promptを新仕様へ更新する。
- 旧Runtime template、旧schema、旧migration、旧State固有文書を削除する。
- Git管理外の既存`CONDUCTOR_modules/Archive/`はpackage対象外のままとし、0.1.2用Archiveを作らない。
- package installer、layout verifier、scaffold generatorを新構成へ更新する。
- `CONDUCTOR_modules/VERSION`とCapability versionを確定Versionへ一括更新する。
- すべてのSkill copyをgeneratorから同期し、旧新混在を検査する。

## 6. Atomic cutover

Phase番号は実装順を示すが、新schemaを現行Runtimeへ部分適用しない。新しいControl State、Ledger、Runtime、Dispatcher、Orchestrator、Interpreter、Audit、Skill adapterが一通り揃うまで現行入口を保持する。

切替時は次を一つの変更単位として実施する。

1. 新Runtimeとschema
2. Dispatcher、Orchestrator、Interpreter
3. 全Skill adapterとCapability metadata
4. Concierge、Node Review、State report
5. Catalog、docs、prompt、package installer
6. testsとverification

現行Runは新Runtimeで開かず、明瞭なVersion mismatchを返す。

## 7. 受入試験

### 7.1 Round権限

- Orchestrator tokenで新Roundを開始できない。
- Active Roundがある状態でDispatcherが新Roundを作らない。
- `AWAITING_HUMAN_REVIEW`から人間指示なしで次Roundを作らない。
- 人間指示なしに`AWAITING_HUMAN_REVIEW`から`ACTIVE`、`FINALIZING`、`CLOSED`のいずれへも遷移しない。
- 人間の同一Round継続ではRound IDを増やさず、新Round開始時だけ次のRound IDを割り当てる。
- `prepare-round`だけではState revision、Round ID、Node数が変化しない。
- Orchestrator tokenでは`authorize-round`と`accept-round`を実行できない。
- 未完了Roundは`partial`として人間へ返り、自動継続しない。
- `complete`、`partial`、`blocked`をRound Outcomeだけに使い、Round FSMやNode statusへ混在させない。
- 人間のaccept前に`CLOSED`へ遷移しない。

### 7.2 Interpretation終端

- Interpretation JSON、Markdown、HTMLのいずれかが欠けるとfinalizeできない。
- 空またはtemplateだけのInterpretationはQuality gateを通らない。
- Interpretation対象集合に含まれる最新Analysisより古いInterpretationではfinalizeできない。
- Interpretation後のFull Auditなしで人間確認待ちへ進めない。
- Interpreter停止後、別Agentが同じNodeから再開する。
- 人間によるReport修正では旧Interpretationが失われず、current pointerだけが新Nodeへ移る。
- Cluster-local ResultをGlobalと記載したdraftをcommitできない。
- scope欠落、Cluster ID不一致、compound set hash不一致をQuality gateが検出する。
- Cluster population countと実解析数を別々に表示する。
- MarkdownとHTMLでscope、Result参照、主要数値が一致する。
- 各Artifact linkが存在し、対象Nodeのcommit済みArtifactを指す。
- 単一scopeの引用だけでGlobal対ClusterまたはCluster間の比較を記載できない。
- 重複Cluster間の比較ではcompound重複数と重複率が表示される。
- 自由記述中の誤ったGlobal／Cluster表現とCluster IDをcontent lintが検出する。
- endpoint有効数、実解析数、除外数の整合が取れないReportをcommitできない。
- 直接構造ClusteringをDescription由来と誤表示せず、Vector Clusteringでは生成元Descriptionを欠落させない。

### 7.3 Nodeと状態遷移

- Node状態が5種類以外にならない。
- Candidateやnot-applicable処理がNode化されない。
- Cluster scopeがDAG dependencyとして誤登録されない。
- 失敗Attemptが再試行可能な間はNodeが最終`failed`にならない。
- validなNegative Resultは`succeeded`として保存される。
- 下流利用不可ResultからCluster-local Nodeが自動生成されない。
- 任意Status変更APIが存在しない。

### 7.4 中断・重複・復旧

- 各Control transition直前・直後のprocess killから復旧できる。
- LedgerへEvent済、Control未更新の状態をbootstrapでreplayできる。
- 二つのOrchestratorが同じAction tokenを使うと片方だけ成功する。
- 期限切れlease takeover後も同じNode IDとAttempt履歴を維持する。
- 古いAgentのstale tokenを拒否する。
- Main AgentがDispatcherを介さずOrchestratorを起動する標準手順が存在しない。
- live lease中のOrchestrator二重起動を`verify-return`が拒否する。
- 失効leaseからの復旧は同じRoundと同じ`required_action`を再開し、新Roundを作らない。
- 状態進捗のない連続停止は自動再起動を打ち切り、人間へblockerを返す。

### 7.5 長期Multi-Round

- 20 Round、5,000 Node fixtureでControl file sizeが設定上限を超えない。
- Working Setがboundedで、全Artifactを読まずに次判断へ進める。
- pinned InsightがWorking Setから脱落しない。
- background Resultを明示queryで再取得できる。
- 新AgentがRun Rootだけを渡されてActive Roundを再開できる。
- 永続的なNext Action状態を読まなくても、InsightとRound Contractから継続判断できる。

### 7.6 Skill出力

- 各stageの必須成果物が最小契約に一致する。
- 管理用manifest、warnings、execution eventがSkill directoryへ重複生成されない。
- 成功成果物が一度だけNode directoryへcommitされる。
- 科学計算fixtureが現行kernelと許容差内で一致する。
- 一般利用時もCONDUCTOR RuntimeなしでSkillを実行できる。
- Skill cacheが各Skillの`env/`外へ作られず、Node一時fileが割当scratch外へ作られない。

### 7.7 Concierge

- 出力が`run_root/concierge/REQ######/`だけに作られる。
- 処理前後でControl、Ledger、DAG、科学Artifactのhashが不変である。
- Concierge requestがNode、Round、Insight、Result countを変更しない。
- ad hoc出力が正式Evidenceとして自動参照されない。

### 7.8 Node Review

- 人間確認なしのapplyを拒否する。
- succeededへの手動変更を提供しない。
- retryは同じNodeで新Attemptになる。
- 下流影響を表示せずにinvalid化できない。
- 適用後Auditが補正EventとSnapshotを確認できる。

## 8. Fault-injection試験

通常のunit testに加え、次の故障を意図的に発生させる。

- Skill processの非zero終了
- 正常終了だがPayload欠損
- 行数不一致、全NaN、壊れたJSON
- Event Ledger末尾の不完全record
- Control file更新前のprocess kill
- Artifact commit途中のprocess kill
- lease期限切れと重複takeover
- Interpreter draft生成後の停止
- HTML render後、Audit前の停止
- Orchestratorが早期finalizeを要求
- Orchestratorが新Round開始を要求
- Orchestratorが存在しないStatusを要求

いずれも、破損した成功扱い、ID重複、自動新Round、Interpretationなし正常終了を起こさないことを確認する。

## 9. リスクと抑制策

### 9.1 Runtimeの複雑化

LLMから責務を移すため、Runtime実装は現行より大きくなる。配布物と呼出し口を増やさないため、Control FSM、Ledger、Planner、Executor、Artifact validatorは一つのRuntime Controller内の独立した関数境界として実装し、各境界をschema testする。

### 9.2 決定論的制御による探索の硬直化

Runtimeは候補適用性と安全性を判定するが、科学的優先順位を固定しない。Orchestratorの候補選択と人間指定deep diveを残し、例外処理は隔離scratchに限定する。

### 9.3 Event Ledgerの長期肥大化

通常再開ではControl Stateとindexだけを読み、Ledger全走査をしない。Snapshotへlast applied sequenceを持たせ、Ledger検証はAudit・復旧時に限定する。Windows上でappend、fsync、atomic replace、exclusive lockの回帰試験を実施し、target Linux／共有filesystemでは導入時smoke testを必須とする。要件を満たさないfilesystemで黙って安全性の低いmodeへ切り替えない。

### 9.4 Skillごとの固有成果物

ファイル数削減を優先して科学的情報を失わないよう、必須成果物は最小化しつつ、手法固有Payloadを`result.json`から宣言的に参照できるようにする。

### 9.5 ConciergeがRun Rootへ書き込むこと

書込みallowlistを`concierge/`だけに限定し、protected scopeのhash検証を行う。Concierge directoryをAudit対象の科学DAGから除外するが、Concierge自身のrequestとprovenanceは残す。

### 9.6 人間権限の識別

LLM instructionだけに依存せず、Dispatcher用authorityとOrchestrator用Round-scoped tokenを分ける。人間の最新依頼からRound Contractを作る入口をDispatcherへ限定し、Orchestrator Agentの利用可能SkillにRound startを含めない。

### 9.7 Interpretation本文の科学的妥当性

Runtimeはscope、Cluster ID、Description、Operator、sample数、引用Result、Report構造の整合を決定論的に保証できるが、LLMが記述する解釈そのものの科学的正しさを完全には証明できない。対策として、事実欄をRuntime生成へ限定し、比較の両側のResult参照、反証、限界、未確認範囲を必須にし、自由記述の矛盾をlintする。最終的な科学的受理は`AWAITING_HUMAN_REVIEW`で人間が行う。

## 10. 実装後の運用像

### 新Round

1. 人間がMain AgentへRun Root、目的、予算を伝える。
2. Main AgentがDispatcherを使用する。
3. DispatcherがRound Contractを提示し、人間の明示指示を根拠に開始する。
4. OrchestratorはRuntimeの一つの`required_action`を処理し続ける。
5. RuntimeがInterpretation reserveまたはContract完遂を検出する。
6. Interpreter、Quality gate、Full Auditを経て`AWAITING_HUMAN_REVIEW`へ進む。
7. 人間がHTMLを確認し、Roundを確定するか、明示的に次Roundを開始する。

HTMLに不足があれば、人間は同じRoundのReport修正を指示できる。科学計算が不足していれば、人間は追加予算とともに同じRoundの継続を指示できる。どちらもOrchestratorが自律判断して開始しない。

### セッション引継ぎ

1. 人間またはMain Agentが同じRun RootをDispatcherへ渡す。
2. DispatcherがActive Roundを検出し、新Roundを作らず再開する。
3. 新OrchestratorはControl StateとWorking Setだけを読む。
4. Runtimeがorphaned Attemptを照合し、唯一の次Actionを返す。

### 結果の詳細確認

1. 人間がInsight、Node、Cluster、比較観点をConciergeへ指定する。
2. ConciergeはRunを読み取り、`run_root/concierge/REQ######/`へ説明資料を作る。
3. Control、DAG、正式Artifactは変更しない。
4. 正式解析へ反映したい観点は、人間が次RoundのContractへ記載する。

## 11. 実装開始時に固定する実装値

- Versionとbranchは`0.1.2`とする。package `VERSION`はcutover時に更新する。
- Ledgerはsingle-writer checksummed JSONLを既定とし、target filesystemで永続化primitiveを受入試験する。
- Skill payload形式はdense／sparse／binary／3D／embeddingごとにCapability metadataで宣言し、一律形式へ強制しない。
- Control fileは32 KiB、Working Setは64 KiB、候補は20件を既定上限とする。
- Round UXはDispatcherの`prepare-round`、`authorize-round`、`accept-round`へ分離する。
- 人間確認待ちからの同一Round継続とReport修正は`continue-round`、`revise-report`へ分離する。
- 標準Taskのscratchは成功commit後に削除可能とし、logとEventは保持する。例外処理のscratchを正式結果へ自動昇格しない。
- 旧Runtime、旧schema、旧migration、旧State固有文書はcutover時に削除し、新規Archiveは作成しない。

後方互換は設けないため、互換層よりも新仕様の一貫性と受入試験を優先する。

## 12. 実装前最終レビュー

| 確認観点 | 0.1.2での扱い | 判定 |
|---|---|---|
| Local LLMの負担 | 小さいControl State、一つの`required_action`、bounded Working Setに限定 | 実装済 |
| 複数Round | 過去全文を通常入力にせず、Result indexと可変attentionで必要結果だけ再取得 | 実装済 |
| 別Agent引継ぎ | DispatcherがActive Roundを検出し、同じActionを再発行 | 実装済 |
| Roundの人間管理 | start、continue、report revision、acceptを人間権限APIへ分離 | 実装済 |
| 二重Orchestrator | lease、token、heartbeat、`verify-return`で拒否 | 実装済 |
| 途中停止 | orphan照合後に同じRound／Node／Actionを再開し、無進捗停止は人間へ返す | 実装済 |
| Interpretation必須 | JSON／Markdown／HTML、quality gate、後続AuditをRound gate化 | 実装済 |
| Interpretationの対象誤記 | canonical `analysis_subject`、固定事実欄、比較参照検証、content lintで防止 | 実装済 |
| 人間向けReport品質 | 固定日本語template、低彩度palette、同一Report model、根拠link、print対応 | 実装済 |
| Node／State簡素化 | Node 5状態、単一ID、Attempt分離、Outcome分離 | 実装済 |
| 科学計算の維持 | Description／Clustering／Operator kernelをfixtureで回帰検証 | 実装済（環境依存実計算は各Pixi環境で確認） |
| 柔軟な探索 | 科学的選択はOrchestrator、例外処理は隔離scratch、再利用処理はSkillへ昇格 | 実装済 |
| Concierge | Run Root内に出力しつつ、科学Stateへの書込みを拒否 | 実装済 |
| 旧Run／Archive | 互換なし、新規Archiveなし、0.1.2は新規Runのみ | 確定 |

実装開始時に未決の仕様判断は残さない。schemaと遷移表、Fault-injection、科学kernel契約、Package verificationはrepository受入試験で確認する。Linux／共有filesystemと各Skill Pixi環境の実計算は、導入先でのsmoke testとして別途確認する。
