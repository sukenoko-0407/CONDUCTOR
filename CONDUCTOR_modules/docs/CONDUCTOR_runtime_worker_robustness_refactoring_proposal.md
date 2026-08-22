# CONDUCTOR Runtime Worker頑健化リファクタリング提案

> 状態: 実装済み。Windows回帰試験と実データE2E試験を実施後、Linux長時間試験で最終受入する。`cs-conductor-executor`は既存導入先向けの互換attachmentとして残すが、通常経路では使用しない。

## 1. 背景

現行構成では、Main AgentがOrchestratorとなり、署名済みExecution Packetを短命なExecutor Subagentへ渡す。ExecutorはRuntime `execute-packet`を一回呼び、Runtimeが科学Skillを実行する。

実運用では、長時間計算の完了前にExecutorが終了し、その後Main AgentがRuntime状態を短い間隔で確認し続ける事象が複数回発生した。Mainが個別科学Skillを直接実行し始める場合は責務境界も崩れる。主な原因候補は次である。

- Executor定義の「short-lived」「Runtime call一回後に終了」が、call開始と最終結果取得を区別していない。
- 数時間の科学計算と、LLM Subagent／Bash Toolの実行寿命が一致しない。
- Executor消失後の復旧がMain Agentへ戻り、短間隔pollと追加Tool callを誘発する。
- Agentが長時間processの生存監視を担うため、Agent停止が実行制御上の障害になる。
- Runtime正常系、Runtime境界障害、科学Node失敗の処理責任が十分に分離されていない。

これはトラブル対応文書だけで吸収する例外ではなく、正常実行経路の所有権を修正すべき設計課題である。

## 2. 目的

1. Main Agent、Executor Subagent、Claude Code sessionが終了しても、投入済み科学計算を安全に追跡できる。
2. 同じPacketを再度指定しても、同じ科学計算を二重起動しない。
3. Main Agentが個別Skill、raw log、短間隔pollを抱えない。
4. Runtime、科学Node、Runtime呼び出し境界の障害を区別する。
5. 人間の明示なしに新Roundを作らず、Interpretation未完成でRoundを閉じない。
6. 新しいState正本、Node状態、LLM Agentを増やさない。
7. Description、Clustering、Operator、Interpretationの科学kernelと一般利用CLIを変更しない。

## 3. 推奨する設計判断

長時間科学processの所有者を、LLM Executor Subagentから決定論的なRuntime Workerへ移す。Executor Subagentは通常実行経路から外し、互換attachmentに限定する。

```text
Human
  |
  v
Main Agent = Orchestrator
  |-- fixed Runtime packet submission
  |      `-- Runtime Worker owns scientific processes
  |
  `-- Interpreter Subagent for read-only interpretation
```

MainがRuntime wrapperを呼ぶこと自体は許可する。ただし、Mainが個別のDescription、Clustering、Operator、Interpretation Skill launcherを直接実行することは禁止する。全科学Skillは、Runtimeが検証した共通`execution_request.json`からだけ起動する。

## 4. 責務

| Component | 担当 | 担当しないこと |
|---|---|---|
| Human | Round開始、修正承認、Round受理 | 自動State編集 |
| Main Orchestrator | 科学候補選択、固定Runtime操作、Interpreter起動、人間報告 | 個別科学Skill実行、raw log監視、State直接編集 |
| Runtime Controller | Packet生成、atomic claim、required action、State単一Writer | 科学的優先順位の自由推論 |
| Runtime Worker | 一つのPacketに含まれるNodeの実行、有限retry、検証、commit | 新Round作成、候補選択、CLI即席修正 |
| Interpreter | 既存結果の比較とdraft作成 | 科学計算、Node作成、State更新 |

Runtime Workerは新しいAgentではない。Runtime package内の決定論的processであり、LLM contextを持たない。

## 5. 正常実行フロー

