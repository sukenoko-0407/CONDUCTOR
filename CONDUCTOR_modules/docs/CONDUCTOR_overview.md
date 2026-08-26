# CONDUCTOR overview

CONDUCTOR 0.2.0は、SARデータを単一の説明へ早急に収束させず、複数の分子表現、Cluster、Operatorを横断してGlobalとLocalの変化を探すClaude Code向け解析基盤です。同じRunを人間主導で複数Round重ね、解析済み領域と比較単位であるReview Bundleを再利用しながら探索の完全性と解釈の質を高めます。

## 解析の流れ

1. Descriptionで化合物を異なる原理のvectorへ表す。
2. 構造またはDescription vectorからClusterを作る。
3. OperatorをGlobalとCluster-localへ適用する。
4. RuntimeがGlobal、Global–Local、sibling ClusterのReview Bundleを作り、少数Bundleずつ絶対複数軸で評価する。
5. 人間がScreening summaryまたは`interpretation.html`を読み、次Roundの開始、同じRoundの継続、レポート改訂、受理を選ぶ。

人間の省略指示がなければ、基本計算では全Description、直接構造Clustering、代表DescriptionのVector Clusteringを揃えます。Operator探索は`exploration`一種類です。成功済みsignatureを除外し、Capability、Description、Clustering、scopeの履歴偏りを抑えつつ、GlobalをLocalより優先してseed付き選択します。

## 制御上の特徴

- 人間が`/cs-conductor-orchestrator`を明示した間だけMain AgentがOrchestratorになる。
- 小さい`conductor_control.json`が現在のRound、必要Action、件数、closure、詳細file pointerを示す運用正本である。
- RuntimeだけがNode ID、5状態、DAG、lease、Attempt、commit、監査を更新する。
- 科学計算は決定論的なRuntime Worker、既存結果の解釈は専用Interpreterへ分離する。
- 全科学Skillを共通`execution_request.json`で起動し、Runtime WorkerはSkill別の長いCLIを組み立てない。
- 署名済packetはRun、Round、Control revision、lease、Request hashへ固定され、最初のclaimだけが科学processを起動する。再投入は既存Workerへ接続する。
- Operator予算は人間が指定し、Runtimeが最大25 Nodeずつ計画する。成功Resultは既定4 Review Bundleずつ評価するため、一括読込量を増やさず広い探索ができる。
- `screening` Roundは評価索引とcompact summary、`full` Roundは`design_lead`と`contextual_anomaly`から選抜した最大50 Resultの正式Interpretationで終了する。
- 過去Roundの成功Nodeは再計算せず、現在Roundから再利用参照する。
- `screening`ではScreening summary、`full`ではInterpretation JSON／Markdown／HTMLを要求し、いずれもFull Auditが揃うまで人間レビュー状態へ進めない。
- CLOSED Roundの一次評価は元Roundを変更せず、Operator計算を伴わない人間承認の再Screening専用Roundで更新できる。旧revisionは監査用に保持し、Agentは最新revisionだけを見る。
- Main sessionやTool callが中断してもRuntime Workerは継続し、同じRound、Packet、Nodeを再開する。人間の明示なしに次Roundを作らない。

DAGは計算の向きと依存関係を保持する詳細表現です。循環を許さないため、どの入力と上流結果からNodeが生じたか、何が実行可能か、どの結果が再利用可能かを追跡できます。ただしLLMはDAGを直接編集せず、通常の再開時に全DAGを読む必要もありません。

## 共通Execution Request

Runtimeは各Nodeについてidentity、入力Artifact、列、endpoint、scope、parameter、CPU資源、出力先を一つのJSONへ確定します。Skill側の薄いadapterがこれを既存科学kernelのCLIへ変換します。科学kernelと一般利用CLIは維持しながら、CONDUCTOR内部の引数不一致、Python path差、scratch衝突を一か所で防ぎます。

## MMP Operator

A014の定型フローは入力全体からGlobal MMP Databaseを一度構築するだけです。通常InterpretationへはcompactなGlobal概要を渡し、Transform／Exact Core／Clusterの詳細は展開しません。Round終了後、人間がread-only `cs-analysis-interpret-mmp`を起動すると、既存Clusteringを使ったGlobal、Local、Outside、分散縮小、Cluster固有效果をDAG外で比較できます。Outsideはpair両化合物が対象Cluster外の比較集合で、境界pairを含みません。

科学正本は正規化SQLite、全詳細CSV、集約CSVです。人間がSpotfire等で再利用できる全Pair情報を保持しつつ、反復文字列と派生SummaryをDBへ重複保存せず、大容量native work DBも完成後に残しません。

## 主成果物

正式解釈を行うRoundの人間向け主成果物は`interpretation.html`です。機能しない解析は索引へ保持しても単独Insightにせず、各Insightは活性改善候補またはGlobal–Local／sibling間の違和感、対象scope、Cluster、Description／Clustering／Operator、支持結果、比較結果、反証、限界を示します。scopeとsample factsはRuntimeがcanonical Result Cardから確定し、Cluster結果をGlobalと誤記したdraftはcommitしません。探索中心のRoundでは`screening_summary.json`と`result_assessments.csv`が短い引継ぎ成果物になります。

全計算結果は保持しますが、OrchestratorとInterpreterへ常時見せるのはbounded Working Setと選択Result Cardだけです。ConciergeはRunの科学結果とStateを変更せず、既存結果の説明、追加集計、可視化を`run_root/concierge/`内で支援します。
