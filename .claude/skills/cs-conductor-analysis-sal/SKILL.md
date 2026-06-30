---
name: cs-conductor-analysis-sal
description: Analyze Structure-Activity Landscape smoothness for descriptor CSVs under descriptions/input_csv_stem, comparing representations primarily with distance-scale-independent kNN property consistency metrics and using SALI as a cliff diagnostic.
allowed-tools: Read Write Bash Grep Glob
---

# Structure-Activity Landscape Analysis

Use this Project Skill when the user wants to evaluate whether descriptor representations form a smooth property landscape, such as pIC50 landscape smoothness.

## Inputs

- Original CSV containing compound IDs and a numeric property column.
- Descriptor CSV files in `descriptions/<input_csv_stem>/`.
- Optional config JSON. Use `${CLAUDE_SKILL_DIR}/config/default_sal_phase1_config.json` when none is supplied.
- User-facing override config: `config/CONDUCTOR_v2_sal_phase1_config.json`.

## Outputs

Write outputs to `analysis/<input_csv_stem>/structure_activity_landscape/` unless the user specifies another directory:

- `sal_representation_summary.csv`
- `sal_knn_edges.csv`
- `sal_local_metrics.csv`
- `sal_sali_distribution.csv`
- `sal_metric_ranking.csv`
- `sal_warnings.json`
- `sal_manifest.json`
- `figures/primary_representation_comparison.png`
- `figures/sali_distribution_by_representation.png`
- `figures/sali_ranking.png`
- `figures/distance_vs_abs_delta_property.png`
- `figures/local_variance_vs_local_property.png`
- `figures/auxiliary_metric_summary.png`

## Workflow

1. Locate the original input CSV.
2. Detect or accept compound ID and property columns.
3. Locate descriptor CSVs in `descriptions/<input_csv_stem>/`.
4. Match descriptor files to representation metric definitions in config.
5. Extract numeric feature columns and apply representation-specific scaling.
6. Compute kNN with config-defined metric.
7. Compute distance-scale-independent kNN property consistency metrics.
8. Compute raw SALI and normalized SALI as cliff diagnostics.
9. Write CSV summaries and figures.
10. Summarize representation ranking and warnings.

## Core Metrics

Use these as the primary representation-comparison metrics because they do not compare raw distance magnitudes across different descriptor metrics:

- median absolute property delta among kNN
- local property variance
- neighbor property autocorrelation

Use raw SALI as a within-representation cliff diagnostic, not as the first cross-representation ranking criterion:

```text
SALI(i,j) = |property_i - property_j| / max(distance(i,j), epsilon)
```

Also report distance-percentile-normalized SALI for secondary cross-representation diagnostics.

Lower is better:

- median absolute property delta among kNN
- median local property variance
- median normalized SALI
- raw median/p90/p95 SALI, within a representation

Higher is generally better:

- neighbor property autocorrelation
- distance-property Spearman correlation

## Metric Config

Metric definitions live in config. New descriptor representations should be added by editing:

```text
config/CONDUCTOR_v2_sal_phase1_config.json
```

Do not hard-code new descriptor metrics in the Skill unless the config schema itself changes.

## Execution Command

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_sal_phase1.py \
  --input data/input.csv \
  --config config/CONDUCTOR_v2_sal_phase1_config.json
```

Useful overrides:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_sal_phase1.py \
  --input chemble_jak2.csv \
  --property-column pIC50 \
  --k 10
```

## Do Not Do

- Do not use `groups/<input_csv_stem>/`.
- Do not generate grouping artifacts.
- Do not normalize IC50 to pIC50.
- Do not train predictive models.
- Do not modify input CSV or descriptor CSVs.
- Do not make SAR mechanism claims.
