# CONDUCTOR 0.1.7 仕様概要

## 1. 位置づけ

0.1.7は、0.1.6のRun、Node、Result Card、Operator成果物、MMP Databaseをそのまま利用できる後方互換Versionである。Description、Clustering、Operatorの科学計算機能は変更せず、Operator探索とInterpretationの接続方法を改善する。

0.1.6では、一Roundにつき最大50 Analysis Nodeを生成し、そのRoundのResult Cardを最大50件まとめてInterpreterへ渡し、正式Interpretationを作成していた。この上限はInterpreterの認知負荷を抑えるために必要だったが、探索初期に50件ごとにRoundを終了し、長文Reportを生成する非効率を生じさせていた。

0.1.7では、Operator数を単純に増やして一括Interpretationする方式を採用しない。Result Cardを少数ずつ評価する逐次Screeningを導入し、人間が承認した資源予算まで同一Round内で探索を継続できるようにする。正式Interpretationは、評価索引から選抜した限定的なResult Cardだけを用いて作成する。

## 2. 目的

- 初期探索で、50 Operatorごとに正式Interpretationを作る必要をなくす。
- 一つのLLM Agentへ大量のResult Cardを同時に読ませない。
- Operator探索数とInterpreterの認知負荷を分離する。
- Roundを重ねても、評価済みの低優先度Result Cardを繰り返し読まない。
- 高得点結果だけでなく、Global–Local変化、異種Description間の一致、矛盾、反証、negative resultを正式Interpretation候補へ残す。
- 0.1.6の成果物とRun状態を破壊せず、新しいRoundから0.1.7方式を利用できるようにする。

## 3. 非目的

- Description、Clustering、Operatorの科学kernelを変更しない。
- Result Cardの既存schemaや内容を採点値で書き換えない。
- 10点評価を統計的有意性、真実性、予測精度として扱わない。
- 低得点結果やnegative resultを削除しない。
- Screening評価から自動的に追加Nodeや新Roundを生成しない。
- 人間の明示指示なしにRoundを開始しない。

## 4. 基本概念

### 4.1 Operator探索予算

人間はRound開始時に、Wall Time、最大Analysis Node数、並列数、利用可能CPU core数を承認する。Runtimeは、承認値のいずれかへ到達するまで探索を継続できる。

0.1.6の`max_additional_nodes`は後方互換のため維持し、Analysis Node予算として解釈する。省略時は50とする。0.1.7ではprofileの安全上限まで人間が50を超える値を明示指定できる。Wall Timeを長く指定しただけではNode上限を暗黙に増加させない。

大量Nodeを一つのLLM判断でまとめて生成しない。Runtimeは履歴重複を除外し、Globalを優先しながら、既存のbalanced selectionで実行候補を小さな単位へ分ける。この単位は実行と復旧の境界であり、Interpretation Reportの境界ではない。

### 4.2 Result Screening

成功し、`eligible_for_downstream=true`となったResult Cardを少数件ずつ評価する。評価単位はOperator NodeではなくResult Cardである。一つのNodeがGlobalと複数Clusterなど複数Result Cardを生成し得るためである。

Screeningは既存のInterpreter役を短時間の`screening` modeで起動して行う。一回のcontextには少数の新規Result Card、Runtimeが特定した直接Comparator、固定rubricだけを含める。過去のResult Card本文や長いInterpretation Reportを一括して渡さない。

各Screening呼出しは独立し、評価結果をcommitした後に終了する。Main Orchestratorへ返す情報は、評価件数、未評価件数、成否、次の`required_action`に限定する。

### 4.3 10点評価の意味

`interest_score`は0～10の整数とし、「正式Interpretationまたは人間の詳細確認で優先する価値」を表す。科学的正しさの確率ではない。

評価rubricは次の五観点を各0～2点で評価する。

| 観点 | 0～2点で見る内容 |
|---|---|
| signal | 変化、偏り、例外、Landscape、関連性の明瞭さ |
| contrast | Global–Local、Cluster間、Comparatorとの差 |
| independence | 既存の類似結果に対する非冗長性、異なる表現での再現可能性 |
| interpretability | 化学・構造・実験仮説へ接続できる程度 |
| follow-up value | 反証、深掘り、人間判断へつながる程度 |

