# cs-conductor-runtime

## SKILLの目的

CONDUCTORの小さなControl、5状態Node、DAG、単一Writer lease、署名付きExecutor packet、実行attempt、事故復旧、Interpretation終端条件を決定論的に管理します。

## 想定利用シーン

人間が開始したRoundの計画登録、専門Skill実行、同一Node再試行、中断後再開、Interpretation commit、監査ゲートに使用します。通常はOrchestratorから内部利用します。

## 環境構築

launcherがSkill内Pixi環境を再利用または自動構築し、cacheも`env/`内へ置きます。Runtime Controllerが必要とするJSON Schema、Pandas、Parquet依存関係はこの環境へ集約されています。

## 利用例

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state query --run-root /path/to/run --kind control
```

## 制約事項

人間の代わりにRoundを開始・受理しません。Runtime JSON/JSONLの直接編集、複数Writer、Action token再利用、InterpretationなしのRound終了は許可しません。新規RunではSMILES列を一意に確定し、Description、構造ベースClustering、構造を直接読むOperatorへ明示的に引き渡します。候補が複数の場合は`init --smiles-column <column>`が必要です。旧Runだけは、同じ列を`resume-round --smiles-column <column>`で補えます。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Control／Event Ledger／5状態DAG Runtimeを実装 |
| 1.1.0 | 0.1.3のcompact protocol、Executor packet、有限Interpretation retryを追加 |
| 1.1.1 | SMILES列をRun入力契約へ記録し、DescriptionとC001～C004へ明示的に引き渡す処理を追加 |
| 1.1.2 | 記録済みSMILES列をA006・A009・A013へも明示的に引き渡す処理を追加 |
