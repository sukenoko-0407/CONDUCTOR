---
name: cs-conductor-on-demand-analysis
description: Perform flexible human-requested analysis inside run_root/on_demand/REQ###### without changing Round, Runtime DAG, or canonical scientific artifacts.
allowed-tools: Read, Write, Glob, Grep, Bash
---

# CONDUCTOR On-demand Analysis

人間が明示した依頼だけを処理する。Round状態に関係なく実行でき、書込先は`<run_root>/on_demand/REQ######/`とOn-demand専用のappend-only `index.jsonl`だけである。通常DAG、Node番号、Lease、Round、Description/Clustering/analysis/interpretation成果物を変更しない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare --run-root <RUN_ROOT> --request "依頼" --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" add-source --request-dir <REQ_DIR> --source <RUN_ARTIFACT>
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" run-helper --request-dir <REQ_DIR> --script <REQ_DIR>/scratch/check.py
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" run-mmp --request-dir <REQ_DIR> --role type-ii --target-compound-id <ID>
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" finalize --request-dir <REQ_DIR>
```

依頼固有PythonはREQ内`scratch/`へ置ける。固定Pixi環境だけを使い、実行中のnetwork installは禁止。既存metricを推測式で置換せず、追加集計には式、source、filter、scope、分母Nを記録する。Type-II/III MMPは`run-mmp`でREQ内だけへ生成する。
同一Runの明示済みType-III DatabaseをType-IIで再利用する場合だけ、上記へ`--mmp-database <PATH>`を追加する。自動探索はしない。
