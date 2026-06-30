# CONDUCTOR_v2 Phase2 Design Specification: Group Insight Analysis

## 1. Objective

This document defines the design for the CONDUCTOR_v2 Phase2 Analysis Skill:

```text
cs-conductor-analysis-insight
```

The analysis name is:

```text
Group Insight Analysis
```

Phase2 uses Grouping outputs to identify groups with meaningful property trends and interpretable evidence. It should prioritize not only high-activity groups, but also high-activity groups that are structurally diverse by ECFP4 Tanimoto similarity.

Phase2 is a standalone Skill. It reads artifacts from v1 Grouping and optionally from v1 Desc and v2 Phase1. It does not create new groups.

## 2. Scope

Phase2 does:

- read the original input CSV
- detect or accept a numeric property column
- read `groups/<input_csv_stem>/group_membership_matrix.csv`
- read `groups/<input_csv_stem>/group_registry.json`
- compute group-level property profiles
- compute group-level enrichment statistics
- compute group-level activity consistency metrics
- optionally compute ECFP4 within-group Tanimoto similarity
- compute group overlap and redundancy metrics
- rank groups across several insight dimensions
- generate summary CSVs, figures, and a human-readable report

Phase2 does not:

- generate new groups
- modify Grouping outputs
- normalize IC50 to pIC50
- train prediction models
- infer causal SAR mechanisms
- generate new compounds
- replace expert interpretation

## 3. Proposed Skill Layout

Recommended Skill directory:

```text
.claude/skills/cs-conductor-analysis-insight/
  SKILL.md
  config/
    default_insight_config.json
  scripts/
    run_group_insight.py
    insight_config.py
    insight_io.py
    insight_groups.py
    insight_metrics.py
    insight_structural_diversity.py
    insight_plots.py
    insight_report.py
```

User-facing override config:

```text
config/CONDUCTOR_v2_phase2_insight_config.json
```

Config priority:

```text
Skill default config < user-facing override config < CLI explicit options
```

## 4. Inputs

### 4.1 Original CSV

The original CSV is required.

It must contain:

- compound ID column
- property column

ID column handling:

- accept explicit `--id-column`
- otherwise infer common ID names
- hard error when the ID column is missing
- hard error when IDs are missing or duplicated

Property column handling:

- accept explicit `--property-column`
- otherwise use config `property.preferred_names`
- hard error when no property column can be determined
- rows with missing or non-numeric property values are excluded from property-based analysis and recorded in warnings

Default preferred property names:

```json
["pIC50", "PIC50", "pActivity", "activity", "Activity", "score", "Score"]
```

Property direction must be configurable:

```json
{
  "property": {
    "higher_is_better": true
  }
}
```

For pIC50, `higher_is_better` should be true. For raw IC50, it should be false unless the user preprocesses the data.

### 4.2 Grouping Outputs

Required:

```text
groups/<input_csv_stem>/group_membership_matrix.csv
groups/<input_csv_stem>/group_registry.json
```

Optional:

```text
groups/<input_csv_stem>/group_membership.csv
groups/<input_csv_stem>/group_relations.json
groups/<input_csv_stem>/grouping_manifest.json
groups/<input_csv_stem>/selected_groups.json
```

`group_membership_matrix.csv` is the primary membership artifact.

Expected format:

```text
compound_id,<group_id_1>,<group_id_2>,...
```

Rules:

- group columns must contain `0` or `1`
- compounds may belong to multiple groups
- group IDs should map to entries in `group_registry.json`

### 4.3 Optional ECFP4 Descriptor Input

For structural diversity analysis, Phase2 should read:

```text
descriptions/<input_csv_stem>/L02_ecfp4_bit.csv
```

This file is optional but recommended.

If unavailable:

- skip ECFP4 Tanimoto metrics
- skip structurally diverse active group ranking
- record a warning
- still run property enrichment and consistency analysis

### 4.4 Optional Phase1 Outputs

Optional Phase1 context:

```text
analysis/<input_csv_stem>/structure_activity_landscape/sal_representation_summary.csv
```

Phase2 may use this only for annotation. Phase2 must not require Phase1 outputs.

## 5. Output Directory

Default output directory:

```text
analysis/<input_csv_stem>/group_insight/
```

CLI may allow:

```text
--outdir
```

to override the output directory.

## 6. Config Specification

Recommended config structure:

