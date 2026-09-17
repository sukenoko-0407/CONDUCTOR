---
name: cs-context-builder
description: Build deterministic CONDUCTOR 0.2.1 cluster, quantile, scaffold, and diagnostic contexts; deduplicate them by Jaccard connected components; and translate Tier 3 clusters to Tier 1 features. Use only inside an explicit CONDUCTOR Run.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR context builder

Invoke `scripts/launch.py` with one `compounds`, one `endpoint_table`, and one `feature_spaces` input. The public operation is `parameters.operation: build_contexts`.

Reuse each registered distance matrix for every configured average-linkage cluster count. Quantile contexts contain only the lower side of each Tier 1 cutoff. Preserve Murcko, generic-MCS, BRICS, and RECAP contexts and keep activity bands diagnostic-only.

Deduplicate with the transitive connected components of Jaccard overlap. Keep every original context; select the largest member set, then lexical context ID, as representative. Only representatives are eligible for downstream multiple-comparison families.

Translate Tier 3 clusters with a three-fold stratified L2 logistic model using only Tier 1 inputs. Imputation and scaling must be fitted inside each fold. Use the fixed top-three signed-feature template; do not use an LLM in Phase 2.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, sections 5.3 and 7.5.
