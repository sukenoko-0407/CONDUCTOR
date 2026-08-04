# Overlap-based meta clustering

## SKILLの目的

long形式のGrouping結果またはBoolean wide matrix shardにあるcompound重複を使ってmeta groupを生成する。

## 想定利用シーン

複数Groupingの重複関係を要約し、上位のgroup構造を確認する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-clustering-meta-overlap/scripts/launch.py --input grouping_a.csv --input grouping_b.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-clustering-meta-overlap/scripts/launch.py --input grouping_a.csv --input grouping_b.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- 一般利用ではClustering、CONDUCTOR内ではGroupingとして扱う。入力分子やfeature値は変更しない。
- `--input`を反復指定でき、異なるGrouping nodeのmembershipを一つのmeta解析へ渡せる。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
