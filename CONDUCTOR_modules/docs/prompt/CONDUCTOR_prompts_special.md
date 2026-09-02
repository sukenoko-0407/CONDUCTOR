# CONDUCTOR 0.1.9 特別対応プロンプト集

- [Failed Node修復](#failed-node修復)
- [Wall Time後の継続](#wall-time後の継続)
- [MMP Type-III](#mmp-type-iii)
- [監査のみ](#監査のみ)

## Failed Node修復

```text
Run root <RUN_ROOT> のRuntimeが`FAILED_NODE_REPAIR_REQUIRED`を返しています。新Roundを開始せず、対象Nodeのdiagnosticとlog末尾だけを確認してください。原因を実装または入力契約で修正し、科学的scopeが同じなら同じNode IDを`retry-node`してください。別CLIを直接組み立てて代行しないでください。
```

## Wall Time後の継続

```text
Run root <RUN_ROOT> のPAUSED RoundへWall Time <MINUTES>を追加し、同じRoundをcontinueしてください。未完Nodeから再開し、新しいRoundを開始しないでください。
```

## MMP Type-III

```text
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> の全化合物についてMMP Type-IIIを明示実行してください。REQをprepareした後、専用の`run-mmp --role type-iii`を使用してください。1-cut、radius 0-2とし、Spotfire用の全詳細CSVと集約CSVを正本、SQLiteを派生成果物としてREQ directory内へ保存してください。通常analysis NodeやDAGは変更しないでください。
```

## 監査のみ

```text
Run root <RUN_ROOT> に対してRuntime `audit --mode full`を実行し、結果だけを報告してください。State/DAGの登録・変更、Round進行、Node実行は行わないでください。監査成果物が`state/<TIMESTAMP>/`へ保存されることは許容します。
```
