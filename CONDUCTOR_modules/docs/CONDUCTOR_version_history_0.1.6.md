# CONDUCTOR 0.1.6 変更履歴

0.1.6は、科学Skillの疎結合性を維持したまま、Main Orchestrator、Runtime Worker、互換Executor、Interpreterの責務境界を実行コードと文書で一致させた受入Versionです。

## 主な変更

- 通常経路からLLM Executorを外し、detached Runtime Workerが科学processをterminalまで所有する。
- Packetを原子的にclaimし、再投入を再接続または保存済み結果の返却として冪等化する。
- `WAIT_RUNNING`と`RECONCILE_RUNNING`をprocess生存状態で明確に分離する。
- 失敗Nodeを同じRound・同じNode IDの新Attemptとして安全に再試行できるようにする。
- 再試行成功時に過去Attemptの失敗品質が残る問題を修正する。
- Interpretation HTMLの長い識別子の折返しと、主要数値を本文へ過剰表示しないrendererを適用する。
- Windowsの長いSkill環境pathでChemBERTaのTransformers importが失敗する問題を修正する。
- Windows／OneDrive上の一時的なfile占有で原子的置換が失敗する場合に、`PermissionError`だけを最大5秒再試行する。
- 実Runtime／PixiコマンドでD016、C002、A014、D020の並列動作を確認する。
- Package、Catalog、Capability、Runtime protocol、schema、現役文書を0.1.6へ統一する。

## 変更しないもの

- Mordred 3Dの複素数変換警告と欠損Descriptorの現行処理
- Description、Clustering、Operatorの一般利用CLI
- 一Round最大100 Analysis NodeとGlobal優先exploration
- 人間だけがRound開始を許可する原則
- 旧Runとの非互換方針

## 受入状況

静的検証、回帰試験、Windows拡大E2E、Linux HPC受入を[CONDUCTOR_verification.md](CONDUCTOR_verification.md)で個別に管理します。Windows拡大E2Eは231化合物、代表科学Node 8件、Interpretation、Full Auditまで完了しました。Windowsで確認できないxTB native実行と共有Pixi運用はLinux受入項目です。
