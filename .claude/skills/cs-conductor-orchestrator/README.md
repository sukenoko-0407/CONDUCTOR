# CONDUCTOR v4 Orchestrator

## SKILLの目的

Catalog、Policy、run Stateを参照し、Description、Grouping、Operator、InterpretationをDAGとして計画・実行管理する。

## 想定利用シーン

SAR解析を広く浅い探索から開始し、得られたevidenceに基づいて局所的な深掘り解析を選択する場合。中断runの再開、依存関係、並列上限、高コスト計算の承認管理にも使用する。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

Catalogを検証・更新する:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py catalog
```

run Stateを初期化する:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state init \
  --input compounds.csv --endpoint pIC50 --higher-is-better \
  --project PROJECT --parallel-limit 8
```

## 制約事項

- `catalog/included_skills.json`に人間が収載したSkillだけを使用する。
- 1 runにつきendpointは一つとし、活性の向きを必須とする。
- 高コスト処理は人間の明示承認前に実行しない。
- 分子標準化、活性単位変換、pActivity変換は行わない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
