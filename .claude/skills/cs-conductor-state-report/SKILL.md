---
name: cs-conductor-state-report
description: Render an explicitly supplied CONDUCTOR state.json as a read-only human report with a circular-node execution DAG, status-aware edges, progress summaries, and artifact links. Use only when a human explicitly requests State visualization and provides the State JSON path; never invoke automatically during orchestration or register it as a DAG analysis node.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# CONDUCTOR State report

## Required workflow

1. Confirm that the human explicitly requested State visualization and supplied the target `state.json` path.
2. Do not infer a State path from the current repository, recent run, or `results/CONDUCTOR/` contents.
3. Run `scripts/launch.py` with both `--state` and `--explicit-request`.
4. Verify that the source State hash reported in `state_summary.json` matches the requested file.
5. Return the timestamped `state_report.html` path. Do not modify State or register this report as a State node.

## Command

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" \
  --state /path/to/run/state.json --explicit-request
```

The output location is fixed to `<state.json directory>/state/<UTC timestamp>/`. Each invocation creates a new timestamp directory and writes `state_report.html`, `state_dag.svg`, `state_nodes.csv`, and `state_summary.json`.

## Report semantics

- Circle fill encodes Node status; a second ring denotes pending human approval.
- Solid completed edges connect succeeded work; dashed or muted edges distinguish planned, blocked, or lineage relationships.
- The SVG shows the execution graph only. `previous_interpretation_nodes` are added as dotted read-only lineage edges and are not presented as execution dependencies.
- The HTML contains coarse progress, runnable Nodes, stage/status counts, warnings, and detailed Node metadata with artifact links.

## Environment

Use `scripts/launch.py`; do not invoke Pixi directly. It prefers `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`, then falls back to `pixi` on PATH. It keeps `PIXI_HOME`, every `PIXI_CACHE_*`, `UV_CACHE_DIR`, XDG, temporary, and runtime caches under this Skill's `env/` directory, independent of the caller's working directory.

## Boundaries

- Require `--explicit-request`; reject unattended or implicit invocation.
- Treat the supplied State as read-only and verify its SHA-256 before and after rendering.
- Never write into `CONDUCTOR_modules/`.
- Never change Node status, approval, Group data, exploration budget, history, or handoff.
- Do not claim that report generation advances or completes the scientific analysis.
