# ChemBERTa-100M-MLM embedding

## SKILLの目的

CSVまたは1件以上のSMILESからChemBERTa-100M-MLM embeddingを計算し、Description表を生成する。

## 想定利用シーン

ローカルに配置したChemBERTa modelからCPUで分子embeddingを抽出する場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-description-chemberta-embedding/scripts/launch.py --input compounds.csv --model-dir /shared/models/ChemBERTa-100M-MLM
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-description-chemberta-embedding/scripts/launch.py --input compounds.csv --model-dir /shared/models/ChemBERTa-100M-MLM --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。
- model weightを自動downloadしない。`--model-dir`で完全なlocal model directoryを指定し、CPUだけを使用する。
- ROUND1ではDescription Databaseのmiss化合物だけを追加承認なしで計算する。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
