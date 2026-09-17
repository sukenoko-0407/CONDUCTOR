---
name: cs-scoring
description: Score CONDUCTOR 0.2.1 Findings with fixed gates, block-bootstrap robustness, confounder adjustment, frontier relevance, and retained duplicate merges. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR scoring

Combine all lens Findings and their standardized score-observation tables. Rank q values only within each lens, estimate robustness by block bootstrap, and apply the fixed statistical-strength and robustness gates before composite ranking.

Load D001 MW, cLogP, and TPSA plus the structure-derived Murcko scaffold class. Fit the confounder model to the selected Endpoint, residualize at each Lens's minimum observation unit, and recompute that Lens's original effect statistic. Do not approximate `E_adj` by multiplying `E_raw` by an explained-variance fraction.

Do not lower thresholds when fewer than K Findings survive. Mark the node `needs_design_review`. Merge cross-lens duplicates only when two typed entities and `subject_type` match; retain losers with `merged_into`.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.8.
