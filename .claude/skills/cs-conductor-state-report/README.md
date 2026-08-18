# CONDUCTOR State report

## SKILLの目的

明示的に指定されたRun RootのControlとDAG snapshotを読み取り、解析進捗と実行DAGをHTMLおよびSVGとして可視化する。

## 想定利用シーン

何が完了・未実行・失敗・取消済みか、Node間の依存関係、現在のRequired Actionを確認する場合。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を自動作成または再利用する。cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

```bash
python .claude/skills/cs-conductor-state-report/scripts/launch.py \
  --run-root results/CONDUCTOR/PROJECT/RUN --explicit-request
```

出力はRun Rootの`state/<UTC timestamp>/`へ保存される。

## 制約事項

- 人間が可視化を明示し、対象Run Rootを指定した場合だけ使用する。
- Runtimeを変更せず、DAG Nodeとしても登録しない。
- 出力先は変更できず、`CONDUCTOR_modules/`には書き込まない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。読み取り専用State要約、円形Node DAG、HTML／SVG出力を追加。 |
