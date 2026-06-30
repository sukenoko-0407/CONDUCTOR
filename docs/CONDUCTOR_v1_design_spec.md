# CONDUCTOR_v1 Design Specification

## 1. Objective

This document defines the CONDUCTOR_v1 implementation target for the two Project Skills in this repository:

- `.claude/skills/cs-conductor-desc-ligand`
- `.claude/skills/cs-conductor-grouping`

CONDUCTOR_v1 connects the two Skills through filesystem artifacts:

- Desc writes descriptor vectors to `descriptions/<input_csv_stem>/`.
- Grouping reads compatible descriptor CSVs from `descriptions/<input_csv_stem>/`.
- Grouping writes group artifacts to `groups/<input_csv_stem>/`.

The Skills remain loosely coupled. Grouping must not depend on an internal Desc Python API. It only depends on the descriptor CSV contract.

## 2. Repository-Level Directory Layout

Expected top-level runtime directories:

```text
CONDUCTOR/
  descriptions/
    <input_csv_stem>/
      *.csv
      run_metadata.json
      errors.csv
  groups/
    <input_csv_stem>/
      group_registry.json
      group_membership.csv
      ...
```

These directories are runtime output directories and should not be required to exist before execution.

## 3. Desc Skill v1 Specification

### 3.1 Responsibility

The Desc Skill generates ligand-only descriptor and fingerprint CSV files.

It must:

- accept an input CSV
- infer or accept compound ID and SMILES columns
- parse SMILES using RDKit
- retain invalid rows in descriptor outputs when configured
- calculate descriptor sets
- write outputs to `descriptions/<input_csv_stem>/` by default
- write `errors.csv`
- write `run_metadata.json`

It must not:

- generate grouping artifacts
- make SAR conclusions
- run MCS grouping
- run Murcko grouping
- run BRICS/RECAP grouping
- normalize biological activity
- train models

### 3.2 Default Output Directory

The v1 default output directory is:

```text
descriptions/<input_csv_stem>
```

Example:

```powershell
python -m src.run_descriptors --input C:\data\chemble_jak2.csv
```

Default output:

```text
descriptions/chemble_jak2/
```

The CLI may still allow `--output-dir` as an override.

### 3.3 Descriptor Set Changes

Remove these descriptor sets from Desc:

- `L12 scaffold`
- `L13 brics_recap`

Reason:

- Murcko scaffold grouping belongs to Grouping.
- BRICS/RECAP fragment grouping will be implemented in Grouping.

Retain:

- L01 RDKit 0D/1D/2D descriptors
- L02 ECFP4 bit
- L03 ECFP4 count
- L04 ECFP6 bit
- L05 ECFP6 count
- L06 FCFP4 bit
- L07 FCFP4 count
- L08 MACCS keys
- L09 AtomPair
- L10 TopologicalTorsion
- L11 RDKit fragment counts
- L14 RDKit 3D descriptors, gated by `--enable-3d`
- L15 USR/USRCAT, gated by `--enable-3d`
- L16 basic 3D shape descriptors, gated by `--enable-3d`

Do not renumber L14-L16 in v1. Keeping the IDs stable is preferable to introducing a breaking semantic renumbering.

### 3.4 Descriptor CSV Format

Desc output CSVs should continue to include common metadata columns:

```text
compound_id, canonical_smiles, mol_parse_ok, descriptor_error, <features...>
```

Grouping will ignore known non-feature columns and use only numeric feature columns.

### 3.5 Implemented Desc File State

The v1 implementation is centered on:

- `.claude/skills/cs-conductor-desc-ligand/SKILL.md`
- `.claude/skills/cs-conductor-desc-ligand/config/descriptor_sets.yaml`
- `.claude/skills/cs-conductor-desc-ligand/src/run_descriptors.py`

`src/scaffold_fragment.py` and the Skill-local test/example folders are not part of the v1 runtime Skill contents. L12/L13 call paths were removed.

## 4. Grouping Skill v1 Specification

### 4.1 Responsibility

The Grouping Skill generates grouping artifacts from:

- the original input CSV
- structure-derived grouping builders
- optional descriptor CSVs in `descriptions/<input_csv_stem>/`

It must:

- detect or accept ID and SMILES columns
- validate IDs strictly
- perform only minimal structure preparation
- record invalid SMILES
- build structure groups
- build descriptor-file clustering groups
- write all outputs to `groups/<input_csv_stem>/` by default

It must not:

