---
name: cs-conductor-desc-ligand
description: Generate RDKit ligand-only descriptors and fingerprints from CSV files, with automatic ID/SMILES column inference and split descriptor CSV outputs under descriptions/<input_csv_stem>. Use when the user asks Claude Code to calculate RDKit molecular descriptors, Morgan/ECFP/FCFP fingerprints, MACCS/AtomPair/Torsion fingerprints, RDKit fragment-count descriptors, or 3D ligand descriptors with an external conformer generator.
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, LS
---

# RDKit Ligand Descriptor Generation

## Purpose

Generate ligand-only RDKit descriptors and fingerprints from an input CSV. Outputs are split by descriptor set under `descriptions/<input_csv_stem>/` so downstream QSAR/SAR workflows and the Grouping Skill can consume stable `Lxx_*.csv` files.

## When To Use

Use this Skill when the user provides a CSV containing low-molecular-weight compounds and wants RDKit descriptors or fingerprints. Do not use it for grouping, Murcko grouping, BRICS/RECAP grouping, protein-ligand complex descriptors, docking poses, MOE execution, ML embeddings, or QSAR model training.

## Claude Code Usage

Claude Code may use `Read`, `Write`, `Edit`, `MultiEdit`, `Bash`, `Glob`, `Grep`, and `LS` for this Skill. Prefer running the CLI through `uv` from the Skill directory so the local `.venv` and locked dependencies are used.

## Input Requirements

The input CSV must contain:

- a compound ID column
- a SMILES column

Column names may vary. The CLI infers ID and SMILES columns from names and values. If inference is uncertain, specify columns explicitly.

## Output Naming

Descriptor CSV files are named exactly:

```text
L01_<descriptor_set_name>.csv
L02_<descriptor_set_name>.csv
...
```

Each descriptor CSV starts with:

```text
compound_id, canonical_smiles, mol_parse_ok, descriptor_error
```

## Commands

Default L01-L11:

```bash
uv run python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --overwrite
```

Dry run:

```bash
uv run python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --dry-run
```

Explicit columns:

```bash
uv run python -m src.run_descriptors \
  --input path/to/input.csv \
  --id-col CompoundID \
  --smiles-col SMILES \
  --overwrite
```

Specific sets:

```bash
uv run python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir descriptions/input_ecfp \
  --sets L02,L03,L04,L05 \
  --overwrite
```

3D sets:

```bash
uv run python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir descriptions/input_3d \
  --sets L14,L15,L16 \
  --enable-3d \
  --overwrite
```

## Descriptor Sets

- L01: RDKit 0D/1D/2D descriptors
- L02: ECFP4 bit
- L03: ECFP4 count
- L04: ECFP6 bit
- L05: ECFP6 count
- L06: FCFP4 bit
- L07: FCFP4 count
- L08: MACCS keys
- L09: AtomPair
- L10: TopologicalTorsion
- L11: RDKit fragment counts
- L14: RDKit 3D descriptors, requires `--enable-3d`
- L15: USR/USRCAT, requires `--enable-3d`
- L16: basic 3D shape descriptors, requires `--enable-3d`

L12 and L13 are intentionally not emitted in CONDUCTOR_v1. Murcko, BRICS, and RECAP grouping belong to `cs-conductor-grouping`.

## Failure Handling

Invalid SMILES rows are retained. Descriptor values are left missing, `descriptor_error` is populated, and `errors.csv` records details. Existing outputs are not overwritten unless `--overwrite` is passed.

## Out Of Scope

MOE is not executed. MOE supplementation candidates are documentation-only in `docs/moe_coverage_table.md`.
