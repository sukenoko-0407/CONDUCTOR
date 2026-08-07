---
name: cs-analysis-interpret-evidence
description: Prepare and render policy-guided SAR Interpretation across Operator Evidence, Groups, representations, scopes, and Rounds. Use with the dedicated Interpreter Agent to create agent-friendly JSON and human Markdown/HTML, or in standalone review mode. CONDUCTOR mode requires a State-allocated Interpretation Node and ID reservation.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Evidence Interpretation

## Purpose

This Skill is the deterministic preparation and rendering layer for Interpretation. It indexes selected Operator Evidence, proposes efficient comparison candidates, creates a clearly labelled draft, and renders the final human report after the dedicated Interpreter Agent completes semantic review.

It does not execute Description, Grouping, or Operator computations. It does not decide resource use, mutate State, or force one coherent SAR story.

Read `references/interpretation_policy.md` completely before use. In a packaged Project, `CONDUCTOR_modules/docs/CONDUCTOR_v4_interpretation_policy.md` is the normative source.

## Mode selection

General mode is the default. Do not add `--conductor` merely because inputs came from a CONDUCTOR Run.

CONDUCTOR mode is valid only when Orchestration supplies all of:

- `--project`
- `--run-id`
- State-allocated `--node-id` (`NI####`)
- current `--round-id` (`RND####`)
- `--state`
- State-generated `--id-reservation`
- optional State-recorded `--interpretation-focus`

If any identity is absent, return to Orchestration instead of inventing it. A human request to reinterpret an existing Run must create a new Interpretation Node through `state add-interpretation`; do not overwrite an earlier `NI####` directory.

The core identity sequence is `--project PROJECT --run-id RUN_ID --node-id NODE_ID`; CONDUCTOR Interpretation additionally requires Round and reservation identity.

## Inputs

- Repeated `--evidence path/to/evidence.json`, or repeated `--evidence-dir`.
- In CONDUCTOR mode, omitting explicit Evidence selects from State: current-Round succeeded Evidence first, then priority/pinned Evidence and Evidence attached to active Questions, capped by `--max-full-evidence`.
- `--previous-interpretation` may be repeated for read-only semantic lineage.
- `--stage discovery|validation|mixed` distinguishes exploration from confirmation.
- `--seed` controls only reproducible candidate ordering; it does not compute scientific results.

The Skill reads compact Evidence digests for navigation and full Evidence/CSV/Operator HTML for claims retained in the report.

## Algorithm-specific options

`--stage`, `--seed`, `--max-full-evidence`, repeated Evidence paths, and prior Interpretation paths control the review context only. They never launch or replace an Operator calculation.

## CONDUCTOR draft command

Use the exact paths and identities stored in the Node:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" \
  --state /run/state.json \
  --conductor --project PROJECT --run-id RUN_ID \
  --node-id NI0003 --round-id RND0002 \
  --interpretation-focus "Compare global versus local landscape smoothness" \
  --id-reservation /run/interpretation/NI0003/id_reservation.json \
  --output-dir /run/interpretation/NI0003
```

The runner writes:

- `interpretation.json`: agent-friendly draft and final source of truth
- `interpretation_context.json`: provenance, State summary, candidate relations, Group candidates, and prior context
- `interpretation.md` and `interpretation.html`: initially explicit draft previews
- `question_updates.json`, `relation_updates.json`, `analysis_requests.json`, `triage_updates.json`
- `execution_event.json` in CONDUCTOR mode

The State-selected output directory is the `<node-id-safe>` location for the reserved `NI####` execution.

## Dedicated Agent workflow

1. Read Policy, context, selected Evidence, corresponding numeric outputs, and relevant Operator HTML reports.
2. Compare global versus local, sibling Groups, the same Group in other Descriptions, different Operators in the same scope, and genuinely independent representations.
3. Distinguish expected agreement from independent support. Shared compounds, pairs, metrics, preprocessing, Grouping, or upstream nodes lower independence.
4. Preserve contradictions, exceptions, negative results, failures, and incomparable analyses.
5. For every retained Finding, write the scientific question, exact analysis context, numeric observation, interpretation, why it matters, limitations, and Evidence links. Remove mere execution notices from the main body.
6. Create a Hypothesis only for a testable claim. It is valid to create none.
7. Create Questions as optional future branches. `deep_dive_potential` is advisory. Never assume every Question should be pursued.
8. Attach falsification/control/independent replication to every notable discovery, or state explicitly why it is unavailable.
9. Set `agent_review.completed=true`, `reviewed_at`, `review_scope`, and `report_status=agent_interpreted`.
10. Validate and render:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" render \
  --input /run/interpretation/NI0003/interpretation.json
```

The final renderer rejects unreviewed drafts and generic placeholder prose.

## Run-global entity identities

- `F####`: Finding, a concrete interpreted observation
- `H####`: Hypothesis, a testable explanatory claim
- `Q####`: Question, an optional future investigation
- `REL####`: Evidence Relation
- `REQ####`: Analysis Request

New entities use IDs from the current reservation. Existing entities listed in `revisable_ids` may be updated only by retaining the ID and incrementing `revision`; record `origin_round_id` and `last_updated_round_id`. Do not renumber entities in a later Round.

## Human report contract

The Markdown and HTML are interpretation reports, not work logs. Their main body must answer:

- What data, Description, Grouping, Group/scope, metric, and Operator were examined?
- What was observed numerically and directionally?
- What might it mean, and what does it not establish?
- Why is it notable relative to global, sibling, or alternative representations?
- Which counter-evidence, alternative explanation, uncertainty, or sample-size limitation remains?

The HTML uses restrained accessible colors, visible IDs, compact appendices, and links to Operator HTML drill-down reports. It explicitly separates Findings, contradictions, Hypotheses, Questions, and Analysis Requests.

## Interpretation principles

- Multiple-testing false positives are acceptable discovery candidates; label Discovery versus Validation and preserve trial history.
- Prefer adequately sized local Groups. Flag >30% of the dataset as less local and >50% as global-like. Retain small Groups when structural cohesion or clear MCS makes them interpretable.
- SALI compares landscape roughness/smoothness in one representation. Keep endpoint, metric, and preprocessing comparable. Do not compare raw SALI across different metric scales.
- Use indexed joins for Evidence relations; never form an unrestricted Cartesian pair list.
- Interpretation is read-only. It may recommend `REQ####` work, but only Orchestration maps requests to Catalog capabilities and DAG Nodes.

## General mode

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" \
  --evidence-dir path/to/evidence --stage discovery
```

General mode creates ordinary output under `results/interpretation/standalone/`. It neither reads nor updates a CONDUCTOR State unless `--state` is explicitly provided as read-only context.

## Environment

Always use `scripts/launch.py`. It prefers `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`, falls back to Pixi on `PATH`, resolves the manifest independently of working directory, and places `PIXI_CACHE_*`, `UV_CACHE_DIR`, XDG, temporary, and runtime caches under this Skill's `env/` directory.
