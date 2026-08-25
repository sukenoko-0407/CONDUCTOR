---
name: cs-conductor-node-review
description: Inspect and apply narrowly defined human-confirmed corrections to a CONDUCTOR 0.1.6/0.1.7 Node. Use only on explicit human request; never expose arbitrary status editing and never include this Skill in the Orchestrator Agent.
allowed-tools: Read, Bash
---

# CONDUCTOR Node Review

人間が明示したNodeだけを対象とする。最初に`inspect`し、下流影響を提示する。変更は次の二種類だけである。

- `cancel`: `pending` Node、または人間がPlanning契約自体を無効と確認した`failed` Nodeをcancelする。activeな下流Nodeがあれば拒否する。計算失敗を成功へ読み替える操作ではない。
- `disable-result`: `succeeded`結果を保持したまま、今後の下流候補とInterpretation対象から除外する。依存する`pending` Nodeは連鎖的にcancelし、`running`子孫があれば安全のため拒否する。既存の`succeeded`子孫は履歴として保持する。現行Interpretationが当該Resultを参照していればReportを失効させ、同じRoundの再Interpretationを要求する。

任意Status setter、成功への手動変更、Node ID再付番は提供しない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" inspect --run-root /path/to/run --node-id N000123
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" cancel --run-root /path/to/run --node-id N000123 --reason "人間確認済み理由"
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" disable-result --run-root /path/to/run --node-id N000123 --reason "下流利用に不適切と人間が確認"
```
