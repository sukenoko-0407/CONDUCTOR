---
name: cs-compute-clustering-meta-overlap
description: Cluster enriched Clusters into Series with an undirected Jaccard-weighted Leiden graph (C012).
allowed-tools: Read, Bash
---

# C012 Overlap-weighted Leiden Series

A001/A002の全Cluster統計から実効`min_ff_evaluate`とFF 0.50で一次選抜を再生成し、選抜Clusterを頂点、化合物集合のJaccard重複率を無向Edge weightとしてweighted Leidenを実行する。正の重複はすべてEdgeとして保持し、containmentも診断表へ保存する。Series membershipは構成Clusterの和集合である。

source Clusterが1件のCandidate SeriesはFF 0.50、2件以上はFF 0.40を基準とする。不採用Seriesはsource Clusterを決定論的にfallbackする。まず`min_ff_evaluate=10`でresolutionを1.0、1.25、1.5、2.0、2.5、3.0の順に評価し、最初の24件以下を自動採用する。該当がなければ`min_ff_evaluate=10,15,20,25,30`との全30条件を評価し、Runtimeがcoverage付きMatrixを返して人間の選択を待つ。25～100件は承認可、101件以上は不可。previewはcanonical Series Artifactとして確定しない。