信頼性は点数へ埋め込まず、別の`evidence_strength`として`low`、`medium`、`high`で記録する。これにより、小規模だが構造的に凝集したClusterの大きな変化を「高関心・低信頼」として保持できる。

評価には短い理由、評価不能理由、関連Result、rubric version、Result Cardのhashを含める。新しい結果によって重要性が変わった場合はrevisionを追記し、過去評価を上書きしない。

### 4.4 評価索引

Result Cardはimmutableのまま保持し、評価を別索引へ保存する。

- Run正本: `runtime/result_assessment_index.jsonl`
- Round別の人間向けview: `rounds/<round_id>/result_assessments.csv`
- 探索終了時のcompact summary: `rounds/<round_id>/screening_summary.json`

最低限の評価項目は次のとおりとする。

| Field | 内容 |
|---|---|
| `result_ref` | 評価対象Result Cardの不変参照 |
| `node_id` / `round_id` | 由来NodeとRound |
| `capability_id` | Operator ID |
| `scope_mode` / `cluster_ids` | Runtime確定scope |
| `interest_score` | 0～10の確認優先度 |
| `evidence_strength` | low / medium / high |
| `reason` | 一文の評価理由 |
| `related_result_refs` | Comparator、支持、反証候補 |
| `assessment_status` | scored / not_scorable |
| `rubric_version` | 評価基準Version |
| `source_hash` | 元Result Cardのhash |
| `revision` | 再評価履歴 |

同じ`result_ref`、`source_hash`、`rubric_version`の組合せは再評価しない。低得点結果も索引に残し、同じ結果の再読込と同一解析の再実行を避ける。

## 5. Interpretationの二つの処理

0.1.7では、Interpreterの責務を二つのmodeへ分ける。ただし新しいSubagentは増やさず、既存`cs-conductor-interpreter`を使う。

### 5.1 Screening mode

- 新規Result Cardを少数件ずつ定型評価する。
- 長文のInsightやHTML Reportを作らない。
- Operator成果物はResult Cardだけでは評価不能な場合に限って開く。
- Node、DAG、State、Insight IDを変更しない。
- Runtimeが評価schema、参照、hash、重複を検証して索引へcommitする。

### 5.2 Synthesis mode

- 正式Interpretationを要求されたRoundだけで起動する。
- すべてのResult Cardではなく、評価索引とRuntimeが作るbounded shortlistを読む。
- shortlistから原Result Cardを確認し、必要な場合だけOperator成果物を開く。
- 高得点順だけでなく、結果の多様性、Global–Local対、矛盾、反証、negative resultを確認する。
- 既存の品質ゲートに従い、日本語の`interpretation.json`、`interpretation.md`、`interpretation.html`を生成する。

Shortlistは、次を満たすようにRuntimeが機械的に候補化する。

1. 高い`interest_score`を持つ候補。
2. Operator、Description、Clustering、scopeが一種類へ偏らない代表。
3. Global–LocalまたはCluster間の比較対。
4. 高得点候補に対する反証、不一致、negative result。
5. 人間が明示した重点Result、Cluster、Operator。

Runtimeは候補を選ぶが、科学的Insightの採否や意味づけは決定しない。最終的な比較、解釈、限界記載はInterpreterの推論責務とする。

## 6. RoundのReport mode

Round Contractへ`report_mode`を追加する。

| Mode | 用途 | Round終端成果物 |
|---|---|---|
| `screening` | 序盤の広いOperator探索 | 評価索引、CSV view、compact screening summary、Audit |
| `full` | 正式な科学解釈と人間レビュー | 上記に加え、Interpretation JSON／Markdown／HTML、Full Audit |

新規0.1.7 Runの序盤では`screening`を推奨する。人間が重要候補の統合を求めるRound、深掘りRound、報告Roundでは`full`を使用する。

0.1.6由来のRound Contractに`report_mode`がない場合は`full`として扱う。進行中の0.1.6 Roundは途中でmodeを変更せず、従来のInterpretation gateで終了する。0.1.7方式への切替えは`AWAITING_HUMAN_REVIEW`または`CLOSED`後の新Roundから行う。

`screening`でもRoundの引継ぎ情報は省略しない。`screening_summary.json`には、評価済み件数、未評価件数、得点分布、上位Result参照、Operator／scope coverage、終了理由、評価索引参照を記録する。長文の科学解釈は含めない。

