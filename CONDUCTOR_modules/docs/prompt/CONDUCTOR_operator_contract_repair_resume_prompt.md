# Operator契約修正後に同一Roundを再開するプロンプト

対象Version: `0.1.6`

A003のCanonical subject不一致、A012への無効なLocal Cluster指定、またはDescription有効行数の報告不一致を修正したPackageへ差し替えた後、既存Runを同じRoundのまま安全に再開するためのプロンプトです。`<...>`を実際の値へ置き換えて使用してください。

このプロンプトは、既存RunのControl／Stateが読めており、修復対象が今回のOperator契約不一致に限定される場合に使用します。新しいRunやRoundは作りません。

## 再開プロンプト

```text
/cs-conductor-orchestrator

操作: Operator契約修正後のActive Roundを、同じRun・同じRoundのまま修復再開
Run Root: <absolute run_root>
期待するRun ID: <run_id>
期待するRound: <RND####>

人間による明示承認:
- 修正版のCONDUCTOR_modulesおよび対象Skillへの差し替えは完了しています。
- 今回特定された実装契約不一致に限り、修正済みFailed Nodeを同じNode IDの新Attemptとして再試行して構いません。
- A012へLocal Clusterを指定して作られた無効なPlanning Nodeは、cs-conductor-node-reviewでinspectした後にcancelして構いません。
- 新しいRunおよび新しいRoundの開始は許可しません。

最初に実施する確認:
1. conductor_control.jsonとRuntimeのcompact inspectionを読み、Run ID、Active Round、required_actionを照合する。
2. live lease、Runtime Worker、running Nodeを確認する。生存中のWorkerがあれば二重起動せずterminalまで待つ。
3. Failed NodeごとにCapability ID、scope、role、failure code、failure pointerを確認する。全artifactや長いStateを先に読み込まない。
4. 期待するRun／Roundと異なる、State検証に失敗する、または今回と異なる決定論的障害がある場合は、何も変更せず人間へ報告して停止する。

Node別の処置:
- A003/A004のrole=cluster-overlayでCanonical subjectまたは投影payload件数が不一致となったFailed Node:
  修正版RuntimeはGlobal投影集合を維持して照合するため、同じNode IDをrepair retryする。代替Nodeを作らない。
- A002/A005/A007/A008で、実際に利用可能なDescription行数とsample_countの不一致により失敗したNode:
  同じNode IDをrepair retryする。欠損Endpoint、無効分子、利用可能Vectorなし、Local標本数不足などの正当な除外はwarningまたはnot-applicableとして保持し、全化合物を強制的に解析対象へ戻さない。
- A012にtarget_clusterまたはsingle_cluster scopeが付いたFailed/Pending Node:
  A012はGlobal専用であり、そのNodeは再試行しない。cs-conductor-node-reviewでinspectし、activeな下流Nodeがないことを確認してから、理由「A012へLocal scopeを割り当てた旧Planning契約が無効」でcancelする。Global A012の成功Nodeがあれば再利用し、なければ通常PlannerがGlobal Nodeだけを扱う。
- 上記に該当しないFailed Node:
  一括retry、cancel、skipped化をしない。failure pointerを簡潔に報告して人間判断を待つ。
- すでにsucceededのNode:
  warningがあるだけでは再計算しない。既存結果を保持する。

再開条件と処理:
- running Nodeがゼロになってから保守操作を行う。
- FAILED_NODE_REPAIR_REQUIREDで修正済みNodeを再試行する場合、Control Authorityを付けたretry-nodeを一回だけ使う。
- A012の無効Node取消しは、人間承認済みのcs-conductor-node-reviewだけを使う。
- State、DAG、Event Ledger、Node Statusを直接編集しない。
- cancelledをsucceededまたはskippedの代用にしない。
- 修復後は同じRoundの現在のrequired_actionへ戻り、通常の0.1.6固定ループを継続する。
- 専門SkillをMain Agentから直接実行せず、RuntimeのExecution Request／Packet経路を使う。
- 同じRoundのInterpretation、Full Auditまで完了させ、AWAITING_HUMAN_REVIEWで停止する。
- Roundを自動受理せず、次Roundを開始しない。

終了報告に含める内容:
- 再試行したNode IDと新Attempt ID
- cancelした旧A012 Node IDと理由
- 変更しなかったsucceeded Node数
- 残ったFailed/Pending/Running Node数
- InterpretationおよびFull Auditの状態
- 最終required_action
```

## この方法を使わず新Runを選ぶ条件

次のいずれかに該当する場合は、同一Roundの修復再開を中止し、人間へ新Runを提案します。

- Control／State／Event Ledgerの検証自体が失敗する
- Node ID、依存関係、Run入力、endpoint、またはCluster registryの整合性が崩れている
- 失敗の大半が今回修正した契約不一致では説明できない
- 入力CSV、endpoint、前処理方針、科学Parameterを変更する必要がある
- 人間が既存Operator／Clustering結果を信頼しないと判断した

新Runを選ぶ場合でも、Descriptionだけを無条件にコピーしてStateを手編集しません。現行Versionが正式に提供するMigration手順が対象Descriptionの`result.json`、payload hash、compound ID集合、入力hashを検証できる場合に限り、基本計算の再利用を行います。

