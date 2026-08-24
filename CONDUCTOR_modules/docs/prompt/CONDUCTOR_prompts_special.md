# CONDUCTOR 特別対応プロンプト集

対象Version: `0.1.6`

障害修復、旧契約の補正、特定Operatorの再解析、限定的な深掘り、既存Reportの翻訳に使う。通常のRound運用には[日常運用プロンプト集](CONDUCTOR_prompts_daily.md)を使用する。

## 目次

- [共通原則](#special-common)
- [実行中packet完了後の安全な一時停止](#special-safe-pause)
- [Failed Nodeの原因調査・実装修正](#special-failure-maintenance)
- [修正済みFailed Nodeを同一Roundで再実行](#special-failure-retry)
- [既知のOperator契約不一致を修復して再開](#special-operator-contract)
- [A010を同一Run内で再実行](#special-a010)
- [Interpretation日本語HTMLの追加作成](#special-translation)
- [同一Runを使用せず新Runを選ぶ条件](#special-new-run)

<a id="special-common"></a>
## 共通原則

- State、DAG、Event Ledger、Node Statusを直接編集しない。
- `pending / running / succeeded / failed / cancelled`以外の独自Statusを作らない。
- 生存中のRuntime Workerや科学processを二重起動、強制的にreconcile、代行実行しない。
- 技術的不具合の修復と、科学的scope／parameterの変更を区別する。科学的意味が変わる場合は人間判断を待つ。
- succeeded Nodeと既存artifactを削除・上書きしない。無効化が必要なら`cs-conductor-node-review`を使う。
- 人間が許可していない新Run、新Round、代替Nodeを作らない。

<a id="special-safe-pause"></a>
## 実行中packet完了後の安全な一時停止

実行中のNodeを強制終了せず、現在発行済みExecution packetがterminalになった直後でActive Roundを止める。

```text
現在のCONDUCTOR処理を安全に一時停止してください。

Run Root: <absolute run_root>
対象Round: <RND####>

目的:
失敗したNodeの原因を修正し、同じRound・同じNode IDで再実行することです。

指示:
- 起動済みRuntime Workerと、そのExecution packet内のNodeは中断せずterminalまで完了させる
- WAIT_RUNNING中はreconcileせず待ち、RECONCILE_RUNNINGになった場合だけ一回実行する
- 現在のpacket処理後は、新しいExecution packet、二つ目のWorker、failed Nodeのretryを開始しない
- 実行中Nodeがゼロになった時点を停止境界とする
- RoundはACTIVEのまま維持し、request-checkpoint、ENTER_FINALIZING、Interpretation、Full Audit、accept-roundを実行しない
- failed Nodeをcancelledまたは独自Statusへ変更しない
- failed NodeごとにNode ID、Capability ID、Attempt数、failure code、failure pointerを報告する
- State、DAG、Event Ledgerを直接編集しない
- 最後にOrchestrator leaseをreleaseして終了する
```

`request-checkpoint`はRoundを`FINALIZING`へ進めるため、この一時停止には使用しない。一つのpacketに複数Nodeがある場合は、packet単位で停止境界まで完了させる。

<a id="special-failure-maintenance"></a>
## Failed Nodeの原因調査・実装修正

Orchestratorを動かさず、通常のMain Agentへ保守作業として依頼する。

```text
これはCONDUCTOR Roundの再開ではなく、失敗原因の保守作業です。

Run Root: <absolute run_root>
対象Node: <N######>
failure pointer: <failure_packet等のpath>

Run Rootはread-onlyとして扱い、State、DAG、Node、既存artifactを変更しないでください。failure情報と該当Skillの必要最小限の実装を調査し、原因を特定してください。

CLI、環境、path、入出力契約などの技術的不具合であれば、該当Skillを修正して回帰試験まで実施してください。修正対象、原因、科学的意味が不変であること、検証結果を報告してください。

科学的アルゴリズム、対象化合物、endpoint、Metric、Cluster scope、乱数seed、parameterの意味を変更する必要がある場合は、修正前に人間の判断を待ってください。Stateを書き換えたり代替Nodeを作成したりしないでください。
```

<a id="special-failure-retry"></a>
## 修正済みFailed Nodeを同一Roundで再実行

```text
/cs-conductor-orchestrator

操作: 修正後のActive Roundを同じRoundのまま再開
Run Root: <absolute run_root>
対象Round: <RND####>
優先対象Node: <N######>
修正内容: <修正した技術的不具合の要約>
SMILES列名（旧Runでmetadataがなく自動推定できない場合のみ）: <column name>

最初にconductor_control.jsonを確認し、対象RoundがACTIVEであること、running Nodeがゼロであることを照合してください。修正済みfailed Nodeを同じNode IDの新Attemptとして再実行し、代替Nodeや新Roundを作らないでください。

required_actionがRETRY_FAILED_NODEなら同じNodeを再試行してください。FAILED_NODE_REPAIR_REQUIREDで、上記の人間承認済み修正が完了している場合はrepair retryしてください。EXECUTE_RUNNABLE_BATCHでも、このプロンプトで人間が優先再実行を明示しており、running Nodeがゼロなら、Control Authorityを付けたretry-nodeで同じNodeをpendingへ戻してください。

それ以外のrequired_actionでは別の科学Nodeを実行せず、required_actionと対象Node状態を報告して停止してください。修復後は通常の固定ループへ戻り、InterpretationとFull Auditまで完了してAWAITING_HUMAN_REVIEWで停止してください。Roundを自動受理せず、次Roundを開始しないでください。
```

Wall Timeが先に終了して`FINALIZING`へ進んだ場合はretryを強行しない。得られた結果でInterpretationとAuditを完成させ、人間がpartial Round受理または同一Round継続を選ぶ。

<a id="special-operator-contract"></a>
## 既知のOperator契約不一致を修復して再開

A003/A004のCanonical subject不一致、Description有効行数とsample countの不一致、A012への無効なLocal scopeなど、複数Runで別々に観測された既知事象に使用する。対象Runに実在する事象だけを処置する。

```text
/cs-conductor-orchestrator

操作: Operator契約修正後のActive Roundを、同じRun・同じRoundのまま修復再開
Run Root: <absolute run_root>
期待するRun ID: <run_id>
期待するRound: <RND####>

人間による明示承認:
- 修正版Packageへの差し替えは完了しています。
- このRunのfailure pointerで確認できる既知の実装契約不一致だけを、同じNode IDの新Attemptとして再試行して構いません。
- このRunにA012へLocal Clusterを指定した無効Nodeが実在する場合だけ、cs-conductor-node-reviewでinspect後にcancelして構いません。
- 新しいRunおよび新しいRoundの開始は許可しません。

最初にconductor_control.jsonとcompact inspectionを読み、Run ID、Active Round、required_action、live lease、Worker、running Nodeを照合してください。このRunに実在するFailed/Pending NodeだけについてCapability、scope、role、failure code、failure pointerを確認し、別Runを探索しないでください。

Node別処置:
- A003/A004 role=cluster-overlayでCanonical subjectまたは投影payload件数不一致により失敗したNode: 同じNode IDをrepair retryする。
- A002/A005/A007/A008で利用可能Description行数とsample_countの不一致により失敗したNode: 同じNode IDをrepair retryする。正当な欠損・無効分子・Vectorなし・Local標本数不足はwarningまたはnot-applicableとして保持する。
- A012へtarget_clusterまたはsingle_cluster scopeが付いたFailed/Pending Node: A012はGlobal専用なので再試行しない。inspectし、activeな下流Nodeがないことを確認して「旧Planning契約が無効」を理由にcancelする。Global A012は再利用する。
- 上記以外のFailed Node: 一括retry、cancel、独自Status化をせず、人間判断を待つ。
- succeeded Node: 他Runで同じCapabilityに問題があっても再計算しない。

ACTIVEかつ修復可能なrequired_actionの場合だけ処置してください。FINALIZINGならretryせずInterpretationとFull Auditを完成させてAWAITING_HUMAN_REVIEWで停止してください。AWAITING_HUMAN_REVIEWなら自動continue／acceptせず、CLOSEDなら新Roundを作らず報告してください。

State、DAG、Ledgerを直接編集せず、RuntimeのExecution Request／Packet経路を使用してください。終了時に再試行NodeとAttempt、cancel Node、未処置事象、残存Status件数、Interpretation、Audit、最終required_actionを報告してください。
```

<a id="special-a010"></a>
## A010を同一Run内で再実行

旧形式のA010を監査履歴として残し、現在の`cs-analysis-cluster-profile`で再実行する。

Round操作は状態に合わせて人間が明記する。

- `ACTIVE`：現在のRoundをそのまま再開
- `AWAITING_HUMAN_REVIEW`：現在のRoundを継続
- `CLOSED`：同じRun内で新しいRoundを開始

```text
/cs-conductor-orchestrator

Run Root: <absolute RUN_ROOT path>
Roundの扱い: <現在のRoundをそのまま再開 / 現在のRoundを継続 / 同じRun内で新しいRoundを開始>
追加Wall Time: <minutes>
A010再実行対象: <旧A010 Node IDを列挙 / 旧形式のA010をすべて>

同じRun IDを維持し、現在のcs-analysis-cluster-profile Skillを使用してA010を再実行してください。人間が上記で許可したRound操作だけを行い、別Runや許可されていない新Roundを作らないでください。

対象A010 Nodeをqueryして次を区別してください。
- failed Node: 同じ科学的契約が成立する場合は同じNode IDの新Attemptとしてretryする。
- succeeded Node: 削除・上書きしない。cs-conductor-node-reviewで下流影響をinspect後、旧結果をdisable-resultで下流利用停止にし、同じ入力Node、scope、Cluster、parameterを使う新しいA010 Nodeとして実行する。
- favorable_fraction、favorable_threshold、favorable_comparatorを持つ新形式の成功Node: 再実行対象から除外する。

新A010でhigh_threshold／low_thresholdが維持され、favorable／unfavorableのfraction、count、comparator、quantile、threshold populationがCSVとoperator_summary.jsonへ記録されていることを確認してください。operator_report.htmlのFavorable definitionとGlobal favorable baselineも確認してください。

A010以外の科学Nodeをこの依頼だけを理由に追加しないでください。公開Runtime操作だけでは対象A010を限定できない場合は、State編集やprivate関数呼出しをせず、人間へ報告して停止してください。

新結果を正規commitし、Interpretationを更新してFull Auditまで完了してください。旧A010 Nodeは監査履歴に残し、新旧Node IDの対応を報告してください。
```

`disable-result`は旧成果物を削除しないが、旧A010を参照するInterpretationを失効させることがある。新結果commit後にInterpretationを再作成する。

<a id="special-translation"></a>
## Interpretation日本語HTMLの追加作成

標準Interpretationは日本語である。例外的に英語で作成された既存Reportだけに使用し、Stateや既存Reportは変更しない。

```text
Plan modeで実施してください。

指定したinterpretation.mdを内容の正本、interpretation.htmlをlayout／CSS templateとして、日本語のinterpretation_jp.htmlを同じdirectoryに新規作成してください。

入力Markdown: <absolute path>/interpretation.md
参照HTML template: <absolute path>/interpretation.html
出力: <same directory>/interpretation_jp.html

最初に入力Markdownと参照HTMLをread-onlyで確認してください。Markdown本文がすでに日本語ならfileを作らず報告してください。出力fileが存在する場合は上書きせず人間へ確認してください。

翻訳対象はMarkdownの人間向け文章です。見出し構造、INS######、N######、C######、RND####、Capability ID、数値、単位、metric、sample数、Operator result reference、相対リンク、警告、limitations、recommended follow-upsを省略・追加・再解釈しないでください。新しいInsightや現行仕様にないIDを生成しないでください。

HTMLのsection順、低彩度配色、table、fact panel、print CSS、埋め込みassetを参照HTMLから維持してください。大容量HTMLを翻訳元にせず内容はMarkdownから取得し、外部CDN、font、network取得を追加しないでください。

既存のinterpretation.json、interpretation.md、interpretation.html、quality report、Runtime、DAG、State、その他artifactは変更しないでください。書き込みはinterpretation_jp.htmlの新規作成一回だけとし、実行前に計画と書き込み対象を人間へ示してください。
```

<a id="special-new-run"></a>
## 同一Runを使用せず新Runを選ぶ条件

次のいずれかに該当する場合は修復再開を中止し、新Runを人間へ提案する。

- Control、DAG、Event Ledgerの検証自体が失敗する
- Node ID、依存関係、Run入力、endpoint、Cluster registryの整合性が崩れている
- 失敗の大半を既知の技術的不具合で説明できない
- 入力CSV、endpoint、前処理方針、科学parameterを変更する必要がある
- 人間が既存Operator／Clustering結果を信頼しないと判断した

新Runを選ぶ場合も、Descriptionを無条件にコピーしたりStateを手編集したりしない。正式なMigrationが`result.json`、payload hash、compound ID集合、入力hashを検証できる場合だけ再利用する。
