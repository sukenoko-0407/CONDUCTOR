# Standalone MMP Database and Report

This directory preserves the CONDUCTOR 0.1.11 matched molecular pair calculation and interactive target-report format as a **standalone tool**. It does not require CONDUCTOR, does not use an Execution Request, and is not registered in the current CONDUCTOR catalog or DAG.

The tool supports two operations:

- Build a canonical MMP SQLite database from a CSV file.
- Use an already-built database to render detailed HTML reports for explicitly named compounds.

The detailed target report retains the 0.1.11 presentation: 2D structures, transformation views, target-oriented endpoint differences, direct and transferred evidence, 1-cut/2-cut views, interactive relationship maps, evidence tables, and downloadable CSV artifacts.

## 1. Environment

Pixi is required. The committed `pixi.toml` and `pixi.lock` pin Python, RDKit, pandas, NetworkX, NumPy, and mmpdb. Generated `.pixi/` environments are local files and are not committed.

```bash
cd /absolute/path/to/CONDUCTOR/.claude/skills/matched-molecular-pair-report/env
pixi install --locked
pixi run python ../scripts/run.py --help
```

The examples below assume the current directory is `env/`.

## 2. Build a database from CSV

The input CSV must contain:

- a non-empty, unique compound ID column;
- a SMILES column;
- a numeric endpoint column (missing endpoint values are allowed);
- no more than 5,000 rows under the preserved 0.1.11 contract.

You must explicitly state endpoint direction. For activity values such as pIC50, use `--higher-is-better`. For IC50 in concentration units, use `--lower-is-better`.

```bash
pixi run python ../scripts/run.py build \
  --input /absolute/path/compounds.csv \
  --output-dir /absolute/path/mmp_database_build \
  --id-column compound_id \
  --smiles-column smiles \
  --endpoint-column pIC50 \
  --higher-is-better \
  --workers 8
```

`--workers` controls mmpdb fragmentation and is capped at 8 by the preserved engine. A value above 8 is accepted but does not create more than 8 fragmentation workers.

Important input behavior:

- compound IDs are opaque strings (`001` remains `001`);
- salts are not automatically removed;
- structures are not neutralized, tautomer-normalized, or stereochemically completed;
- invalid SMILES are retained in coverage metadata but excluded from MMP generation;
- the output directory must be new or empty.

Principal build outputs:

- `mmp_database.sqlite` — immutable canonical database;
- `mmp_database_report.html` — build summary;
- `mmp_pair_detail.csv`, `mmp_fragmentations.csv`;
- transformation, context, two-cut quality, and environment summaries;
- `mmp_database_manifest.json`, `mmp_database_audit.json`;
- `standalone_run_summary.json`, `standalone_artifact_manifest.json`.

## 3. Generate reports from an existing database

No source CSV is needed. The report command reads the database's stored compounds, endpoint values, endpoint direction, and structural parameters. The SQLite database is opened read-only and is not copied or modified.

Repeat `--target-id` to create more than one report:

```bash
pixi run python ../scripts/run.py report \
  --database /absolute/path/mmp_database.sqlite \
  --output-dir /absolute/path/mmp_reports_CMP001_CMP017 \
  --target-id CMP001 \
  --target-id CMP017
```

Every target must exist in the database's `compounds` table. Target selection is always human-explicit; the standalone tool does not select Top-1 compounds, clusters, or analysis units.

Principal report outputs:

- `mmp_report.html` — index page linking all requested targets;
- `targets/mmp_target_<id>_<hash>.html` — interactive individual report;
- target relationship-map SVGs, evidence CSVs, and virtual-candidate CSVs;
- `mmp_target_summary.csv`, `mmp_target_registry.csv`;
- `mmp_report_index.json`, `mmp_report_audit.json`;
- `standalone_run_summary.json`, `standalone_artifact_manifest.json`.

The report output repeats canonical pair and summary CSVs so the HTML package is self-contained. The reused database remains outside the output and is recorded as an input with its SHA-256 hash.

## 4. Result acceptance

A successful process exit is not the only acceptance condition. Confirm:

1. `standalone_run_summary.json` has `status: succeeded`.
2. `mmp_database_audit.json` or `mmp_report_audit.json` has `status: passed`.
3. `standalone_artifact_manifest.json` records the expected input hashes and output artifacts.
4. The HTML opens locally and its internal links resolve.

If the command fails, do not reuse its partially populated output directory. Diagnose the error, then run again with a new empty directory.

## 5. Independence from CONDUCTOR

This Skill deliberately contains no `capability.json`, CONDUCTOR launcher, Execution Request adapter, catalog entry, or DAG entry. Historical `A008-*` strings remain only as 0.1.11 HTML template identifiers required by the preserved report audit. They do not create a route from current CONDUCTOR.

Scientific and storage compatibility details are documented in [references/database_contract.md](references/database_contract.md). Source provenance is documented in [references/provenance.md](references/provenance.md).

