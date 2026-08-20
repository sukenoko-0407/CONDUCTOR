# GFN2-xTB quantum descriptors

## SKILLの目的

CSVまたは1件以上のSMILESからGFN2-xTB quantum descriptorsを計算し、Description表を生成する。

## 想定利用シーン

電子エネルギーや原子電荷など、量子化学由来の特徴量が必要な場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-compute-description-tblite-xtb/scripts/launch.py --input compounds.csv --compound-workers 2 --cores-per-compound 4
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-compute-description-tblite-xtb/scripts/launch.py --input compounds.csv --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 入力分子の標準化は行わない。重複IDはerror、invalid SMILESは行を保持して警告対象とする。
- 入力SMILESからconformerを生成するため、結果と計算時間は3D生成条件の影響を受ける。
- `--compound-workers`化合物を並列化し、各計算へ`--cores-per-compound` CPU threadsを割り当てる。両者の積を利用可能CPU数以下にする。
- CONDUCTORではD019を単独実行し、RuntimeがAvailable CPU Coresから原則4コア/化合物で並列数を決める。OrchestratorのNode並列数とは独立している。
- 高コスト計算として、CONDUCTORでは実行前に人間の承認が必要。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
| 1.1.0 | 化合物単位の並列計算と、1化合物あたりのCPU割当を追加。 |