```json
{
  "property": {
    "column": null,
    "auto_detect": true,
    "preferred_names": ["pIC50", "PIC50", "pActivity", "activity", "Activity", "score", "Score"],
    "higher_is_better": true
  },
  "activity_bins": {
    "mode": "quantile",
    "high_quantile": 0.8,
    "low_quantile": 0.2
  },
  "group_inputs": {
    "base_dir": "groups",
    "subdir": null,
    "membership_matrix": "group_membership_matrix.csv",
    "registry": "group_registry.json",
    "relations": "group_relations.json"
  },
  "structural_diversity": {
    "enabled": true,
    "descriptor_base_dir": "descriptions",
    "descriptor_subdir": null,
    "ecfp4_bit_file": "L02_ecfp4_bit.csv",
    "max_exact_pair_count": 200000,
    "sample_pair_count": 200000,
    "random_seed": 42
  },
  "statistics": {
    "enabled": true,
    "permutation_test": true,
    "permutation_count": 2000,
    "fdr_method": "benjamini_hochberg"
  },
  "filters": {
    "min_group_size": 5,
    "max_group_fraction": 0.95
  },
  "overlap": {
    "enabled": true,
    "jaccard_threshold": 0.8,
    "top_n_for_heatmap": 50
  },
  "ranking": {
    "top_n_report": 30,
    "redundancy_penalty_enabled": true
  },
  "figures": {
    "enabled": true,
    "format": "png",
    "dpi": 160,
    "max_groups_per_plot": 80
  },
  "outputs": {
    "base_dir": "analysis",
    "subdir": null
  }
}
```

## 7. Data Preparation

### 7.1 Property Table

Build a property table:

```text
compound_id, property
```

Rules:

- strict ID validation on the original CSV
- convert property to numeric
- exclude rows with missing or non-numeric property
- record excluded row count in warnings and manifest

### 7.2 Membership Matrix

Load `group_membership_matrix.csv`.

Rules:

- detect compound ID column
- validate group columns as binary `0` or `1`
- inner join to property-valid compounds
- skip groups below `filters.min_group_size`
- optionally skip near-global groups above `filters.max_group_fraction`

Near-global groups are often less informative because they do not narrow the dataset enough.

### 7.3 Group Registry

Load `group_registry.json` and map each group ID to:

- group label
- group type
- group source
- compound count
- definition
- quality status

If a group exists in the membership matrix but not in the registry:

- keep the group
- record a warning
- fill registry-derived fields as missing

## 8. Metrics

### 8.1 Group Property Profile

For each group:

```text
group_size
property_count
property_mean
property_median
property_std
property_variance
property_min
property_max
property_q25
property_q75
property_iqr
property_mad
```

Also compute global background values once and store them in manifest and repeated summary columns where useful.

### 8.2 Activity Enrichment

Define high and low activity using config.

Default for `higher_is_better = true`:

```text
high_active = property >= global 80th percentile
low_active = property <= global 20th percentile
```

For `higher_is_better = false`, reverse the interpretation.

For each group:

```text
high_active_count
high_active_fraction
low_active_count
low_active_fraction
global_high_active_fraction
global_low_active_fraction
high_active_fraction_delta
low_active_fraction_delta
```

Recommended statistical tests:

- Fisher exact test for high-active enrichment
- Fisher exact test for low-active enrichment
- Mann-Whitney U test for group property distribution vs background
- optional permutation p-value for median shift
- FDR q-values across groups

Recommended effect columns:

```text
median_shift_vs_global
mean_shift_vs_global
rank_biserial_effect
high_active_odds_ratio
low_active_odds_ratio
```

### 8.3 Activity Consistency

Consistency is separate from enrichment.

For each group:

```text
property_variance
property_std
property_iqr
property_mad
median_pairwise_abs_property_delta
```

Lower dispersion means higher consistency.

Recommended rank:

```text
consistent_group_rank
```

### 8.4 ECFP4 Structural Diversity

If enabled and `L02_ecfp4_bit.csv` is available, compute within-group pairwise Tanimoto similarity.

For a binary fingerprint pair `(a, b)`:

```text
tanimoto(a,b) = intersection_bits / union_bits
```

For each group:

```text
ecfp4_pair_count
mean_ecfp4_tanimoto
median_ecfp4_tanimoto
p25_ecfp4_tanimoto
p75_ecfp4_tanimoto
min_ecfp4_tanimoto
max_ecfp4_tanimoto
structural_diversity_score = 1 - mean_ecfp4_tanimoto
```

Pair-count policy:

- exact calculation when pair count <= `max_exact_pair_count`
- otherwise sample `sample_pair_count` pairs with `random_seed`
- record whether the value is exact or sampled

Interpretation:

- high mean ECFP4 Tanimoto: structurally similar group
- low mean ECFP4 Tanimoto: structurally diverse group

### 8.5 Structurally Diverse Active Group Insight

This is a core Phase2 insight category.

Target pattern:

```text
high activity enrichment
+ activity consistency
+ low mean ECFP4 Tanimoto
```

Recommended output rank:

```text
structurally_diverse_active_group_rank
```

Recommended rank basis:

```text
rank_high_activity_enrichment_strength
rank_activity_consistency
rank_structural_diversity_score
```

