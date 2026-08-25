# CONDUCTOR ドキュメント

対象Versionは`0.2.0`です。Description、Clustering、Operator、Interpretationを疎結合に接続し、同じRunを人間主導の複数Roundで探索します。共通Execution Request、Global優先の単一exploration、Review Bundleによる絶対複数軸評価、活性改善候補中心のInterpretation、実務的範囲の省容量MMP Databaseを採用します。

## 利用時に読む文書

- [CONDUCTOR_overview.md](CONDUCTOR_overview.md): 全体像
- [CONDUCTOR_user_guide.md](CONDUCTOR_user_guide.md): 開始、再開、人間レビュー
- [CONDUCTOR_policy.md](CONDUCTOR_policy.md): Orchestratorの科学的原則
- [CONDUCTOR_interpretation_policy.md](CONDUCTOR_interpretation_policy.md): Interpretationの比較視点
- [CONDUCTOR_output_contract.md](CONDUCTOR_output_contract.md): Run Rootと最小artifact
- [CONDUCTOR_identifier_reference.md](CONDUCTOR_identifier_reference.md): ID体系

## 実装・監査

- [CONDUCTOR_0.2.0_result_interpretation_refactor_proposal.md](CONDUCTOR_0.2.0_result_interpretation_refactor_proposal.md): Result Card、Review Bundle、絶対評価、Interpretation再設計
- [CONDUCTOR_version_history_0.2.0.md](CONDUCTOR_version_history_0.2.0.md): 0.2.0の実装変更と互換性
- [CONDUCTOR_targeted_fix_plan_packet_mmp_a005.md](CONDUCTOR_targeted_fix_plan_packet_mmp_a005.md): Packet CLI、read-only MMP全Clustering survey性能、A005 Artifact重複の局所改修計画
- [CONDUCTOR_version_history_0.1.7.md](CONDUCTOR_version_history_0.1.7.md): 0.1.0以降の要約と0.1.7の変更点
- [CONDUCTOR_design_spec.md](CONDUCTOR_design_spec.md): Main Orchestrator、Executor、Interpreter、Runtime、Control、Event Ledger、詳細DAG snapshot
- [CONDUCTOR_skill_catalog.md](CONDUCTOR_skill_catalog.md): 人間allowlistから生成したCatalog
- [CONDUCTOR_skill_catalog_ja_quick_reference.md](CONDUCTOR_skill_catalog_ja_quick_reference.md): Description、Clustering、Operator、Interpretationの日本語早見表
- [CONDUCTOR_verification.md](CONDUCTOR_verification.md): 検証方法

`prompt/`には初回、探索screening Round、full Interpretation Round、継続Round、別session引継ぎ、Failed Nodeの同一Round再試行、read-only MMP Global–Local解釈、Concierge用のプロンプト例があります。Catalog収載対象は`catalog/included_skills.json`、標準解析範囲は`catalog/analysis_profile.json`が正本です。0.2.0は旧Runを継続せず、新規Runとして開始します。

過去Version固有の仕様書・実装計画・是正計画は現役Packageへ同梱せず、Git履歴および各Version branchを参照します。
