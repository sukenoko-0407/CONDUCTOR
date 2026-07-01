---
name: cs-conductor-desc-ligand
description: Generate RDKit ligand-only descriptors and fingerprints from CSV files, with automatic ID/SMILES column inference and split descriptor CSV outputs under descriptions per input CSV stem. Use when the user asks Claude Code to calculate RDKit molecular descriptors, Morgan/ECFP/FCFP fingerprints, MACCS/AtomPair/Torsion fingerprints, RDKit fragment-count descriptors, or low-cost RDKit 3D ligand descriptors with ETKDG/MMFF conformer generation.
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, LS
---

# RDKit Ligand Descriptor Generation

## Purpose

Generate ligand-only descriptions from an input CSV. Outputs are split by descriptor set under `descriptions/<input_csv_stem>/` so downstream QSAR/SAR workflows and the Grouping Skill can consume stable `Lxx_*.csv` files. Descriptions include RDKit descriptors/fingerprints, optional Mordred descriptors, optional pharmacophore fingerprints, optional pretrained embeddings, and optional ligand-only quantum descriptors.

## When To Use

Use this Skill when the user provides a CSV containing low-molecular-weight compounds and wants ligand-only descriptors, fingerprints, or embeddings. Do not use it for grouping, Murcko grouping, BRICS/RECAP grouping, protein-ligand complex descriptors, docking poses, MOE execution, or QSAR model training.

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

Pretrained embedding with a local model directory:

```bash
uv run python -m src.run_descriptors \
  --input path/to/input.csv \
  --sets L30 \
  --model-dir L30=C:\path\to\ChemBERTa-100M-MLM \
  --overwrite
```

For repeated use, put local model paths in `config/model_registry.yaml`. Command-line `--model-dir` overrides the registry for that run.

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
- L14: RDKit 3D descriptors, requires `--enable-3d`; conformers are generated with bundled RDKit ETKDG + MMFF94s minimization
- L15: USR/USRCAT, requires `--enable-3d`; uses the same bundled conformer generator
- L16: basic 3D shape descriptors, requires `--enable-3d`; uses the same bundled conformer generator
- L17: Mordred 2D descriptors, optional
- L18: Mordred 3D descriptors, requires `--enable-3d`
- L19: RDKit path fingerprint, optional
- L20: RDKit pattern fingerprint, optional
- L21: RDKit layered fingerprint, optional
- L22: Avalon fingerprint, optional and requires RDKit Avalon support
- L23: chiral Morgan fingerprint, optional
- L24: Gobbi 2D pharmacophore folded bit fingerprint, optional
- L25: Gobbi 2D pharmacophore TruncatedSVD representation, optional and dataset-specific
- L30-L49: pretrained embedding adapters, optional and require local model directories
- L60: tblite/xTB single-point descriptors, optional, requires `--enable-3d` and `tblite-python`

L12 and L13 are intentionally not emitted in CONDUCTOR_v1. Murcko, BRICS, and RECAP grouping belong to `cs-conductor-grouping`.

Heavy and external-dependency sets are disabled by default. Run them explicitly with `--sets`.

## Failure Handling

Invalid SMILES rows are retained. Descriptor values are left missing, `descriptor_error` is populated, and `errors.csv` records details. Existing outputs are not overwritten unless `--overwrite` is passed.

## Out Of Scope

MOE is not executed. MOE supplementation candidates are documentation-only in `docs/moe_coverage_table.md`.