## 7. 状態遷移

概念上の処理は次のとおりである。

```text
Human starts Round
        |
        v
Plan / Execute Operator work
        |
        v
Screen newly committed Result Cards in bounded batches
        |
        +---- authorized budget remains ----> Plan / Execute next work
        |
        v
Finalize Round
        |
        +---- report_mode=screening ---> screening summary + audit
        |
        +---- report_mode=full --------> shortlist + Interpretation + full audit
        |
        v
AWAITING_HUMAN_REVIEW
```

Operator成功とScreening成功は別管理とする。Screening失敗によって成功済みOperator Nodeを`failed`へ戻さない。評価batchは冪等に再試行でき、同じ評価を二重commitしない。評価不能なResult Cardは`not_scorable`と理由を記録し、隠して完了扱いにしない。

## 8. 過去Roundと複数Round

評価索引はRun全体で一つとする。後続Roundは、すべての過去Result Cardを読み直さず、評価索引の上位候補、関連候補、人間指定候補だけを参照する。

正式Interpretationは原則として当該Roundの新規評価結果を中心とするが、次の場合は過去Roundを参照できる。

- 新規候補のGlobal comparatorまたはcounterexampleである。
- 同一Cluster、Operator、Descriptionに関する過去の高優先度結果である。
- 人間がResultまたはInsightを明示した。
- 過去評価の再検討が必要になった。

過去の低得点結果を自動的に全件再読込しない。重要度は可変であるため、関連性が生じたResultはrevision付きで再評価できる。

## 9. MMPの境界

A014の通常Screeningでは、従来どおりcompactなGlobal Result Cardだけを扱う。MMP Database、詳細CSV、Reference Card、Global–Local MMP surveyの仕様は変更しない。

Transform、Exact Core、Environment、Clusteringを横断する詳細解釈は、人間起動のread-only `cs-analysis-interpret-mmp`が担当する。通常Interpretationへ大量のMMP詳細Cardを混入させない。

## 10. 0.1.6後方互換性

### 維持するもの

- Run Root構造とNode ID。
- `runtime/result_index.jsonl`と既存Result Card schema。
- Description、Clustering、Operator、MMP Databaseの成果物。
- 既存Interpretation、Insight Index、Audit。
- Execution Request、Packet、Worker、Leaseの基本契約。
- 0.1.6の`report_mode`なしRoundを`full`として完了する挙動。

### 追加するもの

- Result assessment schemaとRun-wide評価索引。
- Round別CSV viewとscreening summary。
- Interpreterの`screening` mode。
- Round Contractのoptional `report_mode`。
- Result assessmentを要求するRuntime actionとcommit gate。

既存成果物の変換や一括migrationは不要とする。0.1.6 Result Cardを0.1.7で参照したとき、評価索引に存在しなければ必要なものだけを遅延評価する。

## 11. 頑健性原則

- RuntimeだけがState、評価索引、正式IDを更新する。
- Interpreterはread-onlyの入力からschema準拠draftだけを返す。
- Screening contextの件数とbyte数を固定上限で検証する。
- Result Card hashとrubric versionにより、評価の再利用と再評価を区別する。
- 評価失敗、Operator失敗、Interpretation失敗を混同しない。
- 低得点を削除や失敗の意味に使用しない。
- 正式Interpretationは得点だけで結論を決めず、原Result、Comparator、反証を確認する。
- `screening` Roundで長文Reportを作らない一方、再開に必要なcompact summaryとAuditは必ず残す。
- Main Orchestratorへ大量のResult Card本文や評価明細を返さない。

## 12. 完成条件

0.1.7は、次を満たした時点で完成とする。

1. 一Roundで50件を超えるOperator探索を人間承認予算内で継続できる。
2. 一つのInterpreter contextへ大量Result Cardを渡さない。
3. 各eligible Result Cardが、score済みまたは理由付き`not_scorable`として追跡される。
4. 探索Roundを正式Interpretationなしで安全に終了・再開できる。
5. 正式Interpretationは評価索引から限定的かつ多様なResultを選び、原Resultを検証する。
6. 0.1.6 Runの既存成果物を再計算・変換せず参照できる。
7. Description、Clustering、Operator、MMP Databaseの科学出力が0.1.6から変化しない。

