---
name: cs-stat-core
description: Execute CONDUCTOR 0.2.1 deterministic block permutation, empirical p-value, BH correction, or block-bootstrap primitives from a versioned Execution Request. Use as a pipeline dependency, not for free-form statistical interpretation.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR statistical core

Use this Skill only with a validated CONDUCTOR 0.2.1 Execution Request. Invoke `scripts/launch.py`; do not call the package through an implicit `PYTHONPATH`.

The request `parameters.operation` selects `permute_within_blocks`, `empirical_p_value`, `benjamini_hochberg`, or `block_bootstrap_indices`. The `statistic_plan` input artifact supplies the operation data. Preserve its block labels, alternative, family keys, candidate keys, and seeds exactly.

Never infer a missing block, alternative, or family. Null labels, missing values, and singleton blocks are retained. All randomness is derived from the Run seed, candidate key, and iteration so worker order cannot affect output.

Return only the one-object stdout contract. Progress and diagnostics belong on stderr; primary results and audit metadata belong in the attempt directory.

The governing contracts are in `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, sections 2 and 6.
