# CONDUCTOR エラー回復・一次評価再設計 提案書

## 1. 目的

本改良では、次の二点を強化する。

1. CLIまたは科学計算が失敗した際に、Agentが原因と次の修正行動を短い情報から判断できるようにする。
2. 一次評価をFavorable方向の知見候補発見へ集中させ、Medicinal Chemistの専門判断とAgentの責務を分離する。

今回、一次評価の処理時間対策は実装範囲に含めない。batch size、直列処理、Interpreter起動方式、Review Bundle構築数は現状を維持する。

## 2. エラー回復機能

### 2.1 現状の問題

Skill側ではargparseや入力検証により具体的なエラーが出る一方、RuntimeのFailure Packetでは`Skill exited with code 2`等の一般的な記述へ縮退することがある。Agentは不足引数を特定するために長いAttempt logを追加で読む必要がある。

現在の`recoverable`だけでは、同一コマンドの即時再試行と、入力・Execution Request・Package修正後の再試行を十分に区別できない。

### 2.2 改良方針

新しいNode状態、Agent、常時読込Playbookは追加しない。既存Failure Packetと`required_action`へ、短い構造化診断を追加する。

```json
{
  "diagnostic_code": "MISSING_REQUIRED_ARGUMENT",
  "diagnostic_message": "--smiles-column is required",
  "remediation": "Execution Requestのcolumns.smilesを設定し、同じNodeを再試行する",
  "retry_mode": "after_request_fix",
  "log_pointer": "runtime/scratch/.../attempt.log"
}
```

`retry_mode`は次の固定値とする。

| 値 | 意味 |
|---|---|
| `same_command` | timeout等。同一コマンドの再試行が可能 |
| `after_environment_fix` | Pixi、依存関係、cache等の修正後に再試行 |
| `after_request_fix` | 引数またはExecution Request修正後に再試行 |
| `after_input_fix` | CSV列、パス、入力内容の修正後に再試行 |
| `after_package_fix` | adapter、Skill、Schema等の実装修正後に再試行 |
| `human_decision` | 自動判断せず人間確認が必要 |

### 2.3 診断対象

- 必須引数不足
- unknown／unrecognized option
- 必須input role不足
- CSV列不足または列名不一致
- 入力ファイル不存在
- 値の型・範囲違反
- Execution Request、Manifest、Schema不一致
- Pixi環境構築失敗
- timeout、process消失、resource failure

Attempt log末尾から`ERROR:`またはargparseの`error:`を抽出し、具体的な原因をFailure Packetへ保存する。完全なlogは従来どおり保持する。

`FAILED_NODE_REPAIR_REQUIRED`は分類名だけでなく、`diagnostic_message`、`remediation`、`retry_mode`を返す。修正後は置換Nodeを作らず、同じNode IDの新Attemptとして再試行する。

### 2.4 頑健性上の境界

- timeout等を除き、同一の失敗コマンドを無条件に再試行しない。
- Agentに任意のCLI組み換えやState直接編集を許可しない。
- エラー抽出に失敗した場合は`UNKNOWN_FAILURE`とlog pointerを返し、誤った修正案を断定しない。
- 診断情報は状態を増やすものではなく、既存Attemptの失敗記録に付随する情報とする。

## 3. 一次評価の再設計

### 3.1 責務

Interpreterの責務は、Medicinal Chemistに検討すべき視点と根拠を提示するところまでとする。合成可能性、実務上の置換可能性、化学的妥当性の最終判断はMedicinal Chemistが担う。

現行の`chemical_actionability`は、具体性と化学的実行可能性を混同しやすく、Candidate classの成立条件としてAgentへ過剰な判断を要求しているため廃止する。

### 3.2 新しい絶対評価軸

一次評価は次の3軸を0～3で評価する。単純合計点は作らない。