- generate replacement IDs for missing IDs
- rename duplicate IDs
- normalize activity values
- train ML models
- perform SAR interpretation
- require Desc internals

### 4.2 Default Output Directory

The v1 default output directory is:

```text
groups/<input_csv_stem>
```

Example:

```powershell
python .claude\skills\cs-conductor-grouping\scripts\run_grouping.py --input chemble_jak2.csv
```

Default output:

```text
groups/chemble_jak2/
```

The CLI may still allow `--outdir` as an override.

### 4.3 Strict ID Validation

Before any grouping artifact generation, Grouping must validate the ID column from the original input CSV.

Hard error conditions:

- ID column cannot be detected and was not explicitly specified.
- ID column contains blank or missing values.
- ID column contains duplicate values.

When any hard error is found:

- stop execution
- do not generate group artifacts
- print a clear error message
- include row numbers or example offending IDs when possible

Required behavior change:

- remove automatic `ROW_000001` ID generation
- remove duplicate ID rewriting such as `CMPD1__DUP42`

### 4.4 Minimal Structure Preparation

Grouping keeps only minimal preparation required for structure builders.

Allowed:

- parse SMILES with RDKit
- create canonical SMILES for valid molecules
- write invalid SMILES rows to `excluded_compounds.csv`
- retain valid compounds in `compounds_master.csv`
- normalize Wet/Virtual values only for MCS sampling if a relevant column is available

Not allowed in Grouping v1:

- activity normalization
- pIC50 conversion
- IC50 unit conversion
- activity-based prioritization
- broad imputation
- user data rewriting

If activity preprocessing is required later, create a separate preprocessing Skill.

### 4.5 Structure-Based Group Builders

Default enabled builders:

- human group builder
- Murcko group builder
- MCS group builder
- BRICS/RECAP fragment group builder
- similarity/vector clustering builder
- meta group builder

### 4.6 BRICS/RECAP Fragment Grouping

The Grouping Skill includes a BRICS/RECAP fragment builder.

Implemented file:

```text
.claude/skills/cs-conductor-grouping/scripts/build_fragment_groups.py
```

The builder should:

- use RDKit BRICS decomposition
- use RDKit RECAP decomposition
- aggregate fragments across valid compounds
- create one group per retained fragment
- write group registry and membership records

Recommended group types:

```text
brics_fragment
recap_fragment
```

Recommended group sources:

```text
brics_recap_fragment_builder
```

Implemented group ID prefix:

```text
GRP_FRAG_001
```

Recommended membership sources:

```text
fragment:brics
fragment:recap
```

Default config:

```json
{
  "brics_recap_fragment_builder": {
    "enabled": true,
    "min_fragment_compound_count": 3,
    "min_fragment_heavy_atoms": 4,
    "max_fragments_per_method": 200,
    "include_single_atom_fragments": false,
    "write_fragment_diagnostics": true
  }
}
```

Diagnostic outputs:

```text
fragment_group_summary.csv
```

Recommended diagnostic columns:

```text
method,fragment_smiles,fragment_heavy_atoms,compound_count,wet_count,virtual_count,group_id
```

## 5. Descriptor File Integration in Grouping

### 5.1 Descriptor Discovery

Grouping should look for descriptor CSVs in:

```text
descriptions/<input_csv_stem>/*.csv
```

The path should be configurable.

Recommended config:

```json
{
  "description_inputs": {
    "enabled": true,
    "base_dir": "descriptions",
    "subdir": null,
    "file_glob": "*.csv"
  }
}
```

If `subdir` is null, use the input CSV stem.

Files such as `errors.csv` should be skipped unless they contain usable numeric features and pass the descriptor contract. A practical implementation should skip known non-descriptor names:

```text
errors.csv
run_metadata.csv
```

### 5.2 Descriptor CSV Contract

Each descriptor CSV must contain one compound ID column.

Accepted ID column names should include:

```text
compound_id
Compound_ID
ID
id
mol_id
molecule_id
```

All feature columns are selected by this rule:

1. Exclude known non-feature columns.
2. Keep columns that can be converted to numeric.
3. Drop columns that are all missing after numeric conversion.

Known non-feature columns:

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

### 5.3 Descriptor ID Matching

Descriptor rows should be inner-joined to valid Grouping compounds by compound ID.

If a descriptor file contains IDs not present in the input CSV:

- ignore those rows
- record a warning

If valid input compounds are missing from a descriptor file:

- cluster only the compounds present in that descriptor file
- record a warning

Hard error only when:

