# SKILLの目的

解釈可能なD001・D012・D015・D016・D019特徴量についてGlobalと各analysis unitの差を調べ、相関上位3特徴量を単一特徴量–Endpoint散布図として保存します。D015はacid/base・元素組成・芳香族性・ring count・polarizability、D016は分子geometry・部分表面積に厳選します。

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
| 0.1.10 | 固定Description panelへ拡張し、Description ID付き結果と上位3散布図を追加 |
| 1.0.0 | Series batch Operatorとして新設 |
