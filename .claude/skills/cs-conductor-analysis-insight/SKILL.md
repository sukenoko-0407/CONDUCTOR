---
name: cs-conductor-analysis-insight
description: Analyze CONDUCTOR grouping outputs to identify property-enriched, internally consistent, interpretable, and optionally ECFP4-diverse active groups; use when Grouping artifacts under groups/input_csv_stem should be converted into group-level SAR insight tables, figures, and reports.
allowed-tools: Read Write Bash Grep Glob
---

# Group Insight Analysis

Use this Project Skill when the user wants Phase2 analysis of CONDUCTOR groups.

## Inputs

- Original CSV containing compound IDs and a numeric property column.
- Grouping outputs in `groups/<input_csv_stem>/`.
- Optional ECFP4 bit descriptor file at `descriptions/<input_csv_stem>/L02_ecfp4_bit.csv`.
- Optional config JSON. Use `${CLAUDE_SKILL_DIR}/config/default_insight_config.json` when none is supplied.
- User-facing override config: `config/CONDUCTOR_v2_phase2_insight_config.json`.

## Outputs

Write outputs to `analysis/<input_csv_stem>/group_insight/` unless the user specifies another directory:

- `group_insight_summary.csv`
- `group_property_profile.csv`
- `group_enrichment_stats.csv`
- `group_structural_diversity.csv`
- `group_overlap_summary.csv`
- `group_member_details.csv`
- `group_metric_ranking.csv`
- `top_groups_report.md`
- `insight_manifest.json`
- `insight_warnings.json`
- `figures/activity_enrichment_vs_group_size.png`
- `figures/top_group_property_distributions.png`
- `figures/high_activity_vs_ecfp4_tanimoto.png`
- `figures/structural_diversity_vs_consistency.png`
- `figures/top_group_overlap_heatmap.png`
- `figures/group_source_summary.png`

## Workflow

1. Locate the original input CSV.
2. Detect or accept compound ID and property columns.
3. Load `group_membership_matrix.csv` and `group_registry.json`.
4. Join group membership to valid property rows.
5. Compute group property profiles.
6. Compute high/low activity enrichment.
7. Compute activity consistency metrics.
8. Optionally compute within-group ECFP4 Tanimoto structural diversity.
9. Compute overlap and redundancy metrics.
10. Write summary CSVs, figures, and `top_groups_report.md`.

## Key Ranking Concepts

Use multiple transparent ranks:

- `activity_enriched_group_rank`
- `structurally_diverse_active_group_rank`
- `consistent_group_rank`
- `interpretable_group_rank`
- `insight_priority_rank`

The structurally diverse active rank prioritizes:

```text
high activity enrichment + activity consistency + low mean ECFP4 Tanimoto
```

This targets groups where compounds are active despite low ECFP4 similarity.

## Execution Command

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_group_insight.py \
  --input data/input.csv \
  --config config/CONDUCTOR_v2_phase2_insight_config.json
```

Useful overrides:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_group_insight.py \
  --input chemble_jak2.csv \
  --property-column pIC50 \
  --groups-dir groups/chemble_jak2
```

## Do Not Do

- Do not create new groups.
- Do not modify `groups/` artifacts.
- Do not normalize IC50 to pIC50.
- Do not train predictive models.
- Do not generate new compounds.
- Do not make mechanistic SAR claims.
