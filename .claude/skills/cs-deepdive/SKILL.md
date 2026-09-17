---
name: cs-deepdive
description: Execute CONDUCTOR 0.2.1 deep dives with fixed T01-T10 templates, deterministic state rules, bounded budgets, and an offline JSONL LLM selector. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR deep dive

The Local LLM may select zero to three templates and parameters, but it must not invent tests or decide states. Execute T01-T10 deterministically on registered evidence, consume budget even for non-testable selections, prevent repeated template/parameter calls on one ancestor path, stop refuted branches, and cap depth and tests exactly as configured.

For T03, T04, T07, and T08, dispatch to the parent Lens replay adapter and recompute the parent effect definition on the restricted, residualized, or deleted minimum observation units. If the registered observations cannot replay that Lens, return `not_testable`; never replace the parent statistic with a generic mean-effect proxy.

Build T01 chemical axes mechanically. The bundled Hammett table is versioned and audited; use Hammett only when attachment geometry uniquely establishes meta/para, otherwise use the Gasteiger fallback. Project SMARTS are independent, potentially nested binary axes.

Retry Local LLM schema/timeout/process failures only to the configured bound. Keep a Finding without narrative after a failed logical call, and fail the phase only when the logical-call failure fraction exceeds the configured maximum.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.9.
