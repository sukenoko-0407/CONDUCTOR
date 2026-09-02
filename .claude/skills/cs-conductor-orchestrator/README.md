# SKILLの目的

Main Agentを一時的にCONDUCTORの指揮者として動かします。

## 想定利用シーン

新規Run、明示承認Roundの開始・再開・終了です。

## 環境構築

Orchestrator wrapper自体は標準Pythonだけで動作し、委譲先のRuntime LauncherがRuntime用Pixi環境を自動構築します。重複するOrchestrator環境の構築は行いません。

## 利用例

日常プロンプト集の「新規Run」をMain Agentへ渡します。

## 制約事項

Orchestratorは科学Skillを直接実行せず、新Roundを自動開始しません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 0.1.9固定flowへ簡素化 |
