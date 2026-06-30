# uv Environment Setup

This document describes how to recreate the Python environment used by the Grouping Skill.

## Python

Use Python 3.12 if available.

The current environment was created with:

```powershell
uv venv .venv
```

Then install the required packages:

```powershell
uv pip install --python .venv\Scripts\python.exe pandas numpy rdkit networkx scikit-learn jsonschema pyyaml matplotlib igraph leidenalg
```

## Required Packages

Core data handling:

```text
pandas
numpy
```

Cheminformatics:

```text
rdkit
```

Graph and clustering:

```text
networkx
scikit-learn
igraph
leidenalg
```

Validation and Skill metadata:

```text
jsonschema
pyyaml
```

Diagnostics and figures:

```text
matplotlib
```

## Why Each Package Is Needed

| Package | Purpose |
|---|---|
| `pandas` | CSV input/output and tabular artifacts |
| `numpy` | similarity matrices and numeric summaries |
| `rdkit` | SMILES parsing, canonical SMILES, Murcko scaffold, MCS, fingerprints |
| `networkx` | Louvain community detection and graph utilities |
| `scikit-learn` | hierarchical clustering and DBSCAN |
| `igraph` | graph backend for Leiden clustering |
| `leidenalg` | Leiden community detection |
| `jsonschema` | optional artifact schema validation |
| `pyyaml` | Skill validation script dependency |
| `matplotlib` | MCS and similarity diagnostic figures |

## Confirm Installed Versions

Current tested package versions:

```text
attrs==26.1.0
contourpy==1.3.3
cycler==0.12.1
fonttools==4.63.0
igraph==1.0.0
joblib==1.5.3
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
kiwisolver==1.5.0
leidenalg==0.12.0
matplotlib==3.11.0
narwhals==2.22.1
networkx==3.6.1
numpy==2.5.0
packaging==26.2
pandas==3.0.4
pillow==12.2.0
pyparsing==3.3.2
python-dateutil==2.9.0.post0
pyyaml==6.0.3
rdkit==2026.3.3
referencing==0.37.0
rpds-py==2026.5.1
scikit-learn==1.9.0
scipy==1.18.0
six==1.17.0
texttable==1.7.0
threadpoolctl==3.6.0
typing-extensions==4.15.0
tzdata==2026.2
```

To list packages in the local environment:

```powershell
uv pip list --python .venv\Scripts\python.exe
```

## Smoke Test

Run:

```powershell
.venv\Scripts\python.exe -m py_compile (Get-ChildItem -LiteralPath .claude\skills\grouping\scripts -Filter *.py | ForEach-Object { $_.FullName })
```

Check key imports:

```powershell
.venv\Scripts\python.exe -c "import rdkit, pandas, numpy, networkx, sklearn, igraph, leidenalg, matplotlib, jsonschema, yaml; print('ok')"
```

Run the minimal example:

```powershell
.venv\Scripts\python.exe .claude\skills\grouping\scripts\run_grouping.py --input .claude\skills\grouping\examples\minimal_input.csv --outdir outputs\env_smoke_minimal
```

Run the 100-compound style test if the generated input exists:

```powershell
.venv\Scripts\python.exe .claude\skills\grouping\scripts\run_grouping.py --input outputs\test_inputs\synthetic_100_smiles.csv --outdir outputs\env_smoke_100
```

## Notes

- `.venv/` is intentionally ignored by git.
- `outputs/` is intentionally ignored by git.
- `pip` may not be installed inside the uv-created environment; use `uv pip list` and `uv pip install` instead.
- Leiden clustering is a formal supported method in this project and requires both `igraph` and `leidenalg`.
