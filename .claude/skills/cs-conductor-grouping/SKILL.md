---
name: cs-conductor-grouping
description: Detect molecule ID and SMILES columns from SAR CSV files, validate IDs, ingest optional user-defined grouping columns and descriptor CSVs from descriptions/<input_csv_stem>, and generate grouping artifacts under groups/<input_csv_stem> for downstream SAR analysis.
allowed-tools: Read Write Bash Grep Glob
---

# Grouping

Use this Project Skill when a SAR CSV must be organized into comparison groups for downstream LBDD, ML, SBDD, or integrated interpretation. The operation name is `Grouping`; the explicit command is `/grouping`.

## Inputs

- A CSV containing at least a molecule identifier column and a SMILES-like structure column.
- Optional Wet/Virtual and human-defined grouping columns.
- Optional descriptor CSV files in `descriptions/<input_csv_stem>/`.
- Optional config JSON. Use `${CLAUDE_SKILL_DIR}/config/default_grouping_config.json` when none is supplied.
- User-facing override config: `config/CONDUCTOR_v1_grouping_config.json`.

## Outputs

Write outputs to `groups/<input_csv_stem>/` unless the user specifies another directory:

- `compounds_master.csv`
- `excluded_compounds.csv`
- `group_registry.json`
- `group_membership.csv`
- `group_membership_matrix.csv`
- `group_relations.json`
- `selected_groups.json`
- `group_summary.json`
- `group_graph_packet.json`
- `grouping_warnings.json`
- `grouping_manifest.json`
- `detected_schema.json`
- `column_detection_report.json`
- Context compatibility aliases when enabled: `context_registry.json`, `context_membership.csv`, `context_relations.json`, `selected_contexts.json`

`group_membership_matrix.csv` is the main consolidated final artifact for downstream table workflows. It contains one row per compound and one column per group. Group columns use `0` for false/non-member and `1` for true/member.

## Workflow

1. Locate the input CSV.
2. Run `detect_columns.py` unless ID and SMILES columns are explicitly specified.
3. Ask the user only if ID or SMILES columns are ambiguous or missing.
4. Check whether the user requested specific grouping columns.
5. If requested, identify the grouping columns; ask only if the requested columns are ambiguous or absent.
6. Stop with an error if the input ID column has missing or duplicated IDs.
7. Run `run_grouping.py` with detected or user-specified columns.
8. Read compatible descriptor CSVs from `descriptions/<input_csv_stem>/` when present.
9. Verify that required artifacts exist and are non-empty where applicable.
10. Summarize generated groups and warnings.

## Column Detection Rules

- Infer molecule ID using column-name matches, low missingness, uniqueness, string-likeness, and low SMILES-likeness.
- Infer SMILES using column-name matches plus RDKit parse valid ratio. If RDKit is unavailable, the script emits a warning and uses a conservative SMILES-like heuristic for detection only.
- Detect grouping candidates from categorical columns whose unique values are neither too sparse nor near-row-unique.
- Detect Wet/Virtual columns from names such as `is_virtual`, `virtual`, `wet_virtual`, and values such as `true/false`, `1/0`, `wet/virtual`, `measured/predicted`, and `experimental/virtual`.
- Treat all compounds as Wet if no Wet/Virtual column is found, and record a warning.
- Treat missing or duplicated input IDs as hard errors. Do not generate replacement IDs or rename duplicates.
- Record invalid SMILES in `excluded_compounds.csv`; do not treat them as hard errors.

## Ask-User Policy

Ask only for:

- Missing or ambiguous Molecule ID column.
- Missing or ambiguous SMILES column.
- Multiple high-confidence SMILES columns that cannot be distinguished.
- User-requested grouping columns that cannot be identified.
- CSV parse failure.
- Extremely low SMILES valid ratio.

Continue with warnings for all other uncertainty.

## Execution Command

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_grouping.py \
  --input data/input.csv \
  --config ${CLAUDE_SKILL_DIR}/config/default_grouping_config.json
```

Useful overrides:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_grouping.py \
  --input data/input.csv \
  --config config/CONDUCTOR_v1_grouping_config.json \
  --id-column Compound_ID \
  --smiles-column SMILES \
  --grouping-columns human_series,scaffold_class \
  --skip-mcs
```

## Descriptor CSV Integration

By default, Grouping reads CSV files from:

```text
descriptions/<input_csv_stem>/
```

Each descriptor CSV must contain a compound ID column. Known non-feature columns such as `canonical_smiles`, `mol_parse_ok`, and `descriptor_error` are ignored, and all usable numeric columns are treated as vector dimensions. Multiple descriptor CSV files are clustered independently.

## Default Grouping Methods

By default, Grouping runs:

- Human-defined groups
- Murcko scaffold groups
- MCS groups
- BRICS/RECAP fragment groups
- Morgan/Tanimoto structural similarity groups
- Descriptor CSV clustering groups
- Meta groups

Vector clustering methods default to all supported methods:

- Butina
- hierarchical
- DBSCAN
- Louvain
- Leiden
- connected components

The default config runs multiple conservative parameter patterns for these methods. Users can restrict methods or parameter sweeps by editing the config.

## Group Filtering

By default, CONDUCTOR_v1 accepts only groups with at least 5 compounds:

```json
{
  "group_filters": {
    "min_compound_count": 5
  }
}
```

Groups with `compound_count < 5` are removed from final `group_registry.json`, `group_membership.csv`, `group_membership_matrix.csv`, relations, graph packet, and selected groups. Dropped counts are written to `group_filter_report.json`.

## Validation Checklist

- Confirm `detected_schema.json` contains `id_column` and `smiles_column`.
- Confirm invalid or unsupported structures are represented in `excluded_compounds.csv`, not silently dropped.
- Confirm missing or duplicate input IDs stop the run with a clear error.
- Confirm `group_filter_report.json` records any groups dropped by `min_compound_count`.
- Confirm `group_membership_matrix.csv` exists and contains `compound_id` plus one 0/1 column per group.
- Confirm `group_registry.json`, `group_membership.csv`, `group_relations.json`, `selected_groups.json`, and `grouping_manifest.json` exist.
- Confirm schema validation passes when `jsonschema` is available.
- Confirm the final user summary includes input CSV, detected columns, grouping columns, processed compound count, excluded compound count, generated group counts by type, output directory, and major warnings.

## Do Not Do

- Do not make SAR conclusions or mechanism claims.
- Do not run MMP, activity cliff, ML, docking, ProLIF, pose, or integrated interpretation analysis.
- Do not train models or generate new compound proposals.
- Do not normalize activity values.
- Do not generate HTML reports.
- Do not modify the input CSV in place.
- Do not create replacement IDs for missing IDs.
- Do not rename duplicate IDs.
- Do not discard ambiguous rows without recording them.
- Do not ask unnecessary questions.
