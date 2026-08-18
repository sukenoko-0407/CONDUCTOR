# CONDUCTOR ドキュメント

対象Versionは`0.1.3`です。Description、Clustering、Operator、Interpretationを疎結合に接続し、同じRunを人間主導の複数Roundで探索します。

## 利用時に読む文書

- [CONDUCTOR_overview.md](CONDUCTOR_overview.md): 全体像
- [CONDUCTOR_user_guide.md](CONDUCTOR_user_guide.md): 開始、再開、人間レビュー
- [CONDUCTOR_policy.md](CONDUCTOR_policy.md): Orchestratorの科学的原則
- [CONDUCTOR_interpretation_policy.md](CONDUCTOR_interpretation_policy.md): Interpretationの比較視点
- [CONDUCTOR_output_contract.md](CONDUCTOR_output_contract.md): Run Rootと最小artifact
- [CONDUCTOR_identifier_reference.md](CONDUCTOR_identifier_reference.md): ID体系

## 実装・監査

- [CONDUCTOR_design_spec.md](CONDUCTOR_design_spec.md): Main Orchestrator、Executor、Interpreter、Runtime、Control、Event Ledger、詳細DAG snapshot
- [CONDUCTOR_0.1.3_main_orchestrator_overview.md](CONDUCTOR_0.1.3_main_orchestrator_overview.md): 0.1.3制御系の設計根拠
- [CONDUCTOR_0.1.3_implementation_plan.md](CONDUCTOR_0.1.3_implementation_plan.md): 実装計画と受入条件
- [CONDUCTOR_skill_catalog.md](CONDUCTOR_skill_catalog.md): 人間allowlistから生成したCatalog
- [CONDUCTOR_verification.md](CONDUCTOR_verification.md): 検証方法

`prompt/`には初回、継続Round、別session引継ぎ、Concierge用のプロンプト例があります。Catalog収載対象は`catalog/included_skills.json`、標準解析範囲は`catalog/analysis_profile.json`が正本です。0.1.1以前のRunとの後方互換やmigrationは提供しません。
