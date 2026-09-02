---
name: cs-analysis-series-structural-signature
description: Report all structural source Clusters for each Series, or bounded Murcko and MCS fallback signatures when none exist (A007).
allowed-tools: Read, Bash
---

# A007 Series structural signature

SeriesにC001-C004由来Clusterが含まれる場合はその定義をすべてありのまま提示する。存在しない場合だけ、Seriesの全有効化合物へMurckoとtimeout付きMCSを適用する。化合物を黙ってsampleせず、timeoutは成果物に明記する。単一の「正しいCore」へ統合しない。
