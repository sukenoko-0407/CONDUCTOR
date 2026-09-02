# Runtime Supervisor（限定Driver）改良案

Status: **保留中。未実装**

## 背景

0.1.9の固定Loopでは、Main AgentがRuntimeの`required_action.code`を一件ずつ解釈し、対応するRuntimeコマンドを呼び出す。長時間処理をBackground Taskとして実行した際、Shell完了通知をMain Agentが受け取れず、処理自体は終了していたにもかかわらず、人間が発話するまで固定Loopが再開されない事象が確認された。

Main Agentが短い間隔で状態確認を繰り返す方式は、Tool履歴とContextを消費するため採用しない。

## 改良案の概要

常駐Daemonを新設するのではなく、Runtime Skillへ仮称`drive-until-gate`という限定Driverを追加する。Main Agentが人間承認済みの一つのRoundに対して一回起動し、Driverは機械的に決定できる`required_action`だけを連続実行する。

```text
Main Agent
  └─ drive-until-gate（承認済みRound）
       ├─ plan
       ├─ Execution Packet（既存の最大N並列）
       ├─ 次のrequired_actionを評価
       └─ Gate到達時に停止してcompact JSONを返す
```

Driverは人間承認、科学的判断、Interpretationを代行しない。新しいRoundも開始しない。

## 停止するGate

- `AUTHORIZE_ROUND`、`HUMAN_APPROVAL_REQUIRED`、`HUMAN_SERIES_REVIEW_REQUIRED`
- `WRITE_INTERPRETATION`
- `FAILED_NODE_REPAIR_REQUIRED`、`BLOCKED_BASIC`、`BLOCKED_STANDARD`、`INTERPRETATION_BLOCKED`
- `ROUND_PAUSED`、`PAUSE_ROUND`
- `AWAIT_HUMAN_REVIEW`、`AWAIT_HUMAN_ROUND`
- 未知の`required_action.code`

停止時は、到達したcode、Round ID、State revision、Node件数、必要な次操作だけをcompact JSONで返す。詳細ログはRun内へ保存し、Main AgentのContextへ逐次投入しない。

## 並列実行

既存のExecution Packetと`parallel_limit`／`available_cpu_cores`を維持する。限定DriverはPacketの外側の制御だけを担当し、Node Schedulerや計算手法は変更しない。したがって、一Packet内では現在と同じ最大N並列とし、全Nodeがterminalになった後に次のPacketを計画する。

空いた並列枠への動的補充は本案の対象外とする。

## 通知との関係

限定DriverはShell通知の配送信頼性を改善するものではない。通知欠落を「解析途中で固定Loopが止まる問題」から「完了または人間Gateの提示が遅れる問題」へ限定する。

Main Agentの自動再開まで保証するには、次のいずれかを別途必要とする。

- `drive-until-gate`をForeground Tool呼び出しとして完了まで保持する
- Hostが永続的な通知と受領確認を提供する
- Main AgentのContext外にある外部Watcherが再通知する

HostにAgent再開APIがない場合、Repository内のRuntimeだけでMain Agentの再覚醒を完全には保証できない。Main Agentは新しいTurnの開始時にRuntime `query`を一回実行し、永続Stateから結果を回収する。

## Pros

- Main Agentによる短間隔Pollingが不要になり、ContextとTokenを節約できる
- Shell通知を取り逃しても、機械的に実行可能な解析途中では停止しない
- 既存のDAG、Lease、Execution Packet、N並列、Artifact契約を再利用できる
- 固定状態遷移を決定論的なPython処理へ集約できる
- Main Agentを人間との対話とInterpretationへ集中させられる

## Cons

- Main Agentへの最終通知欠落そのものは解消しない
- 固定Loopの実行主体が一部Main AgentからRuntimeへ移るため、仕様と責任境界の変更になる
- Driver crash、Lease失効、`running` Node残存、再開、停止要求の扱いを追加検証する必要がある
- 一つのDriver不具合が複数の連続操作へ影響する可能性がある
- 長時間Foreground実行がHostのTool timeoutを超える場合、別の待機・再通知方式が必要になる

## 導入する場合の制約

- 人間が承認した現在のACTIVE Roundだけを対象にする
- 現在のLease tokenを必須とし、single-writer規則を維持する
- 人間Gate、Interpretation、失敗、pause、完了では必ず停止する
- 成功済みNodeとterminal Packetを再実行しない
- Driver再起動時は永続Stateの`required_action`から再開する
- 途中経過を標準出力へ連続表示せず、Run内ログへ保存する
- 新Round作成、parameter自動変更、failed Nodeの自動waiveを禁止する

## 保留中の判断事項

- Foreground最大実行時間とBackground Taskの寿命
- Host側に利用可能な確実なAgent再開／通知確認機構
- ユーザーからの途中停止要求をDriverへ伝える方法
- 本変更を0.1.9の修正とするか、次Versionの機能変更とするか
- `drive-until-gate`が自動実行してよいcodeの確定一覧

