# Operator契約修正後に同一Roundを再開するプロンプト

対象Version: `0.1.6`

A003のCanonical subject不一致、A012への無効なLocal Cluster指定、Description有効行数の報告不一致など、**複数のRunで別々に観測された既知事象**を修正したPackageへ差し替えた後、指定した一つのRunを同じRoundのまま安全に再開するためのプロンプトです。`<...>`を実際の値へ置き換えて使用してください。

すべての事象が同一Runに存在するとは仮定しません。Runごとに一回ずつ使用し、そのRunに実在するNodeとfailure pointerだけを根拠に処置します。他Runで観測された事象を理由として、存在しないNodeの作成、成功Nodeの再計算、Node Statusの変更を行いません。

このプロンプトは、対象RunのControl／Stateが読める場合に使用します。新しいRunやRoundは作りません。

## 再開プロンプト

```text
/cs-conductor-orchestrator

操作: Operator契約修正後のActive Roundを、同じRun・同じRoundのまま修復再開
Run Root: <absolute run_root>
期待するRun ID: <run_id>
期待するRound: <RND####>

人間による明示承認:
- 修正版のCONDUCTOR_modulesおよび対象Skillへの差し替えは完了しています。
- このRun内でfailure pointerにより確認できた既知の実装契約不一致に限り、修正済みFailed Nodeを同じNode IDの新Attemptとして再試行して構いません。
- このRun内にA012へLocal Clusterを指定した無効なPlanning Nodeが実在する場合に限り、cs-conductor-node-reviewでinspectした後にcancelして構いません。
- 新しいRunおよび新しいRoundの開始は許可しません。

最初に実施する確認:
1. conductor_control.jsonとRuntimeのcompact inspectionを読み、Run ID、Active Round、required_actionを照合する。
2. live lease、Runtime Worker、running Nodeを確認する。生存中のWorkerがあれば二重起動せずterminalまで待つ。
3. このRunに実在するFailed/Pending Nodeだけについて、Capability ID、scope、role、failure code、failure pointerを確認する。別のRun Rootを探索せず、全artifactや長いStateを先に読み込まない。
4. 以下の既知事象がこのRunに存在するかを個別に判定する。存在しない事象への修復操作は行わない。
5. 期待するRun／Roundと異なる、State検証に失敗する、または既知事象と異なる決定論的障害がある場合は、推測で処置せず人間へ報告して停止する。

Round状態による分岐:
- ACTIVEかつFAILED_NODE_REPAIR_REQUIRED/RETRY_FAILED_NODEの場合:
  Wall Timeに余裕があり、同じRound内での修復を人間が明示している場合だけ以下のNode別処置へ進む。Wall Time終了によりENTER_FINALIZINGへ変わった場合は、その遷移を異常と決めつけない。
- すでにFINALIZINGの場合:
  FINALIZING中にStateを直接戻したりretry-nodeを強行しない。現在のInterpretationとFull Auditを完了してAWAITING_HUMAN_REVIEWへ進め、そこで停止する。Failed Nodeを含む場合、Round outcomeはpartialになり得る。
- AWAITING_HUMAN_REVIEWの場合:
  自動でcontinueまたはacceptしない。InterpretationとAuditが有効なら、標準選択はpartial Roundとして受理し、修正版Packageで次Roundに補完を引き継ぐことである。同一Round内の比較を必須とする場合だけ、人間の追加指示によりcontinue-roundを選ぶ。
- CLOSEDまたはActive Roundなしの場合:
  新Roundを自動作成せず、人間へ報告して停止する。

Node別の処置:
- このRunに、A003/A004のrole=cluster-overlayでCanonical subjectまたは投影payload件数が不一致となったFailed Nodeが存在する場合:
  修正版RuntimeはGlobal投影集合を維持して照合するため、同じNode IDをrepair retryする。代替Nodeを作らない。
- このRunに、A002/A005/A007/A008で、実際に利用可能なDescription行数とsample_countの不一致により失敗したNodeが存在する場合:
  同じNode IDをrepair retryする。欠損Endpoint、無効分子、利用可能Vectorなし、Local標本数不足などの正当な除外はwarningまたはnot-applicableとして保持し、全化合物を強制的に解析対象へ戻さない。
- このRunに、A012へtarget_clusterまたはsingle_cluster scopeが付いたFailed/Pending Nodeが存在する場合:
  A012はGlobal専用であり、そのNodeは再試行しない。cs-conductor-node-reviewでinspectし、activeな下流Nodeがないことを確認してから、理由「A012へLocal scopeを割り当てた旧Planning契約が無効」でcancelする。Global A012の成功Nodeがあれば再利用し、なければ通常PlannerがGlobal Nodeだけを扱う。
- 上記に該当しないFailed Node:
  一括retry、cancel、skipped化をしない。failure pointerを簡潔に報告して人間判断を待つ。
- すでにsucceededのNode:
  他Runで同じCapabilityに問題が報告されていても再計算しない。warningがあるだけでも再計算せず、既存結果を保持する。
- このRunに上記の既知事象が一つも存在しない場合:
  修復操作を行わず、Stateが正常なら同じRoundの現在のrequired_actionから通常再開する。未知のFailed Nodeがある場合は人間へ報告して停止する。

再開条件と処理:
- running Nodeがゼロになってから保守操作を行う。
- FAILED_NODE_REPAIR_REQUIREDで修正済みNodeを再試行する場合、Control Authorityを付けたretry-nodeを一回だけ使う。
- A012の無効Node取消しは、このRunに該当Nodeが実在すると確認した場合だけ、人間承認済みのcs-conductor-node-reviewを使う。
- State、DAG、Event Ledger、Node Statusを直接編集しない。
- cancelledをsucceededまたはskippedの代用にしない。
- 修復後は同じRoundの現在のrequired_actionへ戻り、通常の0.1.6固定ループを継続する。
- 専門SkillをMain Agentから直接実行せず、RuntimeのExecution Request／Packet経路を使う。
- 同じRoundのInterpretation、Full Auditまで完了させ、AWAITING_HUMAN_REVIEWで停止する。
- Roundを自動受理せず、次Roundを開始しない。

終了報告に含める内容:
- 再試行したNode IDと新Attempt ID（該当がある場合のみ）
- cancelした旧A012 Node IDと理由（該当がある場合のみ）
- このRunには存在せず、処置しなかった既知事象
- 変更しなかったsucceeded Node数
- 残ったFailed/Pending/Running Node数
- InterpretationおよびFull Auditの状態
- 最終required_action
```

