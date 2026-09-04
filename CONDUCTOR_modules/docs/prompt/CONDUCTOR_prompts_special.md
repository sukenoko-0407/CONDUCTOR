# CONDUCTOR 0.1.10 特別対応プロンプト集

- [Failed Node修復](#failed-node修復)
- [中断されたrunning Nodeの回収](#中断されたrunning-nodeの回収)
- [Wall Time後の継続](#wall-time後の継続)
- [人間判断による一時停止](#人間判断による一時停止)
- [任意NodeのWaive](#任意nodeのwaive)
- [Description Databaseの調査](#description-databaseの調査)
- [Description recordの限定無効化](#description-recordの限定無効化)
- [MMP Type-III](#mmp-type-iii)
- [監査のみ](#監査のみ)

## Failed Node修復

```text
Run root <RUN_ROOT> のRuntimeが`FAILED_NODE_REPAIR_REQUIRED`を返しています。新Roundを開始せず、対象Nodeのdiagnosticとlog末尾だけを確認してください。原因を実装または入力要素で修正し、科学的scopeが同じなら同じNode IDを`retry-node`してください。別CLIを直接組み立てて代行しないでください。
```

## 中断されたrunning Nodeの回収

```text
Run root <RUN_ROOT> にrunningのまま残ったNodeがあります。旧Runtime processが存在しないことを人間が確認済みです。対象Node IDと旧host情報を示したうえで、`resume-round --confirm-interrupted-running`により同じRoundを回収してください。旧attemptを`INTERRUPTED_ATTEMPT`として記録し、同じNode IDで再試行してください。二重実行は行わないでください。
```

## Wall Time後の継続

```text
Run root <RUN_ROOT> のPAUSED RoundへWall Time <MINUTES>を追加し、同じRoundをcontinueしてください。未完Nodeから再開し、新しいRoundを開始しないでください。
```

## 人間判断による一時停止

```text
Run root <RUN_ROOT> のACTIVE Roundを、安全なNode境界で一時停止してください。理由は「<HUMAN_REASON>」です。`pause-round`を使ってLeaseを解放し、実行中Nodeが残っていないこととPAUSEDになったことを報告してください。成果物は削除しないでください。
```

## 任意NodeのWaive

```text
Run root <RUN_ROOT> の失敗Node <NODE_ID> は任意解析であり、今回は人間判断で省略します。理由は「<HUMAN_REASON>」です。required control/report Nodeでないことを確認してから`waive-node`を使用し、影響を受ける下流Nodeとレポート上の欠落を報告してください。
```

## Description Databaseの調査

```text
Project <PROJECT_NAME> のDescription Databaseについて、capability <CAPABILITY_ID>を`description-cache-inspect`で調査してください。compound IDを限定する場合は<ID>です。record件数、calculation version、configuration signature、正常・invalid・一時失敗の内訳だけを報告し、DatabaseやRun Stateは変更しないでください。
```

## Description recordの限定無効化

```text
Project <PROJECT_NAME> のDescription Databaseについて、capability <CAPABILITY_ID>、compound ID <ID>のrecordだけを無効化してください。理由は「<HUMAN_REASON>」、operatorは「<OPERATOR_NAME>」です。まず`description-cache-inspect`で対象を特定し、対象ID以外を変更しないことを確認してから`description-cache-invalidate`を実行してください。ID/SMILES不一致のfail-fastは迂回しないでください。
```

## MMP Type-III

```text
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> の全化合物についてMMP Type-IIIを明示実行してください。REQをprepareした後、専用の`run-mmp --role type-iii`を使用してください。1-cut、radius 0-2とし、Spotfire用の全詳細CSVと集約CSV、正規化SQLiteを派生成果物としてREQ directory内へ保存してください。通常analysis NodeやDAGは変更しないでください。
```

## 監査のみ

```text
Run root <RUN_ROOT> に対してRuntime `audit --mode full`を実行し、結果だけを報告してください。State/DAGの登録・変更、Round進行、Node実行は行わないでください。監査成果物が`state/<TIMESTAMP>/`へ保存されることは許容します。
```
