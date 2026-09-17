---
name: cs-report
description: Assemble CONDUCTOR 0.2.1 entity-connected narratives and fail closed on numeric, row, hash, entity, or test citation inconsistencies. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR report

Build connected components from shared typed entities and ask the configured offline JSONL LLM for one cited paragraph per component. Give it only Findings and registered citeable rows.

Before publishing, independently verify every narrative number within 1% against its cited rows, every table hash and unique row ID, every referenced compound, every cited pair against the optional `mmp_database` Run registry, and every Finding test statistic/p/q against test artifacts. If cited evidence contains pair IDs, `mmp_database` is required. Preserve invalid drafts for diagnosis and fail Phase 6 on the first or any accumulated citation error. Never rewrite unsupported text automatically.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.10.