## AWAITING_HUMAN_REVIEW到達後の推奨手順

InterpretationとFull Auditが完了している場合は、限定的な解釈であることをRound outcomeに残したまま、現在Roundを受理します。

```text
/cs-conductor-orchestrator

操作: Partial Roundを受理して閉じるだけ
Run Root: <absolute run_root>
対象Round: <RND####>

InterpretationとFull Auditが有効であることを確認してください。Failed Nodeと未解析範囲は履歴から削除せず、partial outcomeおよび次Roundへの引継ぎ事項として保持してください。対象Roundをacceptした後は停止し、新しいRoundを自動開始しないでください。
```

受理完了を確認した後、別の指示として次Roundを開始します。

```text
/cs-conductor-orchestrator

操作: 修正版Packageで次の新Roundを開始
Run Root: <absolute run_root>
期待する新Round: <RND####>
Wall Time: <minutes>
parallel_limit: <number>
Available CPU Cores: <number>

Roundの目的:
前RoundのInterpretationとpartial outcomeを引き継ぎ、前Roundに実在したOperator契約由来のFailed Nodeだけを修正版で補完した上で、通常の探索を継続する。

指示:
- 前Roundのsucceeded NodeとResultは再計算せず再利用する。
- 前Roundのfailure pointerを確認し、実在した失敗だけを対象にする。他Runで報告された事象を追加しない。
- 同一signatureで科学的scopeが不変なら同じNodeを再利用する。
- A003/A004 cluster-overlayのように旧scope定義自体が誤っていた場合は、修正後scopeで新しい正規Nodeを作る。
- A012の旧Local Nodeは再実行せず、Global A012だけを対象にする。
- 最後にこのRoundのInterpretationとFull Auditを作成し、AWAITING_HUMAN_REVIEWで停止する。
```

## この方法を使わず新Runを選ぶ条件

次のいずれかに該当する場合は、同一Roundの修復再開を中止し、人間へ新Runを提案します。

- Control／State／Event Ledgerの検証自体が失敗する
- Node ID、依存関係、Run入力、endpoint、またはCluster registryの整合性が崩れている
- 失敗の大半が今回修正した契約不一致では説明できない
- 入力CSV、endpoint、前処理方針、科学Parameterを変更する必要がある
- 人間が既存Operator／Clustering結果を信頼しないと判断した

新Runを選ぶ場合でも、Descriptionだけを無条件にコピーしてStateを手編集しません。現行Versionが正式に提供するMigration手順が対象Descriptionの`result.json`、payload hash、compound ID集合、入力hashを検証できる場合に限り、基本計算の再利用を行います。
