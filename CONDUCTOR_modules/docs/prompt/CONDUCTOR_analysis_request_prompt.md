# CONDUCTOR解析依頼プロンプト

Claude Codeを対象Projectのrootから起動し、以下のテンプレートを必要に応じて編集して使用する。

同じInput、endpoint、`higher_is_better`に対して解析の完全性を段階的に高める場合、2回目以降は原則として同じCONDUCTOR runと`state.json`を継続する。ここでは一回の人間確認と追加探索のまとまりを「解析Round」と呼び、CONDUCTORのrun IDとは区別する。Input内容、endpoint、方向性が変わる場合、または独立した再現実験として比較したい場合だけ新しいrunを作る。

## 新しいCONDUCTOR Runを開始する

```text
このProjectに導入されている `cs-conductor-orchestrator` Agentを使用して、
CONDUCTORとしてSAR解析を開始してください。

解析対象は以下のCSVだけです。
- Input CSV: <INPUT_CSV_PATH>
- Compound ID列: <COMPOUND_ID_COLUMN>
- SMILES列: <SMILES_COLUMN>
- Endpoint列: <ENDPOINT_COLUMN>
- higher_is_better: <true または false>

Run設定:
- Project名: <PROJECT_NAME>
- 並列実行数: <PARALLEL_LIMIT>
- 分子標準化状況: <例: 人間により事前標準化済み>

`CONDUCTOR_modules/docs/CONDUCTOR_v4_policy.md`、
`CONDUCTOR_modules/docs/CONDUCTOR_v4_design_spec.md`、
`CONDUCTOR_modules/catalog/catalog.json`
を読んでから処理を開始してください。

初手はCatalogで定められた広域解析プロファイルを省略せず実行してください。
各解析Skillは必ずCONDUCTORモード、つまり `--conductor` を付けて実行し、
State DAGを通じて管理してください。

指定したInput CSVとCONDUCTORの管理ファイル以外については、
解析上の依存関係が明示されていない限り探索対象に含めないでください。

人間の承認が必要な高コスト処理に到達した場合は、
目的、期待される情報、計算資源、代替手段を説明して停止してください。

今回の停止時には、run rootの `session_handoff.md` を
`CONDUCTOR_modules/docs/prompt/CONDUCTOR_session_handoff_template.md`に沿って作成または更新してください。
```

## 2回目以降の解析Roundを実行する

前回結果を踏まえて、同じrunへ追加解析を積み重ねる場合に使用する。

```text
`cs-conductor-orchestrator` Agentを使用して、次のCONDUCTOR runに対する
第<ROUND_NUMBER>回の解析Roundを実行してください。

State:
<STATE_JSON_PATH>

この解析は前回までの続きです。新しいrunやrun IDを作らず、既存のState DAG、
Group ID、evidence graph、Interpretation履歴、exploration ledgerを引き継いでください。

今回の人間からの指示:
<例: MCS由来GroupとMorgan空間で生じるCliffの関係を優先して検討する>

今回追加で許容する資源:
- 追加解析Round数: <ADDITIONAL_ITERATIONS>
- 追加node数: <ADDITIONAL_NODES>
- 追加walltime: <ADDITIONAL_WALLTIME_MINUTES>分
- 並列実行数: <PARALLEL_LIMIT>

最初に `state status` を実行し、完了node、未完了node、失敗node、coverage gap、
既存のanalysis signature、exploration budgetの累積消費量を確認してください。
既存budgetを変更する場合は、消費済み量を無視してresetせず、今回の追加許容量を
反映した新しい累積上限として設定してください。

最新および過去のInterpretation、positive/negative evidence、未解決矛盾、
discard済み領域を確認し、完了済みの同一解析を繰り返さないでください。
今回の指示に沿って追加branchを計画し、各注目候補について反証探索を含め、
追加結果を新しいInterpretation nodeで既存結果と比較してください。

停止時にはrun rootの `session_handoff.md` を更新し、今回の人間指示、実行内容、
新しい発見、反証結果、未解決事項、次回候補、主要artifact pathを記録してください。
```

## 新しいClaude Codeセッションで解析Roundを継続する

前回と異なるClaude Codeセッションから同じrunを引き継ぐ場合に使用する。