1. MainがControlの一つの`required_action`を確認する。
2. `EXECUTE_RUNNABLE_BATCH`なら`prepare-execution-packet`を一回実行する。
3. Mainが固定されたRuntime wrapperでPacketを一回だけ投入する。
4. RuntimeがPacket、Control revision、Request hash、入力hash、working directoryを検証する。
5. RuntimeがPacketをatomicにclaimし、既存process recordへ実行情報を記録する。
6. Runtime WorkerがCPU予算内で科学Skillを実行する。
7. stdout／stderrはAttempt logへ逐次保存し、Mainへ返さない。
8. Runtime WorkerがArtifactを検証し、canonical directoryへ昇格してStateをcommitする。
9. Mainは完了通知後にcompact responseを一回確認する。
10. Mainは次の`required_action`へ進む。

Mainは、正常なWorkerが動作中である間、`reconcile-running`を繰り返さない。

## 6. Packetの冪等性

Packet IDを実行識別子として再利用し、新しい実行ID体系を追加しない。

```text
unclaimed -> running -> terminal
```

| Packet状態 | 同じPacketを再投入した場合 |
|---|---|
| `unclaimed` | atomicにclaimし、一回だけ開始 |
| `running` | 新規起動せず、既存実行のcompact状態を返す |
| `terminal` | 保存済みの最終compact結果を返す |
| invalid／expired／別revision | fail closedで拒否 |

二重投入の抑止はAgentへの注意書きだけに依存させない。Runtimeのwriter lock、Packet claim、Control revision、Packet署名で決定論的に保証する。

## 7. Node失敗と再試行

Runtime Workerが障害を分類し、Mainや旧Executorは同じPacketを推測で再実行しない。

### 7.1 有限自動再試行を許可するもの

- 明確に一時的なfile lock
- 一時的なprocess spawn失敗
- 明確に一時障害と分類できるI/Oエラー

同じNode ID、同じRequest、同じ科学パラメータでのみ再試行する。上限到達後は人間修正待ちにする。

### 7.2 自動再試行しないもの

- OOM、長時間timeout、SIGKILL
- 入力列、Schema、引数、Artifact contractの不一致
- Skill実装エラー
- 必須成果物不足
- identity、scope、hashの不一致

これらは`FAILED_NODE_REPAIR_REQUIRED`を返す。人間が原因修正と再開を承認した場合だけ、同じNode IDへ新しいAttemptを追加する。別Nodeや次Roundを作らない。

## 8. Runtime境界障害

Runtime自身だけを異常検出の唯一の主体にしない。Orchestrator launcherは、Runtimeの外側で次を検出する。

- Runtime processの非ゼロ終了
- 応答JSON欠落または不正
- 要求commandと応答種別の不一致
- Packet claim前の起動失敗
- Worker heartbeat staleまたはprocess消失

境界障害時は、状態を推測で進めず、短い定型結果をMainへ返す。

```json
{
  "status": "runtime_boundary_error",
  "error_code": "RUNTIME_INVALID_RESPONSE",
  "state_mutation_allowed": false,
  "incident_reference": "runtime_unavailable.md"
}
```

応答が失われた場合は、計算が開始されていないと推測して同じPacketを新規実行しない。Packetの冪等な再照会により、`unclaimed`、`running`、`terminal`をRuntime側で確定する。

## 9. 待機とreconcile

曖昧な`WAIT_OR_RECONCILE_RUNNING`を、Runtimeが判定した二つのActionへ分ける。

| required action | Mainの固定操作 |
|---|---|
| `WAIT_RUNNING` | 再実行、State更新、別Worker起動をせず待機 |
| `RECONCILE_RUNNING` | `reconcile-running`を一回だけ実行 |

原則はClaude Codeのbackground completion通知を利用する。環境上通知を利用できない場合だけ、十分に長い固定間隔のcompact status確認をfallbackとして許可する。数秒単位のpollは禁止する。

`reconcile-running`で全processが生存中なら、Control revision、Event Ledger、Working Setを更新しない。reconcileは監査・復旧操作であり、進捗pollとして使用しない。

## 10. Incident対応文書

詳細対応集はOrchestratorの常時contextへ入れない。Orchestrator Skillには短い安全原則とエラーコード対応表だけを置き、異常発生時に該当する一ファイルだけを読む。

