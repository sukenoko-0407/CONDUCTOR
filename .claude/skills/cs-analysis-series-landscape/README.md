# SKILLの目的

GlobalとSeriesのLandscape平滑性、内部Cliff、境界Cliffを比較し、条件を満たすCliff pairを完全CSVへ保存します。

## 想定利用シーン

Series化によりLandscape解釈が変化する箇所の検出です。

## 環境構築

Pixi環境を自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

D002/Tanimoto固定の定型解析です。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Series batch Landscapeとして新設 |
