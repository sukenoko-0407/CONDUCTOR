# Failed Nodeを同一Roundで修復・再実行するプロンプト

対象Version: `0.1.6`

科学Nodeの技術的失敗を調査・修正し、Roundを閉じずに同じNode IDの新しいAttemptとして再実行するためのプロンプト例です。`<...>`を実際の値へ置き換えて使用してください。

## 1. 現在のRuntime Worker完了後にActive Roundを安全に一時停止する

実行中のMain Agentへ送ります。停止境界は、現在発行済みのExecution packetが完了し、Runtimeが結果をcommitまたはreconcileした直後です。現在のRuntime Workerや科学processを強制終了しません。

```text
現在のCONDUCTOR処理を安全に一時停止してください。

Run Root: <absolute run_root>
対象Round: <RND####>

目的:
失敗したNodeの原因を修正し、同じRound・同じNode IDで再実行することです。

指示:
- 現在すでに起動済みのRuntime Workerと、そのExecution packetに含まれるNodeは中断せず完了させる
- `WAIT_RUNNING`中はreconcileせず待ち、`RECONCILE_RUNNING`になった場合だけ一回実行する
- 現在のExecution packetの処理後は、新しいExecution packetや二つ目のWorkerを開始しない
- 次のDescription、Clustering、Operatorを新たに実行しない
- failed Nodeの自動retryも、この一時停止中は開始しない
- 実行中Nodeがゼロになったことを確認した時点を停止境界とする
- RoundはACTIVEのまま維持する
- request-checkpoint、ENTER_FINALIZING、Interpretation、Full Audit、accept-roundを実行しない
- 新しいRoundを開始しない
- failed Nodeをcancelledまたはskippedへ変更しない
- failed NodeごとにNode ID、Capability ID、Attempt数、failure code、failure pointerを簡潔に報告する
- State、DAG、Event Ledgerを直接編集しない
- 最後にOrchestrator leaseをreleaseして終了する
```

`request-checkpoint`は使用しません。これは安全な一時停止ではなく、同じRoundを`FINALIZING`へ進める操作だからです。

一つのExecution packetに複数Nodeが含まれている場合、そのpacket内のNodeはまとめて停止境界まで完了させます。個々のNode完了ごとに途中停止させる指示ではありません。MainのTool応答が失われても代替科学processを起動せず、同じPacketへの冪等な再接続または`RECONCILE_RUNNING`で状態を確定します。

## 2. 失敗原因を調査・修正する

Orchestratorを再開せず、通常のMain Agentへ依頼します。

```text
これはCONDUCTOR Roundの再開ではなく、失敗原因の保守作業です。

Run Root: <absolute run_root>
対象Node: <N######>
failure pointer: <failure_packet等のpath>

Run Rootは読み取り専用として扱い、State、DAG、Node、既存artifactを変更しないでください。
failure情報と該当Skillの必要最小限の実装を調査し、原因を特定してください。

CLI、環境、path、入出力契約などの技術的不具合であれば、該当Skillを修正して検証してください。
修正対象、原因、科学的意味が不変であること、実施した検証を報告してください。

科学的アルゴリズム、対象化合物、endpoint、Metric、Cluster scope、乱数seed、Parameterの意味を変更する必要がある場合は、修正前に報告して人間の判断を待ってください。
Stateを直接書き換えたり、代替Nodeを作成したりしないでください。
```

同じ原因が共通実装を持つ複数Skillへ影響する場合は、対象範囲を確認してから共通の修正と回帰試験を行います。

## 3. 修正後に同じRoundを再開する

```text
/cs-conductor-orchestrator

操作: 修正後のActive Roundを同じRoundのまま再開
Run Root: <absolute run_root>
対象Round: <RND####>
優先対象Node: <N######>
修正内容: <修正した技術的不具合の要約>
SMILES列名（旧Runでmetadataがなく自動推定できない場合のみ）: <column name>

最初にconductor_control.jsonを確認し、対象RoundがACTIVEであることを照合してください。
修正済みのfailed Nodeを、同じNode IDの新しいAttemptとして再実行してください。
代替Nodeを作成せず、failed Nodeをcancelledまたはskippedへ変更しないでください。
新しいRoundを開始しないでください。

Runtimeのrequired_actionがRETRY_FAILED_NODEであれば、一時障害として同じNodeを再試行してください。
Runtimeのrequired_actionがFAILED_NODE_REPAIR_REQUIREDで、上記の人間承認済み修正が完了していれば、
同じNodeをrepair retryしてください。required_actionがEXECUTE_RUNNABLE_BATCHでも、このプロンプトで人間が
対象Nodeの優先再実行を明示しており、running Nodeがゼロであれば、Control Authorityを付けた`retry-node`で
同じNodeをpendingへ戻してください。running Nodeが残る場合は、それらを中断せずterminalまで待ってから
一度だけ実行してください。それ以外のrequired_actionでは、他の科学NodeやExecution packetを実行せず、
そのrequired_actionと対象Nodeの状態を報告して停止してください。
State、DAG、Event Ledgerを直接編集して回避しないでください。
```

## 現行Runtimeの注意点

`0.1.6`のRuntimeは通常時、実行可能な`pending` Nodeを、有限再試行が可能な`failed` Nodeより先に選びます。ただし、人間がこの保守操作で対象Nodeを明示し、running Nodeがゼロで、MainのleaseとControl Authorityが揃う場合だけ、`EXECUTE_RUNNABLE_BATCH`中でも同じNode IDを優先再試行できます。自動探索がこの例外を利用することは認めません。再試行packetも共通`execution_request.json`を使い、Runtime Workerが引数を修正することはありません。一時障害は`RETRY_FAILED_NODE`、決定論的な契約不良または自動retry上限到達は`FAILED_NODE_REPAIR_REQUIRED`で区別されます。

- 他のNodeを先に実行してよい場合は、優先停止条件を外して同じRoundを通常再開します。
- failed Nodeを必ず先に再実行する場合は、上記の人間承認済み保守操作を使います。
- 再試行上限へ達したNodeは自動再試行しません。人間が原因修正を承認した場合だけ、`FAILED_NODE_REPAIR_REQUIRED`から同じNode IDへrepair retryします。Stateを直接編集しません。

科学Nodeの正式Statusは`pending / running / succeeded / failed / cancelled`です。`skipped`をNodeの代替Statusとして設定しません。失敗Nodeに依存する下流Nodeは、その依存関係が満たされるまでrunnableになりません。
