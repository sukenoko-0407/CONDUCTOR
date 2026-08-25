# CONDUCTOR 0.1.7 実装計画書

## 1. 目的

0.1.6の「一Round最大50 Analysis NodeをまとめてInterpretationする」制約を、逐次Result Screeningと選抜型Interpretationへ置き換える。Operator探索件数をInterpreterの一括読込件数から分離し、Local LLMでもbounded contextを維持したまま広い探索を行えるようにする。

本計画は0.1.6後方互換を必須とする。既存Run、Result Card、Operator成果物、MMP Databaseを書き換えず、0.1.7の新しい索引とRound設定を加算的に導入する。

## 2. 変更範囲

### 変更対象

- RuntimeのAnalysis予算、Screening queue、評価commit、Round終端判定。
- Round ContractとWorking Setの最小拡張。
- Interpreterの`screening`／`synthesis` mode分離。
- Interpretation Skillの入力・draft契約。
- Orchestrator Skillの`required_action`対応。
- 評価索引、CSV view、screening summaryのschemaとrenderer。
- 0.1.7用Policy、User Guide、prompt、Version表記。
- Unit、integration、compatibility、E2E test。

### 変更しない対象

- Description Skillの計算実装と出力。
- Clustering Skillの計算実装と出力。
- Operator Skillの科学計算実装と既存Result Card。
- MMP Database作成、詳細Table、read-only MMP Interpretation。
- Node ID、Cluster ID、Result ID、Insight ID体系。
- Packet署名、Runtime Worker、Leaseの基本設計。
- Conciergeのread-only／専用出力境界。

## 3. 実装原則

1. Result Cardを変更せず、評価を別索引へ保存する。
2. Runtimeを唯一のWriterとする。
3. InterpreterへState更新、Node生成、正式ID発行をさせない。
4. Screeningは少数件、再開可能、冪等とする。
5. Main Orchestratorへ長い評価内容を返さない。
6. `report_mode`がない0.1.6 Roundは従来どおり`full`とする。
7. 進行中Roundの意味をPackage差替えだけで変更しない。
8. 得点を科学的真実や統計的有意性として扱わない。

## 4. Phase 1: 現行挙動の固定と互換fixture

### 作業

- 0.1.6のRound Contract、Control、DAG snapshot、Result Index、Result Card、Interpretationをfixture化する。
- `max_additional_nodes=50`、最大50 Analysis Node、最大50 Result Cardの現行挙動をlegacy testとして固定する。
- `report_mode`を持たないactive、FINALIZING、AWAITING_HUMAN_REVIEW、CLOSEDの各状態を用意する。
- 一Nodeが複数Result Cardを生成するA005等のfixtureを含める。

### 合格条件

- 実装前の0.1.6 testが再現する。
- 0.1.7 Runtimeでfixtureを読んでもschema errorや暗黙の成果物変更が起きない。

## 5. Phase 2: Schemaと永続化形式

### 新規schema

- `result_assessment.schema.json`
- `screening_batch.schema.json`
- `screening_draft.schema.json`
- `screening_summary.schema.json`

### 既存schemaの拡張

- `round_contract.schema.json`
  - optional `report_mode: screening | full`を追加する。
  - 欠落時はRuntimeで`full`へ正規化する。
  - `max_additional_nodes`の既定値50を維持し、profile安全上限内で50超を許可する。
- 必要な場合だけ`working_set.schema.json`へcompactなScreening進捗を追加する。

### 永続化

- `runtime/result_assessment_index.jsonl`をRun-wide正本とする。
- 同一`result_ref + source_hash + rubric_version`の二重active評価を禁止する。
- revisionはappend-onlyとし、最新値はRuntimeが投影する。
- `rounds/<round_id>/result_assessments.csv`は正本から再生成可能なviewとする。
- `rounds/<round_id>/screening_summary.json`はRound handoff用のcompact artifactとする。

