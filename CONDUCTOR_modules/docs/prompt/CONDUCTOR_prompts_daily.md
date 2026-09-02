# CONDUCTOR 0.1.9 日常プロンプト集

- [新規Run](#新規run)
- [同じRoundの再開](#同じroundの再開)
- [Series数超過の承認](#series数超過の承認)
- [Series条件の明示変更](#series条件の明示変更)
- [Round結果の確認後](#round結果の確認後)
- [On-demand解析](#on-demand解析)
- [MMP Type-II](#mmp-type-ii)

## 新規Run

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用し、CONDUCTOR 0.1.9の新規Runを開始してください。
入力CSV: <ABSOLUTE_CSV_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
Endpoint列: <ENDPOINT_COLUMN>
higher_is_better: <true|false>
Project: <PROJECT_NAME>
Run root: <NEW_EMPTY_RUN_ROOT>
並列Node数: <N>
Available CPU cores: <N、未指定なら8>
Wall Time: <MINUTES>
min_ff_evaluate: <未指定なら10>
Leiden resolution: <未指定なら1.0>

全Descriptionと全標準Clusteringを基本計算し、A001/A002、C012、A003-A009、軽量Interpretation、Full Auditまで同じRoundで進めてください。高コストDescriptionは一括承認を求めてください。新しいRoundを自動開始しないでください。
```

## 同じRoundの再開

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用してください。
Run root: <RUN_ROOT>
現在のRuntime required_actionを確認し、PAUSEDまたはACTIVEの同じRoundだけを再開してください。Failed Nodeはdiagnosticを示し、実装修正後は同じNode IDをretryしてください。新Roundは開始しないでください。
```

## analysis unit数超過の承認

```text
Run root <RUN_ROOT> のC012成果物について、採用Seriesとfallback Clusterを合わせた実解析単位数が24を超えたことを確認しました。accepted Series数、棄却Series数、fallback Cluster数も示してください。現在のmin_ff_evaluateとLeiden resolutionを変更せず、同じRoundの定型解析へ進むことを承認します。`approve-series`を使用してください。
```

## Series条件の明示変更

```text
Run root <RUN_ROOT> の同じACTIVE Roundで、定型解析を計画する前にSeries条件だけを再評価してください。
min_ff_evaluate: <5以上の整数>
Leiden resolution: <正の数>
変更理由: <HUMAN_REASON>

`revise-series`を使い、新しいA001、A002、C012 Nodeとして登録してください。成功済みDescriptionとC001-C010は再計算せず、新Roundを開始しないでください。Runtimeが値を自動調整してはいけません。
```

## Round結果の確認後

```text
Run root <RUN_ROOT> のA009 `standard_summary.html`とSeries詳細Reportを確認しました。以下の人間所見は通常Stateへ直接書き込まず、必要な確認をOn-demand解析として実施してください。
重視点: <FINDING/SERIES/CLUSTER/COMPOUNDと依頼>
```

## On-demand解析

```text
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> に対する次の依頼を処理してください。
依頼: <QUESTION_OR_ANALYSIS>
参照対象: <EXPLICIT_ARTIFACT_OR_ID>
通常DAG、Round、既存成果物は変更せず、`on_demand/REQ######/`だけへMarkdown/HTMLと必要な図・表を保存してください。
```

## MMP Type-II

```text
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> のcompound_id `<ID>`を中心としたMMP Type-IIを実施してください。複数の上位化合物を調べる場合は、対象IDごとに`--target-compound-id <ID>`を繰り返してください。REQをprepareした後、専用の`run-mmp --role type-ii --target-compound-id <ID>`を使用してください。再利用する同一RunのType-III `mmp_database.sqlite`を人間が明示した場合だけ`--mmp-database <PATH>`を追加してください。1-cut、radius 0-2とし、観測MMPをありのまま示してください。near-core参考はTanimoto>=0.70かつ両側MCS coverage>=0.60を満たす場合だけ別枠で表示してください。
```
