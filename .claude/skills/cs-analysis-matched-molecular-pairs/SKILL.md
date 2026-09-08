---
name: cs-analysis-matched-molecular-pairs
description: Build a Target-independent 1/2-cut MMP database or analyze explicitly supplied Target compounds as transformation evidence (A008).
allowed-tools: Read, Bash
---

# A008 MMP transformation evidence

Use exactly one mode.

- `database`: build the immutable, Target-independent canonical MMP database for all Run compounds.
- `target`: analyze an explicit Target list. The normal CONDUCTOR caller supplies every selected analysis-unit Top1 plus Global Top1; On-demand calls supply human-selected Run compound IDs.

Do not create a `standard`/`explicit` submode and do not select Targets inside the scientific engine. Deduplicate a repeated Target and retain every `selection_source`.

## Scientific invariants

1. Store fixed canonical structural direction and signed Endpoint delta in the database. Favorable A→B orientation is report-only and must never overwrite the database value.
2. Treat `|delta| < 0.10` as neutral. Neutral and missing pairs do not enter direction-consistency denominators.
3. Keep 1-cut and 2-cut IDs, views, summaries, and report filters separate.
4. Keep Target-independent 2-cut structural quality (`2C-A/B/X`) separate from Target-specific evidence quality (`high/limited/not_applicable/ambiguous`).
5. Do not count radius, analysis-unit membership, Target reuse, or duplicate fragmentation rows as independent support.
6. Direct/Transferred connection and Target interpretation are separate axes. In Target reports, always display the Target as the product/arrow end and preserve a signed `target_oriented_delta`; positive supports the Target Endpoint and negative is an improvement clue. These are interpretations, not different grades of evidence.
7. For Transferred evidence, require attachment-aware mapping and compare Target's current variable fragment with fixed A/B. Environment-mismatched rows remain reference evidence and never join Radius-1/2 direction voting.
8. Direct observed pairs remain accessible regardless of support count. Default Transferred high-quality display requires at least 3 unique pairs, 2 unique contexts, direction consistency ≥0.80, valid mapping, and exact/Radius-2 environment agreement.

## Output and report

Mode `target` writes one wide, offline Interactive HTML per unique Target. The first view is a compact Target—Core/Retained-anchors—Neighbor portal map with at most 5 Core groups per cut layer. Show every Neighbor individually through five; at six or more use a count node and expose every row in Core detail. For the same Target–Neighbor and cut count, retain only maximal Core rows in the report: compare 1-cut Cores after removing attachment dummies, compare 2-cut Cores by a bijection of their two dummy-stripped retained-anchor components, and keep mutually incomparable Cores. Canonical CSV/SQLite remain complete. Arrows always end at Target, every map connector is dashed, and outer Neighbor columns must not overlap. Target is navy, Core green, Neighbor orange. Core detail must provide all Direct MMPs, a Similar-Core evidence map with both mapped Core structures, individual MMP routes, and Back navigation. Detail uses a wide panel. Always show both whole compounds; mark failed constrained depictions as `Align ×`. Use `ΔN2T` and hierarchical navigation: Relationship Map; N2T Direction with `ΔN2T ≥ 0` / `ΔN2T < 0`; Core Type with Exact Core / Similar Core; N-Cuts with 1 Cut / 2 Cuts; Data Table; and a rightmost Evidence Guide utility tab. Raw rows are secondary. The Evidence Guide must define `2C-A`, `2C-B`, and `2C-X`. For 2-cut, both retained anchors must contain at least 4 heavy atoms; below-minimum rows remain auditable as `2C-X` but are excluded from the main Evidence display.

Mode `database` writes the canonical SQLite database, four aggregate CSVs, and a compact database summary. A009 reads only `mmp_report_index.json` and embeds the referenced static map; it does not copy Interactive HTML or pair tables.

All HTML must be produced from versioned templates. Do not use an LLM Vision step for validation. Validate links, counts, DOM behavior, and bounding boxes mechanically.

Read [references/mmp_contract.md](references/mmp_contract.md) for the field-level contract and human checkpoints.