```text
.claude/skills/cs-conductor-orchestrator/references/incidents/
  runtime_unavailable.md
  worker_stale.md
  execution_outcome_unknown.md
  node_repair_required.md
  output_incomplete.md
  interpretation_missing.md
```

常時保持する原則は次に限定する。

1. 復旧のために新Roundを作らない。
2. 同じ処理を無制限に再試行しない。
3. live Workerがある間に別Workerを起動しない。
4. Runtime応答が不正ならStateを進めない。
5. InterpretationとFull Auditが合格するまでRoundを閉じない。

新しいRecovery Agent、Recovery State正本、外部State writerは追加しない。

## 11. InterpretationとRound gate

次のいずれかが成立する場合、Roundを`AWAITING_HUMAN_REVIEW`へ進めない。

- Interpretation Nodeが`succeeded`ではない。
- `interpretation.json`、`interpretation.md`、`interpretation.html`のいずれかがない。
- Interpretation scope、参照Result、必須sectionの検証が不合格である。
- Full Auditが不合格である。
- running Node、未回収process、未解決の必須Failed Nodeがある。

Main、Runtime Worker、Interpreterの終了自体をRound完了と解釈しない。

## 12. 現行0.1.5との互換性

互換性は層ごとに異なる。完全なhot compatibilityは提供しない方が頑健である。

| 対象 | 互換性 | 方針 |
|---|---|---|
| Description／Clustering／Operator科学kernel | 高い | 変更しない |
| 一般利用CLI | 高い | `--conductor-request`なしの動作を維持 |
| 共通`execution_request.json` | 原則維持可能 | 必要なresource／identity fieldだけを互換範囲で追加検討 |
| 完了済みcanonical Artifact | 条件付きで再利用可能 | schema、hash、identity、scopeが現行検証を通るものだけ使用 |
| 成功済みNode、Result Card、Result Index | 条件付きで再利用可能 | deterministic migrationとFull Auditが必要 |
| Control／DAG／Ledger | migrationが必要 | Action codeとprocess lifecycleの差を決定論的に変換 |
| 未使用の発行済みPacket | 非互換 | 破棄し、新Runtimeで再発行 |
| 実行中Packet／process | 非互換 | hot switchしない。旧Runtimeで完了または安全停止後に切替 |
| 旧Executor Subagent session | 非互換 | 引き継がず終了 |
| Active Round | 条件付き | running processと発行済みPacketがない静止境界だけ移行候補 |

### 12.1 安全な互換方針

最も安全なのは新規Runで開始することである。ただし、高コストの完了済みDescription等を再利用する価値があるため、実装時には次の限定migrationを検討できる。

1. 旧Run Rootを直接変更せず、新しいRun Rootへコピーする。
2. 旧RunでFull Auditを成功させる。
3. running Node、live process、発行済み未消費Packetがないことを確認する。
4. 完了済みNode、canonical Artifact、Result Card、Cluster Registryをhash付きで移す。
5. 旧Packet、旧process record、lease、scratchは引き継がない。
6. pending／failed NodeはIDを維持し、新RuntimeでRequestとPacketを再生成する。
7. 新RuntimeでFull Auditを再実行する。
8. 検証が一項目でも不合格なら、そのRunは互換移行せず新規Runとする。

このmigrationは、実装とfault testが完了するまで「対応可能性」であり、現時点では保証しない。

### 12.2 禁止する混在

- 同じRun Rootを旧Runtimeと新Runtimeから同時に開く。
- 旧Runtimeが発行したPacketを新Runtime Workerで実行する。
- 実行中Nodeを強制的に成功・失敗へ書き換えて移行する。
- 旧Executorと新Runtime Workerを同じRoundで併用する。
- migration失敗をMain Agentの手作業によるJSON編集で補う。

## 13. 実装Phase

### Phase 1: 安全契約

- Mainによる個別科学Skill実行を明示的に禁止する。
- Packet開始、完了、境界障害のcompact envelopeを固定する。
- `WAIT_RUNNING`と`RECONCILE_RUNNING`を分離する。
- Executorが残る期間も、task IDや`async_launched`を計算完了として扱わない。

### Phase 2: Runtime Worker