### 合格条件

- 追記途中の失敗から復旧しても重複評価が生じない。
- CSVを削除してもJSONLから同一内容を再生成できる。
- 0.1.6 Runに索引がなくても正常に起動できる。

## 6. Phase 3: Runtime Screening queue

### 対象

- `CONDUCTOR_modules/tools/runtime_controller.py`
- Runtime関連schema、test、Skill文書。

### 作業

1. `runtime/result_index.jsonl`から、downstream利用可能かつ現rubricで未評価のResult Cardを抽出する。
2. Result Cardのnode、round、scope、Cluster、Operator、Description、ClusteringをRuntimeで確定する。
3. 直接比較可能なGlobal／Local、同一Clustering sibling、同一Operator comparatorの参照だけを付与する。
4. Result Card件数とserialized byte数の両方でScreening batchを制限する。
5. batchに不変IDと入力hashを付与し、再実行時に同一batchを再利用する。
6. Interpreter draftをschema検証し、参照外Result、範囲外得点、欠落理由を拒否する。
7. commit後にJSONL、Round CSV、compact progressを更新する。

### 新しいRuntime action

名称は実装時に既存command規則へ合わせるが、責務は次の二つに限定する。

- `PREPARE_RESULT_SCREENING`: 未評価Resultからbounded contextとdraftを作る。
- `COMMIT_RESULT_SCREENING`: draftを検証して評価索引へcommitする。

MainはRuntimeが返す一つの`required_action`だけに従う。候補検索、batch分割、重複判定をMainに行わせない。

### 失敗時

- Screening失敗でOperator Node statusを変更しない。
- 同じbatchを既定回数だけ再試行する。
- 評価不能なResultは`not_scorable`と具体的理由を要求する。
- InterpreterまたはRuntimeの実装不良を低得点へ変換しない。
- retry exhausted時はcompact blockerを出し、人間判断なしで無限継続しない。

### 合格条件

- 100件以上のResult Cardを複数batchで評価できる。
- 一つのScreening contextが件数・byte上限を超えない。
- process中断後に未commit batchから再開できる。
- MainのWorking SetへResult Card本文が蓄積しない。

## 7. Phase 4: Operator探索予算の分離

### 作業

- `_analysis_planning_limits()`の固定50検査を廃止する。
- Round Contractの`max_additional_nodes`とprofile安全上限を分離する。
- 省略時50を維持し、人間が明示した場合だけ50超を許可する。
- Wall Time、Node予算、human checkpointのうち最初に到達した条件で探索を止める。
- 実行候補の小分けはRuntimeが担当し、各単位の完了後に未評価ResultをScreeningへ回す。
- 既存のGlobal優先、履歴横断重複除外、balanced selectionを維持する。
- 実行単位ごとの正式Interpretation作成は禁止する。

### 合格条件

- `max_additional_nodes=50`は0.1.6と同等に動く。
- 人間指定値が50を超えるRoundで、50件到達だけを理由にFINALIZINGへ移行しない。
- Wall Timeだけを増やしてもNode予算は増えない。
- 同一signatureが別の実行単位で重複登録されない。

## 8. Phase 5: Interpreter screening mode

### 対象

- `.claude/agents/cs-conductor-interpreter.md`
- `.claude/skills/cs-analysis-interpret-results/`
- Interpretation Policyと関連test。

### 作業

- Interpreter入力へ明示的な`mode`を追加する。
- `screening` modeでは固定rubricに基づく構造化評価だけを返す。
- Insight、正式ID、HTML、Markdown、追加Nodeを生成しない。
- 得点は0～10整数、`evidence_strength`はenum、理由は一文とする。
- scope、Cluster、sample count、Operator IDはRuntime値を引用し、Interpreterに推測させない。
- Result Cardだけで不足する場合に限り、許可されたartifactを一段だけ確認する。
- 関連性や反証候補は`allowed_result_refs`内だけを参照する。

