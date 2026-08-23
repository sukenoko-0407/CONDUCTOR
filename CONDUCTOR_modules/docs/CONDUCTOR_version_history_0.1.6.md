# CONDUCTOR 0.1.6 変更履歴

0.1.6は、科学Skillの疎結合性を維持したまま、Main Orchestrator、Runtime Worker、互換Executor、Interpreterの責務境界を実行コードと文書で一致させた受入Versionです。

## 0.1.0以降の要約

| Version | 主な変更 |
|---|---|
| 0.1.0 | beta系列を開始し、Grouping／GroupをClustering／Clusterへ統一。PCA、UMAP、複数Description特徴量モデル、ChemBERTaを追加。 |
| 0.1.1 | Vector Clusteringを表現別の距離分布に基づく校正へ変更。0.1.0 Descriptionだけを移す一回限りのmigrationを整備。 |
| 0.1.2 | 小さいControl正本、Event Ledger、詳細DAG snapshotへ状態管理を階層化し、人間だけがRoundを開始する原則を強化。 |
| 0.1.3 | Main AgentをOrchestratorとし、Runtimeと短命Executor／Interpreterを分離。共通packet、再試行、100 Node上限を整備。 |
| 0.1.4 | CoreとTransformを保持するGlobal MMP解析を追加。MCS、xTB、Mordred 3D等のHPC並列実行を改善。 |
| 0.1.5 | 共通Execution RequestとSkill-local adapterへ移行。Global優先の単一explorationと省容量MMP Databaseを採用。 |
| 0.1.6 | Runtime Workerによるprocess所有、冪等な再接続、同一Node再試行、Interpretation品質とWindows動作を頑健化。 |

各Version固有の詳細はGit履歴および対応branchを正本とし、現役Packageには現行仕様だけを保持します。

## 主な変更

- 通常経路からLLM Executorを外し、detached Runtime Workerが科学processをterminalまで所有する。
- Packetを原子的にclaimし、再投入を再接続または保存済み結果の返却として冪等化する。
- `WAIT_RUNNING`と`RECONCILE_RUNNING`をprocess生存状態で明確に分離する。
- 失敗Nodeを同じRound・同じNode IDの新Attemptとして安全に再試行できるようにする。
- 再試行成功時に過去Attemptの失敗品質が残る問題を修正する。
- Interpretation HTMLの長い識別子の折返しと、主要数値を本文へ過剰表示しないrendererを適用する。
- A003/A004のCluster overlayをGlobal投影上の強調表示として正規化し、Canonical subjectとの集合不一致を解消する。
- Description依存Operatorの`sample_count`を実際に利用できたDescription行へ統一し、除外数をwarningとして明示する。
- Capabilityのscope契約をNode登録時に検証し、Global専用A012へLocal Cluster引数をPlanningしない。
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
