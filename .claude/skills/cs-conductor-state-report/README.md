# CONDUCTOR State report

## SKILLの目的

明示的に指定された`state.json`を読み取り、解析進捗と実行DAGを人間向けHTMLおよびSVGとして可視化する。

## 想定利用シーン

何が完了・未実行・失敗・stale・承認待ちかを確認し、Node間の依存関係やInterpretationの系譜を監査する場合。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を自動作成または再利用する。cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

```bash
python .claude/skills/cs-conductor-state-report/scripts/launch.py \
  --state results/CONDUCTOR/PROJECT/RUN/state.json --explicit-request
```

出力はStateと同じdirectoryの`state/<UTC timestamp>/`へ保存される。

## 制約事項

- 人間がState可視化を明示し、対象State pathを指定した場合だけ使用する。
- Stateを変更せず、DAG Nodeとしても登録しない。
- 出力先は変更できず、`CONDUCTOR_modules/`には書き込まない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。読み取り専用State要約、円形Node DAG、HTML／SVG出力を追加。 |
