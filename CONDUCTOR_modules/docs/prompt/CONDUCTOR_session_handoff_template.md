# CONDUCTOR session引継ぎテンプレート

通常は次の短い情報だけで再開できます。

```text
cs-conductor-orchestrator Agentを使ってCONDUCTORを再開してください。
state.json: <absolute path>
期待する次Round: RND####
今回の依頼: <追加探索／特定Insightの深掘り／人間checkpoint等>
parallel_limit: <number>
Wall Time: <time>

Runtime bootstrapを行い、leaseを取得できない場合は変更せず停止してください。orchestrator_brief.jsonから開始し、必要な情報だけをqueryしてください。異常中断の痕跡があればFull Auditでattemptとartifactを照合してから続行してください。
```

手作業の引継ぎ文書は補助情報です。正本は`state.json`、`summaries/`、`indices/`、`rounds/`です。
