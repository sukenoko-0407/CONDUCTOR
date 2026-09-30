# Standalone MMP database contract

## Identity and immutability

The canonical database is SQLite schema `2.0.0`, calculation version `0.1.11`, model revision `canonical-evidence-v6`, and engine `mmpdb-3.1.4`. A completed database has `build_complete=true`, `target_independent=true`, a structure signature, and an effect signature in its `metadata` table.

The structure signature binds compound IDs, canonical structures, fragmentation SMARTS, cut count, core/variable limits, radius range, and two-cut thresholds. The effect signature binds compound IDs, endpoint values, endpoint column name, favorable direction, and the fixed neutral tolerance of `0.10`.

Report mode reconstructs its dataset view from the database's `compounds` table and reuses the stored structural parameters. It rejects a database if the reconstructed structure signature differs. The database is opened with SQLite `mode=ro` and is never updated.

## Stable report behavior

- Maximum cuts: 2, with separate 1-cut and 2-cut evidence.
- Radius: 0 through 2 under the default build CLI.
- Maximum input compounds: 5,000.
- Neutral endpoint tolerance: 0.10.
- Target selection: human-explicit compound IDs only.
- Report template version: 0.1.11.

The report's arrow is oriented from neighbor/observed counterpart toward the target. `target_oriented_delta` is the signed endpoint difference after applying the stored favorable direction. Positive and negative directions are interpretation categories, not evidence-quality categories.

## Core tables

The database includes `metadata`, `compounds`, `fragmentations`, `transformation_families`, `transformations`, `exact_cores`, `retained_anchors`, `pairs`, `pair_transformations`, `environments`, `two_cut_quality`, and `exclusion_reasons`, plus 1-cut and 2-cut views.

The `compounds` table stores the original compound ID, SMILES, endpoint, parse/eligibility information, heavy-atom count, endpoint availability, and exclusion reason. This is why report mode does not require the original CSV.

