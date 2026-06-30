# CONDUCTOR_v2 Phase1 Design Specification: Structure-Activity Landscape

## 1. Objective

This document defines the design for the CONDUCTOR_v2 Phase1 Analysis Skill:

```text
cs-conductor-analysis-sal
```

The analysis name is:

```text
Structure-Activity Landscape
```

Phase1 evaluates descriptor representations from the Desc Skill by measuring how smooth or rugged a target property landscape is in each representation space.

The first objective is representation-method comparison. Because raw distance values are not commensurate across Tanimoto, cosine, standardized Euclidean, and other metrics, raw SALI is not used as the first cross-representation ranking criterion.

Phase1 is a standalone Skill. Phase2 will be designed as a separate Skill.

## 2. Scope

Phase1 does:

- read the original input CSV
- detect or accept a numeric property column
- read descriptor CSV files from `descriptions/<input_csv_stem>/`
- select a metric per descriptor representation from config
- compute kNN in each representation space
- compute distance-scale-independent kNN property consistency metrics
- compute raw SALI and normalized SALI as cliff diagnostics
- generate summary CSVs
- generate figures for visual evaluation

Phase1 does not:

- use `groups/<input_csv_stem>/`
- perform group-level analysis
- normalize IC50 to pIC50
- train prediction models
- infer mechanisms
- generate new compounds
- modify input CSV or descriptor CSVs

## 3. Proposed Skill Layout

Recommended Skill directory:

```text
.claude/skills/cs-conductor-analysis-sal/
  SKILL.md
  config/
    default_sal_phase1_config.json
  scripts/
    run_sal_phase1.py
    sal_config.py
    sal_io.py
    sal_features.py
    sal_metrics.py
    sal_plots.py
```

User-facing override config:

```text
config/CONDUCTOR_v2_sal_phase1_config.json
```

The Skill default config is the stable fallback. The user-facing config is passed through `--config` and deep-merged over the Skill default config.

Priority:

```text
Skill default config < user-facing override config < CLI explicit options
```

## 4. Inputs

### 4.1 Original CSV

The original CSV is required.

It must contain:

- compound ID column
- property column

ID column inference should reuse the v1 style:

- accept explicit `--id-column`
- otherwise infer common ID names
- hard error when missing or ambiguous

Property column handling:

- accept explicit `--property-column`
- otherwise use config `property.preferred_names`
- if exactly one candidate exists, use it
- if no candidate exists, hard error
- if multiple candidates exist, hard error and ask the user to specify one

Default preferred property names:

```json
["pIC50", "PIC50", "pActivity", "activity", "Activity", "score", "Score"]
```

Phase1 uses property values as provided. It does not invert IC50 or normalize units.

Rows with missing or non-numeric property values are excluded from analysis and recorded in warnings/metadata.

### 4.2 Descriptor CSVs

Descriptor CSVs are read from:

```text
descriptions/<input_csv_stem>/*.csv
```

Config controls:

```json
{
  "description_inputs": {
    "enabled": true,
    "base_dir": "descriptions",
    "subdir": null,
    "file_glob": "*.csv",
    "skip_files": ["errors.csv", "run_metadata.csv"]
  }
}
```

If `subdir` is null, use the original CSV stem.

Each descriptor CSV must contain:

- a compound ID column
- numeric feature columns

Known non-feature columns are excluded:

```text
compound_id
canonical_smiles
input_smiles
original_smiles
mol_parse_ok
descriptor_error
mol_error
source_row_index
row_index
exclusion_reason
```

Descriptor rows are inner-joined to valid property rows by compound ID.

## 5. Output Directory

Default output directory:

```text
analysis/<input_csv_stem>/structure_activity_landscape/
```

CLI may allow:

```text
--outdir
```

to override the output directory.

## 6. Config Specification

### 6.1 Top-Level Config

Recommended user-facing config:

```json
{
  "property": {
    "column": null,
    "auto_detect": true,
    "preferred_names": ["pIC50", "PIC50", "pActivity", "activity", "Activity", "score", "Score"]
  },
  "knn": {
    "k": 10,
    "include_self_in_local_variance": true
  },
  "sali": {
    "epsilon": 1e-6,
    "use_knn_edges_only": true
  },
  "description_inputs": {
    "enabled": true,
    "base_dir": "descriptions",
    "subdir": null,
    "file_glob": "*.csv",
    "skip_files": ["errors.csv", "run_metadata.csv"]
  },
  "representations": {},
  "figures": {
    "enabled": true,
    "format": "png",
    "dpi": 160,
    "max_points_per_plot": 20000
  },
  "outputs": {
    "base_dir": "analysis",
    "subdir": null
  }
}
```