### 認知負荷対策

- 一batchのResult Card件数を小さく固定する。
- 過去Report全文、DAG snapshot、State詳細を渡さない。
- 評価済みResultの本文を次batchへ継承しない。
- rubricとJSON schemaを毎回同一にする。
- Mainへは評価明細ではなくcompact completionだけを返す。

### 合格条件

- 同じfixtureに対してschema上安定した評価を返す。
- scopeやCluster IDの創作を品質ゲートが拒否する。
- 一文字単位の配列化や空の理由を拒否する。

## 9. Phase 6: 選抜型Synthesis

### 作業

- `prepare-interpretation`を、全Result Cardのround-robin抽出から評価索引を利用するshortlist作成へ変更する。
- shortlistは高得点だけでなく、Operator／Description／Clustering／scopeの分散、Comparator、反証、negative result、人間focusを含める。
- 同一または高度に冗長な結果群は代表Cardを選び、必要な関連参照だけを保持する。
- 過去Roundは自動全件読込せず、新規候補に直接関連する評価済みResultだけを追加する。
- Interpreterはshortlistから原Result Cardを確認し、保持Insightだけ元artifactで検証する。
- 正式Reportの既存品質ゲート、scope検証、日本語本文、空でないInsight title、完全なlimitations文を維持する。

### 選抜と推論の境界

Runtimeが行うこと:

- score順序、重複排除、strata coverage、Comparator接続、context上限。

Interpreterが行うこと:

- 結果の意味、Insight採否、矛盾の価値、限界、反証、次の人間判断への説明。

Runtimeは得点閾値だけでInsightを自動生成しない。

### 合格条件

- 200件以上の評価索引からbounded shortlistを作れる。
- 上位が同一Operatorだけでもshortlistが完全に単一種類へ偏らない。
- Global–Local claimに双方のResult参照が必要である。
- 低得点Resultを根拠なく削除または失敗扱いしない。

## 10. Phase 7: Round終端とAudit

### `screening` mode

- 新規eligible Result Cardがすべて`scored`または理由付き`not_scorable`であることを確認する。
- `result_assessments.csv`と`screening_summary.json`を作成する。
- Summaryのschema、参照、件数、hashをAuditする。
- 正式Interpretation Nodeを要求せず、Audit後に`AWAITING_HUMAN_REVIEW`へ進む。

### `full` mode

- Screening完了後にshortlistを作る。
- Interpretation JSON／Markdown／HTMLを生成する。
- 既存Full Audit後に`AWAITING_HUMAN_REVIEW`へ進む。

### Legacy mode

- `report_mode`欠落時は`full`。
- 進行中0.1.6 Roundでは、0.1.6のResult Card selectionと50件上限を保持してRoundを完了する。
- Legacy Round完了後の新Roundから0.1.7 Screeningを選択できる。

### 合格条件

- `screening` RoundがInterpretation欠落エラーにならない。
- `full` RoundがInterpretationなしで終了しない。
- どちらもAuditなしで人間レビュー状態へ進まない。
- Runtimeが新Roundを自動開始しない。

## 11. Phase 8: 0.1.6互換試験

### 必須ケース

1. 0.1.6 CLOSED Runから0.1.7 `screening` Roundを開始する。
2. 0.1.6 AWAITING_HUMAN_REVIEW Runをacceptし、次Roundを開始する。
3. 0.1.6 active Roundをlegacy `full`として完了する。
4. 既存Result Cardを変換せず、必要なものだけ遅延評価する。
5. 既存Interpretation、Insight ID、Result ID、MMP Databaseのhashが変化しない。
6. 評価索引が存在しないRunで正常にbootstrapする。
7. 0.1.6と同じExecution Request／Packetを実行できる。

### 互換性を保証しないもの

- 0.1.6の終了済みInterpretationを自動的に再採点・再生成すること。
- 進行中Roundを途中から`screening`へ切り替えること。
- 旧Result Cardに存在しない情報を推測して補完すること。

