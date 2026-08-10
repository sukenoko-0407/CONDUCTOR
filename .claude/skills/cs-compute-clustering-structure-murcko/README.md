# Murcko scaffold clustering

## SKILLの目的

compound IDとSMILESをMurcko scaffold clusteringで直接Cluster化し、cluster membershipとsummaryを生成する。

## 想定利用シーン

SMILESを直接扱うseries分割やscaffold/fragment解析を行い、Description vector由来のClusteringと比較する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-clustering-structure-murcko/scripts/launch.py --input compounds.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-clustering-structure-murcko/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 一般利用とCONDUCTORの両方でClustering／Clusterと呼ぶ。入力分子やfeature値は変更しない。
- 5化合物未満のClusterは出力・登録しない。
- Description vectorは入力にせず、fingerprint生成を内部に隠した距離clusteringも行わない。
- 一般利用・CONDUCTOR利用ともcompound IDとSMILESを含むCSVを必須入力とし、CLIへのSMILES直接指定は受け付けない。
- invalid SMILESは未割当として保持する。分子標準化は行わない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
