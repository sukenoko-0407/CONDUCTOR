# SKILLの目的

複数Descriptionの少数特徴量を統合し、GlobalとSeriesの説明可能性を比較します。

## 想定利用シーン

定型解析における局所モデルの有効性確認です。

## 環境構築

Pixi環境を自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

予測製品ではなく探索用OOF評価です。Seriesは30化合物以上を標準とします。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Global/Series batch OOFモデルへ再設計 |