- no ID column can be found in the descriptor CSV
- no numeric feature columns are available
- fewer than the configured minimum compounds are available for clustering

These errors should skip that descriptor file, not stop the entire Grouping run.

### 5.4 Multiple Descriptor Files

If multiple descriptor CSVs exist, cluster each file independently.

Do not merge feature spaces by default.

Each descriptor file should produce method-specific and parameter-specific groups. Group definitions must record:

- source descriptor file
- feature count
- matched compound count
- scaling method
- clustering method
- parameter pattern

Implemented group source:

```text
descriptor_clustering_builder
```

Implemented group type examples:

```text
descriptor_butina_cluster
descriptor_hierarchical_cluster
descriptor_dbscan_cluster
descriptor_louvain_cluster
descriptor_leiden_cluster
descriptor_connected_component
```

## 6. Vector Clustering Design

### 6.1 Default Method Set

Default config must run all methods:

```json
{
  "methods": [
    "butina",
    "hierarchical",
    "dbscan",
    "louvain",
    "leiden",
    "connected_components"
  ]
}
```

Users can restrict the methods by editing the config.

### 6.2 Parameter Patterns

Each method supports multiple parameter patterns by default.

Recommended config shape:

```json
{
  "parameter_sweeps": {
    "butina": {
      "similarity_thresholds": [0.6, 0.7, 0.8]
    },
    "hierarchical": {
      "similarity_thresholds": [0.6, 0.7, 0.8],
      "linkages": ["average"]
    },
    "dbscan": {
      "similarity_thresholds": [0.6, 0.7, 0.8],
      "min_samples": [3, 5]
    },
    "louvain": {
      "resolutions": [0.5, 1.0, 1.5],
      "graph_modes": ["top_k_weighted_graph"],
      "top_k_neighbors": [10, 20]
    },
    "leiden": {
      "resolutions": [0.5, 1.0, 1.5],
      "graph_modes": ["top_k_weighted_graph"],
      "top_k_neighbors": [10, 20]
    },
    "connected_components": {
      "similarity_thresholds": [0.6, 0.7, 0.8]
    }
  }
}
```

These are conservative initial values. They can be revised after runtime and output-size testing.

### 6.3 Similarity and Distance for Descriptor CSVs

For numeric descriptor CSVs:

- apply per-file numeric feature extraction
- apply per-file scaling before distance calculation
- use cosine similarity by default for descriptor vectors
- allow Euclidean distance where methods require distance matrices

Recommended config:

```json
{
  "descriptor_clustering": {
    "scaling": "standard",
    "similarity_metric": "cosine",
    "min_compounds": 3,
    "drop_constant_features": true,
    "missing_value_strategy": "median_impute"
  }
}
```

This feature preparation is local to clustering and should not be treated as broad data preprocessing.

### 6.4 Similarity and Distance for Structure Fingerprints

The existing structure similarity builder may continue using Morgan fingerprints and Tanimoto similarity.

For fingerprint-based methods:

- Butina uses Tanimoto distance.
- hierarchical can use Tanimoto distance.
- DBSCAN can use Tanimoto distance.
- connected components uses a threshold graph.
- Louvain and Leiden use weighted similarity graphs.

### 6.5 Method-Parameter Group Identity

Every clustering group must carry enough information to trace the method and parameter pattern.

Recommended group definition fields:

```json
{
  "method": "leiden",
  "parameter_set_id": "leiden_res1.0_topk20",
  "source_descriptor_file": "L02_ecfp4_bit.csv",
  "feature_count": 2048,
  "matched_compound_count": 95,
  "scaling": "standard",
  "similarity_metric": "cosine"
}
```

Implemented group ID prefixes:

```text
GRP_SIM_001          # structure fingerprint clustering groups
GRP_DESC_001         # descriptor CSV clustering groups
```

The method and parameter set are stored in each registry entry's `definition`, not encoded into the group ID.

## 7. Grouping Config v1 Requirements

The default config file is:

```text
.claude/skills/cs-conductor-grouping/config/default_grouping_config.json
```

Implemented v1 requirements:

1. Default output path behavior should be `groups/<input_csv_stem>`.
2. Similarity methods should default to all supported methods.
3. Parameter sweeps should be represented in config.
4. Descriptor input discovery should be represented in config.
5. BRICS/RECAP fragment builder should be represented in config.
6. Activity normalization options should be removed from Grouping behavior.
7. Final group filtering should default to `min_compound_count = 5`.

Implemented high-level config structure:

