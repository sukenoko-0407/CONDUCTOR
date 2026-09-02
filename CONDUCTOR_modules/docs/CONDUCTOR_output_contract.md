# CONDUCTOR 0.1.9 出力契約

`0.1.9`は製品Versionであり、各JSONの`schema_version`とは別に管理する。現行契約ではExecution Request／Runtime成果物は原則`1.0.0`、Capability metadataは`2.0.0`、Analysis Profileは`4.0.0`である。Schema番号はそのfile形式の世代を表し、CONDUCTOR製品Versionの大小や互換性を意味しない。

```text
run_root/
├─ conductor_control.json
├─ runtime/
│  ├─ dag.json
│  ├─ events.jsonl
│  ├─ cluster_registry.csv
│  ├─ cluster_membership/
│  ├─ series_registry.csv
│  ├─ series_cluster_membership.csv
│  ├─ compound_series_support.csv
│  ├─ analysis_unit_registry.csv
│  └─ analysis_unit_membership.csv
├─ description/N######/
├─ clustering/N######/
├─ analysis/N######/
├─ interpretation/RND####/
├─ state/<timestamp>/audit.{json,md}
└─ on_demand/
   ├─ index.jsonl
   └─ REQ######/
```

各正規Node directoryはprimary artifact、manifest、`execution_event.json`を持ちます。`execution_event.json`に登録するartifact pathはNode出力内の相対pathに限定し、重複、欠落、Hash不一致をRuntimeがcommit前に拒否します。Nodeの`parameters`にはCapability既定値とRun固有overrideを統合した実効値を保存します。Description NodeにはRuntimeがpayload・意味型・自然metricを結び付けた`description_result.json`も作成し、Vector Clusteringはこの契約を必須入力とします。A009は`standard_summary.html`とSeries別HTML、I001は`interpretation.{json,md,html}`を出力します。On-demandは`result.md`、`result.html`、`artifact_manifest.json`を持ちます。

各Clustering primaryは全入力化合物を明示的に記録します。Cluster所属行は正の`membership_value`、未所属・invalid・最小Cluster未満は空の`cluster_id`と0の`membership_value`を用います。Runtimeは入力化合物の黙示的欠落、未知ID、無効なmembership、最小Cluster未満のactive Clusterを拒否してから単一のCluster Registryへ統合します。

Full auditはprimaryだけでなく、各`execution_event.json`に登録されたCSV・JSON・HTML・画像の存在とSHA-256、およびInterpretation 3形式のSHA-256を検証します。`quick` auditはState revision・入力・Node状態・DAG依存だけを確認し、Round完了判定には登録できません。

`conductor_control.json`と`runtime/dag.json`は一つの論理Stateです。更新途中のprocess停止に備え、Runtimeは一時的な`runtime/state_transaction.json`へ完全な組を先に記録します。残存transactionはRuntimeが正本として読み、旧process停止確認後の同一Round再開で通常Stateへ確定します。残存中は不整合なsnapshotを避けるためOn-demand作成を拒否します。実行packetは生成元Leaseのfingerprintを持ち、Lease失効・交代後の古いpacketは再実行できません。

Skill scratchは`runtime/scratch/`、Skill cacheは各Skillの`env/`内です。Pixi初期構築はSkill単位のbootstrap lockで直列化し、生存中の同一host ownerを経過時間だけで回収しません。`CONDUCTOR_modules/`にはRun結果を書きません。
