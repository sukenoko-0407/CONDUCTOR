# CONDUCTOR session引継ぎテンプレート

```text
/cs-conductor-orchestrator をMain sessionで有効化してCONDUCTORを引き継いでください。
Run Root: <absolute path>
人間が意図する操作: <Active Round再開／同一Round継続／report revision／Round accept／新Round開始>
今回の指示: <任意>

最初にconductor_control.jsonだけを確認してください。Active Roundがあれば同じRoundを再開し、別Roundを作らないでください。live leaseなら二重実行せず停止してください。Main自身がOrchestratorです。科学計算は署名付きpacketをExecutorへ、Interpretation contextはInterpreterへ渡し、lease tokenをSubagentへ渡さないでください。
```

引継ぎ正本はRun Rootの`conductor_control.json`です。詳細は必要時だけ`runtime/dag_snapshot.json`、Event Ledger、Result Cardへ辿ります。長いInterpretation本文や独自handoff Markdownを毎回読ませる必要はありません。
