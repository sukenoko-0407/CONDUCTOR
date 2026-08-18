---
name: cs-conductor-result-concierge
description: Explain, trace, compare, or re-visualize existing results from an explicit CONDUCTOR 0.1.2 Run without changing Runtime or scientific artifacts.
allowed-tools: Read, Write, Glob, Grep, Bash
---

# CONDUCTOR Result Concierge

Use only on a human request while the Run is `AWAITING_HUMAN_REVIEW`, `CLOSED`, or has no active Round. The sole writable area is `<run_root>/concierge/REQ######/`; all other Run files are hash-protected and read-only. Concierge output is not a DAG Node and cannot affect future planning unless a human attaches its proposal to a later Round request.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare --run-root /path/to/run \
  --request "INS000123の根拠をGlobalとClusterで比較して説明する" --focus-id INS000123 --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" add-source --request-dir /path/to/run/concierge/REQ000001 --source analysis/N000120/result.json
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" finalize --request-dir /path/to/run/concierge/REQ000001
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" verify --request-dir /path/to/run/concierge/REQ000001
```

It may extract, filter, compare, explain provenance, and redraw existing values. It must not calculate new Descriptions, Clusters, Operators, models, Insights, or Node states. If new analysis would help, write an optional `next_round_prompt.md` for human review.

Answers must explain method, representation, subject scope, sample count, observation, interpretation, and limitation. Never label a Cluster result as Global or claim causality from correlation.
