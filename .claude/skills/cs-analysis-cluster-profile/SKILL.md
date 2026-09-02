---
name: cs-analysis-cluster-profile
description: Compute A001 endpoint profiles and Favorable Fraction for every registered Cluster in one CONDUCTOR Node.
allowed-tools: Read, Bash
---

# A001 All-Cluster profile

Runtimeが発行した`execution_request.json`だけを受け取り、全Clusterを一括評価する。FavorableはGlobal endpointの上位20%（`higher_is_better=false`では下位20%）で固定し、`min_ff_evaluate`未満を削除せず評価対象外として記録する。ClusterごとのNodeは作らない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --conductor-request /path/to/execution_request.json
```

`A001_cluster_profile.csv`、選抜Cluster表、HTML、manifest、eventを出力する。分子標準化やendpoint補完は行わない。
