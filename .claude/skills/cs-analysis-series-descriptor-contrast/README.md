# SKILLの目的

解釈可能なD001特徴量についてGlobalとSeriesの差を調べます。

## 想定利用シーン

定型解析でSeries固有の特徴量–Endpoint関係を探す場合です。

## 環境構築

Pixi環境を自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

相関は因果を意味しません。選抜済Seriesに対する解析です。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Series batch Operatorとして新設 |