## 12. Phase 9: E2E試験

### 小規模

- 10～20 Operator ResultでScreening、CSV、Summary、full Interpretationを確認する。
- 一Node複数Result Card、低得点、評価不能、negative resultを含める。

### 拡大試験

- 50を超えるOperator Nodeを同一Roundで実行する。
- 100件以上のResult Cardを複数Screening batchで処理する。
- Agentごとの最大context件数とserialized byte数を記録する。
- Screening途中でInterpreterを停止し、同一batchから再開する。
- 正式Interpretationが全Cardを読まずshortlistだけを使用したことを確認する。

### 複数Round

- Round 1を`screening`で終了する。
- 新sessionからRound 2を`screening`で継続し、評価済みResultを再読込しない。
- Round 3を`full`とし、過去の高優先度候補と当該Round候補を限定的に統合する。
- 人間focusで過去の低得点Resultを再評価できることを確認する。

### 合格基準

- Node ID、Result参照、評価revisionに重複がない。
- MainのWorking SetとInterpreter contextが上限内に保たれる。
- 100件以上を探索しても一つのAgentが全Result Cardを同時に読まない。
- Operator成功とScreening失敗が混同されない。
- scoreだけを根拠に科学的断定を生成しない。
- 0.1.6成果物が書き換えられない。

## 13. 文書・Prompt更新

実装完了時に次を更新する。

- `CONDUCTOR_modules/docs/README.md`
- `CONDUCTOR_overview.md`
- `CONDUCTOR_user_guide.md`
- `CONDUCTOR_design_spec.md`
- `CONDUCTOR_policy.md`
- `CONDUCTOR_interpretation_policy.md`
- `CONDUCTOR_output_contract.md`
- `CONDUCTOR_verification.md`
- `CONDUCTOR_version_history_0.1.7.md`
- `docs/prompt/`の日常用・特別時用prompt集
- Orchestrator、Runtime、Interpretationの各README／SKILL.md

Promptでは、人間が最低限次だけを指定できるようにする。

- Run RootとRound番号。
- `report_mode`。
- Wall Time、最大Analysis Node数、並列数、CPU core数。
- 任意の重点視点。

MainへScreening batchの組立てや評価CSV編集を指示しない。

## 14. 実装順序

推奨順序は次のとおりである。

1. 0.1.6互換fixtureと回帰test。
2. 新schemaと評価索引Writer／Reader。
3. Runtime Screening queueと冪等commit。
4. Interpreter screening mode。
5. 50件固定の解除と人間承認予算への接続。
6. shortlist生成とSynthesis改修。
7. `screening`／`full`の終端gateとAudit。
8. Skill、Agent、Policy、Prompt、Catalog文書の整合。
9. 小規模test、拡大E2E、複数Round、0.1.6互換試験。

状態遷移と互換性を先に固定し、最後に50件制限を解除する。Screeningが未完成の状態でOperator上限だけを増やしてはならない。

## 15. 中止・見直し条件

次の場合は実装を止め、設計を見直す。

- ScreeningのためにResult Card schemaの破壊的変更が必要になる。
- Mainが評価待ちqueueや個別scoreを直接管理しなければ動かない。
- 一batchの失敗が成功済みOperator Nodeを破壊する。
- 0.1.6 active Roundの意味を安全に判定できない。
- scoreがOperator固有の科学指標と混同される。
- `screening` mode追加によりRoundの人間開始原則が崩れる。

## 16. 完了時に提出するもの

- 変更したSkill、Subagent、`CONDUCTOR_modules`上位ファイルの一覧。
- 0.1.6互換試験結果。
- 50超Operator探索のE2E結果。
- 最大Screening context件数・byte数。
- retry／resume test結果。
- `screening`と`full`各Roundの成果物例。
- 残存制約とLinux HPCでの確認事項。

