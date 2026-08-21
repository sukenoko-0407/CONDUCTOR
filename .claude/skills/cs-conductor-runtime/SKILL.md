---
name: cs-conductor-runtime
description: Deterministic CONDUCTOR 0.1.4 Runtime for Node IDs, five-state DAG records, signed Executor packets, crash recovery, bounded working sets, Interpretation gates, and audit. Main Orchestrator uses it only inside an authorized Round.
allowed-tools: Read, Bash
---

# CONDUCTOR Runtime

Runtime owns mechanical state management. The Orchestrator must not edit `conductor_control.json`, `runtime/dag_snapshot.json`, or the Event Ledger.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state <command> --run-root /path/to/run ...
```

The small `conductor_control.json` is the operational source of truth. Detailed Nodes are in the Runtime-owned DAG snapshot; the append-only Event Ledger and transaction journal keep it synchronized and auditable. Node status is only `pending`, `running`, `succeeded`, `failed`, or `cancelled`.

`init --available-cpu-cores N`でRunのCPU総予算を記録する。省略時は8。`prepare-round --available-cpu-cores N`を明示したRoundでは、承認時にRunの現行予算を更新する。`parallel_limit`は同時Node数であり、CPU総予算とは別に管理する。C002 MCSは最大8個の単一thread workerを使う単独Execution packetとする。D019も単独packetとし、原則4コア/化合物で`compound_workers × cores_per_compound <= available_cpu_cores`を保証する。D020とA014 `global-build`も内部並列を使うため単独packetとし、その他の同時Nodeは1 CPU threadずつに制限する。

`init`は入力CSVのSMILES列を一意に解決してControlへ記録する。列名が曖昧な場合は`--smiles-column`を必須とし、全Description、C001～C004、ならびに構造を直接読むA006・A009・A013へ記録済み列名を明示的に渡す。旧Runに記録がない場合は保存済み`runtime/input.csv`から同じ規則で解決し、それも不可能なら人間指定の`resume-round --smiles-column`で一度だけ補う。既存値は変更できない。

## Orchestrator loop

Use the command named by `required_action.code`. Mutating calls require `--lease-token` and the latest one-use `--action-token`. The returned Action token replaces the previous token.

- `PLAN_BASIC` → `plan-basic`
- `PLAN_INITIAL_GLOBAL` → `plan-initial-global`
- `PLAN_INITIAL_LOCAL` → `plan-initial-local`
- `EXECUTE_RUNNABLE_BATCH` → Main runs `prepare-execution-packet`; `cs-conductor-executor` runs `execute-packet`
- `WAIT_OR_RECONCILE_RUNNING` → `reconcile-running`
- `RETRY_FAILED_NODE` → `retry-node --node-id <required_action.node_id>`
- `SCIENTIFIC_DECISION` → inspect `runtime/working_set.json`, then `scientific-decision`
- `ENTER_FINALIZING` → `enter-finalizing`
- `PLAN_INTERPRETATION` → `prepare-interpretation`
- `WRITE_INTERPRETATION` → Interpreter draft, `commit-interpretation`
- `RUN_FULL_AUDIT` → `audit --mode full --register`
- `COMPLETE_FINALIZING` → `complete-finalizing`

`HUMAN_APPROVAL_REQUIRED`, `HUMAN_REVIEW_REQUIRED`, `INTERPRETATION_BLOCKED`, and `AWAIT_HUMAN_ROUND` are stop-and-return conditions. Do not substitute a scientific command. If a live lease still exists at a human stop, consume the current token with `release-lease --reason <reason>` before returning. A scientific Node gets a finite same-Node retry budget; retries never allocate a replacement Node ID.

Runtime refuses Round finalization until the formal Interpretation JSON, Markdown, HTML, quality report, and Full Audit all pass. It never starts a new Round. The manually activated Main Orchestrator performs only human-authorized Round control.

Mutation responses use the bounded `0.1.4` compact protocol. Full Control, DAG, Ledger, raw logs, and full Audit are returned only by explicit read-only queries or file pointers. Executor packets are signed, action-scoped, short-lived, and single-use through Control revision and Action-token binding; the Executor never receives the Main lease token. Packet command hashes use an environment-neutral Runtime Python token, which this Runtime resolves to its own `sys.executable` only after packet validation.

Interpretation input is a balanced, bounded set of Result Cards. Runtime records omitted cards as unreviewed instead of asking the Interpreter to load an unbounded history.

Runtime limits the Analysis workload assigned to one Round to 200 Nodes and materializes deterministic, stratified slices of at most 50 Nodes. Initial Global materialization stops at 100 Nodes so capacity remains for Cluster-local Analysis. Deferred candidates are not DAG Nodes. Repeated `PLAN_INITIAL_GLOBAL` or `PLAN_INITIAL_LOCAL` actions therefore mean that the next bounded slice is ready to be registered, not that planning failed. A longer Wall Time never increases this limit. At the limit, Runtime proceeds through Interpretation and Audit; only a later human-authorized Round may reconstruct the remaining candidates. Basic Description and Clustering Nodes are outside this Analysis limit.

A014 is additive: one Global database Node, one all-Cluster screening Node, and bounded representative Local-detail Nodes. A014 payload promotion is atomic and verifies the stable SQLite, full CSV, and Parquet row counts. Existing 0.1.3 active Rounds are not retroactively given A014; a Round newly authorized by 0.1.4 may schedule it.

All execution scratch and caches stay under the Skill `env/` or Run `runtime/scratch/`; scratch is not a scientific artifact. Scientific Skills keep their general-use interfaces, while Runtime validates and promotes only canonical minimal outputs.

For read-only navigation use `query`; for an abnormal Node use human-only `cs-conductor-node-review`. Do not repair JSON manually.
