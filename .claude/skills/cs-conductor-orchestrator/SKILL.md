---
name: cs-conductor-orchestrator
description: Initialize, plan, resume, and update CONDUCTOR v4 SAR analysis runs as execution DAGs using the human-curated capability Catalog, Markdown Policy, run State, and execution events. Use when Claude Code must autonomously choose broad shallow analyses, identify local deep-dive opportunities, request human approval for expensive work, or coordinate Description, Grouping, Operator, and Interpretation Skills.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# CONDUCTOR v4 Orchestrator

## Required context

1. Read `docs/CONDUCTOR_v4_policy.md` completely before planning or changing a run.
2. Read `catalog/catalog.json`; use only listed capabilities.
3. Read the target run's `state.json` before choosing a next action.
4. Treat `catalog/included_skills.json` as human-managed. Never add a Skill to it autonomously.

## Workflow

1. Build or verify the Catalog with `scripts/build_catalog.py`.
2. Initialize one run per endpoint with a required `higher_is_better` direction and human-specified parallel limit.
3. Create the mandatory `representative-family-wide-v1` plan from capabilities marked `default_wide_shallow`. Preserve every declared Description, Grouping, and Operator axis, including the 3D Description axis.
4. Expand each dependent capability only across its explicit `wide_shallow_sources`; add dependency edges and `input_bindings` before execution. Never bind a downstream node to the first Description or Grouping merely because it was created first.
   - For `grouping_kind=direct_structure`, pass the run SMILES input and never substitute a Description artifact.
   - For `grouping_kind=description_vector`, pass exactly the artifact from `input_bindings.description`; never pass raw SMILES or let the Clustering Skill generate a fingerprint internally.
5. If a Catalog capability exposes `variants`, choose one explicitly. Keep the same capability ID, create a separate node for each compared variant, and store CLI destinations in the node's `parameters` using `state_manager.py add --parameters-json`. Do not represent a variant as an unplanned argument change.
6. Use `scripts/state_manager.py runnable` to find nodes whose dependencies and approval requirements are satisfied.
7. Mark each selected node `running` with `state_manager.py start`; this enforces the human-specified parallel limit.
8. Invoke the Project Skill with `--conductor`, the State project, the same run ID, the reserved node ID, and the exact node `parameters`. The planned parameters already include node-specific `output_dir` and resolved upstream artifact arguments derived from `input_bindings`. Never omit or replace these CONDUCTOR context arguments.
9. Record each schema-valid `execution_event.json` through `state_manager.py record`. State rejects events whose `configuration` does not match the planned parameter subset. If execution terminates without an event, use `state_manager.py fail` with the concrete error; a failed node is not automatically retried.
10. Complete a coverage audit with `state status`. Do not stop the initial pass because early results lack signal. Replace a failed/inapplicable axis where practical, or preserve its concrete skip rationale. Only then inspect evidence, contradictions, warnings, and representation independence and add focused nodes that can resolve a concrete uncertainty.
11. Before a high/very-high cost node, or a normally medium-cost node made expensive by dataset scale, explain purpose, target, expected information, resources, and alternative; add it with `--require-approval` when necessary, wait for explicit human approval, then record it. The exception is a Catalog capability explicitly marked `approval_policy=preauthorized_initial`.
    C002 MCS is the mandatory central direct-structure axis and carries that policy. Plan it in every initial profile and start it as soon as State reports it runnable; do not request run-specific approval or convert it into an optional deep dive.
12. Run Interpretation only after every initial node is terminal and after passing both positive and contradictory evidence, failures, coverage gaps, and unexecuted relevant options. State enforces this gate.

## Environment

Use `scripts/launch.py`; do not invoke `pixi` directly. It prefers `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`, then falls back to `pixi` on PATH. It resolves absolute paths from the Orchestrator Skill directory and forces `PIXI_HOME`, all `PIXI_CACHE_*`, `UV_CACHE_DIR`, XDG, temporary, and runtime caches into `<skill>/env/` before creating or reusing `<skill>/env/.pixi/envs/default/`, independent of the caller's working directory.

## Project Skill invocation contract

- Every Skill launched as a State DAG node is CONDUCTOR mode. Pass `--conductor --project <state.project> --run-id <state.run_id> --node-id <reserved-node-id>` together.
- Use the exact node ID returned or reserved through State management; do not synthesize a replacement after planning.
- A user request to run an individual computation without explicit CONDUCTOR intent is outside this Orchestrator workflow and must remain that Skill's general mode.
- Do not infer CONDUCTOR mode only from repository location, compatible artifacts, or an output path. The active Orchestrator run and State node are the explicit context.
- Require the Project Skill's `execution_event.json`; reject a successful-looking output that cannot be associated with the expected project, run, node, and capability.

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

Reserve a runnable node before launching it:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state start \
  --state path/to/state.json --node-id D001:001
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

Record an execution failure that produced no event:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state fail \
  --state path/to/state.json --node-id D001:001 --reason "concrete error message"
```

## Planning principles

- Treat the initial breadth profile as a required hint-discovery pass, not as an optional low-cost sample.
- Preserve all Catalog-declared representative axes; 3D Description is mandatory in the initial profile.
- Treat C002 MCS as a mandatory, preauthorized initial Grouping axis even though its cost class is `high`.
- Prefer representation-family diversity over redundant variants during the first pass.
- Preserve the boundary between direct SMILES Grouping and Description-vector Clustering; never recreate the retired SMILES-to-fingerprint clustering wrappers inside the workflow.
- Use a non-default variant only when it can answer a stated question; represent every compared variant as a separate State node.
- Do not make every possible Grouping × evaluation representation combination.
- Do not claim absence of a useful signal until `wide_shallow_coverage` has been audited across Description, Grouping, and Operator.
- Prefer nodes that can change the next decision.
- Separate execution DAG, group relation graph, and evidence dependency graph.
- Never infer approval from silence. `preauthorized_initial` is a human-defined Catalog policy, not inferred approval.
- Never modify molecular structures or endpoint units.
