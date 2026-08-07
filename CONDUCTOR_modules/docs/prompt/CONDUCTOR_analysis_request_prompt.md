# CONDUCTOR解析依頼プロンプト

## 新しいRunを開始する

```text
`cs-conductor-orchestrator` Agentを使用して、新しいCONDUCTOR Runを開始してください。

Input: <ABSOLUTE_INPUT_CSV_PATH>
Endpoint: <ENDPOINT_COLUMN>
Higher is better: <true|false>
Project: <PROJECT_NAME>
Parallel limit: <INTEGER>
Round envelope:
  walltime: <例 8 hours>
  max additional nodes: <INTEGER>
  max Interpretation iterations: <INTEGER>

Catalogで基本計算に指定された高コストDescriptionを含むbundleを一括承認します。
入力の分子標準化は実施済みであり、CONDUCTOR内では変更しないでください。
```

## Round 2以降

```text
`cs-conductor-orchestrator` Agentを使用して、既存CONDUCTOR Runの解析Round <RND####>を開始してください。
同Roundがactiveなら再開してください。

State: <ABSOLUTE_STATE_JSON_PATH>
今回の重点: <任意。省略時はmandatory coverage、active Question、coverage gap、前Roundのnext_round_briefに基づき自律選択>
```

Round番号はStateに対するguardである。不一致時は番号を自動補正せず、Stateを変更しない。

## Questionを選別する

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>
Round: <RND####>

Question decision:
- <Q####>: allow
- <Q####>: skip
- <Q####>: defer

skipしたQuestionは自動深掘りしないでください。新Evidenceにより再検討価値が生じた場合は、実行せずreopen recommendationだけを提示してください。
```

## 特定領域を深掘りする

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>
Round: <RND####>

重点対象: <Group ID / Finding ID / Hypothesis ID / Question ID / Node ID>
希望する視点: <任意>

既存Evidence、global comparator、sibling Group、異Description、反証候補を確認し、必要な比較bundleをStateへ登録して実行してください。
```

## Interpretationだけを再実行する

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>
Round: <RND####>

新しいOperator計算は行わず、次の視点で新しいInterpretation Nodeを作成してください。
重点: <任意>

既存Finding、Hypothesis、Question、RelationのRun内IDを引き継ぎ、同一entityの変更はrevisionとして記録してください。
```

## 人間指定の部分解析

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>
Round: <RND####>

追加解析: <具体的なDescription / Grouping / Operator / scope>
理由: <任意>
```

専門Skillを先に直接実行せず、OrchestratorがNodeと依存関係を予約してから実行する。

## State／DAGを可視化する

```text
`cs-conductor-state-report` Skillを使用して、次のStateだけをread-onlyで可視化してください。
State: <ABSOLUTE_STATE_JSON_PATH>
解析NodeとしてDAGへ登録しないでください。
```

## 一般利用

```text
`<SKILL_NAME>`を一般モードで実行してください。
CONDUCTOR利用ではないため、`--conductor`を付けないでください。
Input: <PATH_OR_SMILES>
```

## 注意

- 同じinputでもendpointが異なる場合は別Runとする。
- 旧State、一般利用artifact、別Run artifactを自動importしない。
- package hash差分があれば`package_change_gate`を確認し、人間確認前に計画・実行を進めない。承認後だけ`approve-package-change --approve`を使用する。
- 完全Evidenceを毎Roundすべて読まず、digestから必要なものだけを詳細確認する。
