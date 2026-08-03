# BRICS fragment clustering

## SKILLの目的

compound IDとSMILESからBRICS fragment clusteringを実行し、cluster membershipとsummaryを生成する。

## 想定利用シーン

化学構造に基づくseries分割、scaffold/fragment解析、または類似性groupの作成。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-clustering-structure-brics/scripts/launch.py --input compounds.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-clustering-structure-brics/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- 一般利用ではClustering、CONDUCTOR内ではGroupingとして扱う。入力分子やfeature値は変更しない。
- invalid SMILESは未割当として保持する。分子標準化は行わない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
