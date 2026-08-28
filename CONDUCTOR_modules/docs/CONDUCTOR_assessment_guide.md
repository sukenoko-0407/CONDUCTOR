# CONDUCTOR 一次評価ガイド

## 1. 位置づけ

一次評価（Result Screening）は、Operator結果を長文のInsightへ直接変換する処理ではない。Runtimeが関連Resultを`Review Bundle`へまとめ、短命Interpreterが各Bundleを絶対評価し、Runtimeが候補クラスを決定する前処理である。

評価単位は単独のResult CardではなくReview Bundleである。主なBundleは次のとおりである。

| Bundle種別 | 内容 | 主な目的 |
|---|---|---|
| `global` | Global Result 1件 | データ全体での良好方向シグナルを評価する |
| `global_local` | Local Resultと同じ比較系列のGlobal Result | GlobalからLocalへ移った際の変化を評価する |
| `sibling_cluster` | 同一Clustering・同一比較系列の複数Cluster Result | Cluster間の差や局所特異性を評価する |

Operatorの科学計算値はResult Cardに保持される。一次評価は、その値、scope、sample数、比較関係、quality情報を読み取り、後段で注目すべき候補を絞る。

## 2. 一次評価の対象

通常の一次評価対象になるのは、次の条件を満たすAnalysis Resultである。

- Analysis Nodeが`succeeded`である。
- `eligible_for_downstream=true`である。
- RuntimeのResult索引に有効なResult Cardがある。
- 現在Roundに属するResult、または人間が明示したhistorical re-Screening対象である。
- 必須比較対象が揃い、Review Bundleが評価可能である。

次は意図した対象外または保留である。

| 状態 | 扱い |
|---|---|
| `pending`、`running`、`failed`、`cancelled` | 一次評価しない |
| `eligible_for_downstream=false` | 一次評価しない。計算結果自体は保持する |
| 必須Global comparatorが未作成 | `awaiting_comparator`として保留する。低評価ではない |
| Bundle内の情報だけでは妥当な採点ができない | Interpreterが`not_scorable`とする |
| 最低sample数未満 | 採点は可能だが、Runtimeが候補クラスを`background`へ制限する |
| read-only MMP詳細解釈（I002） | 通常DAGの一次評価とは分離し、人間の明示実行で扱う |

したがって、`succeeded`かつ下流利用可能な通常Analysisに有効なResult Cardがあり、比較待ちでもないのに一次評価から消えることは正常ではない。Audit対象の実装・索引不整合として扱う。

なお、Result全体が対象でも、OperatorやBundleの性質上適用できない評価軸は`not_applicable`となる。軸の非適用とAnalysis全体の対象外は別である。

## 3. 3つの絶対評価軸

一次評価は、他Bundleとの順位や得点分布を基準にせず、各Bundleを0～3で絶対評価する。単純合計点は科学的評価として使用しない。実際の0～3の判定基準は、各Operatorの`capability.json`にある`interpretation_profile.anchors`をRuntimeがBundleの`evaluation_anchors`へ展開し、Interpreterへ渡す。

| 軸 | 評価するもの | 高評価の意味 |
|---|---|---|
| `favorable_evidence` | `higher_is_better`を反映した良好方向への変化・関連 | 活性改善方向を示すEvidenceが強い |
| `context_contrast` | Global–LocalまたはCluster間で解釈が変わる度合い | 局所化によって見え方が大きく変わる「違和感」がある |
| `evidence_specificity` | Cluster、特徴量、Transform、Core、化合物Pair等の確認対象がどれだけ具体的か | Medicinal Chemistが元データを確認できる対象が明確である |

Global Bundleでは比較を要する`context_contrast`が非適用になる。Local Bundleでも比較可能な共通metricがなければ`context_contrast`は非適用になる。Interpreterは非適用軸を無理に採点しない。

`chemical_actionability`は廃止した。合成可能性、置換可能性、実務上の化学的妥当性はMedicinal Chemistが判断する。`independent_support`と`follow_up_leverage`も単一Bundleの採点軸にはせず、前者はFull Interpretationの横断比較、後者はFull Interpretationまたは人間の判断として扱う。

## 4. 信頼性の扱い

軸評価とは別に、信頼性を次の4項目で管理する。

| 項目 | 決定主体 | 内容 |
|---|---|---|
| `sample_support` | Runtime | Operator別の最低sample数に対する`strong`、`moderate`、`limited`、`insufficient` |
| `comparator_validity` | Runtime | Global comparator等が`matched`、`partial`、`none`のどれか |
| `effect_stability` | Interpreter | 観察された効果が`stable`、`mixed`、`unstable`、`unknown`のどれか |
| `independence` | Interpreter | 証拠が`independent`、`partially_independent`、`overlapping`、`unknown`のどれか |

