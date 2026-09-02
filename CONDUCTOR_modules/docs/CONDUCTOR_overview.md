# CONDUCTOR 0.1.9 概要

CONDUCTORは、化合物の多様な表現を全体から局所へ組み替えながら、FavorableなEndpointへ向かう手掛かりを人間へ示す解析基盤です。

## 固定flow

```text
全Description
  → 全標準Clustering
  → 全Cluster FF / enrichment
  → 濃縮Cluster
  → overlap-weighted Leiden Series
  → Global / Series定型解析
  → 定型HTML + 軽量Interpretation
  → 人間のOn-demand深掘り
```

「基本計算」はDescriptionからSeries確定まで、「定型解析」はA003-A009です。基本計算・定型解析は一つの人間承認Round内で完了させます。採用Seriesとfallback Clusterを合わせた実解析単位数が24を超える場合は人間確認を挟みます。

RuntimeはDAG、Node番号、依存関係、再試行、Round gateを決定論的に管理します。Main AgentはRuntimeの一つの`required_action`だけを進め、科学SkillのCLIを推測しません。各OperatorはGlobalと全Seriesを一括処理するため、Series数に比例してNodeが増えません。

On-demand解析はRoundと通常DAGの外にあり、`run_root/on_demand/REQ######/`だけへ書き込みます。定型Reportを起点に、人間が自由な比較、図示、Type-II/III MMPを依頼できます。
