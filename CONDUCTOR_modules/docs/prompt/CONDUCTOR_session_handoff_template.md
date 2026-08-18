# CONDUCTOR session引継ぎテンプレート

```text
cs-conductor-dispatch Skillを使ってCONDUCTORを引き継いでください。
Run Root: <absolute path>
人間が意図する操作: <Active Round再開／同一Round継続／report revision／Round accept／新Round開始>
今回の指示: <任意>

最初にconductor_control.jsonだけを確認してください。Active Roundがあれば同じRoundを再開し、別Roundを作らないでください。live leaseなら二重起動せず停止してください。OrchestratorにはControl、Working Set、lease token、Action tokenだけを渡してください。終了後はverify-returnで実状態を報告してください。
```

引継ぎ正本はRun Rootの`conductor_control.json`です。詳細は必要時だけ`runtime/dag_snapshot.json`、Event Ledger、Result Cardへ辿ります。長いInterpretation本文や独自handoff Markdownを毎回読ませる必要はありません。
