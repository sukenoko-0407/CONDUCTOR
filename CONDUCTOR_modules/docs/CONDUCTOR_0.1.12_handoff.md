# CONDUCTOR 0.1.12 引継ぎ・要検討事項

Status: **未承認・未実装。0.1.12仕様協議用。**

## 1. 位置付け

本書は、当初0.1.11候補として整理されていた非MMP項目を0.1.12へ移管した引継ぎ文書である。0.1.11はA008 MMPの大幅更新だけに使用する。

ここに記載した内容は実装承認ではない。仕様、計算量、Report範囲、human gateを個別に合意してから、0.1.12仕様概要書と実装計画書を作成する。

### Version境界

| Version | 対象 |
|---|---|
| 0.1.10 | A003判定、calculation version、Schema、Series、Report監査、Prompt等の追補。MMP追加改修は行わない |
| 0.1.11 | A008 MMPだけを大幅更新する |
| 0.1.12 | 本書のRuntime、選抜安定性、A005安定性、共通runner再編を検討する |

0.1.10で対応する次の項目は本書の対象外とする。

- A003判定契約
- calculation version必須化
- JSON Schema hardening
- Cross-representation Core／Core／FringeとSeries救済条件
- A009 Report Template忠実性、link／件数監査
- Prompt集補強

0.1.11で扱うA008 MMPの2 Mode化、Global Top 1、Transformation evidence、Core／Environment解析、情報抽出、Interactive visualization、1/2-cut方針も本書の対象外とする。

## 2. Bounded Runtime Supervisor（限定Driver）

### 2.1 背景

Main AgentがRuntimeの`required_action.code`を一件ずつ解釈する固定Loopでは、長時間Background TaskのShell完了通知がMain Agentへ届かない場合、処理自体が終了していても人間が発話するまで次のRuntime actionへ進まない。

Main Agentが短間隔でqueryを繰り返す方式は、ContextとTool履歴を消費するため採用しない。

### 2.2 候補案

常駐Daemonではなく、Runtime Skillへ仮称`drive-until-gate`を追加する。

```text
Main Agent
  └─ drive-until-gate（承認済みACTIVE Round）
       ├─ Runtime query
       ├─ plan
       ├─ Execution Packet（既存の最大N並列）
       ├─ 次のrequired_actionを評価
       └─ 人間Gate／失敗／pause／完了で停止
```

Driverは、人間が承認済みの一つのRoundに対して一回起動され、機械的に決定できるactionだけを連続実行する。新Round開始、parameter自動変更、failed Nodeの自動retry／waive、Interpretation作成を行わない。

### 2.3 必須停止Gate

- `AUTHORIZE_ROUND`
- `HUMAN_APPROVAL_REQUIRED`
- `HUMAN_SERIES_REVIEW_REQUIRED`
- `WRITE_INTERPRETATION`
- `FAILED_NODE_REPAIR_REQUIRED`
- `BLOCKED_BASIC`／`BLOCKED_STANDARD`／`INTERPRETATION_BLOCKED`
- `ROUND_PAUSED`／`PAUSE_ROUND`
- `AWAIT_HUMAN_REVIEW`／`AWAIT_HUMAN_ROUND`
- 未知の`required_action.code`

停止時はcode、Round ID、State revision、Node件数、次の必要操作だけをcompact JSONで返す。詳細な途中経過はRun内logへ保存し、Main Agent Contextへ投入しない。

### 2.4 並列実行

- 既存Execution Packet、`parallel_limit`、`available_cpu_cores`を維持する。
- 一Packet内は現在と同じ最大N並列とする。
- DriverはPacket外側の状態遷移だけを担当する。
- terminal Packet完了後に次Packetを計画する。
- 空いたslotへの動的補充は初期案の対象外とする。

### 2.5 通知との限界

限定DriverはShell通知配送そのものを修復しない。通知欠落の影響を、解析途中の停止から、Driver完了または人間Gate提示の遅延へ縮小する。

Main Agentの確実な再覚醒には次のいずれかが別途必要である。

- Foreground Tool呼出しを完了まで保持する。
- Hostが永続通知と受領確認を提供する。
- Main Agent Context外のWatcherが再通知する。

HostにAgent再開APIがない場合、Repository内Runtimeだけで再覚醒を完全保証できない。新しいTurn開始時はRuntime `query`を一回実行し、永続Stateから結果を回収する。

### 2.6 Pros／Cons

Pros:

- Main Agentの短間隔pollを除去できる。
- 機械的な中間actionでLoopが停止しにくい。
- 既存DAG、Lease、Packet、N並列、Artifact契約を再利用できる。
- Main Agentを人間対話とInterpretationへ集中させられる。

Cons:

