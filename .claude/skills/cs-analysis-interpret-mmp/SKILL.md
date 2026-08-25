---
name: cs-analysis-interpret-mmp
description: Human-triggered read-only interpretation of an existing Global A014 MMP database across canonical CONDUCTOR Clusters. Use after a Round to survey variance collapse, Cluster-specific Transform effects, and direction reversals without changing DAG or State.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Read-only MMP Global–Local interpretation

Use only after an explicit human request while the Run is `AWAITING_HUMAN_REVIEW`, `CLOSED`, or has no active Round. This Skill is not part of automatic Round finalization. It never creates a Node or Insight and writes only below `<run_root>/mmp_interpretation/MMPREQ######/`.

Read-only means that canonical Run artifacts and State are immutable. Deterministic derived calculation inside the request directory is allowed: the Skill reads the successful Global A014 SQLite database and canonical `cluster_registry.jsonl`／`cluster_membership.csv`, then computes Local and Outside summaries without rerunning fragmentation. Outside is the nonlocal comparator in which both pair compounds are outside the target Cluster; boundary pairs are kept separate.

全surveyでは、MMPのユニーク化合物PairをClustering Node単位で一度だけClusterへ投影する。全ClusterのLocal supportを先にScreeningし、`min_local_pairs`を満たす`Cluster × Transform`だけについてOutsideとExact Coreの詳細統計を計算する。空または低supportのClusterも`cluster_screening.csv`には残すが、解釈不能なOutside集計を反復しない。これは既存Databaseを変更しない読み取り最適化である。

## Required workflow

1. Run `prepare` with an explicit Run Root and target Round. By default, use a successful Global A014 Node produced in that Round. Add an older `--mmp-node-id` or optional Clustering Node, Cluster, or Transform filter only when the human supplied it.
2. Read only `mmp_interpretation_context.json` first. It contains bounded candidate tables and exact metric definitions.
3. Improve `mmp_interpretation_draft.json` only when scientific prose benefits. Do not invent values or formulas; cite CSV row keys in `evidence`.
4. Run `finalize`, inspect Markdown／HTML, then run `verify`.
5. Report the request directory. Do not attach the result to a later Round unless the human explicitly asks.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare \
  --run-root /path/to/run --round-id RND0001 --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" finalize \
  --request-dir /path/to/run/mmp_interpretation/MMPREQ000001
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" verify \
  --request-dir /path/to/run/mmp_interpretation/MMPREQ000001
```

Focus examples:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare --run-root /path/to/run \
  --round-id RND0002 --clustering-node-id N000120 --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare --run-root /path/to/run \
  --round-id RND0002 --cluster-id C000321 --transform-id TRF-ABCDEF123456 --explicit-request
```

## Scientific contract

- Local pair: both compounds belong to the target Cluster.
- Outside comparator: neither compound belongs to the target Cluster. Boundary pairs with exactly one member are reported separately.
- Use `favorable_delta`; positive always means the endpoint changed in the favorable direction according to the Run's `higher_is_better` setting.
- Compare Global, Local, and Outside medians, IQR, MAD, direction consistency, pair support, independent compounds, and Exact Core support.
- A Clustering-level variance-collapse candidate requires at least two eligible Clusters, positive robust dispersion reduction, and non-overlapping membership. Overlapping structural Cluster systems remain exploratory.
- A Cluster-specific candidate is prioritized by direction reversal, absolute Local-minus-Outside shift, support, and Local consistency. Do not treat a small-`n` effect as stable.
- Different Exact Core composition can explain an apparent Cluster effect. Report shared Exact Core count and the corresponding limitation.
- Do not claim causality, statistical independence of overlapping Clusters, or significance from descriptive ranking.

## Outputs

- `mmp_interpretation_context.json`: bounded Agent context and metric definitions
- `mmp_interpretation_draft.json`: editable, ID-free human narrative
- `mmp_interpretation.json`, `.md`, `.html`: finalized auxiliary report
- `clustering_transform_summary.csv`: Transform × Clustering variance comparison
- `cluster_transform_summary.csv`: Transform × Cluster Global／Local／Outside comparison
- `cluster_screening.csv`: Cluster coverage and support
- candidate CSVs for variance collapse, Cluster-specific effects, and direction reversal
- `source_inventory.json` and `verification.json`: read-only boundary evidence

## Boundaries

- Do not modify `conductor_control.json`, `runtime/`, `rounds/`, canonical stage directories, or Interpretation outputs.
- Do not register this report in DAG, Result Index, Insight Index, or Event Ledger.
- Do not build a missing Global MMP Database. If the target Round has no new Global A014 Node, stop; reuse an older Database only when the human explicitly specified its Node ID.
- 低supportの`Cluster × Transform`ではLocal／Globalと適格性を保持し、未評価のOutside列は空値になり得る。詳細比較として解釈しない。
- Do not default to OS `/tmp`; all generated helpers and temporary files remain in the request directory or Skill-local `env/`.
