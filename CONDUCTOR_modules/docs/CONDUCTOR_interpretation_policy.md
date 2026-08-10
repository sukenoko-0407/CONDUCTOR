# CONDUCTOR Interpretation Policy

## 目的

Interpretationは作業記録ではなく、Operatorが生成した固定結果を多角的に比較し、人間が次の判断に使える解釈を提示する終端処理である。Interpreterは計算NodeやStateを変更せず、Runtimeが用意したbounded contextだけを読み、draftを返す。

## 基本姿勢

- GlobalとCluster-localの変化を最優先で比較する。
- 同一Clustering内のCluster間、同一Clusterの異Description間、同一表現の異Operator間を横断する。
- 類似Description同士の一致を過大評価せず、原理の異なるDescriptionで再現した傾向を重視する。
- 一致した説明へ収束させることを目的にしない。矛盾、例外、negative resultも保持する。
- 注目候補を見つけたら、必ず反証または不一致を探索する。見つからなかった場合も、その探索範囲を限界として記載する。
- 多重探索による偶然の候補を許容するが、確認済み事実と説明仮説を文章中で区別する。

## Clusterの扱い

- 5化合物未満の集合はClusterとして登録されない。
- 統計的比較では大きいClusterを優先する。ただし全体の50%超はGlobalに近いことを明記する。
- 小さくても構造凝集性が高いClusterは、人間の構造解釈へ接続しやすいため候補に残せる。
- 重複Clusterは独立した再現ではない。membershipの重複と由来を確認する。

## 出力単位

Interpretationが提案するentityは二種類だけである。

1. `Insight`: 観察、解釈、支持result、反証・不一致result、scope、限界を一体で記録する。注目度は`priority`、`watch`、`background`で可変とする。
2. `Next Action`: 追加で確認する価値のある解析候補。状態は`open`または`closed`だけとし、人間が閉じられる。

Insightを無理に作る必要はない。明確な変化、矛盾、例外がなければゼロ件を許容し、その事実をexecutive summaryへ書く。Next Actionもゼロ件を許容する。

## 比較手順

1. context内のOperator summaryから、scope、sample count、Description、Clustering、metric、主要統計、制約を確認する。
2. RuntimeがOperatorとscopeを分散させた最大20件の`comparison_batches`を、許容された反復回数内で順に探索する。
3. 注目候補ごとに原数値artifactまたは個別Operator HTMLを確認する。summaryだけから保持Insightを確定しない。
4. 支持resultと反証・不一致resultを明記する。同一計算signatureの反復を新しい反証として数えない。
5. 人間向けに「どの解析の、どのscopeで、何がどう変わったか」を日本語で具体的に記す。
6. 次の解析候補は必要最小限とし、同一signatureの再実行を要求しない。

## 境界

- InterpreterはState、Cluster索引、Operator result索引を更新しない。
- IDを自分で発行しない。Runtimeがcommit時に`INS####`と`ACT####`を割り当てる。
- 新規Description、Clustering、Operatorを実行しない。
- 因果やSAR機序を断定しない。
- 解析結果を削除・上書きしない。
- Insightがゼロ件でも固定レポートを作る。Interpretationとその後のFull Auditを省略してRoundを閉じない。
