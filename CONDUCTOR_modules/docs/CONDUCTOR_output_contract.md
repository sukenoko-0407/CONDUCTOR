# CONDUCTOR 出力契約

## Run root

```text
results/CONDUCTOR/<project>/<run-id>/
├── state.json
├── summaries/
│   ├── state_summary.json
│   └── orchestrator_brief.json
├── description/<skill>/<node>/attempts/<attempt>/
├── clustering/<skill>/<node>/attempts/<attempt>/
├── analysis/<skill>/<node>/attempts/<attempt>/
├── interpretation/<skill>/<node>/attempts/<attempt>/
├── clusters/
├── indices/
├── rounds/
├── audit/<timestamp>/
├── state/<timestamp>/
└── concierge/CRQ######/
```

## 一般利用とCONDUCTOR利用

`--conductor`を付けない通常モードがdefaultです。通常モードは主成果物だけを`results/description/`、`results/clustering/`、`results/analysis/`等へ出します。CONDUCTOR利用であることが明示された場合だけ`--conductor`を付け、すべての科学Skillへproject、run、Round、Node、attemptを渡します。

CONDUCTORモードでは主成果物に加え、manifest、warnings、`execution_event.json`を生成します。Operatorは`operator_summary.json`と`operator_report.html`を必須とします。A005 Cluster surveyは、集約summaryに加えて適用可能な各Clusterを`NA######@ATT####/CL######`で参照できる短いsummary collectionを生成します。Interpretationの正式成果物はRuntime commit後の`interpretation.json`、`interpretation.md`、`interpretation.html`、`quality_report.json`です。

Vector Clusteringは通常／CONDUCTORの両モードで`cluster_membership.csv`、`cluster_summary.csv`、`clustering_diagnostics.csv`を生成します。CONDUCTORモードではさらに`distance_profile.json`を保存し、`clustering_manifest.json`へ`selection_status`、`quality_flags`、候補parameter、採用parameter、未所属理由内訳を記録します。`selection_status=no_usable_partition`は計算失敗ではなく、正式Clusterを登録しない診断付きnegative resultです。

## 不変条件

- 既存attempt directoryを黙って上書きしない。
- artifactはhashとsource Node／attemptを持つ。
- Description manifestは実際の`value_semantics`と`natural_metric`を記録する。
- binary fingerprintのClustering／SALI metricはTanimotoに固定する。
- Vector ClusteringのMetricはDescription表現から固定し、距離校正と候補選択にendpointを使わない。
- 5化合物未満のClusterへGlobal IDを割り当てない。
- `CONDUCTOR_modules/`へ解析結果を書かない。
- 各Roundは、保持Insightがゼロ件の場合も、品質検証済みInterpretationとその後のFull Auditなしに閉じない。

## Interpretation entity

正式なInterpretation entityはInsight `INS####`とNext Action `ACT####`だけです。Operator result自体が根拠の正本であり、Evidence entityを複製しません。各正式レポートの`result_catalog`は、引用したresult referenceから数値artifact、個別Operator HTML、scope、Description／Cluster provenanceへ辿るための読み取り専用索引です。Next Actionの状態は`open`／`closed`です。
