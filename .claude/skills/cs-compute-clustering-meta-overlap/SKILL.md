---
name: cs-compute-clustering-meta-overlap
description: Cluster enriched Clusters into Series with an undirected Jaccard-weighted Leiden graph (C012).
allowed-tools: Read, Bash
---

# C012 Overlap-weighted Leiden Series

A001/A002で選抜されたClusterを頂点、化合物集合のJaccard重複率を無向Edge weightとしてweighted Leidenを一回実行する。正の重複はすべてEdgeとして保持し、containmentも診断表へ保存する。Series membershipは構成Clusterの和集合である。

Seriesの再計算FFが0.5未満、またはSeriesが得られない場合は、選抜Clusterを解析単位として決定論的にfallbackする。採用Seriesとfallback Clusterを合わせた実解析単位数が24を超える場合、Runtimeが人間確認を要求し、resolutionを自動変更しない。
