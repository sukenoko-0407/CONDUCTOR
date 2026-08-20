# CONDUCTOR session引継ぎテンプレート

対象Version: `0.1.4`

長いState、過去のInterpretation、独自の引継ぎMarkdownを貼り付ける必要はない。Run Rootと人間が意図する操作を新しいMain sessionへ渡す。

```text
/cs-conductor-orchestrator

操作: session引継ぎ
Run Root: <absolute path>
人間が意図する操作: <状態確認のみ／Active Round再開／同一Round継続／Interpretation改訂／Round受理／新Round開始>
期待するRound: <RND#### または none>
今回の指示（任意）: <人間の観点・残作業>

最初にrun_root/conductor_control.jsonだけを確認し、Run ID、Control revision、現在のRound、Round状態、required_action、live leaseの有無を照合してください。人間が指定していない操作へ読み替えないでください。

ActiveまたはFINALIZINGのRoundがある場合は、同じRoundを再開し、別Roundを作らないでください。live leaseがある場合は二重実行せず報告してください。新Roundは、人間が明示的に「新Round開始」を指定し、Active Roundがなく、直前RoundがCLOSEDであることを確認した場合だけprepare／authorizeしてください。

Main Agent自身がOrchestratorです。科学計算はRuntimeが生成した署名付きpacketだけをExecutorへ渡し、Interpretation contextはInterpreterへ渡してください。lease tokenとAction tokenをSubagentへ渡さず、Mainから専門Skillを直接実行しないでください。

通常は全DAG、全Event Ledger、過去全Reportを読まないでください。追加情報が必要な場合だけRuntimeのbounded queryからResult Cardまたはfailure summaryを取得してください。Tool応答を失ったmutationは推測で再送せず、Control revisionとverify-returnで照合してください。

解析を進める操作では、同じRoundのInterpretationとFull Auditを完成させ、AWAITING_HUMAN_REVIEWで停止してください。Roundを自動受理せず、人間の指示なしに次Roundを開始しないでください。
```

引継ぎの正本はRun Rootの`conductor_control.json`である。詳細は必要な場合だけ`runtime/dag_snapshot.json`、Event Ledger、Result Cardへ辿る。
