# cs-conductor-migrate-v430-run

## SKILLの目的

指定されたv4.3.0 run rootから、検証済み計算結果を引き継いだ新しいv4.3.1 run rootを決定論的に作成します。

## 想定利用シーン

Node番号が大きく飛んだ旧Runや、v4.3.1のlease・終端ゲートを持たない旧Runを一度だけ移行する場合です。

## 環境構築

launcherがSkill内Pixi環境を自動構築・再利用し、cacheも `env/` 内に置きます。

## 利用例

`scripts/launch.py scan` を実行し、人間が内容を承認した後だけ `apply --approve`、最後に `verify` を実行します。完了時点ではactive Roundを作らず、別の人間指示を待ちます。詳しいコマンドはSKILL.mdを参照してください。

## 制約事項

sourceは変更しません。旧Interpretation、未完了Node、検証不能artifactはactive DAGへ移行しません。targetは新規でなければなりません。Migration AgentはOrchestratorを起動しません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | v4.3.0からv4.3.1への一回限り移行と明示的handoffを追加 |
