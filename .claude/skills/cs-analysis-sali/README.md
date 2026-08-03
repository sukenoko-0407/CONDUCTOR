# Extended structure-activity landscape index

## SKILLの目的

表現に適した距離でSALIを計算し、property landscapeの局所Cliffと全体的な平滑性を評価する。

## 想定利用シーン

近い表現を持つ化合物間の大きな活性差を優先順位付けする場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-analysis-sali/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better --description description.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-analysis-sali/scripts/launch.py --input compounds.csv --property-column pIC50 --higher-is-better --description description.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- endpoint列と`--higher-is-better`または`--no-higher-is-better`の指定が必要。
- 数値的観察を出力するOperatorであり、SAR機序や因果関係を確定しない。
- Morganとbinary fingerprintにはTanimoto、USR/USRCATにはManhattanを使用する。`--metric auto`でも自動選択できる。
- 高SALI pairは測定誤差・assay条件・他表現で確認し、低い中心値とupper tailはその空間での相対的な平滑性として扱う。
- metricとendpoint scaleが異なるrun間でraw SALI値を直接比較しない。
- Group内／Group間scopeに対応し、連続表現ではglobal前処理基準を既定とする。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
