# SKILLの目的

Endpoint濃縮Clusterを重複関係からSeriesへ整理します。

## 想定利用シーン

基本計算から定型解析へ渡す解析単位の作成です。

## 環境構築

Pixiが`python-igraph`と`leidenalg`を含む環境を自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

Seriesは排他的な化合物partitionではなく、同一化合物が複数Seriesに属し得ます。複数Cluster SeriesはFF 0.40、単独SeriesはFF 0.50を基準とし、resolution自動探索で24件以下にならなければcoverage付きMatrixから人間が条件を選びます。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Jaccard-weighted Leiden Series化へ再設計 |