### 6.2 Representation Metric Config

Metric definitions must be config-driven.

Each representation block should include:

```json
{
  "match": "L02_ecfp4_bit.csv",
  "metric": "tanimoto",
  "scaling": "none"
}
```

Matching can be exact filename or glob-style pattern.

Supported metrics:

```text
tanimoto
jaccard
cosine
euclidean
standardized_euclidean
manhattan
correlation
```

Supported scaling:

```text
none
standard
robust
l2
```

Initial v1 Desc representation config:

```json
{
  "representations": {
    "L01_rdkit_0d_1d_2d": {
      "match": "L01_rdkit_0d_1d_2d.csv",
      "metric": "standardized_euclidean",
      "scaling": "standard"
    },
    "L02_ecfp4_bit": {
      "match": "L02_ecfp4_bit.csv",
      "metric": "tanimoto",
      "scaling": "none"
    },
    "L03_ecfp4_count": {
      "match": "L03_ecfp4_count.csv",
      "metric": "cosine",
      "scaling": "none"
    },
    "L04_ecfp6_bit": {
      "match": "L04_ecfp6_bit.csv",
      "metric": "tanimoto",
      "scaling": "none"
    },
    "L05_ecfp6_count": {
      "match": "L05_ecfp6_count.csv",
      "metric": "cosine",
      "scaling": "none"
    },
    "L06_fcfp4_bit": {
      "match": "L06_fcfp4_bit.csv",
      "metric": "tanimoto",
      "scaling": "none"
    },
    "L07_fcfp4_count": {
      "match": "L07_fcfp4_count.csv",
      "metric": "cosine",
      "scaling": "none"
    },
    "L08_maccs_keys": {
      "match": "L08_maccs_keys.csv",
      "metric": "tanimoto",
      "scaling": "none"
    },
    "L09_atom_pair": {
      "match": "L09_atom_pair.csv",
      "metric": "cosine",
      "scaling": "none"
    },
    "L10_topological_torsion": {
      "match": "L10_topological_torsion.csv",
      "metric": "cosine",
      "scaling": "none"
    },
    "L11_rdkit_fragment_counts": {
      "match": "L11_rdkit_fragment_counts.csv",
      "metric": "cosine",
      "scaling": "none"
    }
  }
}
```

When a descriptor CSV has no matching representation block:

- skip by default
- record a warning

Optional future behavior may allow a default fallback metric, but v2 Phase1 should prefer explicit metric definitions.

## 7. Feature Preparation

For each descriptor CSV:

1. Read CSV.
2. Detect ID column.
3. Remove known non-feature columns.
4. Convert candidate feature columns to numeric.
5. Drop all-missing numeric columns.
6. Drop constant columns by default.
7. Inner join with original CSV rows that have valid property values.
8. Apply representation-specific scaling.

Missing feature values:

```text
median impute by default
then fill remaining missing values with 0
```

This imputation is local to the analysis matrix and does not modify source files.

## 8. Distance and kNN

For each representation:

1. Build the feature matrix.
2. Compute pairwise distance matrix.
3. For each compound, select `k` nearest neighbors excluding self.

Effective k:

```text
effective_k = min(config.knn.k, n_valid_compounds - 1)
```

kNN edges should be stored in long format.

Distance conventions:

- lower distance means more similar
- Tanimoto distance is `1 - tanimoto_similarity`
- Jaccard distance is equivalent to Tanimoto distance for binary vectors
- Cosine distance is `1 - cosine_similarity`

## 9. Metrics

### 9.0 Primary Representation Comparison

The primary comparison should use kNN property consistency metrics that do not compare raw distance magnitudes across representation metrics:

```text
median_abs_delta_property_among_knn
median_local_property_variance
neighbor_property_autocorrelation
```

The primary comparison rank is the mean rank across:

```text
rank_by_median_abs_delta_property_among_knn
rank_by_median_local_property_variance
rank_by_neighbor_property_autocorrelation
```

