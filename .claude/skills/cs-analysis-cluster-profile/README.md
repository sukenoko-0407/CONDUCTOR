# SKILLの目的

全ClusterのEndpoint分布とFavorable Fraction（FF）を一括計算します。

## 想定利用シーン

基本計算におけるFF順位とSeries候補の選定です。

## 環境構築

`scripts/launch.py`がSkill内`env/pixi.toml`から自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

Favorable閾値はGlobalデータから定義し、Clusterごとに再定義しません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 全Cluster一括FF profileとして新設 |
