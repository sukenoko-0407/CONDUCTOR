# CONDUCTOR ドキュメント

対象Versionは`0.1.6`です。Description、Clustering、Operator、Interpretationを疎結合に接続し、同じRunを人間主導の複数Roundで探索します。共通Execution Request、Global優先の単一exploration、Analysis／Interpretation共通上限50、実務的範囲の省容量MMP Databaseを採用します。

## 利用時に読む文書

- [CONDUCTOR_overview.md](CONDUCTOR_overview.md): 全体像
- [CONDUCTOR_user_guide.md](CONDUCTOR_user_guide.md): 開始、再開、人間レビュー
- [CONDUCTOR_policy.md](CONDUCTOR_policy.md): Orchestratorの科学的原則
- [CONDUCTOR_interpretation_policy.md](CONDUCTOR_interpretation_policy.md): Interpretationの比較視点
- [CONDUCTOR_output_contract.md](CONDUCTOR_output_contract.md): Run Rootと最小artifact
- [CONDUCTOR_identifier_reference.md](CONDUCTOR_identifier_reference.md): ID体系

## 実装・監査

- [CONDUCTOR_0.1.6_specification_overview.md](CONDUCTOR_0.1.6_specification_overview.md): Runtime Worker所有、Executor境界、再接続・再試行仕様
- [CONDUCTOR_0.1.6_final_acceptance_plan.md](CONDUCTOR_0.1.6_final_acceptance_plan.md): 実データ拡大E2EとLinux HPC最終受入基準
- [CONDUCTOR_version_history_0.1.6.md](CONDUCTOR_version_history_0.1.6.md): 0.1.0以降の要約と0.1.6の変更点
- [CONDUCTOR_design_spec.md](CONDUCTOR_design_spec.md): Main Orchestrator、Executor、Interpreter、Runtime、Control、Event Ledger、詳細DAG snapshot
- [CONDUCTOR_skill_catalog.md](CONDUCTOR_skill_catalog.md): 人間allowlistから生成したCatalog
- [CONDUCTOR_skill_catalog_ja_quick_reference.md](CONDUCTOR_skill_catalog_ja_quick_reference.md): Description、Clustering、Operator、Interpretationの日本語早見表
- [CONDUCTOR_verification.md](CONDUCTOR_verification.md): 検証方法

`prompt/`には初回、継続Round、別session引継ぎ、Failed Nodeの同一Round再試行、Operator契約修正後の再開、read-only MMP Global–Local解釈、Concierge用のプロンプト例があります。Catalog収載対象は`catalog/included_skills.json`、標準解析範囲は`catalog/analysis_profile.json`が正本です。旧Runとの後方互換やmigrationは提供しません。

過去Version固有の仕様書・実装計画・是正計画は現役Packageへ同梱せず、Git履歴および各Version branchを参照します。
