---
name: cs-production-run
description: Compile and start a CONDUCTOR 0.2.1 Phase 1-6 production Run from one validated Run Spec and hash-bound 3.2A, 3.2B, and 3.3 receipts. Use for the preflight-complete 3.4A new-Database route.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR production run

Use only after the operator has completed 3.2A, 3.2B, and 3.3 for the exact Run Spec. Invoke `scripts/launch.py --run-spec <absolute-path>`.

The compiler must use `CONDUCTOR_modules/pipeline/production_pipeline.v0.2.1.json`. Do not inspect every downstream Skill contract, search for fixture plans, write ad-hoc Execution Requests, generate launch scripts, or change the DAG. It validates the three receipts and minimal start guards, freezes the config and control inputs under the new Run root, then delegates the fixed DAG to `cs-runtime`.

If a receipt hash, machine, scope, CPU limit, absent Database condition, or absent Run-root condition fails, stop without creating the Run root. Never bypass a failed guard.
