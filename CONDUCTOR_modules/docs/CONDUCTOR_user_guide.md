# CONDUCTOR 0.1.10 利用ガイド

## 新規Run

日常プロンプト集の「新規Run」を使い、CSV、Endpoint、`higher_is_better`、`project`、出力先、並列数、CPU数、Wall Timeを指定します。`project`はProgram名であり、同じ化合物群でEndpointだけが異なるRunでは同じ値を使います。Round全体の承認後、Main Agentは基本計算、定型解析、Interpretation、監査まで進めます。Descriptionごとの高コスト承認はありません。

## Description Database

Descriptionは`data/description_database/<project>/`にSkill別SQLiteとして保存されます。同じProgram、compound ID、canonical構造、`calculation_version`、parameter・環境・modelを含む計算signatureが一致すれば再利用し、miss化合物だけを計算します。別Programとは共有しません。同一Programで同じcompound IDに異なるcanonical構造が入力されると処理を停止します。

確認と無効化はRuntime管理commandを使います。

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state description-cache-inspect --project <PROJECT> --capability-id D001 --compound-id <ID>
python .claude/skills/cs-conductor-runtime/scripts/launch.py state description-cache-invalidate --project <PROJECT> --capability-id D001 --compound-id <ID> --reason <理由> --operator <操作者>
```

## 人間確認

まずA009の`standard_summary.html`冒頭にある主要件数card、Endpointヒストグラム、横長のGlobal／Series／fallback Cluster Boxplotを読みます。個別analysis unit HTMLには所属構造例、Description ID付きA003散布図、A005 Local／Global OOF予測比較図、A007構造、Type-I Top 1化合物とMMPレポートへのlinkがあります。気になるSeries、Cluster、化合物、図、仮説はOn-demandへ依頼します。

定型A008 Type-Iは各Series／fallback ClusterのTop 1のみを対象にします。上位K化合物を追加評価する場合は、対象となるrun内compound IDを選び、On-demand Type-IIの`--target-compound-id`を複数回指定します。

A008 Type-I/IIのHTMLはTargetを常にTo、NeighborをFromとして表示し、Favorable deltaもNeighbor→Target方向へ統一します。同一Target–Neighborでは包含関係にある小さいCoreを除きますが、包含関係にないCoreは両方を残します。原本CSV／Databaseは変更しません。Exact CoreごとのcardでFavorable delta上位5件を展開し、各行をNeighbor全体、Target全体、置換前fragment、置換後fragmentの順に確認できます。

## parameter変更

C012はまず`min_ff_evaluate=10`を保ち、Leiden resolutionを`1.0, 1.25, 1.5, 2.0, 2.5, 3.0`の順に自動評価し、最初に最終unit数が24以下となる条件を採用します。該当がなければ、`min_ff_evaluate=10, 15, 20, 25, 30`との全30条件を評価し、Main AgentがSession内に`unit数 / Cluster coverage / Compound coverage / fallback数`のMatrixを表示します。人間は条件を選びます。Matrixは途中判断でありHTMLには載りません。

24件以下は自動進行、25～100件は人間の明示承認で進行できます。50件は目安、100件は絶対上限です。独自条件で再計算する場合は定型解析の計画前に`revise-series`を使い、新しいC012だけを作ります。再計算後も24件を超えれば再度確認します。

## 失敗・停止

Failureはdiagnosticに基づき同一Nodeを修正・retryします。期限切れLeaseと`running` Nodeが残る場合、Runtimeは同一hostで生存中のprocessを検出して二重実行を拒否します。異なるhostまたは旧形式の実行記録は自動的に失敗扱いにせず、旧processの停止を人間が確認した場合だけ`resume-round --confirm-interrupted-running`で回収します。回収されたNodeは`INTERRUPTED_ATTEMPT`となり、同じNode IDをretryできます。Wall Timeでpauseした場合は同じRoundをcontinueします。新Roundを自動開始させません。

## On-demand

Round状態に関係なく使えます。結果は`on_demand/REQ######/`だけに保存され、通常DAGを変えません。
