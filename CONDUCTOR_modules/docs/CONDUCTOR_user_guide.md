# CONDUCTOR 利用ガイド

## 必須入力

- compound ID、SMILES、一つのendpoint列を持つCSV
- endpoint列名
- `higher_is_better`の真偽
- project名、並列上限
- 初回の高コスト基本計算bundleに対する一括承認

分子標準化、IDとSMILESの同一性、単位・測定条件の妥当性は人間の責務です。重複IDはerror、invalid SMILESは行を保持してwarningとします。

## 初回Roundの依頼例

```text
cs-conductor-orchestrator Agentを使ってCONDUCTOR解析を開始してください。
入力CSV: <absolute path>
endpoint: <column>
higher_is_better: true/false
project: <name>
parallel_limit: <number>
Wall Time: <minutes or hours>

基本計算、初期探索、Interpretation、Full Auditまでを一つのRoundとして完遂してください。
CONDUCTOR_modules/catalog/analysis_profile.jsonとPolicyに従い、state.jsonを直接編集しないでください。
```

## Round 2以降

```text
cs-conductor-orchestrator Agentを使い、次のCONDUCTOR Roundを実行してください。
state.json: <absolute path>
Round No: <next number>
parallel_limit: <number>
Wall Time: <minutes or hours>

前RoundのInsight、open Next Action、未実施coverageを確認し、追加探索と有望領域の深掘りを組み合わせ、最後にInterpretationとFull Auditまで完遂してください。
```

人間の見解を付ける場合は、`INS####`、`ACT####`、`CL######`、Operator result referenceを明記し、「重視」「反証したい」「ACTをclosedにしたい」「このscopeを比較したい」を追記します。具体的な指示がなくてもStateから継続できます。

## 新しいClaude Code sessionで再開

新sessionには`state.json`の絶対pathと次Round番号を伝えれば、Runtime bootstrap、brief、bounded queryから状況を再構築できます。多数の過去Markdownをプロンプトへ貼る必要はありません。leaseが残っている場合は勝手にtakeoverせず、監査と人間確認を行います。

## 既存結果を詳しく見る

解析を進めず、既存結果の解説やFigureだけが必要なら`cs-conductor-result-concierge`を指定します。Conciergeはactive Roundやlive leaseのないfrozen Runでだけ使い、`run_root/concierge/CRQ######/`以外を書き換えません。

StateのDAG図だけが必要なら、対象Stateを明示して`cs-conductor-state-report`を依頼します。出力は`run_root/state/<timestamp>/`です。

## 部分実行

特定Description、Clustering、Operator、Interpretationを追加する場合も、OrchestratorまたはRuntimeを介してDAG Nodeとして登録します。Skill出力だけをrun rootへ手置きしないでください。一般利用として独立実行する場合は`--conductor`を付けません。
