---
name: cs-conductor-orchestrator
description: Initialize, plan, resume, and update CONDUCTOR v4 SAR analysis runs as execution DAGs using the human-curated capability Catalog, Markdown Policy, run State, and execution events. Use when Claude Code must autonomously choose broad shallow analyses, identify local deep-dive opportunities, request human approval for expensive work, or coordinate Description, Grouping, Operator, and Interpretation Skills.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# CONDUCTOR v4 Orchestrator

## Required context

1. Read `CONDUCTOR_modules/docs/CONDUCTOR_v4_policy.md` completely before planning or changing a run.
2. Read `CONDUCTOR_modules/catalog/catalog.json`; use only listed capabilities.
3. Read the target run's `state.json` before choosing a next action.
4. Treat `CONDUCTOR_modules/catalog/included_skills.json` as human-managed. Never add a Skill to it autonomously.
5. Use `state status` for coarse progress. Use `state groups` and the external Group index only when detailed membership/provenance is needed.
6. When resuming, read `<run-root>/session_handoff.md` if it exists, but verify it against current State, latest Interpretation, and referenced artifacts. State and artifacts remain authoritative.

## Workflow

1. Verify the Catalog read-only with `scripts/build_catalog.py --check`. Never rebuild Catalog or write under `CONDUCTOR_modules/` during an analysis run. `scripts/build_catalog.py --write` is an explicit, human-directed package-maintenance operation only.
2. Initialize one run per endpoint with a required `higher_is_better` direction and human-specified parallel limit.
3. Create the mandatory `representative-family-wide-v1` plan from capabilities marked `default_wide_shallow`. Preserve every declared Description, Grouping, and Operator axis, including the 3D Description axis.
4. Expand each dependent capability only across its explicit `wide_shallow_sources`; add dependency edges and `input_bindings` before execution. Never bind a downstream node to the first Description or Grouping merely because it was created first.
   Apply every Catalog-declared `wide_shallow_parameter_overrides` entry for the bound source. For A006, preserve D002=`tanimoto`, D013=`manhattan`, and D017=`tanimoto`; never replace them with one global metric.
   - For `grouping_kind=direct_structure`, pass the run's compound-ID/SMILES CSV and never substitute a Description artifact or inline SMILES.
   - For `grouping_kind=description_vector`, pass exactly the artifact from `input_bindings.description`; never pass raw SMILES or let the Clustering Skill generate a fingerprint internally.
5. If a Catalog capability exposes `variants`, choose one explicitly. Keep the same capability ID, create a separate node for each compared variant, and store CLI destinations in the node's `parameters` using `state_manager.py add --parameters-json`. Do not represent a variant as an unplanned argument change.
6. Use `scripts/state_manager.py runnable` to find nodes whose dependencies and approval requirements are satisfied.
7. Mark each selected node `running` with `state_manager.py start`; this enforces the human-specified parallel limit.
8. Invoke the Project Skill with `--conductor`, the State project, the same run ID, the reserved node ID, and the exact node `parameters`. The planned parameters already include node-specific `output_dir` and resolved upstream artifact arguments derived from `input_bindings`. Never omit or replace these CONDUCTOR context arguments.
   A list-valued `input` means repeat `--input` once per artifact; this is used by C012 meta-overlap.
9. Record each schema-valid `execution_event.json` through `state_manager.py record`. State rejects events whose `configuration` does not match the planned parameter subset. If execution terminates without an event, use `state_manager.py fail` with the concrete error; a failed node is not automatically retried.
10. Complete a coverage audit with `state status`. Do not stop the initial pass because early results lack signal. Replace a failed/inapplicable axis where practical, or preserve its concrete skip rationale. Then invoke the dedicated `cs-conductor-interpreter` Agent; do not duplicate its semantic evidence comparison inside Orchestration.
11. Before a high/very-high cost node, or a normally medium-cost node made expensive by dataset scale, explain purpose, target, expected information, resources, and alternative; add it with `--require-approval` when necessary, wait for explicit human approval, then record it. The exception is a Catalog capability explicitly marked `approval_policy=preauthorized_initial`.
    C002 MCS is the mandatory central direct-structure axis and carries that policy. Plan it in every initial profile and start it as soon as State reports it runnable; do not request run-specific approval or convert it into an optional deep dive.
