# Mordred 3D descriptors

## SKILLの目的

CSVまたは1件以上のSMILESからMordred 3D descriptorsを計算し、Description表を生成する。

## 想定利用シーン

3D形状や立体配置を使った比較、2D表現と異なる観点での深掘り。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-description-mordred-3d/scripts/launch.py --input compounds.csv --available-cpu-cores 8 --compound-workers 8
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-description-mordred-3d/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。
- 入力SMILESからconformerを生成するため、結果と計算時間は3D生成条件の影響を受ける。
- 化合物単位で最大8 processを使う。各workerは1 CPU threadで、指定したAvailable CPU Coresを超えない。
- ROUND1ではDescription Databaseのmiss化合物だけを追加承認なしで計算する。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
| 1.1.0 | 化合物単位の最大8 process並列とCPU予算制御を追加。 |