- Packet claimを冪等化する。
- 既存process recordを使ってWorker PID、heartbeat、開始時刻を管理する。
- 長時間科学processをRuntime Workerが所有する。
- Executor lifecycleと科学process lifecycleを分離する。

### Phase 3: Main Orchestrator切替

- 通常経路からExecutor Subagentを外す。
- Mainは固定Runtime wrapperを一回だけ呼ぶ。
- completion通知、compact status、単発reconcileの手順を固定する。
- Orchestrator Skill、README、prompt集を更新する。

### Phase 4: Incident対応

- Runtime boundary errorを実装する。
- 小さいIncident文書を追加する。
- Runtime完全停止時は自動復旧せず、安全停止する。

### Phase 5: Compatibilityとcutover

- 新規RunのEnd-to-End試験を先に完了する。
- 静止した0.1.5 fixtureだけを対象にmigration試験を行う。
- hot migrationと旧Packet互換は実装しない。

## 14. 必須受入試験

1. Mainまたは旧ExecutorがPacket投入直後に終了しても、投入済み計算を追跡できる。
2. 同じPacketを二回投入しても、Skill processが一回しか起動しない。
3. Worker Kill後に、同じNode IDのまま失敗または復旧状態を確定できる。
4. Runtimeが不正JSONまたは非ゼロ終了しても、Stateを推測で進めない。
5. live Workerがある間に別Workerを起動しない。
6. Mainが個別科学Skillを直接実行しない。
7. Mainへraw scientific stdout／stderrを返さない。
8. `reconcile-running`の生存確認だけでLedgerやrevisionが増えない。
9. Failed Nodeを自動で`skipped`または成功扱いにしない。
10. InterpretationとFull AuditなしでRoundを閉じない。
11. 人間の指示なしに次Roundを開始しない。
12. 別sessionのMain Agentがcompact Controlだけで同じRoundを再開できる。
13. Linuxで6時間許可、process tree終了、共有Pixi環境、CPU上限を確認する。

## 15. Pros／Cons

### Pros

- LLM Executorの早期終了を科学processの成否から切り離せる。
- Agent failure boundaryを一つ減らせる。
- Mainのraw log、CLI補正、短間隔pollを減らせる。
- 二重投入をRuntimeで決定論的に防止できる。
- 別sessionへの引継ぎがPacket IDとcompact Controlで完結する。
- 科学Skillと一般利用CLIへ影響しない。

### Cons

- Runtime process lifecycleの中規模リファクタリングが必要である。
- 現行0.1.5の実行中Packetとはhot compatibilityを持てない。
- background completion通知のLinux実環境試験が必要である。
- Runtime Worker停止時のreconcileとatomic commitをfault injectionで十分に検証する必要がある。
- 限定migrationを提供する場合、検証用コードと監査項目が増える。

## 16. 推奨結論

頑健性を優先する場合、Executorへの待機指示追加だけで完了としない。長時間計算の所有権をRuntime Workerへ移し、Executor Subagentを通常経路から外す。

科学Skillと完了済みArtifactの互換性は高く保てるが、旧Packet、実行中process、旧Executor sessionの互換は明示的に捨てる。既存Runを引き継ぐ場合も、旧Runを保存した静止境界での決定論的migrationと新旧双方のFull Auditを必須とする。

## 17. 実装結果

- `execute-packet`は初回だけPacketをNode Attemptへ原子的にclaimし、独立OS processのRuntime Workerを起動する。
- Attemptへ既存Packet IDを記録し、`worker_status.json`を実行上の補助記録として保持する。Control、DAG、Ledger以外のState正本は追加していない。
- 同じPacketの再投入は、未claimなら一回だけ起動、runningなら既存Workerへ再接続、terminalなら保存済み結果を返す。
- Worker commitはMain leaseの生存に依存せず、署名済PacketとNode／Attempt／Packet IDの結合を検証する。
- `WAIT_RUNNING`と`RECONCILE_RUNNING`を分離し、live processへreconcileを適用しない。
- WorkerがState commit後・status更新前に停止しても、Node Attemptの終端状態からPacketのterminal statusを再構成する。
- A003を含む科学kernel、一般利用CLI、Execution Requestの科学入力契約は変更していない。