```json
{
  "input_validation": {
    "require_non_missing_ids": true,
    "require_unique_ids": true
  },
  "description_inputs": {
    "enabled": true,
    "base_dir": "descriptions",
    "subdir": null,
    "file_glob": "*.csv"
  },
  "outputs": {
    "base_dir": "groups",
    "subdir": null,
    "write_context_aliases": false,
    "write_graph_packet": true
  },
  "relations": {
    "min_jaccard": 0.5,
    "max_relations": 5000
  },
  "group_filters": {
    "min_compound_count": 5,
    "apply_to_sources": ["*"],
    "write_filter_report": true
  },
  "group_builders": {
    "human_group_builder": {
      "enabled": true
    },
    "murcko_group_builder": {
      "enabled": true
    },
    "mcs_group_builder": {
      "enabled": true,
      "max_mcs_sample_compounds": 1000,
      "max_mcs_pair_count": 1000,
      "timeout_seconds_per_pair": 2
    },
    "brics_recap_fragment_builder": {
      "enabled": true
    },
    "similarity_group_builder": {
      "enabled": true,
      "methods": ["butina", "hierarchical", "dbscan", "louvain", "leiden", "connected_components"]
    },
    "descriptor_clustering_builder": {
      "enabled": true,
      "methods": ["butina", "hierarchical", "dbscan", "louvain", "leiden", "connected_components"]
    },
    "meta_group_builder": {
      "enabled": true
    }
  }
}
```

## 8. Output Artifact Requirements

### 8.1 Required Core Outputs

Grouping must write:

```text
compounds_master.csv
excluded_compounds.csv
group_registry.json
group_membership.csv
group_membership_matrix.csv
group_relations.json
selected_groups.json
group_summary.json
group_graph_packet.json
group_filter_report.json
grouping_warnings.json
grouping_manifest.json
detected_schema.json
column_detection_report.json
```

`group_membership_matrix.csv` is the primary consolidated final artifact for table-based downstream workflows.

Required columns:

```text
compound_id,<group_id_1>,<group_id_2>,...
```

Rules:

- one row per valid compound
- one column per individual group in `group_registry.json`
- group columns must use `group_id` as the column name
- group values must be integer `0` or `1`
- `0` means false/non-member
- `1` means true/member
- compounds may have `1` in multiple group columns
- `group_registry.json` provides labels, types, sources, and definitions for the group ID columns

`group_membership.csv` remains the long-format membership table. `group_membership_matrix.csv` is the wide-format consolidated table.

`group_relations.json` and `group_graph_packet.json` are auxiliary artifacts. Because the matrix contains the full compound-by-group assignment, relation and graph artifacts should be lightweight and controlled by `relations.min_jaccard` and `relations.max_relations`.

`group_filter_report.json` records final group filtering. In CONDUCTOR_v1 the default accepted group threshold is:

```json
{
  "group_filters": {
    "min_compound_count": 5
  }
}
```

Groups with `compound_count < 5` are removed from final registry, membership, matrix, relation, graph, and selected-group outputs. The filter is applied after all builders have produced candidate groups, including meta groups.

### 8.2 Descriptor Clustering Diagnostics

Recommended outputs:

```text
descriptor_file_summary.csv
descriptor_cluster_membership.csv
descriptor_cluster_summary.csv
descriptor_clustering_warnings.json
```

Recommended `descriptor_file_summary.csv` columns:

```text
descriptor_file,id_column,input_row_count,matched_compound_count,feature_count,used_for_clustering,skip_reason
```

Recommended `descriptor_cluster_summary.csv` columns:

```text
descriptor_file,method,parameter_set_id,cluster_id,group_id,cluster_size,center_compound_id
```

### 8.3 Structure Similarity Diagnostics

Current similarity diagnostics can remain, but should include parameter set IDs when multiple parameter patterns run.

Recommended outputs:

```text
similarity_cluster_membership.csv
similarity_cluster_summary.csv
similarity_pair_summary.json
similarity_graph_summary.json
```

### 8.4 Fragment Diagnostics

Recommended output:

```text
fragment_group_summary.csv
```

## 9. Error and Warning Policy

### 9.1 Hard Errors

Stop the run:

- input CSV cannot be read
- ID column is missing or ambiguous beyond resolution
- ID contains missing values
- ID contains duplicate values
- SMILES column is missing or ambiguous beyond resolution

### 9.2 Soft Warnings

Continue the run:

