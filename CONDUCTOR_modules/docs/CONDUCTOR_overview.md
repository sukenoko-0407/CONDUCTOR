# CONDUCTOR overview

CONDUCTOR 0.1.2は、SARデータを一つの説明へ早急に収束させず、複数の分子表現、Cluster、Operatorを横断してGlobalとLocalの変化を探すClaude Code向け解析基盤です。

## 解析の流れ

1. Descriptionで化合物を異なる原理のvectorへ表す。
2. 構造またはDescription vectorからClusterを作る。
3. OperatorをGlobalとCluster-localへ適用する。
4. Interpretationが異なる結果を比較し、反証を含むInsightを人間へ報告する。
5. 人間がレポートを読み、次Roundを開始するか、同じRoundの追加作業を明示する。

基本計算と初期探索は広さを優先します。追加探索は未探索領域の偏りを抑え、深掘りはGlobal対Local、同一Clusterの別Description、Sibling Cluster、別Operatorを比較します。

## 制御上の特徴

- Roundの開始、同一Round継続、レポート改訂、受理は人間だけが決める。
- Main AgentはDispatcherを入口とし、同時に一つのOrchestratorだけを起動する。
- Orchestratorは小さな`conductor_control.json`とbounded Working Setだけから制御を再開できる。
- RuntimeがNode連番、5状態、依存関係、lease、Action token、attempt、commit、監査を決定論的に扱う。
- DAG snapshotはRuntimeがControlと同一transactionで更新する詳細な追跡表現であり、LLMが直接編集する正本ではない。Event Ledgerは変更履歴を監査する。
- 中断後も同じRound・同じNodeを再開し、勝手に次Roundを作らない。
- 過去Roundの成功Nodeは再計算せず、次Roundの`reused_node_ids`として明示参照する。
- RoundはInterpretation JSON／Markdown／HTMLとFull Auditが揃うまで人間レビュー状態へ進めない。

## 主成果物

人間にとっての主成果物は`interpretation.html`です。各Insightは、対象がGlobalか特定Clusterか、使用したDescription／Clustering／Operator、sample数、主要数値、支持・比較・反証result、限界を示します。scopeとsample factはLLMの文章ではなくRuntimeがResult Cardから確定するため、Cluster解析をGlobalと誤記したdraftはcommitされません。

すべての計算結果は保持しますが、Orchestratorへ常時見せるのは短いResult Cardと選択されたWorking Setだけです。ConciergeはRunを変更せず、既存結果の説明や再可視化を`run_root/concierge/`内で支援します。
