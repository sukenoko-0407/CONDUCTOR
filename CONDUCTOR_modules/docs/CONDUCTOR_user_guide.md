# CONDUCTOR user guide

## 新規Run

Main Agentで`/cs-conductor-orchestrator`を明示し、入力CSV、endpoint、`higher_is_better`、project、parallel limit、Available CPU Cores、Wall Timeを示してRound 1を開始します。CPU未指定時は8です。Mainは契約案を人間依頼と照合した場合だけauthorizeします。

`parallel_limit`は同時Node数、Available CPU Coresは科学計算へ割り当てる総数です。MCS、Mordred 3D、xTB、ChemBERTa、Global MMPは単独packetで実行し、Skill内部並列と他Nodeを競合させません。

高コスト基本計算は最初に一括承認できます。MCSは基本計算で個別承認不要です。Description／Clustering基本計算後、Operator探索数を`max_additional_nodes`で指定します（既定50、安全上限500）。Runtimeは最大25 Nodeずつ計画し、成功Resultを既定4 Review Bundleずつ絶対評価してから次へ進みます。探索は初期／追加に分けず、成功済み計算を除外し、GlobalをLocalより優先して履歴バランスを取ります。Wall Timeだけでは件数を増やしません。

探索を広く続けるRoundは`report_mode=screening`、人間向けの正式なInsight Reportが必要なRoundは`report_mode=full`を選びます。screeningではReview Bundle単位の`result_assessments.csv`とcompact summary、fullではCandidate class、信頼性、多様性から選抜した最大50 Result参照に対応するBundleの`interpretation.html`まで作成します。

endpointの変換はRun開始前に人間が行います。`endpoint_transform`は実施済み変換の記録で、Runtimeが値を変換する指定ではありません。

RuntimeはRun初期化時にSMILES列を確定し、共通Execution Requestで必要Skillへ引き渡します。候補列が複数なら依頼時にSMILES列名を明示してください。

## 実行中

Main Orchestratorは`conductor_control.json`の一つの`required_action`へ従います。科学計算ではRuntimeが共通`execution_request.json`と署名済packetを作り、MainがRuntime `execute-packet`を一回呼びます。RuntimeはPacketを原子的にclaimし、独立したOS Workerへ科学processを所有させます。MainはSkill個別CLIを組み直しません。

`WAIT_RUNNING`はWorkerまたは科学processが生存している正常な待機です。別Workerやreconcileを開始しません。`RECONCILE_RUNNING`の場合だけ、Worker消失後の成果物または失敗状態を一回回収します。同じPacketの`execute-packet`再呼出しは既存Workerへの再接続であり、二重計算にはなりません。

Node失敗時は同じNode IDへ最大3 Attemptまで再試行できます。即席の引数修正や置換Nodeは作りません。実装契約の欠陥であれば、Roundを安全に停止し、packageを修正して同じNodeを再試行します。

## MMP解析

A014の定型フローはGlobal MMP Databaseを一度だけ構築します。通常InterpretationはcompactなGlobal概要だけを読みます。Round終了後、そのRoundで新しいGlobal A014が成功している場合に人間が`cs-analysis-interpret-mmp`を明示起動すると、同じDBとcanonical Cluster membershipからGlobal、Local、Outsideをread-only再集計し、Clustering別の分散縮小とCluster固有Transformを確認できます。過去RoundのDBは人間がA014 Node IDを明示した場合だけ再利用します。標準範囲は1～2 cuts、radius 0～2、Exact Core 8 heavy atoms以上、両分子の0.50以上、variable part 10 heavy atoms以下です。

全Pairは`mmp_pair_detail.csv`でSpotfireへ渡せます。Exact CoreとEnvironmentはMMP内部のKeyで、CONDUCTORのGlobal／Cluster scopeとは別概念です。

## 中断と再開

別sessionでは`/cs-conductor-orchestrator`、Run Root、「同じRoundを再開」を指定します。MainはControlだけを最初に読み、live leaseなら二重Orchestratorを拒否し、期限切れなら同じRoundをresumeします。claim済みRuntime WorkerはMain sessionから独立して継続します。人間の指示なしに次Roundを作りません。長いInterpretationや全DAGをプロンプトへ貼る必要はありません。

## Round終了後

`AWAITING_HUMAN_REVIEW`で、screening Roundは`screening_summary.json`／`result_assessments.csv`、full Roundは`interpretation.html`を読み、次のいずれかを明示します。

- 同じRoundで残作業を継続する。
- 同じRoundのInterpretationを改訂する。
- Roundを受理して閉じる。
- 新しいRound番号と、重視するInsight、反証、解析方向、予算を指定して開始する。

意見は人間承認Round contractを介してStateへ反映します。Orchestratorは新Roundを自発的に始めません。

### CLOSED Roundの一次評価をやり直す

一次評価に欠落や一律Template適用が後から見つかった場合、元のCLOSED Roundを開き直しません。特別対応プロンプト集のhistorical re-Screeningを使い、一つ以上のSource Roundを明示した新しいscreening Roundを人間承認します。このRoundは保存済みReview Bundleだけを既定4件の小batchへ分けます。最大4 batchの短命Interpreter評価は並列化できますが、Runtime commitは直列で、Operator Nodeを一切作りません。

旧Assessment revisionは監査履歴として残りますが、Interpreter、Round CSV、Summary、累積Interpretationが使用するのはBundleごとの最新revisionだけです。新Assessmentには再評価を実行したRoundと元Source Roundを別々に記録します。

## 読み取り専用支援

- `cs-conductor-state-report`: 指定RunのDAGをHTML／SVG化する。
- `cs-conductor-assessment-report`: 既存の一次評価正本を変更せず、評価軸、Candidate class、信頼性、Round／Operator内訳、Full Interpretation収載状況、有望候補を`run_root/assessment_reports/<timestamp>/`のHTML／CSVに集約する。5軸の合計点は作らない。
- 累積Interpretation: 複数のScreening Roundを受理してCLOSEDにした後、日常プロンプト集の「複数Screening Roundから累積Interpretationを作成」を使用する。新しい報告専用Full RoundがOperator予算0で作られ、各Bundleの最新一次評価から既報Insight使用済みBundleを除いた候補だけを正式Reportへ統合する。
- `cs-conductor-result-concierge`: 凍結Runを変更せず、既存結果の説明、追加集計、比較、Figure化を`run_root/concierge/REQ######/`内で行う。
- `cs-conductor-run-audit`: Quick／Full整合性監査を行う。
