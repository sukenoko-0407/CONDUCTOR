---
name: cs-production-run
description: Compile and start a CONDUCTOR 0.2.1 Phase 1-6 production Run from one validated Run Spec. Use hash-bound receipts for a new Database, or minimal guards for an existing compatible Description Database.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR production run

Invoke `scripts/launch.py --run-spec <absolute-path>`.

- `mode=new_database`: use only after 3.2A, 3.2B, and 3.3 pass for the exact Run Spec. Exactly three hash-bound receipts are required.
- `mode=existing_database`: use an already preflighted compatible Program Database. Receipts must be empty; the compiler verifies the Database manifest, resolved config, CPU affinity, locks, and absent Run root immediately before compilation.

The compiler must use `CONDUCTOR_modules/pipeline/production_pipeline.v0.2.1.json`. Do not inspect every downstream Skill contract, search for fixture plans, write ad-hoc Execution Requests, generate launch scripts, or change the DAG. It validates the mode-specific guards, freezes the config and control inputs under the new Run root, then delegates the fixed DAG to `cs-runtime`.

If a mode-specific receipt, machine, scope, CPU limit, Database condition, or absent Run-root condition fails, stop without creating the Run root. Never bypass a failed guard.
