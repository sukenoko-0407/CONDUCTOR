# Implementation Notes

## Scope

The agent writes one CSV per descriptor set. Every descriptor CSV starts with:

```text
compound_id, canonical_smiles, mol_parse_ok, descriptor_error
```

Invalid SMILES rows are retained by default. Descriptor values for those rows are empty and the parse error is recorded in both `descriptor_error` and `errors.csv`.

## Column Inference

`src.column_infer.infer_columns` combines column-name scores with sampled value scores. SMILES scoring prioritizes RDKit parse success. ID scoring prioritizes ID-like names, high uniqueness, low missingness, and values that are not valid SMILES. If no ID column is confident enough, `prepare_molecule_table` uses `row_000001` style IDs.

## 3D Descriptors

L14-L16 are gated by `--enable-3d`. They require an external function:

```python
from gen_3d_conf import gen_3d_conformer
```

The adapter accepts an RDKit Mol, an SDF path, or a tuple whose first item is one of those values.
