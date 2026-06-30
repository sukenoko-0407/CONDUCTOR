# RDKit Ligand Descriptor Agent

This directory contains a Skill-style RDKit ligand-only descriptor generator. It reads a CSV with compound IDs and SMILES, infers the relevant columns when they are not specified, and writes one output CSV per descriptor set.

## Environment

The project is configured for `uv`.

```bash
cd descriptor_agent
uv sync --dev
```

Run commands through the local environment:

```bash
uv run python -m src.run_descriptors --input tests/data/sample_ligands.csv --output-dir outputs/sample --overwrite
```

## Descriptor Sets

Default sets are L01-L13:

| ID | Output | Content |
|---|---|---|
| L01 | `L01_rdkit_0d_1d_2d.csv` | RDKit 0D/1D/2D descriptors |
| L02-L07 | ECFP/FCFP CSVs | Morgan bit/count fingerprints |
| L08 | `L08_maccs_keys.csv` | MACCS keys |
| L09 | `L09_atom_pair.csv` | hashed atom-pair count fingerprint |
| L10 | `L10_topological_torsion.csv` | hashed topological-torsion count fingerprint |
| L11 | `L11_rdkit_fragment_counts.csv` | RDKit fragment counts |
| L12 | `L12_scaffold.csv` | Murcko and generic Murcko scaffold |
| L13 | `L13_brics_recap.csv` | BRICS and RECAP fragment lists |

L14-L16 are 3D descriptor sets and run only with `--enable-3d`. They require `gen_3d_conf.gen_3d_conformer` to be importable.

## Input CSV

The input CSV must contain at least one compound ID column and one SMILES column. Column names are not fixed. You can override inference:

```bash
uv run python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/sample \
  --id-col compound_id \
  --smiles-col SMILES \
  --overwrite
```

## Dry Run

```bash
uv run python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --dry-run
```

The dry run reports inferred columns, input row counts, valid/invalid SMILES counts, selected descriptor sets, and planned output filenames.

## Select Sets

```bash
uv run python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/ecfp \
  --sets L02,L03,L04,L05 \
  --overwrite
```

## Output

Each descriptor CSV begins with:

```text
compound_id,canonical_smiles,mol_parse_ok,descriptor_error
```

Invalid SMILES rows are retained by default. `errors.csv` captures molecule parse errors and descriptor failures. `run_metadata.json` records the RDKit version, selected sets, inferred columns, row counts, output filenames, and error counts.

## MOE Coverage

MOE is not called by this implementation. RDKit gaps that may be supplemented by MOE are summarized in `docs/moe_coverage_table.md`.

## Troubleshooting

- If output files already exist, pass `--overwrite`.
- If column inference is ambiguous, pass `--id-col` and `--smiles-col`.
- If L14-L16 fail, confirm `gen_3d_conf.py` is importable and `gen_3d_conformer` returns a molecule with at least one conformer or an SDF path.
