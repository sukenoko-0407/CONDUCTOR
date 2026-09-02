# SKILLの目的

既存Runを汚さず、人間の自由な質問、再集計、図示、Type-II/III MMPへ対応します。

## 想定利用シーン

定型レポートの深掘りやHit-to-Lead検討です。

## 環境構築

広めの固定Pixi環境をLauncherが自動構築します。

## 利用例

`python scripts/launch.py prepare --run-root RUN --request "S000001を詳しく" --explicit-request`

MMP Type-II/IIIはprepare後に`run-mmp`を使います。

## 制約事項

書込先は自身のREQ directoryだけで、通常DAGには登録しません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Round非依存On-demand解析と管理されたMMP導線を実装 |
