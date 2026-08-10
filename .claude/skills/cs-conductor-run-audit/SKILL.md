---
name: cs-conductor-run-audit
description: Read and audit an explicitly supplied CONDUCTOR state.json without mutating State. Use Quick mode at bootstrap/control boundaries and Full mode after interruption or takeover, before Round close, or on explicit human request.
---

# CONDUCTOR Run Audit

指定された `state.json` と参照artifactを読み取り、`<run_root>/audit/<timestamp>/` に `audit.json` と `audit.md` を出力する。State、Node、index、解析結果は変更しない。

launcherは共有Pixiを優先し、`PIXI_CACHE_DIR` と `UV_CACHE_DIR` をSkillの `env/` 配下へ設定する。

```bash
python .claude/skills/cs-conductor-run-audit/scripts/launch.py \
  --state /path/to/run_root/state.json --mode quick

python .claude/skills/cs-conductor-run-audit/scripts/launch.py \
  --state /path/to/run_root/state.json --mode full
```

QuickはDAG、ID、lease、parallel limit、running attempt、Interpretation終端条件を検査する。FullはQuickに加え、成功Nodeのartifact存在・hash、主要index、summary/briefも検査する。

`status=fail` の場合は新規Nodeを実行せず、Orchestratorが原因を解消する。`warning` は科学的判断を妨げないが、Round終端前に内容を確認する。

このSkillは監査結果自体をDAG Nodeにしない。監査は制御面の記録であり、科学的なOperator resultではない。
