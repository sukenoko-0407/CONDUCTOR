# SKILLの目的

Node番号、依存関係、実行Request、Round gate、監査を決定論的に管理します。

## 想定利用シーン

Main AgentがOrchestrator Skillに従って一つの明示承認Roundを進める場合です。

## 環境構築

LauncherがSkill内Pixi環境を自動構築します。

## 利用例

`python scripts/launch.py state query --run-root /path/to/run`

## 制約事項

State JSONの手編集は禁止です。Runtimeは科学的な選択や新Round開始を自律判断しません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Enrichment–Series固定flowへ全面再設計 |
