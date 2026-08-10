# CONDUCTOR 解析依頼プロンプト

## Round 1

```text
cs-conductor-orchestrator Agentを使ってCONDUCTOR解析を開始してください。

入力CSV: <absolute path>
endpoint: <column name>
higher_is_better: <true/false>
project: <project name>
parallel_limit: <number>
Wall Time: <time>

CONDUCTOR_modules/catalog/analysis_profile.jsonとPolicyに従い、基本計算、初期探索、Interpretation、Full Auditまでを一つのRoundとして完遂してください。StateはRuntimeだけを介して更新してください。
```

## Round 2以降：指示なし

```text
cs-conductor-orchestrator Agentを使い、次のCONDUCTOR Roundを実行してください。

state.json: <absolute path>
Round No: <number>
parallel_limit: <number>
Wall Time: <time>

過去のInsight、open Next Action、未実施coverageを短いbriefとbounded queryから把握し、偏りの少ない追加探索と有望領域の深掘りを行ってください。最後に現RoundのInterpretationとFull Auditまで完遂してください。
```

## Round 2以降：人間の見解あり

```text
cs-conductor-orchestrator Agentを使い、次のCONDUCTOR Roundを実行してください。

state.json: <absolute path>
Round No: <number>
parallel_limit: <number>
Wall Time: <time>

人間の見解:
- INS####について: <重視点、疑問、代替解釈>
- ACT####: <継続してほしい／closedにしたい>
- CL######またはNA######@ATT####について: <比較・深掘り希望>

見解をRound requestへ記録し、反証も含めて解析してください。既存結果を再計算せず、最後にInterpretationとFull Auditまで完遂してください。
```

新しいClaude Code sessionでも`state.json`とRound番号から再開できます。過去のInterpretation全文を貼る必要はありません。
