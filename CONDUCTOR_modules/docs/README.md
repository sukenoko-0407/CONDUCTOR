# CONDUCTOR 0.2.1 文書案内

このdirectoryには、現行仕様、運用手順、設計根拠、実装・受入履歴が同居しています。
古いcheckpointや質問記録を現行運用指示として使わないよう、以下の区分で参照してください。

## まず読む

| 読者 | 文書 | 目的 |
|---|---|---|
| 利用者 | [利用者ガイド](CONDUCTOR_0.2.1_user_guide.md) | 入力準備から受入・レポート確認まで |
| 全員 | [仕様概要書](CONDUCTOR_0.2.1_specification_overview.md) | CONDUCTORが保証すること／しないこと |
| 運用担当 | [運用プロンプト集](prompt/CONDUCTOR_0.2.1_prompts.md) | Preflight、本番Run、再開、監査 |
| 結果利用者 | [HTMLレポートガイド](CONDUCTOR_0.2.1_reporting_guide.md) | Finding順位、図、Evidenceの読み方 |
| 実装担当 | [実装詳細仕様書](CONDUCTOR_0.2.1_implementation_detail_spec.md) | artifact、Runtime、各Phaseの契約 |

## システムを短時間で説明する資料

- [処理プロセス図](images/CONDUCTOR_0.2.1_process_overview.png)
- [説明スライド](CONDUCTOR_0.2.1_overview_slides.pptx)
- [全Lens HTML例](report_examples/JAK2_all_lens_final_mock/index.html)

HTML例の数値はレイアウト確認用mockです。本番Findingではありません。

## 現行の正本文書

| 文書 | 位置づけ |
|---|---|
| [仕様概要書](CONDUCTOR_0.2.1_specification_overview.md) | 最上位の決定事項 |
| [実装計画書](CONDUCTOR_0.2.1_implementation_plan.md) | 0.2.1実装の工程と受入基準 |
| [実装詳細仕様書](CONDUCTOR_0.2.1_implementation_detail_spec.md) | 現行コード契約 |
| [R1修正計画書](CONDUCTOR_0.2.1_R1_remediation_plan.md) | 本番試験で確定した修正事項 |
| [R1実装詳細計画](CONDUCTOR_0.2.1_R1_implementation_detail_plan.md) | R1修正の実装単位と試験 |
| [本番正式受入報告](CONDUCTOR_0.2.1_R1_production_acceptance_report.md) | 受入済みRunの実測結果 |

正本文書間で矛盾がある場合は、仕様概要書の最新決定事項、R1修正計画、実装詳細仕様の順に確認し、
それでも決まらない事項は独断で補完せず質問文書へ記録します。

## 設計解説

| 文書 | 内容 |
|---|---|
| [Endpoint model](design/endpoint_model.md) | 向き、transform、欠測、MPO拡張点 |
| [Feature-space roles](design/feature_space_roles.md) | Description、距離、文脈条件付け |
| [Discovery lenses](design/discovery_lenses.md) | L1b/L2a/L2b/L4/L5/L7 |
| [Finding model](design/finding_model.md) | claim、test、state、反証、引用 |
| [Candidate generation](design/candidate_generation.md) | 未探索候補とscoring |
| [Deep-dive protocol](design/deep_dive_protocol.md) | 固定templateによる反証 |
| [LLM operating contract](design/llm_operating_contract.md) | 決定論コードとLocal LLMの境界 |
| [Calibration results](design/calibration_results.md) | 閾値・rateの根拠 |

## 運用文書

- [運用プロンプト集](prompt/CONDUCTOR_0.2.1_prompts.md): 通常使用する入口。
- [既存Run HTML export](prompt/CONDUCTOR_0.2.1_R1_HTML_report_export_prompt.md): HTML実装前の受入済みRun専用。
- `R1_P04_P06_recovery`、`R1_P06_recovery`、`R1_stage3_production_checkpoint`:
  特定障害・検証段階の記録用。通常の新規Runには使わない。
- `performance_redesign_independent_review_prompt`: R1設計レビュー時の履歴資料。

## 履歴・監査資料

次は意思決定の追跡に残す文書であり、通常運用の手順書ではありません。

- `*_implementation_questions.md`
- `*_implementer_brief.md`
- `*_stage*_checkpoint.md`
- `CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md`
- `CONDUCTOR_0.2.1_independent_performance_review.md`
- `CONDUCTOR_0.2.1_scale_measurement_report.md`
- `CONDUCTOR_0.2.1_spec_conformance_audit.md`
- `CONDUCTOR_0.2.1_production_remediation_report.md`
- `CONDUCTOR_0.2.1_stage11_implementation_report.md`

これらは削除せず、なぜ現行仕様になったかを説明する監査証跡として保存します。

## Schemaと設定

- Schemaとexampleの区別: [`../schemas/README.md`](../schemas/README.md)
- 既定設定: [`../config/defaults.yaml`](../config/defaults.yaml)
- resolved config例: [`../config/resolved_config.example.yaml`](../config/resolved_config.example.yaml)
- 固定production DAG: [`../pipeline/production_pipeline.v0.2.1.json`](../pipeline/production_pipeline.v0.2.1.json)

`resolved_config.yaml`、`provider_config.json`、Run Specは本番環境固有値を含むため、exampleを複製して
本番解析directory側で管理します。
