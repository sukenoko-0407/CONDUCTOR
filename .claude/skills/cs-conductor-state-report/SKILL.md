---
name: cs-conductor-state-report
description: Render an explicitly supplied CONDUCTOR 0.1.8 Run Root as a read-only human DAG report. Use only on explicit human request and never as an analysis Node.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR State Report

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --run-root /path/to/run --explicit-request
```

The Skill reads `conductor_control.json` and `runtime/dag_snapshot.json`, verifies source hashes before and after rendering, and writes a new `<run_root>/state/<UTC timestamp>/` directory containing `state_report.html`, `state_dag.svg`, `state_nodes.csv`, and `state_summary.json`.

Circular Nodes and directed edges show the derived DAG. Fill color distinguishes the five Node states; report panels show current Round, required action, counts, runnable work, and artifact links. It never changes Runtime, scientific results, or Round state.