12. Before iterative Interpretation exploration, obtain a human budget and record it with `state configure-exploration`. Run Interpretation only after every initial node is terminal. Pass State, positive and negative evidence, failures, coverage gaps, prior Interpretation, and unexecuted relevant options. State enforces the initial gate.
13. Treat every Interpretation node as read-only and terminal. The Interpreter may write an `exploration_plan.json` but may not execute it. Validate and register that plan with `state register-exploration`; this rejects repeated analysis signatures, duplicate or dangling IDs, requests outside Orchestrator bounds, over-budget batches, missing falsification requests, and dependencies on terminal Interpretation nodes. For an explicit Plan `scope`, registration validates compound IDs against the run input and materializes a content-addressed membership CSV under `interpretation/scopes/`.
14. Execute registered low-cost nodes within the delegated budget and normal parallel limit. Request human approval for high-cost or out-of-budget work. After the branch is terminal, add a new I001 node over the new and relevant prior evidence. If findings remain too numerous for humans, prefer further discriminating Description–Grouping–Operator–Interpretation branches over discarding findings.
15. Treat Group IDs as immutable identities. Inspect `grouping/group_index/group_registry.csv` and only the needed columns in `Cpd_Group_matrix_*.csv`. Mark a low-value explored region with `state discard-group`; retain its membership and history for audit.
16. At each human checkpoint or completed Interpretation round, create or update `<run-root>/session_handoff.md` using `CONDUCTOR_modules/docs/prompt/CONDUCTOR_session_handoff_template.md`. Record the State timestamp, cumulative budget use, human direction, positive and negative findings, unresolved contradictions, pending approvals, and artifact paths. Treat the handoff as a concise navigation index, not a replacement for State or evidence.
17. When a human requests any partial Description, Grouping, Operator, or Interpretation within an existing CONDUCTOR run, never invoke the specialist Skill outside State. Resolve the requested Catalog capability and succeeded upstream nodes, then register it with `state add --human-request --reason ...`. State allocates a run-local execution node ID (`D###`, `G###`, `O###`, or `I###`), binds artifacts, and records the instruction. Start, execute, and record the node normally. For a later Interpretation round, use capability `I001`, depend on every selected Evidence-producing Operator node, and pass the latest succeeded Interpretation through `--previous-interpretation-node`; this is read-only lineage, not an execution dependency.

## Environment

Use `scripts/launch.py`; do not invoke `pixi` directly. It prefers `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`, then falls back to `pixi` on PATH. It resolves absolute paths from the Orchestrator Skill directory and forces `PIXI_HOME`, all `PIXI_CACHE_*`, `UV_CACHE_DIR`, XDG, temporary, and runtime caches into `<skill>/env/` before creating or reusing `<skill>/env/.pixi/envs/default/`, independent of the caller's working directory.

## Project Skill invocation contract

- Every Skill launched as a State DAG node is CONDUCTOR mode. Pass `--conductor --project <state.project> --run-id <state.run_id> --node-id <reserved-node-id>` together.
- Use the exact node ID returned or reserved through State management; do not synthesize a replacement after planning.
- A user request to run an individual computation without explicit CONDUCTOR intent is outside this Orchestrator workflow and must remain that Skill's general mode.
- Do not infer CONDUCTOR mode only from repository location, compatible artifacts, or an output path. The active Orchestrator run and State node are the explicit context.
- Require the Project Skill's `execution_event.json`; reject a successful-looking output that cannot be associated with the expected project, run, node, and capability.
- Keep Capability ID and Node ID distinct. For example, capability `I001` may execute as nodes `I001`, `I002`, and `I003`; the latter are Interpretation rounds, not different Skills.
- Repeat list-valued `evidence`, `input`, and `previous_interpretation` parameters as repeated CLI options when invoking a specialist Skill.

## Commands

Build Catalog:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" catalog
```

Initialize:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state init \
  --input compounds.csv --endpoint pIC50 --higher-is-better \
  --project project_name --parallel-limit 8
```

Plan broad-shallow nodes:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state plan-wide --state path/to/state.json
```

Inspect runnable nodes:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state runnable --state path/to/state.json
```

