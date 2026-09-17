# CONDUCTOR documentation

CONDUCTOR 0.2.1 の設計・実装文書です。段階11と実装適合性残件まで完了し、正式較正と offline provider を用いた本番相当確認が残っています。現在地は [`CONDUCTOR_0.2.1_stage11_implementation_report.md`](CONDUCTOR_0.2.1_stage11_implementation_report.md) を参照してください。

まず [`CONDUCTOR_0.2.1_specification_overview.md`](CONDUCTOR_0.2.1_specification_overview.md) を読んでください。全体像と決定事項はそこにあります。

**実装を担当する方**は [`CONDUCTOR_0.2.1_implementer_brief.md`](CONDUCTOR_0.2.1_implementer_brief.md) から読んでください。読む順序、着手前に作る文書、守るべき制約がまとまっています。

## 各論

| 文書 | 内容 |
|---|---|
| [`design/calibration_results.md`](design/calibration_results.md) | **実データ較正結果。全パラメータの根拠** |
| [`design/endpoint_model.md`](design/endpoint_model.md) | Endpoint レジストリ、欠測パターン診断、MPO 拡張点、許容性 |
| [`design/feature_space_roles.md`](design/feature_space_roles.md) | 特徴量空間の二役割、局所平坦性、条件付き平坦性、文脈の翻訳 |
| [`design/discovery_lenses.md`](design/discovery_lenses.md) | 6つの発見レンズ（L1〜L6）の詳細仕様 |
| [`design/finding_model.md`](design/finding_model.md) | Finding スキーマ、型、反証条件、状態、ラベル、引用規則 |
| [`design/candidate_generation.md`](design/candidate_generation.md) | 条件の語彙、探索深度、段階A/B/C、スコアリング |
| [`design/deep_dive_protocol.md`](design/deep_dive_protocol.md) | 深堀エンジン、テンプレート集合、予算、実行例 |
| [`design/llm_operating_contract.md`](design/llm_operating_contract.md) | Local LLM の分業線、引用強制、タスク分解 |
| [`prompt/CONDUCTOR_0.2.1_prompts.md`](prompt/CONDUCTOR_0.2.1_prompts.md) | **本番運用プロンプト、Database再利用手順、Local LLM内部プロンプト** |
| [`design/open_questions.md`](design/open_questions.md) | 未決事項。**Chemist の知識が必要な項目を A 群に集約** |

## 設計テーゼ

> 条件付けによって初めて現れる構造を、網羅的な試行によって発見する。

Global なデータが単純な関係性で記述できることは現実にはほぼ無い。しかしある局所に条件付けると有用な関係性が現れることがある。条件の探索空間は人間には広すぎるが、機械には可能である。

Local LLM に求めるのは「賢いこと」ではなく「倦まず大量にこなすこと」である。1回の深い洞察ではなく、1000回の浅い作業の集積で深さに到達する。

## 0.1.x のドキュメント

`archive_0.1.x/` へ退避しました（Git 管理対象外）。0.2.1 は思想もコードも 0.1.x を引き継ぎません。技術的に流用する資産は仕様概要書 第11章に列挙しています。

## 工程

```text
① 仕様概要書の最終化      完了
② 実装計画書の作成・最終化  完了
③ 段階1〜11の初回実装       完了
④ 実装適合性確認             完了
⑤ 正式較正・本番相当確認     ← 現在地
```

閾値類は `CONDUCTOR_modules/diagnosis/` の診断モジュールを実データへ適用して確定済みです。結果は [`design/calibration_results.md`](design/calibration_results.md)。

診断モジュールを本解析パイプラインへ組み込む（診断 → パラメータ自動設定 → 本解析）のは **0.2.2** で行います。0.2.1 では独立した計測ツールとして維持します。