Cluster間の化合物重複など、決定論的に算出できる事実はRuntimeがBundleへ記録する。Interpreterがscopeやsample数を推測して書き換えることはない。

## 5. Candidate class

`favorable_clue`、`contextual_clue`、`supporting_evidence`、`background`は採点項目ではない。Interpreterの3軸評価とRuntime factsから、Runtimeが固定決定表で付与する候補クラスである。

| Candidate class | 位置づけ | 固定判定の要点 |
|---|---|---|
| `favorable_clue` | 活性改善へ接続し得る知見候補 | `favorable_evidence>=2`かつ`evidence_specificity>=1`。Operator Profileが単独Insightを許すこと |
| `contextual_clue` | Global–LocalまたはCluster間の注目すべき違和感 | 有効な比較があり、`context_contrast>=2`、`evidence_specificity>=1`。`favorable_evidence`が適用可能なOperatorでは同軸が1以上、SALI等の非方向性Operatorでは有効な文脈差そのものを候補とする。単独Insightが許されること |
| `supporting_evidence` | 他候補の支持、制約、反証に使う結果 | supporting-only／specialized-only Operator、またはいずれかの軸に補助情報がある |
| `background` | 実行済みだが人間の注意を直接誘導しない結果 | 上記に該当しない、または最低sample数未満 |
| `not_scorable` | 妥当な採点ができなかった | Result不良とは限らず、bounded Bundleだけでは判断不能 |
| `awaiting_comparator` | 必須比較対象待ち | 未評価。低評価・失敗ではない |

Operator Profileの`standalone_insight`が`supporting_only`または`specialized_only`なら、高い軸評価があっても単独の`favorable_clue`にはならない。これにより、補助的な可視化や記述的結果が過剰にInsight化されるのを防ぐ。

## 6. `assessment_summary.html`の選択

`cs-conductor-assessment-report`はStateを変更しないread-only可視化である。各Bundleの最新revisionだけを読み、Bundleの`source_hash`とRubric Versionが一致するcurrent評価を対象にする。

有望候補Top Nは`favorable_clue`と`contextual_clue`だけから、Runtimeと共通の`candidate_priority_v3`で選ぶ。

1. Candidate class（`favorable_clue`を先、`contextual_clue`を次）
2. `sample_support`
3. `favorable_evidence`
4. `context_contrast`
5. `evidence_specificity`
6. Capability ID、Bundle ID

既定はTop 10、指定可能な上限は50である。過去の正式InsightがそのBundleを参照したかを`Fullレポート収載済／未収載`として併記し、未収載候補も別表で示す。ヒストグラムや分布表示は全current評価を要約するものであり、新しい採点やState更新ではない。

## 7. Full Interpretationとの違い

`assessment_summary.html`の候補表示とFull InterpretationのInsight抽出は、入口となる候補クラスは同じだが、同一処理ではない。

- 共通点: 原則として`favorable_clue`と`contextual_clue`だけを正式候補とし、同じ`candidate_priority_v3`を使用する。
- Assessment Summary: 人間向けダッシュボードとして、上記の固定表示順でTop Nを列挙する。
- Full Interpretation: Runtimeが共通priority keyでbounded shortlistを作る。明示的なOperator別quotaは設けていない。その後Interpreterが支持・反証・比較妥当性・重複性を確認し、複数Bundleの統合や候補の見送りを行う。選抜外Bundleから新しいInsightは作らない。
- 累積Full Interpretation: 過去の正式Insightで使用済みのBundleを除き、各Bundleの最新かつcurrentな一次評価から未報告候補だけを扱う。

したがって、Assessment SummaryのTop 10がそのままFullレポートのInsight 10件になるとは限らない。未収載は「見落とし」とは限らず、詳細読込上限、証拠の重複、反証、比較妥当性、既報済みなどが理由になり得る。

## 8. 関連する正本

- 行動原則: `CONDUCTOR_modules/docs/CONDUCTOR_interpretation_policy.md`
- Operator別評価Anchor: 各Operator Skillの`capability.json`内`interpretation_profile`
- 標準解析範囲とbatch上限: `CONDUCTOR_modules/catalog/analysis_profile.json`
- 一次評価正本: `run_root/runtime/result_assessment_index.jsonl`
- Review Bundle正本: `run_root/runtime/review_bundle_index.jsonl`
- Round別可読表: `run_root/rounds/<round_id>/result_assessments.csv`
- 一次評価要約: `run_root/rounds/<round_id>/screening_summary.json`
- 正式Insight索引: `run_root/runtime/insight_index.jsonl`