Inspect detailed Group provenance only when needed:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state groups \
  --state path/to/state.json --status active
```

Stop automatically prioritizing a well-explored low-value Group without deleting it:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state discard-group \
  --state path/to/state.json --group-id G_G006_4A91C2D0870FB6E3 \
  --reason "Independent representations did not support this region"
```

Reserve a runnable node before launching it:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state start \
  --state path/to/state.json --node-id D001
```

Resume and verify the input hash:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state resume --state path/to/state.json
```

Record an event:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state record \
  --state path/to/state.json --event path/to/execution_event.json
```

Add a parameterized variant node (JSON keys use the Python/CLI destination name with underscores):

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state add \
  --state path/to/state.json --capability-id D002 \
  --parameters-json '{"include_chirality":true}' \
  --reason "Assess whether stereochemical encoding resolves the local inconsistency"
```

Register a human-requested partial analysis without bypassing the DAG:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state add \
  --state path/to/state.json --capability-id A006 --depends-on D002 \
  --human-request --reason "Re-evaluate the requested region in the Morgan landscape"
```

Register a second Interpretation round. `I001` after `--capability-id` is the Skill capability; the returned execution node is `I002` when one Interpretation node already exists:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state add \
  --state path/to/state.json --capability-id I001 \
  --depends-on O001,O004,O017 --previous-interpretation-node I001 \
  --human-request --reason "Reinterpret the selected Evidence using the user's new question"
```

Configure the human-approved Interpretation exploration envelope:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state configure-exploration \
  --state path/to/state.json --max-iterations 5 \
  --max-additional-nodes 40 --walltime-minutes 240 --seed 61453
```

Register a schema-valid plan produced by the Interpretation Agent:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state register-exploration \
  --state path/to/state.json --plan path/to/exploration_plan.json
```

Record an execution failure that produced no event:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state fail \
  --state path/to/state.json --node-id D001 --reason "concrete error message"
```

## Planning principles

- Treat the initial breadth profile as a required hint-discovery pass, not as an optional low-cost sample.
- Preserve all Catalog-declared representative axes; 3D Description is mandatory in the initial profile.
- Treat C002 MCS as a mandatory, preauthorized initial Grouping axis even though its cost class is `high`.
- Interpret A006 as a landscape Operator: examine the SALI center and upper tail for overall smoothness/roughness, then investigate top pairs as localized cliffs. Seek structural, pharmacophore, Grouping, assay-context, and independent-representation explanations; do not treat a high score alone as mechanism.
- Do not compare raw SALI values across different metric scales. Compare ranks, local property deltas, neighborhood consistency, and whether the same cliff recurs in independent representations.
- Prefer representation-family diversity over redundant variants during the first pass.
- Preserve the boundary between direct SMILES Grouping and Description-vector Clustering; never recreate the retired SMILES-to-fingerprint clustering wrappers inside the workflow.
- Use a non-default variant only when it can answer a stated question; represent every compared variant as a separate State node.
- Do not make every possible Grouping × evaluation representation combination.
- Do not claim absence of a useful signal until `wide_shallow_coverage` has been audited across Description, Grouping, and Operator.
- Prefer nodes that can change the next decision.
- Separate execution DAG, group relation graph, and evidence dependency graph.
- Read `CONDUCTOR_modules/docs/CONDUCTOR_v4_interpretation_policy.md` before registering Interpretation exploration. Interpretation proposes scientific questions; Orchestration maps them to Catalog capabilities, enforces budget and approval, and never rewrites them into a preferred coherent story.
- Accept multiple-testing false positives as discovery candidates, but preserve trial history and distinguish Discovery from Validation. Every registered discovery must have a falsification request.
- Prioritize adequately sized Groups, flag Groups above 30% and especially 50% of the dataset as progressively less local, and retain small structurally cohesive or clear-MCS Groups as candidates.
- Never repeat a Description, Grouping, or Operator analysis signature already present in the execution DAG or exploration ledger. A new Interpretation round may revisit the same fixed Evidence because semantic comparison is its purpose; give it a new `I###` node and retain prior Interpretation lineage.
- Never infer approval from silence. `preauthorized_initial` is a human-defined Catalog policy, not inferred approval.
- Never modify molecular structures or endpoint units.
