# SKILLの目的

GlobalとSeriesのLandscape平滑性、内部Cliff、境界CliffをD002 ECFP4で比較し、Tanimoto similarity 0.75以上かつabsolute Endpoint差がGlobal Endpoint IQR以上のCliff pairを詳細CSVへ保存します。

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
| 0.1.10 | Tanimoto閾値を0.75へ変更し、Boundary favorable directionの件数表示を追加 |
| 1.0.0 | Series batch Landscapeとして新設 |
