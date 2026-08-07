---
name: cs-conductor-orchestrator
description: Manage a comprehensive multi-Round CONDUCTOR SAR run through a resumable execution DAG. Use for Run/Round creation, mandatory basic computation, initial global/local exploration, balanced random exploration, Question-led deep dives, partial human requests, State updates, and handoff between Claude Code sessions.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# CONDUCTOR Orchestrator

## Operating model

A **Run** is one input CSV × one endpoint × one `higher_is_better` direction. A Run normally contains multiple **Rounds**. One Round is the cycle from a human request through Orchestration, execution, Interpretation, and a checkpoint for the next human request.

Use the execution DAG as the authoritative control plane. Capability IDs (`D001`, `C002`, `A006`, `I001`) name methods. Run-global execution Node IDs (`ND####`, `NG####`, `NO####`, `NI####`) name executions. Scientific entity IDs (`G######`, `E######`, `F####`, `H####`, `Q####`, `REL####`, `REQ####`) remain continuous across Rounds.

Before changing a Run, read completely:

1. `CONDUCTOR_modules/docs/CONDUCTOR_v4_policy.md`
2. `CONDUCTOR_modules/docs/CONDUCTOR_v4_design_spec.md`
3. `CONDUCTOR_modules/catalog/catalog.json`
4. `CONDUCTOR_modules/catalog/analysis_profile.json`, the Run snapshot of that profile, and the target `state.json`
5. `summaries/state_summary.json` and, for Round 2+, the preceding `rounds/RND####/next_round_brief.json`

Before Interpretation, also read `CONDUCTOR_modules/docs/CONDUCTOR_v4_interpretation_policy.md`.

Never write analysis results under `CONDUCTOR_modules/`. That directory is a replaceable read-only package. Results and mutable State belong under the Run root.

## Phase order

Unless a human explicitly waives a gap, follow this order:

1. `basic_compute`: every Catalog Description plus every direct-structure Grouping and every configured vector-Clustering method over the representative Description panel.
2. One human decision for the complete high-cost basic bundle. Do not request separate approval for each member.
3. `initial_global`: every applicable Operator role over the common Description master panel or its required input type.
4. `initial_local`: for every succeeded Grouping node, select a diverse representative subset of Groups and run every applicable local Operator role. Do not hard-wire one Operator to one Description/Grouping.
5. Interpretation and checkpoint.
6. Later Rounds: balanced seeded `additional_exploration`, Question-led `deep_dive`, human-directed analysis, and another Interpretation.

The initial pass deliberately incurs meaningful compute cost. Its purpose is to discover hints; it must not collapse to a narrow cheap probe. MCS is part of basic computation. The one-time high-cost bundle decision covers the configured high-cost Descriptions and does not make MCS optional.

## Run and Round control

Use the launcher so `PIXI_CACHE_*`, `UV_CACHE_DIR`, and all runtime caches remain inside this Skill's `env/` directory:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state init \
  --input compounds.csv --endpoint pIC50 --higher-is-better \
  --project project_name --parallel-limit 8 \
  --request "Round 1: comprehensive initial analysis"
```

For a later session, the human can provide only the State path, next Round ID, resource envelope, and optional scientific emphasis:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state round-start \
  --state /path/to/state.json --round-id RND0002 \
  --request "Previous resultsを引き継ぎ、Q0012を重視する" \
  --walltime-minutes 240 --max-additional-nodes 40 --interpretation-iterations 3
```

Pause or checkpoint only after no Node is `running`:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state round-end \
  --state /path/to/state.json --round-id RND0001 \
  --status checkpoint --reason "Human review checkpoint"
```

`paused` preserves the same active Round for resume. `checkpoint` or `completed` closes it and advances the expected Round number.

## Planning commands

```bash
# Mandatory basic computation
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-basic --state /path/to/state.json

# One human decision for the full high-cost basic bundle
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state approve-basic-bundle \
  --state /path/to/state.json --approve --rationale "Approved once for basic computation"

# Initial breadth
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-initial-global --state /path/to/state.json
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-initial-local --state /path/to/state.json

# Reproducible, balanced, non-repeating additional exploration
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-additional \
  --state /path/to/state.json --count 30 --seed 61453

# Human-directed partial analysis
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state add \
  --state /path/to/state.json --capability-id A006 --depends-on ND0002,NG0011 \
  --parameters-json '{"scope_mode":"within-group","target_group":"G000042"}' \
  --reason "Requested local landscape comparison"
