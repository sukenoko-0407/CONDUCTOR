# CONDUCTOR 0.1.9 利用ガイド

## 新規Run

日常プロンプト集の「新規Run」を使い、CSV、Endpoint、`higher_is_better`、出力先、並列数、CPU数、Wall Timeを指定します。高コストDescriptionの一括承認後、Main Agentは基本計算、定型解析、Interpretation、監査まで進めます。

## 人間確認

まずA009の`standard_summary.html`を読み、必要ならSeries別HTML、A008 MMP HTMLを確認します。気になるSeries、Cluster、化合物、図、仮説はOn-demandへ依頼します。

## parameter変更

`min_ff_evaluate`またはLeiden resolutionを変える場合、定型解析の計画前であれば、同じACTIVE Roundで`revise-series`を明示実行します。新しいA001、A002、C012 Nodeを作りますが、成功済みDescriptionとC001-C010は再計算しません。定型解析を計画した後は科学的scopeの混在を避けるため変更できません。Series数24超ではRuntimeが停止するので、人間が結果を確認し、現条件を承認するか条件変更を指示します。Runtimeは値を勝手に変更しません。

## 失敗・停止

Failureはdiagnosticに基づき同一Nodeを修正・retryします。期限切れLeaseと`running` Nodeが残る場合、Runtimeは同一hostで生存中のprocessを検出して二重実行を拒否します。異なるhostまたは旧形式の実行記録は自動的に失敗扱いにせず、旧processの停止を人間が確認した場合だけ`resume-round --confirm-interrupted-running`で回収します。回収されたNodeは`INTERRUPTED_ATTEMPT`となり、同じNode IDをretryできます。Wall Timeでpauseした場合は同じRoundをcontinueします。新Roundを自動開始させません。

## On-demand

Round状態に関係なく使えます。結果は`on_demand/REQ######/`だけに保存され、通常DAGを変えません。
