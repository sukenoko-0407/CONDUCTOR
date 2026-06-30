# MCS Extraction Revision Plan

## 1. Purpose

This document defines the revision plan for MCS-based group extraction in the `grouping` Skill.

The current implementation computes MCS on deterministic first-N compound pairs. This is useful as a smoke-test implementation, but it is not a robust frequent-core mining strategy. The revised design should mine candidate MCS cores from a sampled compound set, rank/filter those cores, and then apply selected core definitions to all compounds to generate group membership.

## 2. Core Policy

MCS group definitions are determined only from the sampled compound set.

After core definitions are selected, each selected core is applied to all valid compounds by substructure matching. This expands group membership to the full dataset, but it does not change the selected core definitions.

```text
input compounds
  -> choose up to N sample compounds
  -> compute all sample pairs
  -> extract and count MCS SMARTS candidates
  -> select core definitions using TopN / count cutoff K / heavy atom count cutoff H
  -> apply selected core definitions to all compounds
  -> write group_registry and group_membership
```

## 3. Sampling Strategy

### 3.1 Default Sample Size

Default:

```json
{
  "max_mcs_sample_compounds": 1000
}
```

For 1000 sampled compounds, the all-pairs calculation is:

```text
1000 * 999 / 2 = 499,500 pairs
```

If pair direction or repeated comparison accounting is reported as approximately 1,000,000 operations, that is acceptable for this workflow. Computational cost is considered acceptable.

### 3.2 Wet-First Sampling

If an `is_virtual` or equivalent column is detected:

1. Prefer Wet compounds for the sample.
2. If Wet compounds are fewer than `max_mcs_sample_compounds`, fill the remaining slots with Virtual compounds.
3. Preserve deterministic sampling with a fixed random seed.

If no Wet/Virtual column is detected:

1. Treat all valid compounds equivalently.
2. Sample from all valid compounds.

Default:

```json
{
  "mcs_sampling": {
    "strategy": "random_wet_first",
    "max_mcs_sample_compounds": 1000,
    "random_seed": 42
  }
}
```

### 3.3 Future Sampling Option

Fingerprint-stratified sampling may be added later, but it should not replace the initial random Wet-first implementation.

Possible future option:

```json
{
  "mcs_sampling": {
    "strategy": "fingerprint_stratified_wet_first"
  }
}
```

This is useful when rare chemotypes should be preserved in the sample.

## 4. Pairwise MCS Mining

For each pair in the sampled set:

1. Compute RDKit MCS.
2. Skip canceled or empty MCS results.
3. Convert MCS to SMARTS.
4. Record:
   - `mcs_smarts`
   - `heavy_atom_count`
   - `pair_count`
   - source pair IDs
   - optional representative pair examples

Recommended per-pair settings:

```json
{
  "timeout_seconds_per_pair": 5,
  "ringMatchesRingOnly": true,
  "completeRingsOnly": true,
  "matchValences": true
}
```

## 5. Candidate Core Counting

MCS candidates are aggregated by canonical SMARTS where possible.

For each candidate core:

```json
{
  "mcs_smarts": "...",
  "pair_count": 123,
  "heavy_atom_count": 14,
  "sample_compound_support_count": 47,
  "sample_wet_support_count": 45,
  "representative_pairs": [
    ["Cpd001", "Cpd014"],
    ["Cpd003", "Cpd021"]
  ]
}
```

`pair_count` is the number of sampled pairs that produced the candidate core.

`sample_compound_support_count` should be computed by applying the candidate core back to the sampled compounds, because pair count alone can overrepresent redundant local pair structure.

## 6. Core Selection Modes

The implementation should support all three selection modes.

### 6.1 TopN

Select the top N candidate cores after ranking.

Default:

```json
{
  "mcs_candidate_top_n": 50
}
```

Ranking order:

1. Higher `pair_count`
2. Higher `sample_compound_support_count`
3. Higher `heavy_atom_count`
4. Deterministic SMARTS sort key

### 6.2 Count Cutoff K

Select candidate cores whose pair count is at least K.

Default:

```json
{
  "mcs_candidate_min_pair_count": 10
}
```

### 6.3 Heavy Atom Count Cutoff H

Select candidate cores whose heavy atom count is at least H.

Default:

```json
{
  "min_mcs_heavy_atoms": 8
}
```

MW-based filtering is intentionally rejected. Use heavy atom count instead.

### 6.4 Combined Selection Policy

The Skill should support independent and combined modes.

Recommended default:

```text
candidate is selected if:
  candidate is in TopN
  AND pair_count >= K
  AND heavy_atom_count >= H
```

Optional exploratory mode:

```text
candidate is selected if:
  candidate is in TopN
  OR pair_count >= K
  OR heavy_atom_count >= H
```

Config:

```json
{
  "mcs_selection": {
    "mode": "intersection",
    "top_n": 50,
    "min_pair_count": 10,
    "min_heavy_atoms": 8
  }
}
```

Allowed values:

```text
intersection
union
top_n_only
count_cutoff_only
heavy_atom_cutoff_only
```

## 7. Deduplication and Pruning

MCS mining can produce many similar or nested cores. The revised implementation should include at least basic pruning.

### 7.1 Exact Deduplication

Merge candidates with identical SMARTS.

### 7.2 Substructure Redundancy Pruning

When two candidate cores have strong containment:

```text
core A is substructure of core B
and support(A) is close to support(B)
```

Prefer the more specific core, usually the one with higher heavy atom count.

