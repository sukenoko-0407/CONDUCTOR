# CONDUCTOR v4 Orchestrator
## SKILLの目的

Catalog、Policy、run Stateを参照し、Description、Grouping、Operator、InterpretationをDAGとして計画・実行管理する。初手は3Dを含む代表family網羅profileを展開し、SMILES直接型GroupingとDescription-vector Clusteringを明確に分離する。
## 想定利用シーン

SAR解析を広く浅い探索から開始し、得られたevidenceに基づいて局所的な深掘り解析を選択する場合。中断runの再開、人間指定の部分解析、依存関係、並列上限、高コスト計算の承認管理にも使用する。
## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。
## 利用例

Catalogを読み取り専用で検証する:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py catalog --check
```

人間がCatalog収載内容を保守するときだけ、`catalog --write`で管理資産を再生成する。通常の解析runでは使用しない。

run Stateを初期化する:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state init \
  --input compounds.csv --endpoint pIC50 --higher-is-better \
  --project PROJECT --parallel-limit 8
```

粗い進捗と、必要なGroupだけを確認する:

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state status --state path/to/state.json
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py state groups --state path/to/state.json --status active
```

人間がDAG図を求めた場合は、専用`cs-conductor-state-report` SkillへState pathを明示して読み取り専用snapshotを生成する。Orchestratorは自動実行しない。

## 制約事項

- `CONDUCTOR_modules/catalog/included_skills.json`に人間が収載したSkillだけを使用する。
- 通常解析では`CONDUCTOR_modules/`を読み取り専用として扱い、結果・State・handoffを書き込まない。
- 1 runにつきendpointは一つとし、活性の向きを必須とする。
- 高コスト処理は原則として人間の明示承認前に実行しない。ただしCatalogで`preauthorized_initial`と明記されたC002 MCSは必須初手として承認待ちなしで実行する。
- 初手の一部で信号が弱くても残りを打ち切らず、coverage audit後に深掘りへ進む。
- vector ClusteringにはStateでbindingされたDescription artifactだけを渡し、raw SMILESからの内部fingerprint生成を許可しない。
- Interpretation探索は人間設定のiteration・追加node・walltime・seed内で行い、専用Interpreterのplanを重複署名と反証要求について検証する。
- random、matched random、交差、差分などの明示scopeは入力IDを検証し、再現可能なmembership CSVへ固定する。
- Group IDはrun内で一意とし、由来は`group_registry.csv`、全化合物の所属はBooleanの`Cpd_Group_matrix_*.csv`で監査できる。低価値領域は削除せず`discarded`にする。
- 人間指定の部分解析もSkillを直接起動せず`state add --human-request`で登録する。Node IDは実行段階別の`D###/G###/O###/I###`であり、Capability IDとは別に管理する。Interpretation nodeは読み取り専用の終端とし、再解釈は前回を参照する新しい`I###`として登録する。
- State可視化は人間の明示要求とState pathがある場合だけ実行し、Stateを更新せずDAG nodeにも登録しない。Operator成功時はCSV、`evidence.json`、`operator_report.html`を一組として記録する。
- 分子標準化、活性単位変換、pActivity変換は行わない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.3.0 | 明示要求型State可視化とOperator個別HTMLの管理規則を追加。 |
| 1.2.0 | 人間指定の部分解析と反復InterpretationのNode管理を追加。 |
| 1.1.0 | 通常runにおけるmoduleの読み取り専用境界とCatalog保守commandを明記。 |
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
