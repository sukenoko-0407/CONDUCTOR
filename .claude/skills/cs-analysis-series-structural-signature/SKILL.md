---
name: cs-analysis-series-structural-signature
description: Report each structural source Cluster's registered key, and derive Murcko plus MCS only for vector-derived source Clusters (A007).
allowed-tools: Read, Bash
---

# A007 Series structural signature

各Source Clusterを個別に扱う。C001-C004の構造由来Clusterは登録済み定義だけを提示し、Murcko／MCSを追加計算しない。C005-C010のvector由来Clusterだけ、そのCluster所属の全有効化合物へ代表Murcko scaffoldとtimeout付きMCSを適用する。Series和集合をSource Clusterの代用にしない。化合物を黙ってsampleせず、timeoutは成果物に明記する。単一の「正しいCore」へ統合しない。
