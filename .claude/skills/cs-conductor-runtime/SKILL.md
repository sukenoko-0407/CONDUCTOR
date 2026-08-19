---
name: cs-conductor-runtime
description: Deterministic CONDUCTOR 0.1.3 Runtime for Node IDs, five-state DAG records, signed Executor packets, crash recovery, bounded working sets, Interpretation gates, and audit. Main Orchestrator uses it only inside an authorized Round.
allowed-tools: Read, Bash
---

# CONDUCTOR Runtime

Runtime owns mechanical state management. The Orchestrator must not edit `conductor_control.json`, `runtime/dag_snapshot.json`, or the Event Ledger.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state <command> --run-root /path/to/run ...
```

The small `conductor_control.json` is the operational source of truth. Detailed Nodes are in the Runtime-owned DAG snapshot; the append-only Event Ledger and transaction journal keep it synchronized and auditable. Node status is only `pending`, `running`, `succeeded`, `failed`, or `cancelled`.

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

Mutation responses use the bounded `0.1.3` compact protocol. Full Control, DAG, Ledger, raw logs, and full Audit are returned only by explicit read-only queries or file pointers. Executor packets are signed, action-scoped, short-lived, and single-use through Control revision and Action-token binding; the Executor never receives the Main lease token. Packet command hashes use an environment-neutral Runtime Python token, which this Runtime resolves to its own `sys.executable` only after packet validation.

Interpretation input is a balanced, bounded set of Result Cards. Runtime records omitted cards as unreviewed instead of asking the Interpreter to load an unbounded history.

All execution scratch and caches stay under the Skill `env/` or Run `runtime/scratch/`; scratch is not a scientific artifact. Scientific Skills keep their general-use interfaces, while Runtime validates and promotes only canonical minimal outputs.

For read-only navigation use `query`; for an abnormal Node use human-only `cs-conductor-node-review`. Do not repair JSON manually.
