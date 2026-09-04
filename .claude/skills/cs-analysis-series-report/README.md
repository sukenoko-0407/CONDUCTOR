# SKILLの目的

基本計算・定型解析を7 Sectionの固定HTMLへまとめます。冒頭のcard要約、Legendに統計値と両cutoffを示すEndpointヒストグラム、表示幅固定の横長Global／Series／fallback Cluster Boxplotを表示します。個別analysis unitでは最大20化合物の2D gallery、Description ID付きA003相関表と上位3散布図、A005 Local／Global OOF予測比較図、ECFP4 Tanimoto 0.75基準のA006、Cluster ID付きA007上位5構造、Type-I MMP Top 1への導線を示します。A007は構造由来Clusterなら登録Key構造だけ、vector由来ClusterならSource ClusterごとのMurcko／MCSを表示します。各Sectionは主要Table／画像を先に、解析内容と判定基準を後続の折り畳みに配置し、詳細CSVリンクはSection末尾に置きます。

## 想定利用シーン

Round終了前の正式な定型レポート作成です。

## 環境構築

Pixi環境を自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

科学的な追加推論ではなく、保存済み結果の決定論的表示です。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 0.1.10定型Series reportとして新設 |