- invalid SMILES rows are excluded from structure builders
- no descriptor directory exists
- descriptor CSV has unmatched extra IDs
- descriptor CSV is skipped because it has no numeric features
- optional clustering dependency is missing for a requested method
- a method is skipped because compound count exceeds guard

### 9.3 Descriptor File Skip Policy

Bad descriptor files should not stop Grouping unless all grouping sources fail and no groups can be created.

## 10. Implementation Summary

### 10.1 Documentation

The v1 documentation set is:

- `docs/CONDUCTOR_v1_overview.md`
- `docs/CONDUCTOR_v1_design_spec.md`
- older planning documents in `docs/archive/`
- user-facing override config in `config/CONDUCTOR_v1_grouping_config.json`

### 10.2 Desc Skill Implementation State

1. Default output directory is `descriptions/<input_csv_stem>`.
2. L12 and L13 are removed from config and default set selection.
3. L12/L13 command paths are removed from `run_descriptors.py`.
4. `SKILL.md` reflects CONDUCTOR_v1 behavior.
5. Skill-local test/example folders were removed from the runtime Skill contents.
6. JAK descriptor generation was verified.

### 10.3 Grouping Skill Implementation State

1. Default output directory is `groups/<input_csv_stem>`.
2. ID auto-generation and duplicate renaming were replaced with hard validation.
3. Activity normalization was removed from Grouping.
4. BRICS/RECAP fragment grouping was added.
5. Default config runs all clustering methods.
6. Parameter sweeps are configured for clustering methods.
7. Descriptor CSV discovery reads `descriptions/<input_csv_stem>/`.
8. Descriptor-file clustering was added.
9. Descriptor clustering diagnostics and manifest fields were added.
10. Final `group_filters.min_compound_count` filtering was added.
11. `group_membership_matrix.csv` was added as the primary consolidated table.
12. JAK end-to-end testing was completed.

## 11. Acceptance Criteria

CONDUCTOR_v1 is acceptable when:

1. Desc writes outputs to `descriptions/<input_csv_stem>/` by default.
2. Desc no longer emits L12 and L13.
3. Grouping writes outputs to `groups/<input_csv_stem>/` by default.
4. Grouping stops on missing input IDs.
5. Grouping stops on duplicated input IDs.
6. Grouping records invalid SMILES in `excluded_compounds.csv`.
7. Grouping creates Murcko groups.
8. Grouping creates MCS groups.
9. Grouping creates BRICS/RECAP fragment groups.
10. Grouping reads compatible CSVs from `descriptions/<input_csv_stem>/`.
11. Grouping ignores known non-feature descriptor columns.
12. Grouping uses only numeric descriptor columns for vector clustering.
13. Multiple descriptor CSVs are clustered independently.
14. Default config runs Butina, hierarchical, DBSCAN, Louvain, Leiden, and connected components.
15. Each clustering method can run multiple parameter patterns.
16. Group registry definitions record descriptor source file, method, and parameter set.
17. Grouping writes `group_membership_matrix.csv` with `compound_id` plus one 0/1 column per group.
18. Grouping defaults to accepting only groups with `compound_count >= 5`.
19. `group_filter_report.json` records dropped group counts.
20. Group relations and graph packet outputs are lightweight auxiliary artifacts, not substitutes for the membership matrix.
21. Grouping remains usable without descriptor files, using structure-based grouping only.
22. Grouping does not perform activity normalization.

## 12. Open Implementation Notes

The following choices are intentionally left as implementation-level details but should be made conservatively:

- exact descriptor-feature scaling implementation
- exact default parameter set IDs
- maximum number of descriptor-clustering groups to emit per file and method
- figure generation for descriptor clustering
- whether missing optional clustering dependencies produce warnings or hard errors when explicitly requested

For v1, prefer robust artifact generation and traceability over aggressive clustering.

## 13. Verification Snapshot

The current v1 implementation was verified on `chemble_jak2.csv`.

Results:

```text
input compounds: 231
invalid SMILES: 0
Desc descriptor sets: L01-L11
Desc output directory: descriptions/chemble_jak2/
Grouping output directory: groups/chemble_jak2/
accepted groups after final filter: 2601
dropped groups by final filter: 2372
group_membership_matrix.csv shape: 231 x 2602
matrix values: 0/1 only
relations: capped at 5000
```

Expected warnings:

```text
is_virtual column not found. All compounds are treated as Wet for grouping.
MCS pair mining was capped at max_mcs_pair_count=1000 out of 26565 possible sampled pairs.
Group filter dropped 2372 groups with compound_count < 5.
```
