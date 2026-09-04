# CONDUCTOR 0.1.10 出力契約

`0.1.10`は製品Versionであり、各JSONの`schema_version`とは別に管理する。現行契約ではExecution Request／Runtime成果物は原則`1.0.0`、Capability metadataは`2.0.0`、Analysis Profileは`4.0.0`である。Schema番号はそのfile形式の世代を表し、CONDUCTOR製品Versionの大小や互換性を意味しない。

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
│  ├─ analysis_unit_membership.csv
│  ├─ selected_clusters_effective.csv
│  └─ series_parameter_search.json  # 人間選択が必要な場合のRuntime内部state
├─ description/N######/
├─ clustering/N######/
├─ analysis/N######/
├─ interpretation/RND####/
├─ state/<timestamp>/audit.{json,md}
└─ on_demand/
   ├─ index.jsonl
   └─ REQ######/
```

Runとは別に、`project`をProgram名として次の再利用Databaseを置きます。

```text
data/description_database/<project>/
├─ database_manifest.json
├─ compound_registry.sqlite3
└─ DXXX__<skill_name>/
   ├─ description.sqlite3
   └─ audit.jsonl
```

各正規Node directoryはprimary artifact、manifest、`execution_event.json`を持ちます。`execution_event.json`に登録するartifact pathはNode出力内の相対pathに限定し、重複、欠落、Hash不一致をRuntimeがcommit前に拒否します。Nodeの`parameters`にはCapability既定値とRun固有overrideを統合した実効値を保存します。Description NodeにはRuntimeがcache hitと新規計算をRun入力順に結合した全件payload、cache統計入りmanifest、`description_result.json`を作り、Vector Clusteringはこの契約を必須入力とします。

C012の確定Artifactには`selected_clusters_effective.csv`を含めます。全gridの`series_parameter_search.json`は途中判断用のRuntime stateであり、A009へ掲載しません。A009は7 Sectionの`standard_summary.html`、最終analysis unit別HTML、横長Endpoint Boxplotを出力します。個別HTMLはA003 Description ID付き相関表／上位3散布図と、A005 Local／Global OOF予測比較図を持ちます。Description／Clusteringの説明は該当Table直下の折りたたみ領域へ置き、構造クラスタリングのDescriptionは非該当とします。A007は構造由来Clusterでは登録済みKey構造だけ、vector由来Clusterでは個別Source ClusterのmembershipからMurcko／MCSを出力します。A008 Type-Iは`mmp_report_index.json`を作り、全体HTMLにanalysis unit別Target構造を4列、個別HTMLにTarget単独行とTargetへalignした折りたたみNeighbor galleryを出力します。MMP個別HTMLのSection 4は`表示内容`と`掲載範囲`を分け、詳細CSVリンクを末尾に置きます。A009は巨大なpair CSVではなくこのindexからTop 1 compoundと個別MMP HTMLへのlinkを構築します。I001は`interpretation.{json,md,html}`、On-demandは`result.md`、`result.html`、`artifact_manifest.json`を持ちます。

各Clustering primaryは全入力化合物を明示的に記録します。Cluster所属行は正の`membership_value`、未所属・invalid・最小Cluster未満は空の`cluster_id`と0の`membership_value`を用います。Runtimeは入力化合物の黙示的欠落、未知ID、無効なmembership、最小Cluster未満のactive Clusterを拒否してから単一のCluster Registryへ統合します。

Full auditはprimaryだけでなく、各`execution_event.json`に登録されたCSV・JSON・HTML・画像の存在とSHA-256、およびInterpretation 3形式のSHA-256を検証します。`quick` auditはState revision・入力・Node状態・DAG依存だけを確認し、Round完了判定には登録できません。

`conductor_control.json`と`runtime/dag.json`は一つの論理Stateです。更新途中のprocess停止に備え、Runtimeは一時的な`runtime/state_transaction.json`へ完全な組を先に記録します。残存transactionはRuntimeが正本として読み、旧process停止確認後の同一Round再開で通常Stateへ確定します。残存中は不整合なsnapshotを避けるためOn-demand作成を拒否します。実行packetは生成元Leaseのfingerprintを持ち、Lease失効・交代後の古いpacketは再実行できません。

Skill scratchは`runtime/scratch/`、Skill cacheは各Skillの`env/`内です。Pixi初期構築はSkill単位のbootstrap lockで直列化し、生存中の同一host ownerを経過時間だけで回収しません。`CONDUCTOR_modules/`にはRun結果を書きません。
