# Description限定Migration依頼プロンプト

```text
cs-conductor-description-migrator Agentを使い、CONDUCTOR 0.1.0から0.1.1へのDescription限定Migrationを実行してください。

source_run_root: <既存0.1.0 run rootの絶対path>
target_run_root: <存在しない新規0.1.1 run rootの絶対path>
input CSV: <元Stateと同じ場合は省略。保存場所だけ変わった場合は絶対path>

scan結果として、入力hashと移行対象Description一覧を確認してからapplyし、最後にverifyしてください。Description以外のNode・artifact・IDは移行せず、移行元は変更しないでください。RND0001は基本計算途中のVersion migrationとしてclosedにし、RND0002の作成、Orchestrator起動、解析実行は行わないでください。
```
