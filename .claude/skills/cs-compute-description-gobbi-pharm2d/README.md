# Gobbi 2D pharmacophore fingerprint (optional SVD)

## SKILLの目的

CSVまたは1件以上のSMILESからGobbi 2D pharmacophore fingerprint (optional SVD)を計算し、Description表を生成する。

## 想定利用シーン

2D pharmacophore配置に基づく類似性評価やクラスタリング。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-description-gobbi-pharm2d/scripts/launch.py --input compounds.csv
```

SVD表現を作る例:

```bash
python .claude/skills/cs-compute-description-gobbi-pharm2d/scripts/launch.py --input compounds.csv --reduction svd --svd-dim 128
```

CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-description-gobbi-pharm2d/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- 入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。
- SVD表現は入力datasetに依存する座標系であり、2件以上のvalid moleculeが必要。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
