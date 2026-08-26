# CONDUCTOR Assessment Report

## SKILLの目的

既存の一次評価を集約し、評価軸、総合評価区分、有望候補、Full Interpretationへの収載状況を自己完結HTMLで可視化する。

## 想定利用シーン

- 複数Roundに蓄積した一次評価の全体像を確認する。
- 高評価だがFullレポートに未収載の候補を探す。
- OperatorやRoundごとの候補発生傾向を比較する。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を自動作成または再利用する。cacheと環境はSkillの`env/`内に置かれる。

## 利用例

```bash
python .claude/skills/cs-conductor-assessment-report/scripts/launch.py \
  --run-root results/CONDUCTOR/PROJECT/RUN --explicit-request

python .claude/skills/cs-conductor-assessment-report/scripts/launch.py \
  --run-root results/CONDUCTOR/PROJECT/RUN \
  --round-id RND0002 --round-id RND0003 --top-n 10 --explicit-request
```

出力は`assessment_reports/<UTC timestamp>/`へ保存される。

## 制約事項

- CONDUCTOR 0.2.0の一次評価形式を対象とする。
- DAG、Round、State、科学artifact、Interpretationを変更しない。
- 5つの評価軸は単純合計しない。Candidate classを総合評価区分として表示する。
- 実行中に正本ファイルが変化した場合は、不整合なsnapshotを出力せず終了する。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。一次評価の分布、信頼性、Round推移、Operator内訳、Top候補、Fullレポート収載状況をHTML／CSV化。 |

