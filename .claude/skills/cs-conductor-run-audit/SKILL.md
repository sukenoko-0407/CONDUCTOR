---
name: cs-conductor-run-audit
description: Run a read-only Quick or Full audit of an explicitly supplied CONDUCTOR 0.1.2 Run Root. Full mode is a mandatory Round finalization gate.
allowed-tools: Read, Bash
---

# CONDUCTOR Run Audit

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --run-root /path/to/run --mode quick
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --run-root /path/to/run --mode full
```

Quick mode validates Control, five-state DAG, lease, IDs, Event Ledger chain, revisions, transaction state, dependencies, attempts, Cluster registry, and parallel limit. Full mode additionally checks result files and hashes, Interpretation report integrity, and the closure contract. Reports are written to `<run_root>/audit/<timestamp>/` and never become scientific Nodes.

Do not proceed past a failing audit. Repair only through Runtime or Node Review; never edit State files directly.
