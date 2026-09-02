# CONDUCTOR 0.1.9 利用ガイド

## 新規Run

日常プロンプト集の「新規Run」を使い、CSV、Endpoint、`higher_is_better`、出力先、並列数、CPU数、Wall Timeを指定します。高コストDescriptionの一括承認後、Main Agentは基本計算、定型解析、Interpretation、監査まで進めます。

## 人間確認

まずA009の`standard_summary.html`冒頭にある主要件数表と、Mean／Median／Favorable・Unfavorable 20% cutoffを図内表示したEndpointヒストグラムを読み、必要ならSeries別HTML、A008 MMP HTMLを確認します。気になるSeries、Cluster、化合物、図、仮説はOn-demandへ依頼します。

定型A008 Type-Iは各Series／fallback ClusterのTop 1のみを対象にします。上位K化合物を追加評価する場合は、対象となるrun内compound IDを選び、On-demand Type-IIの`--target-compound-id`を複数回指定します。

A008 Type-I/IIのHTMLはTargetを常にTo、NeighborをFromとして表示し、Favorable deltaもNeighbor→Target方向へ統一します。同一Target–Neighborの複数Coreは最大Coreによる最小変換1件だけをHTML表示しますが、原本CSV／Databaseには全行を保持します。最終sectionではNeighbor全体、置換前fragment、置換後fragmentの2D画像を横一列で確認できます。

## parameter変更

`min_ff_evaluate`またはLeiden resolutionを変える場合、定型解析の計画前であれば、同じACTIVE Roundで`revise-series`を明示実行します。新しいA001、A002、C012 Nodeを作りますが、成功済みDescriptionとC001-C010は再計算しません。定型解析を計画した後は科学的scopeの混在を避けるため変更できません。採用Seriesとfallback Clusterを合わせた実解析単位数が24を超えるとRuntimeが、件数、fallback内訳、現在の両parameterを示して停止します。人間は結果を見て、現条件を承認するか、`min_ff_evaluate`とLeiden resolutionを適切に指定して再計算します。Runtimeは値を勝手に変更しません。

## 失敗・停止

Failureはdiagnosticに基づき同一Nodeを修正・retryします。期限切れLeaseと`running` Nodeが残る場合、Runtimeは同一hostで生存中のprocessを検出して二重実行を拒否します。異なるhostまたは旧形式の実行記録は自動的に失敗扱いにせず、旧processの停止を人間が確認した場合だけ`resume-round --confirm-interrupted-running`で回収します。回収されたNodeは`INTERRUPTED_ATTEMPT`となり、同じNode IDをretryできます。Wall Timeでpauseした場合は同じRoundをcontinueします。新Roundを自動開始させません。

## On-demand

Round状態に関係なく使えます。結果は`on_demand/REQ######/`だけに保存され、通常DAGを変えません。
