# Activity distribution

## SKILLの目的

Activity distributionを実行し、一般利用向け数値結果とCONDUCTOR向けevidenceを生成する。

## 想定利用シーン

endpoint全体または指定groupの分布を最初に把握する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-analysis-activity-distribution/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-analysis-activity-distribution/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID --round-id ROUND_ID --evidence-id EVIDENCE_ID
```

## 制約事項

- endpoint列と`--higher-is-better`または`--no-higher-is-better`の指定が必要。
- 数値的観察を出力するOperatorであり、SAR機序や因果関係を確定しない。
- CONDUCTORモードではState由来のDescription／Grouping Capabilityとsource Node IDを保持し、scope、主要結果、上位個別結果とともに`operator_report.html`へ示す。完全な数値はCSVに保持する。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.2.0 | Description／GroupingのCapabilityとsource Node IDのprovenance表示を追加。 |
| 1.1.0 | CONDUCTORモードの人間向けOperator HTMLレポートを追加。 |
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