| 軸 | 内容 | 評価しないもの |
|---|---|---|
| `favorable_evidence` | `higher_is_better`を反映したFavorable方向への直接的または明示的Evidence | 合成可能性、化学的好ましさ |
| `context_contrast` | Global–Localまたはsibling Cluster間で解釈が変化する強さ | 差が生じたこと自体の価値判断 |
| `evidence_specificity` | Cluster、特徴量、Transform、Core、化合物Pair等、Chemistが確認すべき対象の具体性 | 実際に設計・合成すべきかの判断 |

次の項目は一次評価の採点軸から外す。

- `chemical_actionability`: Medicinal Chemistへ委ねる。
- `follow_up_leverage`: Full Interpretationまたは人間が判断する。
- `independent_support`: 単一Bundleではなく、Full Interpretationの横断比較で確認する。

### 3.3 信頼性

信頼性は評価軸と混ぜず、引き続き別項目で保持する。

- `sample_support`
- `comparator_validity`
- `effect_stability`
- `independence`
- `quality_flags`

sample数、scope、Global comparatorの対応関係はRuntimeが決定し、Interpreterに推測させない。

### 3.4 Candidate class

Runtimeは合計点ではなく固定条件で分類する。

| Candidate class | 判定概要 | Full Insight候補 |
|---|---|---|
| `favorable_clue` | `favorable_evidence>=2`かつ`evidence_specificity>=1` | 対象 |
| `contextual_clue` | `context_contrast>=2`かつ`evidence_specificity>=1`。Favorable軸が適用可能なら同軸1以上、非方向性Operatorでは有効な文脈差を根拠とする | 対象 |
| `supporting_evidence` | Favorable候補の支持・制約・反証に利用できる | 単独では対象外 |
| `background` | Unfavorable-only、無信号、非特異的、または最低sample未満 | 対象外 |
| `not_scorable` | bounded Bundleから妥当な評価ができない | 対象外 |
| `awaiting_comparator` | 必須Global comparator待ち | 未評価 |

Not Favorable方向のみの結果や「機能しないDescription／Operator」は単独Insightとして人間へ提示しない。ただし、Favorable候補の反証や適用限界を説明する場合にはSupporting Evidenceとして参照できる。

### 3.5 Assessment SummaryとFull Interpretationの一貫性

Assessment SummaryとFull Interpretationは共通の候補母集団と`candidate_priority_key`を使用する。

推奨優先順は次のとおりとする。

1. Candidate class（`favorable_clue`、`contextual_clue`）
2. sample support
3. favorable evidence
4. context contrast
5. evidence specificity
6. Capability ID、Bundle IDによる決定論的tie-break

Full Interpreterは複数候補の統合や反証による見送りを行えるが、選抜外Bundleから新しいInsightを作らない。見送る場合はReview Manifestへ次のいずれかを記録する。

- `merged_into_insight`
- `rejected_by_counterevidence`
- `redundant_evidence`
- `deferred_by_detail_limit`
- `not_reportable`

これにより、Assessment SummaryとFull Reportが完全同一でなくても、候補選定の根拠と差分を追跡できる。

### 3.6 Medicinal Chemistへの出力

Full ReportはAgentによるactionability判定ではなく、次を提示する。

- どの解析・scope・Clusterで観察されたか
- Favorable側で何が変化したか
- Globalまたはsibling Clusterから何が変化したか
- Chemistが確認すべき構造、Transform、Core、特徴量または化合物Pair
- sample数、信頼性、反証例、限界
- 個別Operator report、CSV、Conciergeへの参照

## 4. 今回変更しない事項

- screening batch sizeは現行値を維持する。
- 通常一次評価は直列実行を維持する。
- Interpreterの並列数を変更しない。
- Review BundleのGlobal、Global–Local、sibling Cluster構成を変更しない。
- Screening Contextの圧縮・省略を行わない。
- Operator、Description、Clusteringの科学計算機能を変更しない。
- MMP DatabaseおよびCSV出力仕様を変更しない。

処理時間は、一次評価再設計後の実測値を確認してから別改良として扱う。

## 5. 互換性と再評価

エラー診断強化はFailure Packetへの付加情報として実装し、既存Node状態と実行結果との互換性を維持できる。

