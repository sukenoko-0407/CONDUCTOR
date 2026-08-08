# CONDUCTOR documentation

このdirectoryはCONDUCTOR 4.3.1のtarget specificationを収載する。ファイル名の`v4`はmajor系列名として維持する。以下の「正本文書」を設計判断の基準とする。

## 正本文書

| 文書 | 役割 |
|---|---|
| [設計仕様](CONDUCTOR_v4_design_spec.md) | Run、Round、phase、DAG、State、Skill境界の全体仕様 |
| [Orchestration Policy](CONDUCTOR_v4_policy.md) | Orchestratorの行動原則、phase gate、承認と失敗時の扱い |
| [Interpretation Policy](CONDUCTOR_v4_interpretation_policy.md) | Evidence比較、Finding、Hypothesis、Question、salienceの規則 |
| [出力契約](CONDUCTOR_v4_output_contract.md) | 一般利用／CONDUCTOR利用のartifactと保存場所 |
| [識別子リファレンス](CONDUCTOR_identifier_reference.md) | Capability、Node、Round、Group、Evidence等のID契約 |
| [利用手順](CONDUCTOR_v4_user_guide.md) | 新規Run、後続Round、部分解析、再開方法 |
| [リファクタリング計画](CONDUCTOR_refactoring_plan.md) | 実装順序、変更境界、試験、完了条件 |
| [4.3.1実装計画](CONDUCTOR_v4.3.1_refactoring_plan.md) | 単一Writer、Audit、Interpretation gate、移行仕様 |

## 補助資料

- `CONDUCTOR_explanation/`は人間向け概念説明であり、細かな実装契約の正本ではない。
- HTML、PNG、`CONDUCTOR_internal_overview.pptx`は説明用snapshotであり、target specificationの正本ではない。`CONDUCTOR_explanation/`のHTMLは対応Markdownから再生成済みで、画像をbase64埋込みしている。
- `CONDUCTOR_v4_skill_catalog.md`はCapability一覧であり、Catalog生成物と照合して更新する。
- Description計算、Grouping計算、Operator数値Kernelの科学的仕様は現行Skillを基準とし、今回のcontrol-plane refactorでは原則変更しない。

## プロンプト集

- [新規・継続解析依頼](prompt/CONDUCTOR_analysis_request_prompt.md)
- [セッション引継ぎ](prompt/CONDUCTOR_session_handoff_template.md)
- [v4.3.0からv4.3.1への一回限りのMigration](prompt/CONDUCTOR_v430_to_v431_migration_prompt.md)
- [Migration直後の安全確認](prompt/CONDUCTOR_post_migration_audit_prompt.md)

## 互換性

4.3.1の通常Runtimeは4.3.0 Stateを暗黙更新しない。例外として、一回限りのMigration Agent／Skillが `scan → 人間承認 → apply → verify` により、旧run rootを変更せず別の新run rootを作成できる。検証済みDescription／Grouping／Operator artifactだけをactive DAGへ取り込み、旧Interpretationは参照用に保持して新Roundで作り直す。

通常再開時のAgent入力は `summaries/orchestrator_brief.json` であり、`state.json` は機械可読な正本、`state_summary.json` はboundedな事実要約である。監査は `audit/<timestamp>/` に保存する。
