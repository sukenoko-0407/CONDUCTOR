---
name: cs-lens-l2
description: Run the CONDUCTOR 0.2.1 L2a transformation-context and L2b fragment-contribution lenses with series-internal staged permutation and separate BH families. Use only inside an explicit CONDUCTOR Run.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR L2 lens

Invoke `scripts/launch.py` with `parameters.operation: l2b` for the mandatory checkpoint path, or `l2a` with MMP database, Endpoint, context catalog, and membership inputs.

For L2a, include only pairs whose two ends are both inside or both outside a context; exclude crossing pairs. Test the median shift and variance reduction independently. Recreate pair deltas after permuting Endpoint values inside each constant-key series, and keep transform class and question in separate BH families. Preserve near-zero, low-variance effects with the `tolerance` label.

Treat a series as one `(transform_class, constant_key)` group, not as a Phase 2 context. Collapse duplicate compounds for one fragment to their Endpoint mean, then subtract the unweighted mean of fragment observations in that series. Require two series for the two-sided consistent-effect test and three series for the upper-tail variance test. A zero residual standard deviation has `p=1`.

Permute individual finite Endpoint values within each series and recompute duplicate collapse, series means, and residuals. Use the configured 100-iteration screen and 1000-iteration final stage. Preserve every hypothesis in its BH family conservatively; terminal and ring classes and the two questions are separate families. Do not mix linker fragments into L2b.

After writing the production tests, run the within-series enrichment checkpoint and stop. A result at or below 1.5 is `needs_design_review`; even a passing result does not authorize Stage 7 without explicit approval.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.6.