一次評価はRubricとCandidate classを変更するため、旧Assessmentと混在させない。Operator計算やResult Cardの再生成は不要だが、新Rubricを使用する場合は既存Review Bundleをre-Screeningする。

Rubric Version、Assessment Schema、Interpreter契約、Assessment Report、Full Interpretation gateを同時に更新し、producer／consumerのVersion不一致を契約テストで防止する。

## 6. 受入試験

### エラー回復

- 必須引数不足時に不足option名と修正方法がFailure Packetへ入る。
- 必須input role不足、CSV列不足、ファイル不存在を異なるcodeへ分類する。
- timeoutだけが`same_command`再試行になる。
- AgentがAttempt log全文を読まずに次の行動を判別できる。
- 修正後に同じNode IDの新Attemptとして成功できる。

### 一次評価

- `chemical_actionability`をAgentが採点しない。
- Unfavorable-only Resultが単独Insight候補にならない。
- Global–Local比較なしに`contextual_clue`を作れない。
- Assessment SummaryとFull Review Manifestが同じpriority keyを使用する。
- Full Insightが選抜外Bundleを参照できない。
- Supporting／Counter EvidenceはFull Insightの根拠・限界として利用できる。

## 7. MMPをSpotfireで扱う際の推奨構成

### 7.1 結論

`mmp_pair_detail.csv`一枚だけで全集計を再現するより、集計粒度の異なるCSVを別Tableとして読み込み、Spotfire上でRelationを設定する方法を推奨する。

`mmp_pair_detail.csv`の一行は、単純な化合物Pairではなく、原則として「化合物Pair × directed Transform × Exact Core」である。同一Pair／Transformに複数Exact Coreがある場合、行平均はそのPairを複数回数え、効果量やsupportを偏らせる可能性がある。

### 7.2 最小推奨構成

| Spotfire Table | 粒度 | 主な用途 | Relation Key |
|---|---|---|---|
| `transform_summary.csv` | Transform | 全体傾向、support、中央値、方向一貫性 | `transform_id` |
| `transform_core_summary.csv` | Transform × Exact Core | Core依存性、文脈差 | `transform_id` + `core_id` |
| `mmp_pair_detail.csv` | Pair × Transform × Exact Core | 個別化合物、SMILES、活性差のdrill-down | `transform_id`、`core_id`、`mmp_id` |

必要に応じて次を追加する。

- `core_summary.csv`: Exact Core単位の全体傾向
- `context_summary.csv`: Transform × Environment radius／SMARTS
- `pair_summary.csv`: 化合物Pair単位の集約
- `compound_coverage.csv`: MMP未形成化合物やEndpoint欠損の確認
- `mmp_reference_cards.csv`: 自動抽出された限定的候補。全Evidenceではない

### 7.3 Spotfire内での利用方針

- Tableを物理的に一枚へjoinせず、Relationで選択連動させる。粒度の違うTableをjoinすると集計値が複製される可能性がある。
- Transform概要から候補を選び、Transform × Core、最後に個別Pairへdrill-downする。
- Endpoint方向を統一した表示には`favorable_delta`を使う。正値がFavorable方向である。
- Raw detailから再集計する場合は、Transformごとに同一化合物Pairを一度へcollapseしてから評価する。
- `pair_count`と`mmp_instance_count`を混同しない。前者は重複Exact Coreをcollapseした化合物Pair数、後者は保存MMP行数である。
- Environment radius 0～2は入れ子のcontextであり、独立supportとして加算しない。

### 7.4 SQLite

`mmp_database.sqlite`はSpotfire表示のための必須ファイルではない。`compounds`、`transforms`、`cores`、`mmp_pairs`、`mmp_contexts`を正規化して保持し、Local screening、特定Cluster詳細解析、read-only MMP Interpretationを再Fragmentationなしで実行するためのEvidence Storeである。

SpotfireではCSV群を使用する方が簡便である。SQLiteはCONDUCTORによる再利用・再集計の正本として保持する。
