# CONDUCTOR Orchestrator

## SKILLの目的

複数Roundを前提に、Description、Grouping、Operator、Interpretationを実行DAGとして計画・状態管理します。初期網羅、追加探索、Question起点の深掘り、人間指定の部分解析を同じRunへ連結します。

## 想定利用シーン

新規SAR解析の開始、別Claude Codeセッションからの継続、結果を見た次Roundの追加解析、特定部分だけの再解析に利用します。

## 環境構築

`scripts/launch.py`が共有Pixiを優先し、`env/pixi.toml`から環境を作成・再利用します。cacheはすべて本Skillの`env/`内です。

## 利用例

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state init \
  --input compounds.csv --endpoint pIC50 --higher-is-better \
  --project PROJECT --parallel-limit 8 --request "Round 1 initial analysis"

python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state plan-basic \
  --state path/to/state.json
```

Round 2以降は`round-start`にState path、Round ID、resource envelope、人間の注目点を渡します。

Package差分が検出された場合はNode計画・実行が停止します。差分を人間が確認した後だけ、次で新しいsnapshotを受け入れます。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state approve-package-change \
  --state path/to/state.json --approve --rationale "差分を確認して同一Runで継続する"
```

## 制約事項

- `CONDUCTOR_modules/`は解析中read-onlyです。
- Capability IDと実行Node IDを区別し、IDはStateだけが発行します。
- 高コスト基本計算は一括承認、その他の高コスト計算は個別承認が必要です。
- Package差分は人間の明示承認なしに同一Runへ混在できません。
- 分子標準化やendpoint変換は行いません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 複数Round、包括的初期解析、選択的context、継続ID、Question管理に対応。 |
