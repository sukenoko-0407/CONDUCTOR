---
name: cs-analysis-matched-molecular-pairs
description: Build or query a reusable matched molecular pair (MMP) database from a CSV containing compound IDs, SMILES, and an endpoint. Use for exhaustive mmpdb-based transform analysis, exact-core and environment-context summaries, Global-to-Cluster comparisons, or Spotfire-ready exports. Supports general use and explicit CONDUCTOR A014 execution.
---

# Matched molecular pair analysis

Use `scripts/launch.py` for every execution. Read [references/mmp_contract.md](references/mmp_contract.md) before changing defaults or interpreting support counts.

## Select the role

- `global-build`: build the immutable run-level MMP database and complete Global report from the input CSV. Run once per input and endpoint.
- `local-screen`: query that database across all registered Clusters and emit one compact screening table. Do not rebuild MMPs.
- `local-detail`: compare Global evidence with one human- or Orchestrator-selected Cluster. A result with no qualifying pairs remains a successful negative result.

Do not infer a role from filenames. In CONDUCTOR mode the Runtime supplies it explicitly.

## Mode boundary

- General use: omit `--conductor`; write the requested database, tables, and HTML only.
- CONDUCTOR use: add `--conductor` and all context IDs. Never invent IDs and never silently fall back to general mode.
- `--output-dir` changes only the destination, not the mode.

## Commands

```bash
python scripts/launch.py global-build --input compounds.csv --id-column compound_id --smiles-column SMILES --endpoint-column activity --higher-is-better true
python scripts/launch.py local-screen --mmp-database mmp_database.sqlite --cluster-registry cluster_registry.json --cluster-membership Cpd_Cluster_matrix.csv
python scripts/launch.py local-detail --mmp-database mmp_database.sqlite --cluster-membership Cpd_Cluster_matrix.csv --cluster-id C000123
```

For CONDUCTOR, Runtime invokes `scripts/launch.py --conductor-request <execution_request.json>`. Do not hand-build the internal context arguments; the Skill adapter maps the validated common Request to this scientific CLI.

`global-build` uses at most 8 fragment jobs and never exceeds `--available-cpu-cores`. This limit changes only resource use; preserve every MMP detail row, summary table, database table, and report.

## Scientific invariants

- Preserve exact core, transform direction, selected environment radii, and compound-pair identity.
- Standard execution uses 1–2 cuts and radii 0–2. Cuts=3 or radii 3–5 require explicit `--extended-search`; do not enable smallest-transformation-only or symmetric expansion.
- Do not standardize molecules or remove salts. Input preparation is a human responsibility.
- Standard execution requires at least eight heavy atoms and fraction >=0.50 in both molecules for the constant core, with at most ten heavy atoms in the variable part.
- Count one Pair × Transform × exact Core once; radius contexts are related observations, not independent pair support.
- Keep endpoint-missing compounds in the structural database but exclude them from effect statistics.
- Treat the database and detail table as evidence stores. Reference cards are bounded candidates, not final scientific conclusions.

## Output discipline

Do not write outside the chosen output directory. `global-build` writes the complete non-compressed `mmp_pair_detail.csv`, normalized stable SQLite, summaries, reference cards, storage profile, and a self-contained Japanese HTML report. The large native mmpdb work database is deleted after canonical export. Later roles open the Global database read-only.