The implementation should preserve the component ranks so the user can see why a group was prioritized.

This ranking should be skipped or marked unavailable when ECFP4 data is unavailable.

### 8.6 Interpretability

Compute a transparent interpretability annotation rather than a hidden claim.

Recommended fields:

```text
interpretability_tier
interpretability_reason
has_structure_motif
has_fragment_smiles
has_mcs_smarts
source_interpretability_class
```

Recommended classes:

```text
direct_structure_motif
fragment_motif
human_defined
descriptor_cluster
similarity_cluster
meta_group
unknown
```

Interpretability should not override poor property evidence, but it should help prioritize otherwise similar groups.

### 8.7 Overlap and Redundancy

For group member sets `A` and `B`:

```text
jaccard(A,B) = |A intersect B| / |A union B|
```

For each group:

```text
max_jaccard_with_any_group
max_jaccard_with_higher_ranked_group
overlap_count_above_threshold
redundant_with_group_id
redundancy_flag
```

Redundancy should reduce final insight priority but should not remove groups from output.

## 9. Ranking Design

Phase2 should emit multiple ranks:

```text
activity_enriched_group_rank
structurally_diverse_active_group_rank
consistent_group_rank
interpretable_group_rank
insight_priority_rank
```

Recommended rank definitions:

### 9.1 `activity_enriched_group_rank`

Prioritize groups with:

- high median or mean shift in the desired direction
- high-active fraction enrichment
- significant enrichment q-value
- sufficient group size

### 9.2 `structurally_diverse_active_group_rank`

Prioritize groups with:

- high-activity enrichment
- low property dispersion
- high `structural_diversity_score`
- sufficient group size

This rank should identify groups that are active despite low ECFP4 similarity.

### 9.3 `consistent_group_rank`

Prioritize groups with:

- low variance
- low IQR
- low median pairwise property delta

This rank does not require high activity.

### 9.4 `interpretable_group_rank`

Prioritize groups with:

- direct structure motif or fragment evidence
- strong property enrichment
- acceptable consistency

### 9.5 `insight_priority_rank`

Overall pragmatic ranking.

Recommended ingredients:

- activity enrichment rank
- consistency rank
- structurally diverse active rank when available
- interpretability class
- redundancy penalty

Do not hide the component metrics. The final rank is a convenience for triage, not a replacement for inspection.

## 10. Output Artifacts

### 10.1 Required CSV and JSON Outputs

```text
group_insight_summary.csv
group_property_profile.csv
group_enrichment_stats.csv
group_structural_diversity.csv
group_overlap_summary.csv
group_member_details.csv
group_metric_ranking.csv
insight_manifest.json
insight_warnings.json
```

### 10.2 Required Markdown Output

```text
top_groups_report.md
```

### 10.3 `group_insight_summary.csv`

Main table, one row per analyzed group.

Recommended columns:

```text
group_id
group_label
group_type
group_source
group_size
property_median
property_mean
property_std
property_iqr
median_shift_vs_global
high_active_fraction
high_active_fraction_delta
high_active_odds_ratio
high_active_fdr_qvalue
low_active_fraction
low_active_fraction_delta
mannwhitney_pvalue
mannwhitney_fdr_qvalue
rank_biserial_effect
mean_ecfp4_tanimoto
median_ecfp4_tanimoto
structural_diversity_score
structural_diversity_available
activity_enriched_group_rank
structurally_diverse_active_group_rank
consistent_group_rank
interpretable_group_rank
insight_priority_rank
max_jaccard_with_higher_ranked_group
redundancy_flag
interpretability_tier
interpretability_reason
```

### 10.4 `group_property_profile.csv`

Detailed property distribution statistics per group.

### 10.5 `group_enrichment_stats.csv`

Detailed test statistics and enrichment values per group.

### 10.6 `group_structural_diversity.csv`

ECFP4 Tanimoto structural diversity metrics per group.

If ECFP4 is unavailable, write the file with unavailable status or skip it and record a warning. Prefer writing an empty but schema-valid file for downstream stability.

### 10.7 `group_overlap_summary.csv`

Overlap and redundancy metrics per group.

### 10.8 `group_member_details.csv`

Long-format group-member table with property values:

```text
group_id
compound_id
property
is_high_active
is_low_active
```

This helps users inspect top groups manually.

### 10.9 `group_metric_ranking.csv`

Long-format ranking table:

```text
metric_name
direction
group_id
metric_value
rank
```

### 10.10 `top_groups_report.md`

Human-readable report for top groups.

For each top group, include:

- group ID and label
- group type and source
- group size
- property summary
- enrichment summary
- ECFP4 structural diversity summary when available
- overlap/redundancy warning
- concise interpretation note
- caution statement

Example note:

```text
This group is high-activity enriched and internally consistent despite low mean ECFP4 Tanimoto similarity. This may indicate a non-obvious active series or scaffold-hopping-like pattern. Treat this as a prioritization signal, not a mechanistic claim.
```

