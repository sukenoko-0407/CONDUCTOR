# CONDUCTOR 0.1.11 特別対応プロンプト集

- [Failed Node修復](#failed-node修復)
- [中断されたrunning Nodeの回収](#中断されたrunning-nodeの回収)
- [Wall Time後の継続](#wall-time後の継続)
- [人間判断による一時停止](#人間判断による一時停止)
- [任意NodeのWaive](#任意nodeのwaive)
- [Description Databaseの調査](#description-databaseの調査)
- [Description recordの限定無効化](#description-recordの限定無効化)
- [Description calculation versionの確認](#description-calculation-versionの確認)
- [MMP Mode II Database](#mmp-mode-ii-database)
- [監査のみ](#監査のみ)
- [Reportリンク・件数監査](#reportリンク件数監査)
- [MMP個別Report監査](#mmp個別report監査)
- [HPCからのReport持ち出し確認](#hpcからのreport持ち出し確認)
- [0.1.10基盤Regression smoke test](#0110基盤regression-smoke-test)
- [0.1.11 A008 Release smoke test](#0111-a008-release-smoke-test)

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

## Description calculation versionの確認

```text
CONDUCTOR 0.1.10に含まれる全Description Skillのcapability.jsonをread-onlyで検査してください。`calculation_version`が欠落せず、正の整数文字列であることを確認してください。Project <PROJECT_NAME> を指定した場合は、Description Databaseのrecordに保存されたcalculation versionも照合し、再利用可能・version mismatchの件数をcapabilityごとに示してください。Skill、Database、Runtime Stateは変更しないでください。
```

## MMP Mode II Database

```text
`cs-conductor-on-demand-analysis`を使い、Run root <RUN_ROOT> の全化合物についてA008 MMP Mode IIを明示実行してください。REQをprepareした後、`run-mmp --mode database`を使用してください。1-cut／2-cut、radius 0–2のTarget非依存canonical SQLiteと、pair detail、Transformation、Context、2-cut品質、Environmentの各CSVをREQ directory内へ保存してください。Target registryやTarget別Reportは作らず、通常analysis NodeやDAGは変更しないでください。
```

## 監査のみ

```text
Run root <RUN_ROOT> に対してRuntime `audit --mode full`を実行し、結果だけを報告してください。State/DAGの登録・変更、Round進行、Node実行は行わないでください。監査成果物が`state/<TIMESTAMP>/`へ保存されることは許容します。
```

## Reportリンク・件数監査

```text
Run root <RUN_ROOT> のA009 `report_audit.json`を確認し、Template、local link、canonical成果物との件数照合がすべてPASSか報告してください。続けてRuntime `audit --mode full`を実行しますが、Stateへのregister、Round進行、Report再生成は行わないでください。失敗時は壊れた参照または不一致項目と期待値・実値だけを示してください。LLM Vision、screenshot比較、目視判定は使用しないでください。
```

## MMP個別Report監査

```text
Run root <RUN_ROOT> の最新A008 Mode Iをread-onlyで監査してください。`mmp_report_audit.json`、Target別browser audit、`mmp_report_index.json`を確認し、Target registryとの件数、HTML／CSV／static Mapのlocal link、外部SVGが相対pathで存在して正しいSVG XMLであることを検証してください。Interactive HTMLではRelationship Mapの非重複、TransformationのAll／Direct／Transferred、N2T Direction、Target Connection、N-Cuts、Data Table、Evidence Guide、全data viewへのcut・品質filter適用をPlaywrightで確認してください。LLM Visionとscreenshot内容判定、Report再生成、Runtime State変更は行わないでください。
```

## HPCからのReport持ち出し確認

```text
Run root <RUN_ROOT> の確認対象Report directory <REPORT_DIR>を別PCへコピーできる単位としてread-onlyで検査してください。HTML単体ではなく、参照するCSV、JSON、SVG、assets directoryを含む相対path bundleであること、絶対path・file URI・欠損local linkがないことを確認し、コピーすべき最小のdirectory rootを示してください。Archive作成やファイル移動は行わないでください。
```

## 0.1.10基盤Regression smoke test

```text
CONDUCTOR 0.1.11の基盤Regression smoke testとして、0.1.10由来の共通機能を検証してください。順番は、package layout verification、catalog再生成後の差分確認、Schema negative test、Description Database cold/warm/partial-hit test、A003/C012/A009のcontract test、代表fixtureのRuntime Full Auditです。A008固有機能は次の「0.1.11 A008 Release smoke test」で別に検証してください。失敗時はその場で止め、失敗command、対象test、原因を短く報告してください。結果や一時environmentをGit管理対象へ追加しないでください。
```

## 0.1.11 A008 Release smoke test

```text
CONDUCTOR A008 0.1.11のrelease smoke testを実行してください。Mode II Database構築と監査、同Databaseをread-only再利用したMode I、Global Top 1＋analysis unit Top 1の重複除去、1-cut／2-cut分離、Direct／Transferred、signed `ΔN2T`、Transformation横断View、Target Connection分類、最大Core集約、Target HTMLのTemplate・local link・件数・外部SVG XML監査、PlaywrightによるDOM／bounding-box／click／全data view filter試験、A009へのstatic SVGだけの接続を確認してください。LLM Visionとscreenshot内容判定は使用しないでください。生成結果はGit管理対象へ追加しないでください。
```
