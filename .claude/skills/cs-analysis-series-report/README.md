# SKILLの目的

基本計算・定型解析を固定テンプレートによる一貫したHTMLへまとめます。冒頭に主要件数だけの簡略表を置き、Endpointヒストグラム内へMean、Median、方向依存のFavorable／Unfavorable 20% cutoffを描画します。個別解析単位ではA003相関表を7列へ絞り、相関上位3特徴量の散布図を掲載します。完全表は同じ成果物内のCSVへ分離します。

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
| 1.0.0 | 0.1.9定型Series reportとして新設 |
