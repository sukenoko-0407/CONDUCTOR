# SKILLの目的

Global空間における各Seriesの位置とまとまりを可視化します。

## 想定利用シーン

定型解析のPCA/UMAP図とSeries詳細レポートです。

## 環境構築

Pixiがmatplotlib、scikit-learn、UMAPを準備します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

座標は可視化用であり、標準Clusteringの入力にはしません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | PCA/UMAP Series panelとして統合 |
