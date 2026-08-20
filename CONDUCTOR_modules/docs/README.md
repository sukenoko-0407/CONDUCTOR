# CONDUCTOR ドキュメント

対象Versionは`0.1.4`です。Description、Clustering、Operator、Interpretationを疎結合に接続し、同じRunを人間主導の複数Roundで探索します。0.1.4では再利用可能なMatched Molecular Pair Database（A014）を追加しました。

## 利用時に読む文書

- [CONDUCTOR_overview.md](CONDUCTOR_overview.md): 全体像
- [CONDUCTOR_user_guide.md](CONDUCTOR_user_guide.md): 開始、再開、人間レビュー
- [CONDUCTOR_policy.md](CONDUCTOR_policy.md): Orchestratorの科学的原則
- [CONDUCTOR_interpretation_policy.md](CONDUCTOR_interpretation_policy.md): Interpretationの比較視点
- [CONDUCTOR_output_contract.md](CONDUCTOR_output_contract.md): Run Rootと最小artifact
- [CONDUCTOR_identifier_reference.md](CONDUCTOR_identifier_reference.md): ID体系

## 実装・監査

- [CONDUCTOR_0.1.4_specification_overview.md](CONDUCTOR_0.1.4_specification_overview.md): 現行0.1.4のMMP Database／Global・Local統合仕様
- [CONDUCTOR_0.1.4_implementation_plan.md](CONDUCTOR_0.1.4_implementation_plan.md): 0.1.3互換性を含む0.1.4実装計画
- [CONDUCTOR_design_spec.md](CONDUCTOR_design_spec.md): Main Orchestrator、Executor、Interpreter、Runtime、Control、Event Ledger、詳細DAG snapshot
- [CONDUCTOR_version_history_0.1.0_to_0.1.3.md](CONDUCTOR_version_history_0.1.0_to_0.1.3.md): beta系列0.1.0–0.1.3の仕様変更履歴
- [CONDUCTOR_version_history_0.1.4.md](CONDUCTOR_version_history_0.1.4.md): 0.1.4の追加仕様
- [CONDUCTOR_0.1.3_main_orchestrator_overview.md](CONDUCTOR_0.1.3_main_orchestrator_overview.md): 0.1.3制御系の設計根拠
- [CONDUCTOR_0.1.3_implementation_plan.md](CONDUCTOR_0.1.3_implementation_plan.md): 実装計画と受入条件
- [CONDUCTOR_skill_catalog.md](CONDUCTOR_skill_catalog.md): 人間allowlistから生成したCatalog
- [CONDUCTOR_skill_catalog_ja_quick_reference.md](CONDUCTOR_skill_catalog_ja_quick_reference.md): Description、Clustering、Operator、Interpretationの日本語早見表
- [CONDUCTOR_verification.md](CONDUCTOR_verification.md): 検証方法

`prompt/`には初回、継続Round、別session引継ぎ、Failed Nodeの同一Round修復、MMP深掘り、Concierge用のプロンプト例があります。Catalog収載対象は`catalog/included_skills.json`、標準解析範囲は`catalog/analysis_profile.json`が正本です。0.1.1以前のRunとの後方互換やmigrationは提供しません。
