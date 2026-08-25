# CONDUCTOR 0.2.0 output contract

```text
<run_root>/
├── conductor_control.json
├── runtime/
│   ├── input.csv
│   ├── dag_snapshot.json
│   ├── event_ledger.jsonl
│   ├── working_set.json
│   ├── result_index.jsonl
│   ├── review_bundle_index.jsonl
│   ├── result_assessment_index.jsonl
│   ├── insight_index.jsonl
│   ├── cluster_registry.jsonl
│   ├── cluster_membership.csv
│   ├── logs/
│   └── scratch/
│       ├── packets/PKT.../{execution_packet.json,worker_status.json,worker.log}
│       └── RND####/N######/ATT####/
│           ├── execution_request.json
│           ├── process.json / failure_packet.json / tmp/
│           └── skill_output/  # Skill専用。起動前は存在しない
├── rounds/RND####/{round_contract.json,result_assessments.csv,screening_summary.json,round_outcome.json}
├── description/N######/{features.csv,result.json}
├── clustering/N######/{membership.csv,result.json}
├── analysis/N######/{result.*,result.json,result_card.json,report.html,detail.html}
├── interpretation/N######/{interpretation.json,interpretation.md,interpretation.html,quality_report.json}
├── audit/<timestamp>/
├── state/<timestamp>/
├── concierge/REQ######/
└── mmp_interpretation/MMPREQ######/
```

`conductor_control.json`が小さい運用正本です。DAG snapshotとLedgerはRuntime管理の詳細・監査情報であり、通常再開時にLLMが全文を読む対象ではありません。

`runtime/input.csv`はRun開始時に作る変更不能なcanonical copyです。既存ID列は`compound_id`へ写し、ID列がなければ`CMP######`を一度だけ付与します。元CSVは変更しません。

## Execution Requestとscratch

`execution_request.json`はNodeごとの固定実行契約です。identity、入力Artifact hash、列、endpoint、scope、parameter、CPU資源、出力先を持ちます。Execution packetはRequest hash、command hash、Run／Round、Control revision、lease hash、有効期限へ署名されます。`worker_status.json`はPacketのclaim、Worker PID、terminal結果を示す再接続用補助記録であり、Control／DAG／Ledgerに代わるState正本ではありません。

packet実行時、RuntimeはRequestに含まれる全入力の`path`と`sha256`、上流成果物の`result_path`と`result_sha256`を現在のfile内容へ再照合します。canonical input以外のArtifactはRun Root内に限定し、不一致・欠損・Run Root外参照はSkill起動前に拒否します。

Attempt直下はRuntime管理専用です。科学Skillは未作成の`skill_output/`だけへ書きます。実行成功後、Runtime Workerがschema、identity、hash、scope、科学的不変条件を検証し、正本directoryへatomic promotionします。scratch、packet、worker statusはState正本ではありません。

## Canonical Result

`result.json`は機械的stage結果、`result_card.json`はbounded navigation用です。Canonical Resultは`document_type`と`schema_version`で識別します。Description／Clustering／Analysisのstage Resultは各文書型の`1.0.0`、Result Cardは`2.0.0`契約です。これらはCONDUCTOR package versionとは別のschema versionです。

`result_card.json`と`runtime/result_index.jsonl`の`artifact_links`は、すべてRun RootからのPOSIX形式相対pathです。絶対path、`..`、存在しないfile、Run Root外への解決を許可しません。同一pathへNode出力directoryを二重に前置しません。

Operatorの`analysis_subject`がscope mode、Cluster ID、Description／Clustering source、population／endpoint-valid／analyzed count、compound-set hashを確定します。Interpretationはこれを上書きできません。

## Review Bundleと一次評価

`runtime/review_bundle_index.jsonl`はGlobal、Global–Local、sibling Cluster比較のappend-only索引です。Bundleはcomparison family、対象・比較Result、typed comparison table、sample support、comparator validity、Cluster overlapを保持します。sibling Bundleには一致するGlobal baselineを可能な限り含め、favorable値のsibling順位、中央値からの偏差、分散をRuntimeが決定論的に付与します。Localで必須Global comparatorがない場合は`awaiting_comparator`となります。

`runtime/result_assessment_index.jsonl`はBundleごとの0～3絶対評価軸、分離した信頼性、Runtime確定Candidate class、短い理由、支持・反証Resultを保持します。軸の単純合計は保存しません。`rounds/RND####/result_assessments.csv`は再生成可能な人間向けviewです。

`screening_summary.json`はBundle件数、Candidate class、Operator構成、掲載候補pointerだけを持つcompact handoffです。`report_mode=screening`ではこれが正式Interpretationの代わりとなり、`report_mode=full`では`design_lead`と`contextual_anomaly`から最大50 Resultを選抜します。

## MMP A014

Global buildの正本は次です。

```text
analysis/N######/
├── mmp_database.sqlite          # 正規化されたread-only再利用DB
├── mmp_pair_detail.csv          # Spotfire用の全詳細行
├── mmp_storage_profile.json
├── pair_summary.csv
├── transform_summary.csv
├── core_summary.csv
├── transform_core_summary.csv
├── context_summary.csv
├── coverage_summary.csv
├── compound_coverage.csv
└── mmp_reference_cards.{jsonl,csv}
```

Native mmpdb work DBとParquetは正本として残しません。SQLiteはID参照で正規化し、反復SMILES／SMARTS文字列と派生Summaryの重複を避けます。全科学行は`mmp_pair_detail.csv`に保持します。

A014 Skill自体は明示実行用の`local-screen`／`local-detail`も保持しますが、標準Runtime PlannerはGlobal buildだけを正規Nodeとして計画します。人間起動の`cs-analysis-interpret-mmp`はGlobal DBと`runtime/cluster_membership.csv`をread-onlyに集計し、`mmp_interpretation/MMPREQ######/`へGlobal–Local比較CSV、Markdown、HTMLを出力します。この補助directoryはDAG、Result Index、Insight Indexへ登録されません。

## Reportとpackage

各Operator reportはscope、Cluster、Clustering手法、Cluster生成Description、解析Description、Endpoint、sample count、metricを共通fact panelに表示します。Interpretation HTML／Markdownは同じResult Cardを正本とし、Runtimeがscope、数値、日本語本文、参照先を検査します。

`CONDUCTOR_modules/`へRun結果は書きません。`.claude/skills/<skill>/env/`だけはPixi環境とcacheの書込先です。科学成果物はすべてRun Rootにあります。