## 11. Visualization Requirements

Figures are required by default.

Output directory:

```text
figures/
```

Required figures:

```text
figures/activity_enrichment_vs_group_size.png
figures/top_group_property_distributions.png
figures/high_activity_vs_ecfp4_tanimoto.png
figures/structural_diversity_vs_consistency.png
figures/top_group_overlap_heatmap.png
figures/group_source_summary.png
```

### 11.1 `high_activity_vs_ecfp4_tanimoto.png`

Core Phase2 visualization.

Recommended axes:

```text
x-axis: mean_ecfp4_tanimoto
y-axis: high_active_fraction_delta or property_median
point size: group_size
color: group_source or group_type
```

The upper-left region is most interesting:

```text
low ECFP4 similarity + high activity enrichment
```

### 11.2 `structural_diversity_vs_consistency.png`

Recommended axes:

```text
x-axis: structural_diversity_score
y-axis: activity_consistency_score or inverse property dispersion
color: high_active_fraction_delta
```

This figure helps distinguish structurally diverse but noisy groups from structurally diverse and property-consistent groups.

### 11.3 `activity_enrichment_vs_group_size.png`

Recommended axes:

```text
x-axis: group_size
y-axis: high_active_fraction_delta or median_shift_vs_global
color: group_source
```

This figure exposes small but strong groups and large but weak groups.

### 11.4 `top_group_property_distributions.png`

Boxplot, violin plot, or strip plot for top groups.

Use this to verify that a top-ranked group is not driven by one outlier.

### 11.5 `top_group_overlap_heatmap.png`

Jaccard overlap heatmap among top-ranked groups.

Use this to detect redundant groups.

### 11.6 `group_source_summary.png`

Summary of insight ranks by group source/type.

Use this to see whether MCS, fragment, descriptor clustering, or other group types produce the strongest insight candidates.

## 12. Manifest and Warnings

Required JSON outputs:

```text
insight_manifest.json
insight_warnings.json
```

`insight_manifest.json` should include:

- skill name
- analysis name
- input CSV
- group directory
- descriptor directory
- output directory
- ID column
- property column
- property direction
- activity thresholds
- group count before and after filters
- ECFP4 structural diversity status
- config path
- output files
- created timestamp

`insight_warnings.json` should include:

- missing optional ECFP4 descriptor file
- missing optional group relations file
- groups skipped by size filters
- groups with missing registry entries
- property rows excluded
- structural diversity sampling warnings
- statistical test failures
- figure generation failures

## 13. Error Policy

Hard errors:

- input CSV cannot be read
- compound ID column cannot be determined
- compound IDs are missing or duplicated
- property column cannot be determined
- `group_membership_matrix.csv` cannot be read
- `group_registry.json` cannot be read
- no group remains after required joins and filters

Soft warnings:

- optional ECFP4 descriptor file is missing
- optional Phase1 output is missing
- optional group relations file is missing
- group has no registry entry
- ECFP4 IDs do not fully match group IDs
- a group is too large for exact pairwise Tanimoto and sampling is used
- individual statistical test fails for a group

## 14. CLI

Recommended command:

```powershell
.venv\Scripts\python.exe .claude\skills\cs-conductor-analysis-insight\scripts\run_group_insight.py `
  --input chemble_jak2.csv `
  --config config\CONDUCTOR_v2_phase2_insight_config.json
```

Useful overrides:

```powershell
--id-column ID
--property-column pIC50
--groups-dir groups\chemble_jak2
--descriptions-dir descriptions\chemble_jak2
--outdir analysis\chemble_jak2\group_insight
```

## 15. Acceptance Criteria

Phase2 is acceptable when:

1. `cs-conductor-analysis-insight` exists as a standalone Skill.
2. It reads original CSV and Grouping outputs from `groups/<input_csv_stem>/`.
3. It uses `group_membership_matrix.csv` as the primary group membership artifact.
4. It reads `group_registry.json` for group labels, types, sources, and definitions.
5. It detects or accepts a numeric property column.
6. It supports configurable property direction.
7. It computes group property profiles.
8. It computes high-activity and low-activity enrichment metrics.
9. It computes activity consistency metrics.
10. It optionally computes within-group ECFP4 Tanimoto structural diversity.
11. It ranks structurally diverse active groups separately.
12. It computes group overlap and redundancy metrics.
13. It emits multiple transparent ranks, not only one black-box score.
14. It writes required CSV outputs.
15. It writes `top_groups_report.md`.
16. It writes required figures.
17. It writes manifest and warnings.
18. It remains usable when ECFP4 descriptors are unavailable, with structural diversity metrics marked unavailable.
19. It does not create new groups.
20. It does not make mechanistic SAR claims.
