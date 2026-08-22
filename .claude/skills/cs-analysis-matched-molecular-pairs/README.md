# cs-analysis-matched-molecular-pairs

## SKILLの目的

mmpdbを用いてMatched Molecular Pairを網羅的に抽出し、置換、Exact Core、周辺環境、活性差の関係を再利用可能なSQLite・CSV・HTMLとして保存します。CONDUCTORではOperator `A014`です。

## 想定利用シーン

- データ全体のMMPデータベースを一度構築する
- Spotfireで全Pairを可視化・絞り込みする
- 全Clusterを軽量に比較し、詳細解析候補を探す
- 特定ClusterでGlobalと異なる置換効果や反証例を確認する

## 環境構築

`scripts/launch.py`が`env/pixi.toml`を使い、Skill内の環境とcacheを自動構築します。Linuxでは既定の共有Pixi binaryを優先します。

## 利用例

```bash
python scripts/launch.py global-build --input compounds.csv --id-column compound_id --smiles-column SMILES --endpoint-column pIC50 --higher-is-better true
python scripts/launch.py local-detail --mmp-database results/mmp_database.sqlite --cluster-membership Cpd_Cluster_matrix.csv --cluster-id C000123
```

CONDUCTORからはRuntimeが共通`execution_request.json`を渡し、Skill内adapterがRole、Node情報、入力Artifactを既存CLIへ変換します。一般利用では従来どおりRole subcommandを直接指定し、`--conductor`を付けません。
Global構築のfragment並列数は最大8で、Available CPU Coresを超えません。全Pair、Summary、Database、Reportの生成内容は並列数によって省略しません。

## 制約事項

- 分子標準化は行いません。
- 重複化合物IDはエラーです。invalid SMILESはCoverageへ記録します。
- 標準範囲は1～2 cuts、Environment radius 0～2です。3 cutsまたはradius 3～5は明示的な拡張探索だけで使用します。
- Exact Coreが8 heavy atoms未満、両分子の0.50未満、または可変部が10 heavy atomsを超えるPairは標準集計対象外です。
- MMPが見つからないこと自体は失敗ではなく、Negative Resultとして記録します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。Global DB、全Cluster Screening、Cluster詳細比較に対応 |
| 2.0.0 | 標準探索範囲を実務的に限定し、正規化SQLiteと全詳細CSVへ保存を簡素化 |
