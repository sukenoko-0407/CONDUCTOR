---
name: cs-analysis-cluster-enrichment
description: Compute A002 favorable endpoint enrichment, odds ratios, Fisher p-values, and auxiliary BH q-values for all Clusters in one Node.
allowed-tools: Read, Bash
---

# A002 All-Cluster enrichment

Runtime Requestに含まれるGlobal endpointと全Cluster membershipを一括処理する。FF>=0.5かつN>=`min_ff_evaluate`をSeries候補とし、BH q値は人間の区別に使う補助値であって選抜gateにはしない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --conductor-request /path/to/execution_request.json
```

科学的な陰性結果や候補0件も正常終了として記録する。
