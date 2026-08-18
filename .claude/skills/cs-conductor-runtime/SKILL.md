---
name: cs-conductor-runtime
description: Deterministic CONDUCTOR 0.1.2 Runtime for Node IDs, five-state DAG records, execution, crash recovery, bounded working sets, Interpretation gates, and audit. Orchestrator uses it only inside an authorized Round.
allowed-tools: Read, Bash
---

# CONDUCTOR Runtime

Runtime owns mechanical state management. The Orchestrator must not edit `conductor_control.json`, `runtime/dag_snapshot.json`, or the Event Ledger.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state <command> --run-root /path/to/run ...
```

The small `conductor_control.json` is the operational source of truth. Detailed Nodes are in the Runtime-owned DAG snapshot; the append-only Event Ledger and transaction journal keep it synchronized and auditable. Node status is only `pending`, `running`, `succeeded`, `failed`, or `cancelled`.

## Orchestrator loop

Use the command named by `required_action.code`. Mutating calls require `--lease-token` and the latest one-use `--action-token`. The returned Action token replaces the previous token.

- `PLAN_BASIC` → `plan-basic`
- `PLAN_INITIAL_GLOBAL` → `plan-initial-global`
- `PLAN_INITIAL_LOCAL` → `plan-initial-local`
- `EXECUTE_RUNNABLE_BATCH` → `execute-batch`
- `WAIT_OR_RECONCILE_RUNNING` → `reconcile-running`
- `RETRY_FAILED_NODE` → `retry-node --node-id <required_action.node_id>`
- `SCIENTIFIC_DECISION` → inspect `runtime/working_set.json`, then `scientific-decision`
- `ENTER_FINALIZING` → `enter-finalizing`
- `PLAN_INTERPRETATION` → `prepare-interpretation`
- `WRITE_INTERPRETATION` → Interpreter draft, `commit-interpretation`
- `RUN_FULL_AUDIT` → `audit --mode full --register`
- `COMPLETE_FINALIZING` → `complete-finalizing`

`HUMAN_APPROVAL_REQUIRED`, `HUMAN_REVIEW_REQUIRED`, and `AWAIT_HUMAN_ROUND` are stop-and-return conditions. Do not substitute a scientific command. If a live lease still exists at a human stop, consume the current token with `release-lease --reason <reason>` before returning. A scientific Node gets at most one deterministic retry of the same Node ID; a second failure remains explicit and the Round may continue with a partial outcome.

Runtime refuses Round finalization until the formal Interpretation JSON, Markdown, HTML, quality report, and Full Audit all pass. It never starts a new Round. Dispatcher alone performs human-authorized Round control.

Interpretation input is a balanced, bounded set of Result Cards. Runtime records omitted cards as unreviewed instead of asking the Interpreter to load an unbounded history.

All execution scratch and caches stay under the Skill `env/` or Run `runtime/scratch/`; scratch is not a scientific artifact. Scientific Skills keep their general-use interfaces, while Runtime validates and promotes only canonical minimal outputs.

For read-only navigation use `query`; for an abnormal Node use human-only `cs-conductor-node-review`. Do not repair JSON manually.