- 最終通知欠落そのものは解消しない。
- 固定Loopの実行主体がMain Agentから一部Runtimeへ移る。
- Driver crash、Lease失効、running Node残存、停止要求を追加設計する必要がある。
- 長時間Foreground呼出しがHost timeoutを超える可能性がある。
- Driver不具合が連続する複数actionへ影響し得る。

### 2.7 要検討事項

1. Foreground最大実行時間とBackground Task寿命
2. 利用Hostの確実な再通知／受領確認機構
3. ユーザーの途中停止要求を伝える方法
4. 自動実行を許可する`required_action.code`のclosed list
5. Lease heartbeat／延長とRound wall timeの関係
6. Driver crash後の再入可能性とterminal Packetの二重実行防止
7. 動的slot補充を将来追加するか

## 3. Endpoint選抜結果の安定性

### 3.1 Motivation

Cluster／SeriesはEndpointを用いて選抜され、同じEndpointで特徴を記述する。この処理は探索として妥当だが、選ばれたunitが入力化合物やEndpointの小さな変動に対して再現するかは現在評価していない。多数のDescription／Clusteringを試すことで偶然のenrichmentが含まれる可能性もある。

### 3.2 候補評価

- compound bootstrapによるselection frequency
- FF、enrichment ratio、Endpoint代表値の区間推定
- Endpoint permutationによる経験的null／FDR
- Cluster／Series memberの再現率
- stable／fragile等のReport label
- Cross-representation supportとの組合せ

### 3.3 要検討事項

1. bootstrap／permutationの反復数とHPC cost
2. Clusterを固定してFFだけ再計算するか、Clusteringから再実行するか
3. 安定性をhard gateにするか、Report上の補助指標にするか
4. 多重性のfamilyをDescription別、Clustering別、全体のどこに置くか
5. 小Clusterの扱いと信頼区間
6. random seedと再現性契約
7. Standard Reportへ載せる最小限の指標

初期案ではhard gateへ直結させず、selection frequencyと区間推定を診断表示し、実データ分布を確認してから判定利用を決める。

## 4. A005予測安定性

### 4.1 Motivation

A005はLocalと同一化合物に対するGlobalのOOF予測を比較するが、小規模analysis unitでは一回のfold分割によってR²、MAE、最良Descriptionが変動し得る。現在の結果は予測可能性の探索指標であり、安定した優越性まで保証しない。

### 4.2 候補評価

- repeated K-fold OOF
- fold内feature selection／imputationを維持したnested処理
- LocalがGlobalを上回った反復割合
- R²差、MAE差の分布と区間
- sample数、feature数、適用範囲の診断
- 最良model／Description選択の再現率

### 4.3 要検討事項

1. 反復数とKの既定値
2. 現行30化合物境界を維持するか
3. `local R² >= 0.20`等を平均、中央値、下限のどれに適用するか
4. model／Description選択をnested loopへ含める範囲
5. Runtime costと並列化単位
6. Standard Reportに表示する指標数
7. 現行単一OOFとのArtifact互換性

## 5. 共通runner構造整理

### 5.1 背景

複数の解析Skillが同一の大きなcanonical runnerをself-contained copyとして保持している。package verifierによるhash同期はあるが、一つの変更が多数Skill copyへ波及し、review範囲、差分量、未使用code、test責務が大きくなる。

### 5.2 候補案

1. canonical sourceをCapability単位または共通component単位に分割する。
2. build時に各Skillへ必要部分だけを含むself-contained runnerを生成する。
3. 生成fileは手編集禁止とし、headerへ生成元とhashを記録する。
4. CI／package verifierで再生成差分がないことを確認する。
5. Runtime時は他Skill directoryへ依存せず、現行のself-contained性を維持する。
6. `_run_c012_legacy`等の未使用経路を除去する。

### 5.3 要検討事項

1. Skill単独配布時に必要なself-contained範囲
2. canonical module分割単位
3. build toolと生成物をGit管理するか
4. 共通componentのVersion／hash表現
5. CapabilityごとのPixi依存をどう維持するか
6. tracebackとdiagnosticの可読性
7. 既存Runtime Artifactとの互換性
8. 段階移行か一括移行か

## 6. 0.1.12仕様化の推奨順序

1. Bounded Runtime Supervisorの責任境界とHost制約を決める。
2. Endpoint安定性評価を診断用途から設計する。
3. A005の計算量を見積もり、安定性指標を決める。
4. 共通runner再編は科学仕様と分離して実施計画を作る。
5. 各項目について、仕様概要書、Artifact契約、test matrix、migration方針を承認してから実装する。

## 7. 0.1.12着手前の確認質問

- Runtime Supervisorを利用するHostはForeground Toolを何時間維持できるか。
- Endpoint安定性はReport上の信頼度表示か、Series／Cluster採否条件か。
- bootstrap／permutationへ許容する最大追加計算時間はどの程度か。
- A005は安定性を優先して反復計算を増やすか、現在の軽量性を優先するか。
- self-contained Skill配布は0.1.12でも必須か。
