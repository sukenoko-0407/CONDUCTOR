---
name: cs-conductor-runtime
description: Deterministic CONDUCTOR 0.1.6 Runtime for compact Control, five-state DAG Nodes, idempotent OS Workers, common Execution Requests, signed packets, bounded exploration, Interpretation gates, and audit.
allowed-tools: Read, Bash
---

# CONDUCTOR Runtime

Runtimeは機械的な状態管理の唯一のWriterである。Orchestrator、Executor、Interpreterは`conductor_control.json`、`runtime/dag_snapshot.json`、Event Ledgerを直接編集しない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state <command> --run-root /path/to/run ...
```

小さい`conductor_control.json`を運用上の正本とし、詳細NodeはDAG snapshot、監査履歴はappend-only Ledgerへ保持する。Node statusは`pending`、`running`、`succeeded`、`failed`、`cancelled`の5種類だけである。

## 固定制御ループ

mutationはMain Agentだけがlive lease tokenを付けて実行する。one-use Action tokenは使用しない。各応答の`required_action.code`に対応するcommandは次の通り。

- `PLAN_BASIC` → `plan-basic`
- `PLAN_EXPLORATION` → `plan-exploration`
- `EXECUTE_RUNNABLE_BATCH` → Mainが`prepare-execution-packet`後に`execute-packet`
- `WAIT_RUNNING` → live Runtime Workerを再投入・reconcileせず待機
- `RECONCILE_RUNNING` → `reconcile-running`を一回だけ実行
- `RETRY_FAILED_NODE` → `retry-node --node-id <required_action.node_id>`
- `FAILED_NODE_REPAIR_REQUIRED` → 自動再試行せず停止。人間が実装／入力契約を修正した後だけ、同じNodeを`retry-node`
- `SCIENTIFIC_DECISION` → `runtime/working_set.json`を読み`scientific-decision`
- `ENTER_FINALIZING` → `enter-finalizing`
- `PLAN_INTERPRETATION` → `prepare-interpretation`
- `WRITE_INTERPRETATION` → Interpreter draft後に`commit-interpretation`
- `RUN_FULL_AUDIT` → `audit --mode full --register`
- `COMPLETE_FINALIZING` → `complete-finalizing`

Human stop codeでは処理を止める。Runtimeは新Roundを開始せず、Interpretation JSON／Markdown／HTMLとFull Auditが合格するまでRoundをhandoffしない。回復可能な一時障害の自動再試行は同一Nodeで最大3 Attemptとし、修正後の人間承認retryも新しいNode IDを発番しない。

## 科学Skill実行

RuntimeはCapability metadataから共通`execution_request.json`を一度生成し、全Skillを次の固定形で呼ぶ。

```text
<CONDUCTOR_RUNTIME_PYTHON> <skill>/scripts/launch.py --conductor-request <attempt>/execution_request.json
```

Requestはidentity、入力Artifact、列、endpoint、scope、parameter、CPU資源、出力先を持つ。Skill内adapterだけが既存科学kernelのCLIへ変換する。Runtime WorkerはSkill別CLIを再構築しない。Request、command、packetはhashと署名で固定し、実行直前に入力Artifactと上流`result.json`のSHA-256も再照合する。

`execute-packet`はPacketをAttemptへ原子的にclaimし、独立したOS Workerを起動する。呼出元のMain、互換Executor、Bash Tool callが終了してもWorkerは継続する。同じPacketを再投入した場合、`unclaimed`だけを一度起動し、`running`は既存Workerへ再接続し、`terminal`は保存済み結果を返す。Workerと科学processの生存中は`WAIT_RUNNING`、双方が消失したときだけ`RECONCILE_RUNNING`とする。

通常のfailed Node選択はrequired_actionに従う。人間が修正済みNodeの優先再実行を明示した場合に限り、running Nodeがゼロで、Main leaseとControl Authorityが有効なら、`EXECUTE_RUNNABLE_BATCH`中でも`retry-node --control-key`で同じNode IDをpendingへ戻せる。自動探索はこの保守例外を使用しない。Wall Timeが先に終了した場合、Failed Nodeを履歴に保持したpartial RoundとしてInterpretation／Auditへ進み、人間はそのRoundを受理して次Roundで補完するか、同じRoundをcontinueするかを選べる。実装修正後も科学的scope自体が成立しないPlanning由来Nodeは再試行せず、人間の明示承認により`cs-conductor-node-review cancel`でFailedのまま取消す。

Runtime管理fileはAttempt scratch直下、Skill出力は未作成の`skill_output/`へ分離する。cacheと一時fileはSkill `env/`またはRun `runtime/scratch/`の中だけに置く。

## 資源管理

`init --available-cpu-cores N`でCPU総予算を記録し、省略時は8。`parallel_limit`は同時Node数でありCPU総予算とは別である。C002 MCS、D016 Mordred 3D、D019 xTB、D020 ChemBERTa、A014 Global MMPは単独packetにする。各Skillの内部並列もAvailable CPU Coresを超えない。

入力CSVのSMILES列は`init`で一意に解決し、Requestの`columns.smiles`へ常に記録する。Description、structure Clustering、構造を読むOperatorへ同じ値を渡す。

## 探索とInterpretation

Operator探索は`exploration`一種類、最大100 Analysis Node／Roundである。Runtimeは成功済signatureを除外し、履歴上少ないCapability、scope、入力familyを優先しながらseed付きで選ぶ。Failed Nodeは成功履歴として数えず、再選択時も同じNode IDを再利用する。Globalを優先し、概ね`Global, Global, Local`の比率にする。全候補queueはStateへ保存せず、次Roundで再構成する。Description／Clusteringの基本計算はこの上限外である。

Interpretation入力はbounded Result Card集合である。未レビュー結果はcoverage limitationとして記録し、全履歴をInterpreterへ読ませない。A014は正規化SQLite、全詳細CSV、集約CSVを原子的に昇格し、大容量native work DBは残さない。

異常Nodeの人間操作は`cs-conductor-node-review`、read-only確認は`query`を使う。JSONを手修正しない。
