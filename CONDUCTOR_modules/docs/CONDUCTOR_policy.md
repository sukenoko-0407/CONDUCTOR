# CONDUCTOR Orchestration Policy

## 基本原則

- 一つのRunは一つの入力CSV、一つのendpoint、一つの`higher_is_better`を扱う。
- 複数Roundを標準とし、各RoundをInterpretationとFull Auditまで完遂する。
- 人間の明確な省略指示がなければ、全Descriptionと標準Clusteringからなる基本計算を先に揃える。
- 高コストDescriptionは一つのbundleとして一回承認を求める。MCSは基本計算として別承認を求めない。
- 初期探索は広さを優先する。Globalでは適用可能な全Operator、Localでは各Clusteringの代表Clusterへ適用可能なOperatorを偏りなく使う。
- 追加探索は未実施signatureからseed付きで選び、Description family、Clustering family、Operator、scopeの偏りを抑える。
- 深掘りはInsight、人間の指示、矛盾、反証候補を起点とし、同一Clusterの別Operator、兄弟Cluster、Global対Local、別Descriptionの少なくとも一つを比較する。

## 科学的判断と決定論的制御

Runtimeが機械的に決めるものはID、依存関係、重複signature、attempt、metric契約、並列上限、approval、終端gateです。Orchestratorが考えるものは、どの比較が科学的に意味を持つか、何を優先するか、どの反証を試すかです。候補の意味まで固定ルールで決めません。

## Clusterの扱い

- 5化合物未満はClusterとして登録しない。
- 大きいClusterを優先候補にするが、全体の30%超は局所性が弱く、50%超はglobal-likeとして扱う。
- 小さくてもMCS等で構造凝集性が高いClusterは解釈候補に残せる。
- A005のLocal model surveyは30化合物以上かつendpoint変動のあるClusterだけを対象にする。

## Interpretationと継続

- 強い結果だけでなく、矛盾、negative result、適用不能も保存する。
- 注目するInsightには必ず反証・代替説明を探索する。
- InsightのattentionとNext Actionのstatusは後から変更可能とする。
- 人間は次Roundのrequestへ見解、重視点、閉じたいNext Actionを添付できる。単に「次のRoundを継続」と指示しても、Stateから未実施領域を選べる。

## 停止条件

Wall Timeは上限であり、必ず使い切る時間ではありません。Roundは予算消尽、実行候補なし、人間checkpoint、要求範囲完了、異常中断のいずれかを明記して停止し、正常なclosureには最新InterpretationとFull Auditを要求します。
