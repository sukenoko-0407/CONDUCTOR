# CONDUCTOR 0.1.3 output contract

```text
<run_root>/
├── conductor_control.json
├── runtime/
│   ├── dag_snapshot.json
│   ├── input.csv
│   ├── event_ledger.jsonl
│   ├── working_set.json
│   ├── result_index.jsonl
│   ├── insight_index.jsonl
│   ├── cluster_registry.jsonl
│   ├── cluster_membership.csv
│   ├── logs/
│   └── scratch/
│       ├── packets/PKT.../execution_packet.json
│       └── RND####/N######/ATT####/
├── rounds/RND####/
├── description/N######/{features.csv,result.json}
├── clustering/N######/{membership.csv,result.json}
├── analysis/N######/{result.*,result.json,result_card.json,report.html,detail.html}
├── interpretation/N######/{interpretation.json,interpretation.md,interpretation.html,quality_report.json}
├── audit/<timestamp>/
├── state/<timestamp>/
└── concierge/REQ######/
```

Description、Clustering、Operator Skillの既存計算CLIは一般利用のため維持します。CONDUCTORではそれらの詳細manifestやwarningをRuntime scratchで検証し、Run Rootへは上記の最小正本だけを昇格します。

`runtime/scratch/packets/`のExecution packet、Node Attempt scratch、failure packetは制御用一時情報であり、新しいState正本ではありません。署名、Control revision、Action token、期限により一回の実行だけに結び付けられます。Main向けRuntime応答は16 KiB以下のcompact JSONとし、raw log、完全DAG、完全Auditはpointer先へ保持します。

`runtime/input.csv`はRun開始時に元CSVから作る変更不能なcanonical copyです。既存ID列は`compound_id`へ写し、ID列がなければ`CMP######`を一度だけ付与します。以後の全Skill、Cluster matrix、監査はこのcopyを参照し、元CSVは変更しません。

`result.json`は機械的なstage結果、`result_card.json`はbounded navigation用です。Operatorの`analysis_subject`がscope mode、Cluster ID、Description／Clustering source、population／endpoint-valid／analyzed countとcompound-set hashを確定します。Interpretationはこのfactを上書きできません。

Result Cardは生成時点の記録として不変です。人間がNode Reviewで結果を下流利用停止にした場合は、`dag_snapshot.json`のNode `result_quality`が現在値として優先され、Working Set、将来のInterpretation、`query result`に反映されます。科学artifact自体は削除しません。

各Operatorの`report.html`は、scope、Cluster、Clustering手法、Cluster生成Description、解析Description、Endpoint、sample count、metricを共通fact panelに表示します。InterpretationのHTML／Markdownは同じResult Cardを正本とし、Runtimeがscopeと数値の一致、日本語本文、参照先の存在をFull Audit前に検査します。

`CONDUCTOR_modules/`へRun結果は書き込みません。`.claude/skills/<skill>/env/`だけは共有Pixi環境とcacheの構築先として書き込み可能である必要があります。科学的Run成果物はすべてRun Root側にあり、Run停止中なら同じpackage versionのmodulesとSkill本体を差し替えられます。Skillをdirectoryごと差し替える場合は`env/`が再構築されますが、RunのNodeやArtifactには影響しません。
