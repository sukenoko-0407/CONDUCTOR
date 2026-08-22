# CONDUCTOR 0.1.5 変更履歴

0.1.5は、科学Skillの疎結合性を維持しながらRuntime／Executor経路を単純化し、MMPを実務的な保存量へ再設計したVersionです。旧Runとの後方互換は提供しません。

## 主な仕様変更

- 全科学Skillを共通`execution_request.json`と`--conductor-request`入口で起動する。
- Main AgentをOrchestratorとし、RuntimeをStateの単一Writer、Executorを署名済みpacketの短命実行者とする。
- Operator探索を一種類へ統合し、一Round最大100 Node、Global優先、成功済みsignatureの非復元選択とする。
- A014 MMPを標準範囲と明示的拡張範囲へ分け、全詳細CSV、正規化SQLite、Summary、Reference Cardを出力する。
- InterpretationとFull AuditをRound handoffの必須条件として維持する。

## 詳細レビュー後の頑健化

- Execution Requestが参照する入力・上流成果物のSHA-256をSkill起動直前に再照合する。
- Result Card／Result Indexのartifact linkをRun Root相対pathへ統一する。
- Failed Nodeを成功履歴から除外し、同じNode IDでAttemptを追加する。自動retryは一時障害だけに限定する。
- 基本計算は計画Node集合、Global解析はGlobal scopeによって完了判定する。
- subprocess出力を逐次logへ書き、timeout時にprocess treeを停止する。
- MMPのnative context JOINをbounded cursorで読み、全JOIN表のDataFrame複製を廃止する。
- Pixi環境fingerprintとbootstrap owner記録により、設定変更とstale lockを安全に処理する。

## 検証状況

2026-08-22のWindows回帰試験は`92 passed, 9 skipped, 5 subtests passed`、Package layout、48 capability Catalog、Python compile、JSON／TOML parse、差分形式検査は合格しました。Linux HPCでの共有Pixi lock生成、process tree、6時間実行は環境依存の最終受入項目です。

詳細は[CONDUCTOR_0.1.5_specification_overview.md](CONDUCTOR_0.1.5_specification_overview.md)、[CONDUCTOR_0.1.5_implementation_plan.md](CONDUCTOR_0.1.5_implementation_plan.md)、[CONDUCTOR_0.1.5_review_remediation_plan.md](CONDUCTOR_0.1.5_review_remediation_plan.md)を参照してください。
