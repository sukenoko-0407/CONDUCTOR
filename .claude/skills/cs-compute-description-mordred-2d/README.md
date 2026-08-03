# Mordred 2D descriptors

## SKILLの目的

CSVまたは1件以上のSMILESからMordred 2D descriptorsを計算し、Description表を生成する。

## 想定利用シーン

物性傾向の把握、活性との相関確認、解釈可能な特徴量の作成。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-description-mordred-2d/scripts/launch.py --input compounds.csv
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-description-mordred-2d/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- 入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
