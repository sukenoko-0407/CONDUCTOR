---
name: cs-conductor-result-concierge
description: Explain, trace, compare, or re-visualize existing results from an explicit CONDUCTOR 0.1.5 Run without changing Runtime or scientific artifacts.
allowed-tools: Read, Write, Glob, Grep, Bash
---

# CONDUCTOR Result Concierge

Use only on a human request while the Run is `AWAITING_HUMAN_REVIEW`, `CLOSED`, or has no active Round. The sole writable area is `<run_root>/concierge/REQ######/`; all other Run files are hash-protected and read-only. Concierge output is not a DAG Node and cannot affect future planning unless a human attaches its proposal to a later Round request.

Flexible request-specific work is explicitly allowed. You may write and execute temporary Python helpers below `<request_dir>/scratch/` to filter existing tables, calculate request-specific descriptive statistics, compare already-produced results, or create explanatory figures. Prefer the deterministic `run-helper` command so Python, working directory, caches, stdout/stderr, and OS temporary paths remain request-local. This work is explanatory post-processing, not a new CONDUCTOR Description, Clustering, Operator, model Node, or Insight.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare --run-root /path/to/run \
  --request "INS000123の根拠をGlobalとClusterで比較して説明する" --focus-id INS000123 --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" add-source --request-dir /path/to/run/concierge/REQ000001 --source analysis/N000120/result.json
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" run-helper --request-dir /path/to/run/concierge/REQ000001 --script /path/to/run/concierge/REQ000001/scratch/check.py -- --option value
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" finalize --request-dir /path/to/run/concierge/REQ000001
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" verify --request-dir /path/to/run/concierge/REQ000001
```

It may extract, filter, compare, calculate descriptive summaries from frozen values, explain provenance, and redraw existing values. Do not default to `/tmp`; use request-local `scratch/`. An external executable that cannot honor redirected temporary directories may use OS temp exceptionally, but must not write into Runtime or canonical artifact paths and must record the exception in the response limitations. It must not calculate new Descriptions, Clusters, Operators, predictive models, Insights, or Node states. If new CONDUCTOR analysis would help, write an optional `next_round_prompt.md` for human review.

Answers must explain method, representation, subject scope, sample count, observation, interpretation, and limitation. Never label a Cluster result as Global or claim causality from correlation.
