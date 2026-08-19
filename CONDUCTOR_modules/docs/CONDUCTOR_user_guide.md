# CONDUCTOR user guide

## 新規Run

Main Agentで`/cs-conductor-orchestrator`を明示し、入力CSV、endpoint、`higher_is_better`、project、parallel limit、Wall Timeを示してRound 1を開始します。Mainは契約案を人間依頼と照合した場合だけauthorizeします。

高コスト基本計算は最初に一括承認できます。MCSは基本計算であり個別承認不要です。Wall Timeは上限であって消費目標ではありませんが、実行可能で有用な作業が残る限りOrchestratorは早期終了しません。

endpointの単位変換やpActivity化はRun開始前に人間側で行います。`endpoint_transform`は実施済み変換の記録用metadataであり、Runtimeが値を変換する指定ではありません。

RuntimeはRun初期化時にSMILES列を確定し、全Description、Murcko、MCS、BRICS、RECAP、および構造を直接読むPairwise structure similarity、Activity cliff、Cluster structural diversityへ同じ列名を明示的に渡します。`smiles`、`canonical_smiles`等や、名前に`smiles`を含む列を一意に推定できます。候補が複数ある場合は、新規Run依頼でSMILES列名を明示してください。

## 中断と別session再開

新しいMain sessionで`/cs-conductor-orchestrator`を明示し、Run Rootと「同じRoundを再開」を指定します。Mainは`conductor_control.json`を確認し、live leaseがあれば二重実行を拒否し、期限切れなら同じRoundを再開します。新しいRoundは作りません。長いInterpretationやDAG全文をプロンプトへ貼る必要はありません。旧RunでSMILES列metadataがなく列名からも一意に推定できない場合だけ、再開依頼にSMILES列名を追加してください。

## Round終了後

`AWAITING_HUMAN_REVIEW`で`interpretation.html`を読みます。次のいずれかを明示します。

- 同じRoundで残作業を継続する。
- 同じRoundのInterpretationを改訂する。
- Roundを受理して閉じる。

新Roundを始める場合は、Round番号、予算、重視するInsight、代替解釈、追加で確認したい範囲を依頼します。単に「次の解析」と依頼しても標準の追加探索と深掘りを選べます。Main Agentへ意見を伝えるだけではStateへ勝手に登録されず、必ず人間承認Round contractを介します。

## 異常Node

失敗したNodeは自動で別Nodeへ置換しません。通常retryはRuntimeが同じNodeへ有限回の新Attemptを付けます。Executorのraw errorはMainへ貼られず、分類codeとpointerだけが返ります。pending Nodeの取消や、成功resultを今後の自動探索から除外したい場合だけ、人間が`cs-conductor-node-review`を明示的に使用します。

## 読み取り専用支援

- `cs-conductor-state-report`: 明示されたRun RootのDAGをHTML／SVG化する。
- `cs-conductor-result-concierge`: `AWAITING_HUMAN_REVIEW`または完了後のRunを変更せず、既存結果の説明、依頼固有の追加集計、比較、Figure化を行う。補助Pythonと一時領域は`run_root/concierge/REQ######/scratch/`へ隔離する。
- `cs-conductor-run-audit`: Quick／Full整合性監査を行う。
