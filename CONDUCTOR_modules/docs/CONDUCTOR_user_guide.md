# CONDUCTOR user guide

## 新規Run

Main Agentで`/cs-conductor-orchestrator`を明示し、入力CSV、endpoint、`higher_is_better`、project、parallel limit、Available CPU Cores、Wall Timeを示してRound 1を開始します。Available CPU Coresを省略した場合は8です。Mainは契約案を人間依頼と照合した場合だけauthorizeします。

parallel limitは同時に実行するNode数、Available CPU Coresは科学計算へ割り当てるCPU総数です。D019（GFN2-xTB）はRuntimeにより単独実行され、原則として1化合物4コア、`floor(Available CPU Cores / 4)`化合物並列になります。D020（ChemBERTa）とA014 Global MMPもSkill内部並列を使用するため、他Nodeと同じExecution packetへ混在させません。

高コスト基本計算は最初に一括承認できます。MCSは基本計算であり個別承認不要です。Wall Timeは上限であって消費目標ではありませんが、実行可能で有用な作業が残る限りOrchestratorは早期終了しません。

初期探索を含むAnalysisは、1 Roundにつき最大200 Nodeです。Runtimeは最大50 Nodeずつ登録し、初期Globalを最大100 Nodeで区切ってLocal解析用の容量を残します。計画Actionが複数回現れても異常ではありません。上限到達後はInterpretationを作成し、残りは人間が開始する次Roundで継続します。Wall Timeを長くしても200件は増えません。基本Description／Clusteringはこの上限に含まれません。

endpointの単位変換やpActivity化はRun開始前に人間側で行います。`endpoint_transform`は実施済み変換の記録用metadataであり、Runtimeが値を変換する指定ではありません。

RuntimeはRun初期化時にSMILES列を確定し、全Description、Murcko、MCS、BRICS、RECAP、および構造を直接読むPairwise structure similarity、Activity cliff、Cluster structural diversityへ同じ列名を明示的に渡します。`smiles`、`canonical_smiles`等や、名前に`smiles`を含む列を一意に推定できます。候補が複数ある場合は、新規Run依頼でSMILES列名を明示してください。

## MMP解析

A014は初期Globalで入力CSVから一度だけGlobal MMP Databaseを構築します。mmpdbによる1～3 cut、Exact Core heavy atom下限、Environment radius 0～5を使い、salt removalや追加の分子標準化は行いません。全情報は`mmp_pair_detail.csv`でSpotfireへ渡せます。

Global構築後は、同じDatabaseを変更せずに全Cluster screeningと選択Clusterの詳細比較を行います。Exact CoreやEnvironmentはMMP内部の構造Keyであり、CONDUCTORのGlobal／Cluster-local scopeとは別概念です。別Roundで気になるClusterを深掘りする場合もGlobal MMP列挙を再実行しません。

## Schema Versionの見方

`schema_version`はCONDUCTOR本体のVersionではなく、そのJSON文書形式のVersionです。解析DAGの正本であるDescription／Clustering／Analysis Resultは、`document_type`と`schema_version`の組で識別します。現在のCanonical Resultはそれぞれ`description_result/1.0.0`、`clustering_result/1.0.0`、`analysis_result/1.0.0`です。

Skillがscratch内に生成するArtifact ManifestとExecution Eventは、Runtime adapterが実行結果を検証・昇格するためだけの内部契約です。下流Nodeへは渡しません。Vector Clustering、PCA、UMAPはCanonical Description Resultだけを受け付け、旧ManifestやVersion違いを推測して読み替えません。一般利用でCanonical Resultがない場合は、value semanticsとMetricを利用者が明示します。

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
