# Vector hierarchical clustering

## SKILLの目的

Description Skillが生成した数値vectorへVector hierarchical clusteringを適用し、cluster membershipとsummaryを生成する。

## 想定利用シーン

descriptor、fingerprint、embedding空間で化合物をCluster化し、SMILESを直接扱う構造Clusteringと比較する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-clustering-vector-hierarchical/scripts/launch.py --input description.csv --input-representation D001
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-clustering-vector-hierarchical/scripts/launch.py --input description.csv --input-representation D001 --description-manifest path/to/description_manifest.json --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 一般利用とCONDUCTORの両方でClustering／Clusterと呼ぶ。入力分子やfeature値は変更しない。
- 5化合物未満のClusterは出力・登録しない。
- raw SMILESは入力にできず、Descriptionを内部生成しない。MetricはDescription表現に固定し、`--parameter-mode auto`ではactivityを使わず手法固有の距離・近傍parameterを決定する。
- 自動候補がすべて断片化または崩壊する場合は、Clusterを強制せず`no_usable_partition`を返す。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
