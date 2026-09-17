---
name: cs-runtime
description: Initialize and coordinate CONDUCTOR 0.2.1 Runs, validate Endpoint data, maintain the single-writer SQLite state machine, and commit attempt artifacts. Use only for explicit CONDUCTOR pipeline execution.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR runtime

Use only for an explicit CONDUCTOR Run with a complete Execution Request. Invoke `scripts/launch.py` and require project, run, phase, node, and attempt identity from the request; never invent them.

For `parameters.operation: prepare_phase1`, validate compound IDs and structures, build the Endpoint registry artifacts, transform every registered Endpoint, orient all internal values so larger is better, and run the configured missingness tests. For `parameters.operation: coordinate`, execute the supplied dependency DAG and resolve `node://<node>/<role>` only from succeeded manifests. Do not standardize structures, impute Endpoint values, or silently discard transform-domain failures.

Runtime state has one SQLite WAL writer. Workers write attempt events; the coordinator validates lease token and attempt ID before applying them. Late events remain in the audit table and cannot change canonical state. Retry a failed worker once with the same request seed and reuse success only under the same input/config/code key.

Respect `needs_design_review` checkpoints and never lower a statistical gate automatically.
