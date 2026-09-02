# MMP contract

## Counting unit

One stored MMP instance is a canonical compound pair × directed transform × exact constant core. Statistical `pair_count` is the number of unique compound pairs after collapsing multiple Exact Core instances for the same pair; `mmp_instance_count` retains the uncollapsed database row count. Exact Core diversity is reported separately. Standard environment radii 0–2 describe nested contexts and must not inflate either count. Radii 3–5 are explicit extended-search options.

## Standard core eligibility

- Constant core heavy atoms are at least 8.
- Constant core fraction is at least 0.50 in both molecules.
- Variable part heavy atoms are at most 10.

The standard evidence store has one eligibility policy rather than Primary/Extended classes. A deliberately wider search must be a separately parameterized Node.

## Direction

Transform direction follows canonical mmpdb rule orientation. `endpoint_delta = endpoint_to - endpoint_from`. `favorable_delta` equals that value when higher is better and its negative otherwise.

## Context

Environment radius is the number of bond shells around the attachment point included in the environment fingerprint. Radius 0 is attachment-local; larger radii encode progressively more surrounding structure. Context records are nested evidence, not independent replications.

## Global and Local

Global means all compounds in the run. Local means a CONDUCTOR Cluster membership filter over the immutable Global pair database. Local queries never fragment or index molecules again.

Standard Type-I selects only the Top 1 compound from each active Series or fallback Cluster; Global is not an automatic Type-I target. A larger Top K is an On-demand Type-II request with explicit run compound IDs.

## Human report

The canonical database and CSV retain every exact-core instance and their native mmpdb direction. Reporting uses a separate deterministic view. It always orients the Neighbor as From and the Target as To, including the sign of Favorable delta. For duplicate Target–Neighbor rows, a core that is a proper substructure of another candidate core is discarded; the largest remaining core is retained as the smallest displayed transformation. This collapse affects HTML only.

Each target HTML uses a fixed order: Target/Neighbor 2D structures; Target full SMILES plus a basic table containing MMP ID, both compound IDs, both Endpoint values, and the Neighbor→Target Favorable delta; a detail table containing MMP ID, Exact Core, Neighbor-side variable fragment, and Target-side variable fragment; then one visual row per displayed MMP containing the whole Neighbor structure, before fragment, and after fragment. Neighbor full SMILES is not printed. All remaining columns and rows stay in the canonical CSV rather than being expanded into HTML.

## Evidence quality

Always show pair count, independent exact-core count, missing-endpoint count, median, IQR, MAD, direction consistency, and leave-one-core-out stability where calculable. A large pair count from one core is not portable evidence.
