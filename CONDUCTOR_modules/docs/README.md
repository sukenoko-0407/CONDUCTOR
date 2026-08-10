# CONDUCTOR ドキュメント

対象Versionは`0.1.0`です。CONDUCTORは、Description、Clustering、Operator、Interpretationを疎結合なSkillとして接続し、一つの入力・endpointを複数Roundで探索するSAR解析基盤です。

## 最初に読む文書

- [CONDUCTOR_overview.md](CONDUCTOR_overview.md): 全体像と主要機能
- [CONDUCTOR_user_guide.md](CONDUCTOR_user_guide.md): Claude Codeからの開始・継続方法
- [CONDUCTOR_policy.md](CONDUCTOR_policy.md): Orchestratorの行動原則
- [CONDUCTOR_interpretation_policy.md](CONDUCTOR_interpretation_policy.md): Interpretationの比較視点

## 実装・監査

- [CONDUCTOR_design_spec.md](CONDUCTOR_design_spec.md): DAG、State、Runtime、attemptの設計
- [CONDUCTOR_output_contract.md](CONDUCTOR_output_contract.md): directoryとartifact契約
- [CONDUCTOR_identifier_reference.md](CONDUCTOR_identifier_reference.md): ID体系
- [CONDUCTOR_skill_catalog.md](CONDUCTOR_skill_catalog.md): Catalogから生成されるSkill一覧
- [CONDUCTOR_description_relationships_and_coverage.md](CONDUCTOR_description_relationships_and_coverage.md): Description間の関係
- [CONDUCTOR_verification.md](CONDUCTOR_verification.md): 受入確認
- [CONDUCTOR_0.1.0_refactoring_plan.md](CONDUCTOR_0.1.0_refactoring_plan.md): 本Versionの実装計画・判断記録

`prompt/`には初回、継続Round、セッション引継ぎ、Concierge用のプロンプト例があります。Catalog収載対象は`catalog/included_skills.json`、標準的な解析範囲は`catalog/analysis_profile.json`が正本です。
