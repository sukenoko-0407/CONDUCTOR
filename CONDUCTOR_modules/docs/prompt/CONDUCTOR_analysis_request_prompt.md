# CONDUCTOR 解析依頼プロンプト

対象Version: `0.1.4`

`cs-conductor-orchestrator`は、人間が指定した一つの操作だけをMain Agentに実行させる。Round受理と次Round開始は、意図しない自動開始を避けるため別々に指示することを推奨する。

## 新規Run・Round 1開始

```text
/cs-conductor-orchestrator

操作: 新規Runを初期化し、RND0001を開始
入力CSV: <absolute path>
SMILES列名（自動推定が曖昧な場合のみ）: <column name>
endpoint: <column name>
higher_is_better: <true/false>
project: <project name>
Run Root出力先: <absolute path>
parallel_limit: <number>
Available CPU Cores: <number; 省略時8>
Wall Time: <minutes>
高コスト基本計算一括承認: <yes/no>

Roundの目的・重視点（任意）:
<人間の観点。未指定なら標準の基本計算と初期探索を実施>

既存のconductor_control.jsonがないことを確認した場合だけ初期化してください。Main Agent自身がOrchestratorとして動作し、Runtimeの単一required_actionに従ってください。専門SkillをMainから直接実行せず、科学計算は署名付きexecution packetごとにExecutorを一つだけ起動してください。

基本計算、初期探索、Interpretation、Full Auditまで同じRND0001で進め、AWAITING_HUMAN_REVIEWになったら停止してください。Roundを自動的に受理したり、RND0002を開始したりしないでください。
標準のAnalysis上限（1 Round最大200 Node、最大50 Nodeずつ計画、初期Global最大100 Node）を変更せず、長いWall Timeを理由に一括計画を拡大しないでください。
```

## 状態確認のみ

```text
/cs-conductor-orchestrator

操作: 状態確認のみ
Run Root: <absolute path>

conductor_control.jsonとcompactなRuntime inspectionだけを確認し、Run ID、現在のRound、Round状態、required_action、実行中／待機中件数、Interpretation／Audit gate、blockerを簡潔に報告してください。Round、Node、lease、State、artifactを変更せず、ExecutorやInterpreterを起動しないでください。
```

## 中断したActive Roundの再開

新しいClaude Code sessionへ引き継ぐ場合にも使用できる。

```text
/cs-conductor-orchestrator

操作: Active Roundを同じRoundのまま再開
Run Root: <absolute path>
期待するRound: RND####
今回の補足指示（任意）: <人間の観点。既存Round Contractを置換しない範囲>

最初にconductor_control.jsonを確認し、期待するRoundと実状態を照合してください。新Roundや代替Nodeを作らず、現在のrequired_actionから再開してください。live leaseがある場合は二重実行せず、その状態を報告してください。

同じRoundのInterpretationとFull Auditを完成させ、AWAITING_HUMAN_REVIEWになったら停止してください。Roundを自動受理しないでください。
```

## 人間レビュー後に同じRoundを継続

未完了作業や追加作業を、次Roundではなく現在Roundへ含めたい場合に使用する。

```text
/cs-conductor-orchestrator

操作: AWAITING_HUMAN_REVIEWの同じRoundを継続
Run Root: <absolute path>
対象Round: RND####
継続理由・残作業: <具体的な未完了内容または追加指示>

新Roundは開始せず、対象Roundをcontinueしてください。必要な科学Nodeだけを追加し、既存の成功Nodeは再計算しないでください。追加結果を含む新しいInterpretationとFull Auditを作成し、再びAWAITING_HUMAN_REVIEWになったら停止してください。
```

## Interpretationだけを改訂

```text
/cs-conductor-orchestrator

操作: Interpretation reportの改訂のみ
Run Root: <absolute path>
対象Round: RND####
改訂理由: <誤記、説明不足、重視点など>
人間の見解（任意）: <INS######に対する意見等>

新しいDescription、Clustering、Operator Nodeは計画しないでください。同じRoundの既存結果だけを使ってInterpretationを改訂し、Quality gateとFull Auditを通してください。新Roundは開始せず、AWAITING_HUMAN_REVIEWで停止してください。
```

## Roundを受理して閉じる

この操作では次Roundを開始しない。

```text
/cs-conductor-orchestrator

操作: Roundを受理して閉じるだけ
Run Root: <absolute path>
対象Round: RND####

対象RoundがAWAITING_HUMAN_REVIEWで、InterpretationとFull Auditが有効であることを確認してからacceptしてください。次Roundのprepare、authorize、開始は行わないでください。終了後のControl状態とnext Round番号だけを報告してください。
```

## Round 2以降を開始

前Roundを受理して`CLOSED`にした後、別の指示として使用する。

```text
/cs-conductor-orchestrator

操作: 次の新Roundを開始
Run Root: <absolute path>
期待する新Round: RND####（実際の番号はControlで照合）
parallel_limit: <number>
Available CPU Cores: <number; 変更しない場合は省略可>
Wall Time: <minutes>

Roundの目的:
<追加探索、深掘り対象、人間が求める成果物>

人間の見解・優先事項（任意）:
- INS######: <支持、疑問、代替解釈、反証希望>
- 対象Node／Cluster: <N###### / C###### / 比較したい範囲>
- その他: <偏りを避けたいDescription、Operator等>

Active Roundがなく、前RoundがCLOSEDであることを確認してください。契約案をこの依頼と照合してから、人間が明示した新Roundだけを開始してください。過去の成功Nodeは再計算せず、再利用参照として扱ってください。全artifactを読み直さず、Control、bounded Working Set、必要なResult Cardだけから判断してください。

最後に新RoundのInterpretationとFull Auditを作成し、AWAITING_HUMAN_REVIEWで停止してください。さらに次のRoundを開始したり、このRoundを自動受理したりしないでください。
```