Lower `primary_comparison_rank_score` is better.

Raw SALI is diagnostic. It should not be treated as the first cross-representation criterion.

### 9.1 SALI

Raw SALI is a cliff diagnostic.

For each kNN edge `(i, j)`:

```text
delta_property = abs(property_i - property_j)
SALI = delta_property / max(distance(i,j), epsilon)
```

Default:

```json
{
  "sali": {
    "epsilon": 1e-6
  }
}
```

Report distribution statistics per representation:

- count
- mean
- median
- p75
- p90
- p95
- p99
- max

Lower values are better within the same representation.

Because raw SALI divides by representation-specific distance values, it is primarily meaningful within the same representation.

Also report distance-percentile-normalized SALI:

```text
distance_percentile_within_representation =
  empirical percentile rank of the kNN edge distance within that representation

normalized_sali =
  delta_property / max(distance_percentile_within_representation, epsilon)
```

Normalized SALI is a secondary cross-representation diagnostic, not the primary comparison criterion.

### 9.2 Local Property Variance

For each compound:

```text
local_values = property of self + property values of k nearest neighbors
local_property_variance = variance(local_values)
```

If `include_self_in_local_variance` is false, use only neighbor property values.

Report per-compound values and representation-level summary:

- mean
- median
- p75
- p90
- p95

Lower values are better.

### 9.3 Median Absolute Property Delta Among kNN

For each compound:

```text
median_abs_delta_property_among_knn =
  median(abs(property_self - property_neighbor_j) for j in kNN)
```

Also report representation-level median and upper quantiles.

Lower values are better.

### 9.4 Distance-Property Spearman Correlation

For each representation, compute Spearman rank correlation between:

```text
neighbor distance
absolute property delta
```

using kNN edges.

Higher positive values generally indicate better landscape consistency: larger distances tend to correspond to larger property differences.

### 9.5 Neighbor Property Autocorrelation

For each representation, compute correlation between:

```text
property_i
property_j
```

over kNN edges `(i, j)`.

Use Pearson correlation by default, with Spearman as an optional additional value.

Higher values are better.

## 10. Output Artifacts

For a concise user-facing explanation of each output file and figure, see:

```text
docs/CONDUCTOR_v2_phase1_sal_output_guide.md
```

### 10.1 Required CSV Outputs

```text
sal_representation_summary.csv
sal_knn_edges.csv
sal_local_metrics.csv
sal_sali_distribution.csv
sal_metric_ranking.csv
```

### 10.2 `sal_representation_summary.csv`

Recommended columns:

```text
representation_id
descriptor_file
metric
scaling
compound_count
feature_count
effective_k
primary_comparison_rank
primary_comparison_rank_score
median_sali
p90_sali
p95_sali
median_normalized_sali
p90_normalized_sali
p95_normalized_sali
median_local_property_variance
p90_local_property_variance
median_abs_delta_property_among_knn
distance_property_spearman_correlation
neighbor_property_autocorrelation
rank_by_median_abs_delta_property_among_knn
rank_by_median_normalized_sali
rank_by_median_sali
rank_by_p90_sali
```

### 10.3 `sal_knn_edges.csv`

Recommended columns:

```text
representation_id
descriptor_file
compound_id
neighbor_compound_id
neighbor_rank
distance
distance_percentile_within_representation
property
neighbor_property
abs_delta_property
sali
normalized_sali
```

### 10.4 `sal_local_metrics.csv`

Recommended columns:

```text
representation_id
descriptor_file
compound_id
property
local_mean_property
local_median_property
local_property_variance
median_abs_delta_property_among_knn
mean_abs_delta_property_among_knn
max_abs_delta_property_among_knn
```

### 10.5 `sal_sali_distribution.csv`

Recommended columns:

```text
representation_id
descriptor_file
count
mean
median
p75
p90
p95
p99
max
normalized_count
normalized_mean
normalized_median
normalized_p75
normalized_p90
normalized_p95
normalized_p99
normalized_max
```

### 10.6 `sal_metric_ranking.csv`

Recommended columns:

```text
metric_name
direction
representation_id
descriptor_file
metric_value
rank
```

Directions:

```text
lower_is_better
higher_is_better
```

## 11. Visualization Requirements

Figures are required by default.

Output directory:

```text
figures/
```

### 11.1 Primary Comparison Figure

