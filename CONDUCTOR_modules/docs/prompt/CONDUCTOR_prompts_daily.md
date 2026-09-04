# CONDUCTOR 0.1.10 日常プロンプト集

- [状態だけを確認](#状態だけを確認)
- [新規Run](#新規run)
- [同じProjectで別EndpointのRun](#同じprojectで別endpointのrun)
- [同じRoundの再開](#同じroundの再開)
- [analysis unit数超過の承認](#analysis-unit数超過の承認)
- [Series条件Matrixの選択](#series条件matrixの選択)
- [Series条件の明示変更](#series条件の明示変更)
- [Round結果の追加確認](#round結果の追加確認)
- [Round完走後の終了処理](#round完走後の終了処理)
- [On-demand解析](#on-demand解析)
- [MMP Type-II](#mmp-type-ii)

## 状態だけを確認

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用してください。
Run root: <RUN_ROOT>
Runtimeの`query`だけを実行し、現在のRound状態、required_action、進行中・失敗・未実施Nodeの件数を短く報告してください。Roundの再開、Node実行、State変更は行わないでください。
```

## 新規Run

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用し、CONDUCTOR 0.1.10の新規Runを開始してください。
入力CSV: <ABSOLUTE_CSV_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
Endpoint列: <ENDPOINT_COLUMN>
higher_is_better: <true|false>
Project（Program名）: <PROJECT_NAME>
Run root: <NEW_EMPTY_RUN_ROOT>
並列Node数: <N>
Available CPU cores: <N、未指定なら8>
Wall Time: <MINUTES>
min_ff_evaluate: <未指定なら10>
Leiden resolution: <未指定なら1.0>

全Descriptionと全標準Clusteringを基本計算し、C001/A002、C012、A003-A009、軽量Interpretation、Full Auditまで同じRoundで進めてください。Descriptionは同じProjectのDatabaseを再利用し、missだけを計算してください。Descriptionごとの高コスト承認は求めません。新しいRoundを自動開始しないでください。
```

## 同じProjectで別EndpointのRun

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用し、既存ProjectのDescription Databaseを再利用して別Endpointの新規Runを開始してください。
Project（Program名）: <EXISTING_PROJECT_NAME>
入力CSV: <ABSOLUTE_CSV_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
新しいEndpoint列: <ENDPOINT_COLUMN>
higher_is_better: <true|false>
Run root: <NEW_EMPTY_RUN_ROOT>
並列Node数: <N>
Wall Time: <MINUTES>

compound IDとcanonical SMILESの不一致はfail-fastとしてください。計算signatureが一致するcache hitは再利用し、missだけを追加計算・登録してください。終了時にDescriptionごとのhit / miss / registered件数を報告してください。
```

## 同じRoundの再開

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用してください。
Run root: <RUN_ROOT>
現在のRuntime required_actionを確認し、PAUSEDまたはACTIVEの同じRoundだけを再開してください。Failed Nodeはdiagnosticを示し、実装修正後に同じNode IDをretryしてください。新しいRoundは開始しないでください。
```

## analysis unit数超過の承認

```text
Run root <RUN_ROOT> のC012成果物について、最終analysis unit数が25〜100件であることを確認しました。Accepted Series数、単独Series数、fallback Cluster数も示してください。現在のmin_ff_evaluateとLeiden resolutionを変えず、同じRoundの定型解析へ進むことを承認します。`approve-series`を使用してください。
```

## Series条件Matrixの選択

```text
Run root <RUN_ROOT> のRuntimeが返したSeries条件MatrixをSession内に表示してください。行はmin_ff_evaluate、列はLeiden resolutionとし、各cellを「最終unit数 / Cluster coverage / Compound coverage / fallback数」で示してください。HTMLや図は作りません。
確認後、min_ff_evaluate=<10|15|20|25|30>、Leiden resolution=<1.0|1.25|1.5|2.0|2.5|3.0>を選びます。`select-series-configuration`で同じRoundへ反映してください。選択cellが25〜100件なら、この選択を件数超過の承認としても記録してください。
```

## Series条件の明示変更

```text
Run root <RUN_ROOT> の同じACTIVE Roundで、定型解析を計画する前にSeries条件だけを再評価してください。
min_ff_evaluate: <5以上の整数>
Leiden resolution: <正の数>
変更理由: <HUMAN_REASON>

`revise-series`を使い、新しいC012 Nodeとして登録してください。成功済みDescription、C001-C010、A001/A002は再計算せず、新Roundを開始しないでください。再計算後も24件を超える場合は、再度私へ確認してください。
```

## Round結果の追加確認

```text
Run root <RUN_ROOT> のA009 `standard_summary.html`と個別Reportを確認しました。通常Stateへ直接書き込まず、次の疑問をOn-demand解析として実行してください。
質問: <FINDING/SERIES/CLUSTER/COMPOUNDと依頼内容>
```

## Round完走後の終了処理

```text
`cs-conductor-orchestrator` SkillをMain Agentで使用してください。
Run root: <RUN_ROOT>
A009の全体・個別レポートとInterpretationを人間が確認済みです。まずRuntime `query`でrequired_actionが`AWAIT_HUMAN_REVIEW`であること、Full AuditがPASSであることを確認してください。問題がなければ`accept-round --note "<HUMAN_REVIEW_NOTE>"`で現在のRoundをCLOSEDにし、最終Stateと主要レポートへのパスを短く報告してください。新しいRoundやOn-demand解析は開始しないでください。
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
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> のcompound_id `<ID>`を中心としたMMP Type-IIを実行してください。複数の上位化合物を調べる場合は、対象IDごとに`--target-compound-id <ID>`を繰り返してください。REQをprepareした後、専用の`run-mmp --role type-ii --target-compound-id <ID>`を使用してください。再利用する同一RunのType-III `mmp_database.sqlite`を人間が明示した場合だけ`--mmp-database <PATH>`を追加してください。1-cut、radius 0-2とし、観測MMPをありのまま示してください。Near-core参照はTanimoto>=0.70かつ両側MCS coverage>=0.60を満たす場合だけ別枠で表示してください。
```
