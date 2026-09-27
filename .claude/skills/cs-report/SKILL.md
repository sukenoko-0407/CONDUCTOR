---
name: cs-report
description: Assemble CONDUCTOR 0.2.1 entity-connected narratives and fail closed on numeric, row, hash, entity, or test citation inconsistencies. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR report

Build connected components from shared typed entities and ask the configured offline JSONL LLM for one cited paragraph per component. Give it only Findings and registered citeable rows.

Before publishing, independently verify every narrative number within 1% against its cited rows, every table hash and unique row ID, every referenced compound, every cited pair against the optional `mmp_database` Run registry, and every Finding test statistic/p/q against test artifacts. If cited evidence contains pair IDs, `mmp_database` is required. Preserve invalid drafts for diagnosis and fail Phase 6 on the first or any accumulated citation error. Never rewrite unsupported text automatically.

Publish the validated content as `report.json`, `report.md`, a self-contained overview
`report.html`, and detailed `finding_reports/<finding_id>.html` pages for the configured
top `scoring.display_k` reportable Findings. The overview must lead with the substantive
meaning of important Findings; keep the complete Finding table as an audit appendix.
Each detailed page must explain the Lens question, claim, effect, support, all tests,
score basis, triviality/confounder assessment, deep-dive state, falsification contract,
entities, and cited Evidence without adding external knowledge or new inference.

Every detailed page must also include the Lens-native data visualization, not a generic
decorative chart. Use RDKit-generated inline 2D SVG for chemical structures and hashed
`score_observations` for plots: L1b local-SAR points and the saved ordered neighbors of
the highest-improvement compound; L2a before/after MMP fragments, measured full-molecule
pairs, and in/out effect distributions; L2b fragment depiction, per-series residuals,
and highlighted example compounds; L4 candidate
and source-to-candidate structures plus neighbor endpoints; L5 context/complement
feature-versus-Endpoint scatter with fitted lines; L7 paired series cores, common-R
structures, a same-R measured compound pair, and the common-R Endpoint correspondence.
Missing visual inputs are a reporting contract error. Do not
silently fall back to prose-only output or invent a diagram from unsupported data.

HTML must not load remote scripts, styles, fonts, images, or other network resources.
Escape every value originating in Run artifacts before placing it in HTML. `report.html`
is the human-facing primary artifact; JSON/JSONL artifacts and their manifests remain
the machine-auditable source of truth. Additional Findings may be rendered on human
request from an accepted P06 manifest, outside the Run root, without rerunning the LLM
or any analysis.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.10.