Default:

```json
{
  "deduplicate_substructure_cores": true,
  "support_similarity_for_pruning": 0.9
}
```

This should be implemented conservatively. Do not prune aggressively in the first version.

## 8. Full Dataset Expansion

After selected core definitions are finalized from the sampled compounds:

1. Convert each selected MCS SMARTS into an RDKit query molecule.
2. Apply it to all standardized valid compounds.
3. Create group membership for every matching compound.
4. Compute:
   - `compound_count`
   - `wet_count`
   - `virtual_count`
   - `activity_summary`, if activity is available

The full dataset expansion must not introduce new core definitions.

## 9. Output Artifacts

In addition to existing artifacts, MCS mining should write diagnostic artifacts.

### 9.1 Candidate Table

```text
mcs_candidate_cores.csv
```

Recommended columns:

```text
mcs_candidate_id
mcs_smarts
pair_count
heavy_atom_count
sample_compound_support_count
sample_wet_support_count
selected_by_top_n
selected_by_pair_count
selected_by_heavy_atom_count
selected_final
full_compound_count
full_wet_count
full_virtual_count
representative_pair_1
representative_pair_2
```

### 9.2 Parameter Sweep Table

```text
mcs_parameter_sweep.csv
```

Recommended columns:

```text
top_n
min_pair_count
min_heavy_atoms
selection_mode
selected_core_count
full_membership_count
median_group_size
max_group_size
singleton_group_count
```

## 10. Figures

The first implementation should save figures showing how parameter changes affect core selection.

Recommended output directory:

```text
outputs/grouping/figures/
```

### 10.1 Pair Count Distribution

File:

```text
figures/mcs_pair_count_distribution.png
```

Content:

```text
x-axis: pair_count
y-axis: number of candidate cores
```

### 10.2 Heavy Atom Count Distribution

File:

```text
figures/mcs_heavy_atom_distribution.png
```

Content:

```text
x-axis: heavy_atom_count
y-axis: number of candidate cores
```

### 10.3 TopN Sensitivity

File:

```text
figures/mcs_topn_sensitivity.png
```

Content:

```text
x-axis: TopN
y-axis: selected_core_count and full_membership_count
```

Suggested TopN grid:

```text
10, 20, 50, 100, 200
```

### 10.4 Pair Count Cutoff Sensitivity

File:

```text
figures/mcs_pair_count_cutoff_sensitivity.png
```

Content:

```text
x-axis: min_pair_count K
y-axis: selected_core_count and full_membership_count
```

Suggested K grid:

```text
3, 5, 10, 20, 50, 100
```

### 10.5 Heavy Atom Cutoff Sensitivity

File:

```text
figures/mcs_heavy_atom_cutoff_sensitivity.png
```

Content:

```text
x-axis: min_heavy_atoms H
y-axis: selected_core_count and full_membership_count
```

Suggested H grid:

```text
6, 8, 10, 12, 15, 20
```

### 10.6 Combined Parameter Heatmap

File:

```text
figures/mcs_parameter_heatmap.png
```

Content:

```text
x-axis: min_pair_count K
y-axis: min_heavy_atoms H
cell value: selected_core_count
```

Create one heatmap per TopN value if useful, or use the default TopN for the first implementation.

## 11. Config Revision

Proposed config block:

```json
{
  "mcs_group_builder": {
    "enabled": true,
    "include_virtual_in_mcs_mining": false,
    "sampling_strategy": "random_wet_first",
    "max_mcs_sample_compounds": 1000,
    "random_seed": 42,
    "timeout_seconds_per_pair": 5,
    "candidate_top_n": 50,
    "candidate_min_pair_count": 10,
    "min_mcs_heavy_atoms": 8,
    "selection_mode": "intersection",
    "deduplicate_substructure_cores": true,
    "support_similarity_for_pruning": 0.9,
    "write_mcs_diagnostics": true,
    "write_mcs_figures": true,
    "parameter_sweep": {
      "enabled": true,
      "top_n_values": [10, 20, 50, 100, 200],
      "min_pair_count_values": [3, 5, 10, 20, 50, 100],
      "min_heavy_atoms_values": [6, 8, 10, 12, 15, 20]
    }
  }
}
```

## 12. Acceptance Criteria

The revised MCS implementation is acceptable when:

1. It samples up to 1000 compounds with Wet-first behavior when Wet/Virtual information exists.
2. It treats all compounds equally when Wet/Virtual information is absent.
3. It computes all sample pairs.
4. It records and counts MCS candidate cores.
5. It supports TopN selection.
6. It supports pair-count cutoff K selection.
7. It supports heavy atom count cutoff H selection.
8. It rejects MW-based selection.
9. It defines cores only from the sampled set.
10. It applies selected cores to all valid compounds after definitions are fixed.
11. It writes `mcs_candidate_cores.csv`.
12. It writes `mcs_parameter_sweep.csv`.
13. It writes parameter sensitivity figures.
14. It remains deterministic with a fixed random seed.
15. It records MCS parameters and sampling metadata in `group_registry.json` and `grouping_manifest.json`.

## 13. Implementation Notes

The first implementation should prioritize correctness and traceability over clever pruning.

Recommended implementation order:

1. Add sampling function.
2. Add all-pairs MCS candidate mining.
3. Add candidate aggregation table.
4. Add TopN / K / H selection flags.
5. Add full-dataset substructure expansion.
6. Add parameter sweep table.
7. Add figures.
8. Add conservative deduplication and pruning.

