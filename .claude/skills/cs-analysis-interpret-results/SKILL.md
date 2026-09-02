---
name: cs-analysis-interpret-results
description: Produce one compact Japanese Interpretation after the deterministic 0.1.9 standard reports are complete.
allowed-tools: Read, Write
---

# I001 Lightweight Interpretation

Runtimeが返す`context_path`だけを読み、`draft_path`へ次の6 fieldを持つJSONを一回書く。

```json
{
  "title": "...",
  "executive_summary": "...",
  "observations": [],
  "global_series_contrasts": [],
  "on_demand_candidates": [],
  "limitations": []
}
```

定型Reportの数表を再掲しない。活性をFavorable方向へ動かす手掛かりと、Global–Seriesの違和感だけを短く抽出する。該当しない手法を主Insightにしない。科学計算、Node作成、State更新、HTML描画は行わず、Runtimeにcommitさせる。
