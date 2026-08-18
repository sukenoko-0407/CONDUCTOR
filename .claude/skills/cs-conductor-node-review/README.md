# cs-conductor-node-review

## SKILLの目的

異常または不要なNodeを人間確認の下で限定的に補正します。

## 想定利用シーン

Pending Nodeの取消し、成功結果の下流利用停止、影響範囲の確認に使用します。成功結果を無効化すると、それに依存する未実行Nodeもcancelされ、参照中のInterpretationは再作成対象になります。

## 環境構築

Pixi環境を自動構築します。

## 利用例

```bash
python scripts/launch.py inspect --run-root /path/to/run --node-id N000123
python scripts/launch.py disable-result --run-root /path/to/run --node-id N000123 --reason "人間確認済み理由"
```

## 制約事項

任意のStatus変更や成功への手動変更はできません。実行中の下流Nodeがある間は結果を無効化できません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版 |
