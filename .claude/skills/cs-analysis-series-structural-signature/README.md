# SKILLの目的

各Seriesを人間が構造として認識できる手掛かりを示します。

## 想定利用シーン

Series詳細レポートのKey structure欄です。

## 環境構築

PixiがRDKitを準備します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

構造由来Clusterがある場合、fallback MCSは実行しません。fallback MCSは全有効化合物を対象とし、timeout到達を明示します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Series provenance優先の構造signatureへ再設計 |