```

`--override-gate` is an explicit human waiver, never an autonomous shortcut. Preserve the reason in the conversation and State history.

## Execution protocol

1. Call `state runnable`; select no more than the human `parallel_limit`.
2. Call `state start --node-id ...` before launching a specialist Skill.
3. Invoke the exact Skill in the Node with `--conductor`, State-bound `project`, `run_id`, `node_id`, `output_dir`, inputs, provenance, and all Node parameters. Never synthesize IDs or replace a bound artifact with a convenient file.
4. For Operator nodes also pass the reserved `round_id` and `evidence_id`. The expected outputs are numeric CSV, `evidence.json`, `evidence_digest.json`, and `operator_report.html`.
5. Record `execution_event.json` with `state record`. State validates identity, planned configuration, artifacts, Group remapping, Evidence registration, and Interpretation entities.
6. If no event can be produced, use `state mark-terminal` with the concrete reason. Never hide failures or retry automatically under a different unrecorded configuration.

General-mode requests are outside this workflow. Do not add `--conductor` unless the user explicitly requested CONDUCTOR use or an active State Node is being executed.

## Group and metric rules

- Direct-structure Grouping consumes the Run compound-ID/SMILES CSV. Vector Clustering consumes exactly one succeeded Description artifact.
- State remaps Skill-local group labels to immutable Run-global `G######` IDs and records membership as Boolean compound × Group CSV shards plus `group_registry.csv` provenance.
- Never treat identical vectors for different compound IDs as an error.
- Metric follows representation semantics. Binary fingerprints require Tanimoto; USR-like shape vectors use Manhattan; sparse counts/latent embeddings generally use cosine; ordinary dense continuous descriptors generally use Euclidean. Preserve the resolved metric in Evidence.
- MCS pair sampling is seeded random sampling and its limits are defined by the Skill/Profile, not by input row order.

## Interpretation, salience, and Questions

Create an Interpretation Node after the selected branch is terminal:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state add-interpretation \
  --state /path/to/state.json --phase additional_exploration \
  --reason "Integrate this Round with prior priority Evidence" \
  --focus "Compare global versus local landscape smoothness"
```

Without `--evidence-node`, State selects current-Round succeeded Evidence plus priority/pinned Evidence and Evidence attached to active Questions. This avoids rereading every routine result each Round. Use `--evidence-node` for an explicit set. A later Round always receives a new `NI####`; within one Round, a distinct `--focus` creates a distinct perspective while an identical request remains idempotent.

State preallocates the `NI####` Node and ID reservation. Invoke the Interpretation Skill with the exact `round_id` and `id_reservation`. After the dedicated Interpreter finalizes JSON/Markdown/HTML, record its event. Existing Finding/Hypothesis/Question/Relation IDs may be revised with an incremented `revision`; new entities must use reserved IDs.

Classify Evidence without deleting it:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state salience-set \
  --state /path/to/state.json --evidence-id E000123 \
  --attention-class priority --scientific-role contradiction \
  --human-pin --reason "Independent representation contradicts the local trend"
```

Questions are optional future branches. `allow` permits deep-dive planning, `defer` pauses it, and `skip` is a hard gate but not a claim that the Question was scientifically answered.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state question-decision \
  --state /path/to/state.json --question-id Q0012 --decision skip \
  --rationale "Not relevant to the current program"

python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-deep-dive \
  --state /path/to/state.json --question-id Q0013
```

Deep dives are comparison bundles: same Group across other Operators, sibling/global comparators, and the same Group represented by other Descriptions where applicable. Every notable candidate requires a falsification or control path.

## Fast resume and audit

- Prefer `summaries/state_summary.json`, coverage index, Evidence digests, salience view, Question ledger, and Round brief before full artifacts.
- Full scientific outputs are never deleted. `routine` means “do not spend context now,” not “irrelevant forever.” Salience is append-only and can be revised.
- `state resume` verifies package snapshots and input. A package difference changes `package_change_gate` to `approval_required`; planning and execution remain blocked until the human reviews it.
- After explicit human approval, run `state approve-package-change --approve --rationale "..."`. Rejection uses `--reject`; the safest alternative is a new Run. The accepted package receives a new immutable snapshot and audit-history entry.
- `state rebuild-indices` is for explicit repair from recorded artifacts.
- Use `cs-conductor-state-report` only when a human explicitly supplies a State path and requests visualization. It is read-only and is not a DAG Node.
- Never standardize molecules or silently alter endpoint values. Duplicate compound IDs are hard errors; invalid SMILES remain row-level warnings in the relevant Skill.
