# SKILLの目的

全ClusterのFavorable enrichmentを同一基準で比較します。

## 想定利用シーン

基本計算でEndpoint濃縮Clusterを抽出するときに使います。

## 環境構築

Pixi環境をLauncherが自動構築します。

## 利用例

`python scripts/launch.py --conductor-request execution_request.json`

## 制約事項

多重探索による偶然候補を排除する検定ではありません。q値とsupportを併記します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 全Cluster一括enrichmentとして新設 |
