---
name: cs-lens-l5
description: Run the CONDUCTOR 0.2.1 L5 lens for feature correlations that reverse sign between contexts on the same axis. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR L5 lens

Invoke `scripts/launch.py` with compounds, Endpoint, context catalog/membership, and the Phase 1 feature-space registry.

Compare only representative contexts from the same `axis_id`. Require both local correlations to exceed the configured absolute threshold with opposite signs. Keep membership and feature values fixed while permuting the Endpoint inside Murcko blocks; derive the Fisher-z-difference p-value empirically and apply BH within the L5 family. Preserve overlapping contexts and report their shared compound count and the global correlation.

Do not use the unrestricted whole-dataset permutation as the production null. The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.7.
