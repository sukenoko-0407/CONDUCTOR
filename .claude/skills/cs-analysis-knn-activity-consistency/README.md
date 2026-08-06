# kNN activity consistency

## SKILLの目的

kNN activity consistencyを実行し、一般利用向け数値結果とCONDUCTOR向けevidenceを生成する。

## 想定利用シーン

近傍化合物間で活性がどの程度一貫するか評価する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-analysis-knn-activity-consistency/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better --description description.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-analysis-knn-activity-consistency/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better --description description.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- endpoint列と`--higher-is-better`または`--no-higher-is-better`の指定が必要。
- 数値的観察を出力するOperatorであり、SAR機序や因果関係を確定しない。
- CONDUCTORモードではState由来のDescription／Grouping Capabilityとsource Node IDを保持し、scope、主要結果、上位個別結果とともに`operator_report.html`へ示す。完全な数値はCSVに保持する。
- `--metric auto`はbinary vectorへTanimoto、USR/USRCATへManhattan、疎なcount vectorへcosine、その他の連続descriptorへEuclideanを選ぶ。
- Group内／Group間比較ではglobal前処理基準を既定とし、scopeとcompound集合hashをevidenceへ残す。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.2.0 | Description／GroupingのCapabilityとsource Node IDのprovenance表示を追加。 |
| 1.1.0 | CONDUCTORモードの人間向けOperator HTMLレポートを追加。 |
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