Required:

```text
figures/primary_representation_comparison.png
```

This is the first figure for representation-method comparison. It ranks representations by distance-scale-independent kNN property consistency.

### 11.2 SALI Diagnostic Figures

SALI may have multiple figures because it is useful for cliff diagnostics, but raw SALI should not be used as the first representation comparison criterion.

Required:

```text
figures/sali_distribution_by_representation.png
figures/sali_ranking.png
figures/distance_vs_abs_delta_property.png
```

Recommended visual forms:

- normalized SALI distribution: violin, boxplot, or ECDF by representation
- normalized SALI ranking: horizontal bar plot of median and p90 normalized SALI
- distance-property plot: scatter or hexbin of distance vs absolute property delta

### 11.3 Auxiliary Metric Figures

Each auxiliary metric should have at least one clear visualization. By default, do not generate more than two figures per auxiliary metric.

Required:

```text
figures/local_variance_vs_local_property.png
figures/auxiliary_metric_summary.png
```

`local_variance_vs_local_property.png`:

```text
x-axis: local mean or median property
y-axis: local property variance
point: compound
color or facet: representation
```

This figure is the main continuous alternative to Top/Middle/Low binning.

`auxiliary_metric_summary.png` should summarize:

- median local property variance
- median absolute property delta among kNN
- distance-property Spearman correlation
- neighbor property autocorrelation

Recommended form:

- small multiples of horizontal bar plots
- or a normalized heatmap with metric direction clearly indicated

### 11.4 Optional Property Stratification

Property binning is optional and disabled by default.

Recommended config:

```json
{
  "property_stratification": {
    "enabled": false,
    "quantiles": [0.2, 0.8],
    "labels": ["low", "middle", "high"]
  }
}
```

Use it only when the continuous scatter suggests different behavior in high- or low-property regions.

## 12. Manifest and Warnings

Required JSON outputs:

```text
sal_manifest.json
sal_warnings.json
```

`sal_manifest.json` should include:

- skill name
- analysis name
- input CSV
- descriptor directory
- output directory
- property column
- excluded property row count
- config path
- representation configs used
- output files
- created timestamp
- primary comparison basis

`sal_warnings.json` should include:

- missing descriptor directory
- skipped descriptor files
- missing property values
- non-numeric property values
- insufficient compound count for kNN
- unmatched descriptor IDs
- metric calculation failures

## 13. Error Policy

Hard errors:

- input CSV cannot be read
- compound ID column cannot be determined
- property column cannot be determined
- multiple property candidates are found and no explicit property column is supplied
- no descriptor CSV can be used
- no representation has enough valid compounds for kNN

Soft warnings:

- descriptor file skipped because no metric config matched
- descriptor file skipped because no numeric features exist
- descriptor rows ignored because IDs are not in input CSV
- input compounds excluded because property is missing or non-numeric

## 14. CLI

Recommended command:

```powershell
.venv\Scripts\python.exe .claude\skills\cs-conductor-analysis-sal\scripts\run_sal_phase1.py `
  --input chemble_jak2.csv `
  --config config\CONDUCTOR_v2_sal_phase1_config.json
```

Useful overrides:

```powershell
--id-column ID
--property-column pIC50
--descriptions-dir descriptions\chemble_jak2
--outdir analysis\chemble_jak2\structure_activity_landscape
--k 10
```

## 15. Acceptance Criteria

Phase1 is acceptable when:

1. `cs-conductor-analysis-sal` exists as a standalone Skill.
2. It reads original CSV and descriptor CSVs from `descriptions/<input_csv_stem>/`.
3. It does not read `groups/<input_csv_stem>/`.
4. Metric definitions are config-driven.
5. New descriptor representations can be added by editing config.
6. kNN `k` is configurable.
7. Primary comparison rank is based on distance-scale-independent kNN property consistency.
8. Raw SALI is computed on kNN edges for each representation as a diagnostic.
9. Normalized SALI is computed for secondary diagnostics.
10. Local property variance is computed per compound.
11. Median absolute property delta among kNN is computed.
12. Distance-property Spearman correlation is computed.
13. Neighbor property autocorrelation is computed.
14. Required CSV outputs are written.
15. Required figures are written.
16. Manifest and warnings are written.
17. JAK sample can be analyzed end-to-end after Desc generation.
