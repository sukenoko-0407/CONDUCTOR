---
name: cs-lens-l4
description: Run the CONDUCTOR 0.2.1 L4 lens to generate sanitized, unobserved one-step MMP products and score conservative reachable regions. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR L4 lens

Run only after the canonical transformation database exists. Reconnect isotope-labelled attachment points, sanitize every generated molecule, reject observed products, and retain the complete generation audit.

Run every Tier 1/2 Description Skill again on the generated candidate structures, using the exact parameters recorded in the Phase 1 feature-space registry. Compute candidate-to-observed distances with Phase 1's fitted feature columns, imputation values, and scaling. Never substitute a source-compound neighborhood for a candidate description.

Use the exact candidate neighborhoods to form conservative one-sided lower bounds. Multiply the most conservative bound by density gap and validated one-step reachability. Fail closed if a candidate Description is missing or incomplete, and do not relax thresholds merely to increase the candidate count.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.7.
