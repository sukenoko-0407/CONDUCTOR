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
今回の重点: <任意。省略時はorchestrator_brief.jsonの制御actionと科学判断候補に基づき自律選択>

最初にRuntime bootstrapで単一Writer leaseを取得してください。取得できなければStateを変更せず報告してください。Round終了前にInterpretation JSON／Markdown／HTMLとFull Auditを完成させてください。
```

Round番号はStateに対するguardである。不一致時は番号を自動補正せず、Stateを変更しない。

新しいClaude Code sessionでも、この短い指示とState pathでよい。Agentはまずboundedな`orchestrator_brief.json`を読み、必要な項目だけfocused queryする。

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

## 既存結果だけを詳しく確認する

```text
`cs-conductor-result-concierge` Skillを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>

確認したい内容: <具体的な質問>
注目ID: <Finding / Hypothesis / Question / Evidence / Node / Group ID、任意>

解析とStateを完全にFreezeし、既存artifactだけから説明・比較・再可視化してください。
追加解析案は実行せず、次Round用promptとして分離してください。
```

詳細は`CONDUCTOR_result_concierge_prompt.md`を参照する。

## 異常停止後に再開する

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: <ABSOLUTE_STATE_JSON_PATH>
Round: <RND####>

前Agentが途中停止した可能性があります。bootstrap後にFull Auditを行い、running Nodeのevent／artifactを照合してください。既存Nodeを別番号で作り直さず、必要な場合は同じNodeの新execution attemptとして再試行してください。
```

## 一般利用

```text
`<SKILL_NAME>`を一般モードで実行してください。
CONDUCTOR利用ではないため、`--conductor`を付けないでください。
Input: <PATH_OR_SMILES>
```

## 注意

- 同じinputでもendpointが異なる場合は別Runとする。
- 旧State、一般利用artifact、別Run artifactを通常Runtimeへ自動importしない。v4.3.0の一回限り移行は専用Migration Agentで別run rootへ行う。
- package hash差分があれば`package_change_gate`を確認し、人間確認前に計画・実行を進めない。承認後だけ`approve-package-change --approve`を使用する。
- 完全Evidenceを毎Roundすべて読まず、digestから必要なものだけを詳細確認する。
