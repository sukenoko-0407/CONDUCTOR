# MMP contract

## Counting unit

One stored MMP instance is a canonical compound pair × directed transform × exact constant core. Statistical `pair_count` is the number of unique compound pairs after collapsing multiple Exact Core instances for the same pair; `mmp_instance_count` retains the uncollapsed database row count. Exact Core diversity is reported separately. Environment radii 0–5 describe nested contexts and must not inflate either count.

## Core classes

- `primary`: core heavy-atom fraction is at least 0.50 in both molecules.
- `extended`: fraction is at least 0.40 in both molecules but at least one side is below 0.50.
- Core heavy atoms must be at least 6 in every class.

## Direction

Transform direction follows canonical mmpdb rule orientation. `endpoint_delta = endpoint_to - endpoint_from`. `favorable_delta` equals that value when higher is better and its negative otherwise.

## Context

Environment radius is the number of bond shells around the attachment point included in the environment fingerprint. Radius 0 is attachment-local; larger radii encode progressively more surrounding structure. Context records are nested evidence, not independent replications.

## Global and Local

Global means all compounds in the run. Local means a CONDUCTOR Cluster membership filter over the immutable Global pair database. Local queries never fragment or index molecules again.

## Evidence quality

Always show pair count, independent exact-core count, missing-endpoint count, median, IQR, MAD, direction consistency, and leave-one-core-out stability where calculable. A large pair count from one core is not portable evidence.
