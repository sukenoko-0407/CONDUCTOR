---
name: matched-molecular-pair-report
description: Build a standalone canonical matched molecular pair (MMP) SQLite database from a compound CSV, or render the preserved 0.1.11 interactive HTML evidence report for explicitly requested compound IDs from an existing database. Use for MMP work outside CONDUCTOR; do not add it to a CONDUCTOR catalog, DAG, Run, or capability route.
---

# Standalone Matched Molecular Pair Report

Use this Skill independently of CONDUCTOR. It has exactly two workflows:

1. `build`: create a canonical, target-independent MMP SQLite database from CSV.
2. `report`: open an existing database read-only and generate interactive reports for explicit compound IDs.

Read [README.md](README.md) before the first run. Use absolute input, database, and output paths. Require a new or empty output directory; never overwrite an earlier result.

Run through the pinned Pixi environment:

```bash
cd <SKILL_DIR>/env
pixi run python ../scripts/run.py --help
```

For `build`, require the user to state the ID, SMILES, endpoint columns and whether a larger or smaller endpoint is favorable. Do not infer endpoint direction. Invalid SMILES remain in coverage but are excluded from MMP generation.

For `report`, require one or more exact database compound IDs. Do not select Top-1 compounds, analysis units, clusters, or targets automatically. The source database is immutable and is opened read-only.

After execution, inspect `standalone_run_summary.json`, the relevant audit JSON, and `standalone_artifact_manifest.json`. Treat a failed audit as a failed run. Open `mmp_database_report.html` after `build`, or `mmp_report.html` after `report`.

Do not register this Skill in `CONDUCTOR_modules/catalog/catalog.json` or any CONDUCTOR pipeline plan. The historical `A008-*` markers retained inside report templates are format-version identifiers only, not a live CONDUCTOR integration.

