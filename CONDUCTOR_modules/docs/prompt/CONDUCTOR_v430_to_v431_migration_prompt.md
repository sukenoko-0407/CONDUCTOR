# v4.3.0 Runをv4.3.1へ一度だけ移行する推奨プロンプト

次のプロンプトは、通常の解析Agentではなく `cs-conductor-v430-migrator` に渡してください。

```text
cs-conductor-v430-migrator を使用して、次のCONDUCTOR v4.3.0 Runをv4.3.1形式の新しいRun rootへ移行してください。

source run root: <既存v4.3.0 run rootの絶対パス>
target run root: <まだ存在しない新run rootの絶対パス>
new run id: <任意。省略可>

まずscanだけを実行し、移行対象Node、除外Nodeと理由、Node ID再附番表、警告を説明してください。私がscan結果を明示承認するまでapplyしないでください。sourceには一切書き込まず、targetをsource配下に作らないでください。
```

scanの説明を確認した後は、同じセッションで次のように指示します。

```text
提示されたmigration planを承認します。そのplanをapplyし、続けてverifyしてください。verifyが失敗した場合は、新run rootを利用可能とは扱わず、失敗内容を報告してください。
```

成功後の解析再開例:

```text
cs-conductor-orchestrator を使用してください。
state.json: <新run root>/state.json
Round: RND0002

移行済みEvidenceに対する新しいInterpretationを最初に完成させ、その後はorchestrator_brief.jsonに従って解析を継続してください。
```

## 移行で引き継ぐもの

- artifactと依存関係を検証できた成功済みDescription / Grouping / Operator
- 元Node ID、元Round、元run rootのprovenance
- 検証済みartifactのcopyとhash manifest
- Run-global entity counterの下限

## active DAGへ引き継がないもの

- `pending`、`running`、失敗、検証不能、重複署名のNode
- 旧Interpretationとその判断（参照用copyのみ保持）
- 旧Orchestratorの一時的な実行状態やlock

移行後は新しいNode IDが依存順に附番されます。旧IDとの対応は `migration/v430_import/node_id_map.csv` で監査できます。