```text
これは既存CONDUCTOR runの継続です。
`cs-conductor-orchestrator` Agentを使用して、第<ROUND_NUMBER>回の解析Roundを実行してください。

State:
<STATE_JSON_PATH>

Session handoff:
<SESSION_HANDOFF_PATH>

新しいrunは作成しないでください。まずPolicy、Design、Catalogを読み、次に
`state.json`と`state status`で実行状態を復元してください。その後、
`session_handoff.md`、最新の`interpretation.json`と`interpretation.md`、
関連する`evidence.json`、未処理の`exploration_plan.json`を確認してください。

handoffは案内索引であり正本ではありません。handoffに記録されたState更新時刻が
現在の`state.json`より古い場合は、Stateとartifactを優先して内容を補正してください。
Groupの詳細が必要なときだけ`group_registry.csv`と必要なGroup列を確認してください。

今回の人間からの指示:
<今回優先する問い、対象Group、Description、Operator、避ける領域など>

今回追加で許容する資源:
- 追加解析Round数: <ADDITIONAL_ITERATIONS>
- 追加node数: <ADDITIONAL_NODES>
- 追加walltime: <ADDITIONAL_WALLTIME_MINUTES>分
- 並列実行数: <PARALLEL_LIMIT>

完了済みの同一analysis signatureを再実行せず、過去の結果と今回の追加結果を
区別して記録してください。停止時には`session_handoff.md`を更新してください。
```

## 既存runで部分解析だけを追加する

人間がDescription、Grouping、Operator、Interpretationの一部だけを指定する場合に使用する。CONDUCTOR run内では専門Skillを直接指定せず、Orchestratorを通じてState管理する。

```text
`cs-conductor-orchestrator` Agentを使用し、次の既存CONDUCTOR runへ
人間指定の部分解析を追加してください。

State:
<STATE_JSON_PATH>

追加したい処理:
- 段階: <Description / Grouping / Operator / Interpretation>
- 目的: <この処理で確認したいこと>
- 希望する手法またはCapability: <指定があれば記載>
- 対象Group・Description・既存Node: <指定があれば記載>
- parameter: <指定があれば記載>

個別SkillをState外で直接実行しないでください。CatalogからCapabilityを決め、必要な上流Nodeを確認し、
`state add --human-request --reason ...`で新しいNodeを登録してください。
Stateが返したNode ID、input binding、output directoryを使ってstart・実行・event recordまで行ってください。
既存の同一Description、Grouping、Operator signatureは再実行せず、利用可能なartifactを再利用してください。
```

## Interpretationだけを再実行する

```text
`cs-conductor-orchestrator` Agentを使用して、次の既存CONDUCTOR runの
Interpretationだけを新しいRoundとして実行してください。

State:
<STATE_JSON_PATH>

今回の解釈で重視する観点:
<前回から変更・追加する問い、比較対象、注目Groupなど>

新しいrunは作成せず、Capability `I001`を新しいInterpretation NodeとしてStateへ登録してください。
既存の最新Interpretation Nodeをread-onlyの`previous_interpretation`として引き継ぎ、
今回対象とするsucceeded Operator NodeをEvidence依存として指定してください。
最初のInterpretationが`I001`なら、新しいNodeは`I002`として作成してください。
`I001`の既存directoryやartifactは上書きしないでください。

runnerの機械下書きで終了せず、専用`cs-conductor-interpreter` Agentによる意味解釈と
品質gateを完了し、`agent_interpreted`のinterpretation.json、Markdown、HTMLを生成してから
execution eventをStateへ記録してください。
```

## 中断したCONDUCTOR処理を再開する

```text
`cs-conductor-orchestrator` Agentを使用して、
次のCONDUCTOR runを再開してください。

State:
<STATE_JSON_PATH>

新しいrunは作成しないでください。
最初にStateのstatus、未完了node、失敗node、approval待ちnodeを確認し、
既存のDAGとrun IDを維持したまま処理を継続してください。

並列実行数は<PARALLEL_LIMIT>です。
高コスト処理には既存の承認Policyを適用してください。

処理が再び停止する時点で`session_handoff.md`を更新してください。
```

## 個別Skillを一般モードで利用する

CONDUCTOR runを作らず、単一の機能だけを利用するときのテンプレートである。

```text
これはCONDUCTOR runではありません。
`<SKILL_NAME>` Skillを一般モードで使用し、
<INPUT_PATHまたはSMILES>を処理してください。

`--conductor`は付けないでください。
```

## 指定時の要点

- CONDUCTOR全体を使う場合は、`cs-conductor-orchestrator`と「CONDUCTORとして実行」を明示する。
- Input CSV、endpoint、`higher_is_better`、並列実行数を指定する。
- 同じInputとendpointの追加探索では同じrun IDとStateを継続し、解析Roundだけを進める。
- 新しいClaude Codeセッションでは、State、handoff、Interpretation、関連evidenceの順に引き継ぐ。
- 追加予算は既存の消費量を消去せず、累積上限へ換算して管理する。
- 部分解析もOrchestratorから`human_directed` Nodeとして登録し、State外で専門Skillを直接起動しない。
- Interpretation再実行はCapability `I001`を新しい`I###` Nodeとして登録し、前回reportを上書きしない。
- Project内に無関係なファイルがある場合は、解析対象と探索範囲を明示する。
- 一般利用では「CONDUCTOR runではない」と明記し、`--conductor`を付けない。
