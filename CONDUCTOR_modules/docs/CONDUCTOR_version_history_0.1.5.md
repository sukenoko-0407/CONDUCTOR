# CONDUCTOR 0.1.5 変更履歴

0.1.5は、科学Skillの疎結合性を維持しながらRuntime実行経路を単純化し、MMPを実務的な保存量へ再設計したVersionです。旧Runとの後方互換は提供しません。

## 主な仕様変更

- 全科学Skillを共通`execution_request.json`と`--conductor-request`入口で起動する。
- Main AgentをOrchestrator、RuntimeをStateの単一Writer、detached Runtime Workerを科学processの所有者とする。旧Executorは互換attachmentに限定する。
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
- Execution Packetは一度だけAttemptへclaimし、同一packetの再投入を既存Workerへの再接続または保存済みterminal結果の返却として扱う。
- 人間承認済みの技術修正後は、running Nodeがない境界で同じfailed Nodeを同一Round内に優先再試行できる。
- 失敗Attempt後の再試行成功では旧品質判定を残さず、成功成果物から`result_quality`を確定して下流適格性を再評価する。
- Interpretation HTMLは長いRun IDやResult参照をカード内で安全に折り返す。
- Windowsでは、長いSkill環境pathでTransformersがmodule探索に失敗しないよう、D020 ChemBERTaの`site-packages`をimport直前にextended pathへ正規化する。Linuxのimport経路と科学計算条件は変更しない。

## 検証状況

2026-08-22のWindows回帰試験では、MMP専用Pixi環境で`105 tests / 85 passed / 20 environment-dependent skipped`、失敗0でした。加えて、JAK2 50化合物でD001、C001、C005、Operator 5 Node、Interpretation、Full Audit、`AWAITING_HUMAN_REVIEW`まで実Runtime経路を完走しました。D016、C002 pair探索、A014 fragment、D020の実並列もOS process／thread監視で確認しています。D019 xTBはWindows native環境が単一化合物でも異常終了したためLinux受入へ残します。Package layout、48 capability Catalog、変更Python 52ファイルのcompile、差分形式検査も合格しています。Linux HPCでの共有Pixi、6時間実行、CPU／process-tree制御は環境依存の最終受入項目です。

詳細は[CONDUCTOR_0.1.5_specification_overview.md](CONDUCTOR_0.1.5_specification_overview.md)、[CONDUCTOR_0.1.5_implementation_plan.md](CONDUCTOR_0.1.5_implementation_plan.md)、[CONDUCTOR_0.1.5_review_remediation_plan.md](CONDUCTOR_0.1.5_review_remediation_plan.md)を参照してください。
