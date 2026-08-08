---
name: cs-conductor-migrate-v430-run
description: Perform a one-time, deterministic, human-approved import from an explicitly supplied CONDUCTOR v4.3.0 run root into a new v4.3.1 run root. Use only for migration; never modify the source and never run apply without reviewing the scan plan.
---

# CONDUCTOR v4.3.0 Run Migration

このSkillは一回限りの保守作業専用である。旧run rootを読み取り専用として扱い、成功済み科学artifactのうち検証できたものだけを新run rootへコピーする。旧Stateの直接更新、同じパスへの上書き、推論による穴埋めは禁止する。

## 手順

1. `scan` を実行し、移行plan、除外理由、Node ID対応表を生成する。
2. 人間へscan summary、含有/除外Node数、基本計算coverageと不足項目、初期phase引継ぎ状態、警告、source/targetを提示する。
3. 人間が明示承認した場合だけ `apply --approve` を実行する。
4. `verify` を実行する。失敗時は新run rootを解析に使わず、報告する。
5. 成功後は`RND0001` checkpoint、active Roundなし、`migration_handoff=awaiting_human_start`を報告して終了する。Orchestrator、bootstrap、Round開始、科学Skillを呼び出さない。

```bash
python .claude/skills/cs-conductor-migrate-v430-run/scripts/launch.py scan \
  --source-run-root /old/run --target-run-root /new/run --new-run-id imported-run

python .claude/skills/cs-conductor-migrate-v430-run/scripts/launch.py apply \
  --plan /path/to/migration_plan.json --approve

python .claude/skills/cs-conductor-migrate-v430-run/scripts/launch.py verify \
  --target-run-root /new/run
```

移行対象は、artifactと依存関係を検証できた `succeeded` Description / Grouping / Operator Nodeである。`pending`、`running`、失敗Node、重複署名、旧Interpretationはactive DAGへ取り込まない。Node IDは依存順に再附番し、旧IDはprovenanceと対応表に残す。

Migrationは移行済みNodeから基本計算coverageを計算する。次の人間開始Roundでは検証済みDescription／Groupingを再利用し、不足項目だけを計画する。Migration完了だけを理由にInterpretationや基本計算を開始しない。
