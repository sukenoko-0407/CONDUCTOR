# CONDUCTOR 日常運用プロンプト集

対象Version: `0.1.6`

通常のRun／Round運用、状態確認、session引継ぎ、既存結果の閲覧に使うプロンプトをまとめた。`<...>`を実際の値へ置き換えて使用する。

## 目次

- [共通原則](#daily-common)
- [新規Run・Round 1開始](#daily-new-run)
- [状態確認のみ](#daily-status)
- [中断したActive Roundの再開](#daily-resume)
- [人間レビュー後に同じRoundを継続](#daily-continue)
- [Interpretationだけを改訂](#daily-revise)
- [Roundを受理して閉じる](#daily-accept)
- [Round 2以降を開始](#daily-next-round)
- [新しいClaude Code sessionへの引継ぎ](#daily-handoff)
- [Result Conciergeによる既存結果の確認](#daily-concierge)
- [MMP Global–Local専用解釈](#daily-mmp-interpretation)

<a id="daily-common"></a>
## 共通原則

- 人間が指定した一つの操作だけを実行させる。Round受理と次Round開始は別々に指示する。
- Main Agent自身をOrchestratorとし、科学SkillをMain Agentから直接実行しない。
- State、DAG、Event Ledgerを直接編集しない。Runtimeの単一`required_action`に従う。
- claim済みExecution packetはRuntime Workerが所有する。同じpacketの再接続で二重計算を起こさない。
- 解析を進める操作ではInterpretationとFull Auditまで完了し、`AWAITING_HUMAN_REVIEW`で停止する。
- 人間の明示指示なしにRoundを受理したり、次Roundを開始したりしない。

<a id="daily-new-run"></a>
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
<人間の観点。未指定なら標準の基本計算とGlobal優先explorationを実施>

既存のconductor_control.jsonがないことを確認した場合だけ初期化してください。Main Agent自身がOrchestratorとして動作し、Runtimeの単一required_actionに従ってください。専門SkillをMainから直接実行せず、Runtimeが生成した署名付きExecution packetだけをexecute-packetへ一回渡してください。

基本計算、最大50 Analysis Nodeのexploration、Interpretation、Full Auditまで同じRND0001で進め、AWAITING_HUMAN_REVIEWになったら停止してください。長いWall Timeを理由にNode上限を拡大せず、Roundを自動受理したりRND0002を開始したりしないでください。
```

<a id="daily-status"></a>
## 状態確認のみ

```text
/cs-conductor-orchestrator

操作: 状態確認のみ
Run Root: <absolute path>

conductor_control.jsonとcompactなRuntime inspectionだけを確認し、Run ID、現在のRound、Round状態、required_action、実行中／待機中件数、Interpretation／Audit gate、blockerを簡潔に報告してください。

Round、Node、lease、State、artifactを変更せず、Runtime WorkerやInterpreterを起動しないでください。全DAG、全Event Ledger、過去の全Reportを先読みしないでください。
```

<a id="daily-resume"></a>
## 中断したActive Roundの再開

新しいClaude Code sessionから再開する場合にも使用できる。

```text
/cs-conductor-orchestrator

操作: Active Roundを同じRoundのまま再開
Run Root: <absolute path>
期待するRound: RND####
今回の補足指示（任意）: <既存Round Contractを置換しない範囲の人間の観点>

最初にconductor_control.jsonを確認し、期待するRoundと実状態を照合してください。新Roundや代替Nodeを作らず、現在のrequired_actionから再開してください。live leaseがある場合は二重実行せず、その状態を報告してください。

同じRoundのInterpretationとFull Auditを完成させ、AWAITING_HUMAN_REVIEWになったら停止してください。Roundを自動受理しないでください。
```

<a id="daily-continue"></a>
## 人間レビュー後に同じRoundを継続

未完了作業や追加作業を、次Roundではなく現在Roundへ含める場合に使用する。

```text
/cs-conductor-orchestrator

操作: AWAITING_HUMAN_REVIEWの同じRoundを継続
Run Root: <absolute path>
対象Round: RND####
追加Wall Time: <minutes>
継続理由・残作業: <具体的な未完了内容または追加指示>

新Roundは開始せず、対象Roundをcontinueしてください。必要な科学Nodeだけを追加し、既存の成功Nodeは再計算しないでください。追加結果を含む新しいInterpretationとFull Auditを作成し、再びAWAITING_HUMAN_REVIEWになったら停止してください。
```

<a id="daily-revise"></a>
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

<a id="daily-accept"></a>
## Roundを受理して閉じる

この操作では次Roundを開始しない。

```text
/cs-conductor-orchestrator

操作: Roundを受理して閉じるだけ
Run Root: <absolute path>
対象Round: RND####
人間のコメント（任意）: <次Roundへの見解、留保事項>

対象RoundがAWAITING_HUMAN_REVIEWで、InterpretationとFull Auditが有効であることを確認してからacceptしてください。Failed Nodeと未解析範囲がある場合はpartial outcomeと引継ぎ事項を保持してください。次Roundのprepare、authorize、開始は行わず、終了後のControl状態とnext Round番号だけを報告してください。
```

<a id="daily-next-round"></a>
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
<探索、深掘り対象、人間が求める成果物>

人間の見解・優先事項（任意）:
- INS######: <支持、疑問、代替解釈、反証希望>
- 対象Node／Cluster: <N###### / C###### / 比較したい範囲>
- その他: <偏りを避けたいDescription、Operator等>

Active Roundがなく、前RoundがCLOSEDであることを確認してください。契約案をこの依頼と照合し、人間が明示した新Roundだけを開始してください。過去の成功Nodeは再計算せず再利用参照として扱い、全artifactを読み直さず、Control、bounded Working Set、必要なResult Cardだけから判断してください。

最後に新RoundのInterpretationとFull Auditを作成し、AWAITING_HUMAN_REVIEWで停止してください。さらに次のRoundを開始したり、このRoundを自動受理したりしないでください。
```

<a id="daily-handoff"></a>
## 新しいClaude Code sessionへの引継ぎ

長いStateや過去Reportをプロンプトへ貼り付けず、Run Rootと人間が意図する操作だけを渡す。

```text
/cs-conductor-orchestrator

操作: session引継ぎ
Run Root: <absolute path>
人間が意図する操作: <状態確認のみ／Active Round再開／同一Round継続／Interpretation改訂／Round受理／新Round開始>
期待するRound: <RND#### または none>
今回の指示（任意）: <人間の観点・残作業>

最初にrun_root/conductor_control.jsonだけを確認し、Run ID、Control revision、現在のRound、Round状態、required_action、live leaseの有無を照合してください。人間が指定していない操作へ読み替えないでください。

ActiveまたはFINALIZINGのRoundがある場合は同じRoundを再開し、別Roundを作らないでください。live leaseがある場合は二重実行せず報告してください。新Roundは、人間が明示的に新Round開始を指定し、Active Roundがなく、直前RoundがCLOSEDである場合だけprepare／authorizeしてください。

Main Agent自身がOrchestratorです。通常は全DAG、全Event Ledger、過去全Reportを読まず、追加情報が必要な場合だけRuntimeのbounded queryからResult Cardまたはfailure summaryを取得してください。Tool応答を失ったmutationは推測で再送せず、Control revisionとverify-returnで照合してください。

解析を進める操作では同じRoundのInterpretationとFull Auditを完成させ、AWAITING_HUMAN_REVIEWで停止してください。Roundを自動受理せず、人間の指示なしに次Roundを開始しないでください。
```

引継ぎの運用正本は`run_root/conductor_control.json`である。詳細は必要な場合だけDAG snapshot、Event Ledger、Result Cardへ辿る。

<a id="daily-concierge"></a>
## Result Conciergeによる既存結果の確認

既存Runを変更せず、Interpretationや個別結果を詳しく確認する場合に使用する。出力は正式DAGへ登録されない。

```text
/cs-conductor-result-concierge

Run Root: <absolute path>
確認したい対象: <INS###### / C###### / N###### / RND#### / artifact relative path>
依頼:
<説明、根拠追跡、Global対Cluster比較、Description横断比較、既存値の追加集計、表・Figure作成など>

期待する成果物（任意）:
- report.md
- report.html
- figures/<希望する図>

最初にRunの状態をread-onlyで確認してください。AWAITING_HUMAN_REVIEW、CLOSED、またはActive Roundなしの場合だけ開始し、ACTIVE／FINALIZING中ならREQを作成せず報告してください。

既存解析をFreezeし、書き込みは新しく割り当てるrun_root/concierge/REQ######/内だけに限定してください。既存artifactの抽出、filter、依頼固有の記述統計、比較、既存値からのFigure作成は実行して構いません。補助PythonはREQ directory内のscratch/へ置き、可能な限りrun-helperを使用してください。

新しいDescription、Clustering、Operator、予測model、Insight、Node、Stateは作成しないでください。正式な追加解析が必要な場合は実行せず、next_round_prompt.mdとして人間へ提案してください。

Reportにはsource、手法、表現、scope、sample数、観察、解釈、限界を明記してください。Cluster結果をGlobalと表示せず、相関から因果を断定しないでください。

Operator artifactに記録されたmetric、threshold、comparator、scope、denominatorを正本とし、別の式を推測して既存metricの定義を置き換えないでください。定義を確認できない値は「判定不能」としてください。A010ではhigh/low thresholdをendpoint値の上側／下側分位点として扱い、良好側はfavorable threshold、comparator、higher_is_betterから確認してください。

依頼固有の追加集計は「Concierge-derived」と明示し、式、source path、filter、scope、分母Nを記録してください。最後に保護対象のhashが変化していないことをverifyしてください。
```

<a id="daily-mmp-interpretation"></a>
## MMP Global–Local専用解釈

Round終了後、既存のA014 Global MMP DatabaseとClustering結果をread-onlyで突き合わせる。通常のInterpretationやDAGは変更しない。

```text
/cs-analysis-interpret-mmp

Run Root: <absolute path>
対象Round: <RND####>
解析モード: <全Clustering survey / Clustering指定 / Cluster指定 / Transform指定>

対象指定（任意）:
- Global A014 Node: <N######; 過去RoundのDatabaseを人間が明示再利用する場合だけ>
- Clustering Node: <N######>
- Cluster: <C######>
- Transform: <transform_id>

重視する視点（任意）:
<例: Clustering後にTransform効果の分散が縮小する手法、特定Clusterだけで増幅・方向反転するTransform、negative result>

既存RunをFreezeし、成功済みGlobal A014 DatabaseとcanonicalなCluster registry／membershipだけをread-onlyで使用してください。新しいMMP計算、Node、Insight、Roundは作成しないでください。

prepareでrun_root/mmp_interpretation/MMPREQ######/を新規作成し、最初にboundedなmmp_interpretation_context.jsonだけを確認してください。必要な場合だけ同directoryのmmp_interpretation_draft.jsonを改善し、finalizeとverifyまで実行してください。

Global、Local（pair両化合物が対象Cluster内）、Outside（pair両化合物が対象Cluster外）を区別し、Transform効果の中央値、IQR／MAD、方向整合性、pair数、独立化合物数、Exact Core支持を比較してください。特に、非重複Clusteringにおける分散縮小、Cluster特異的な増幅、方向反転を候補化してください。Boundary pairは混ぜず別に数えてください。

出力は割り当てられたMMPREQ directory内だけに保存し、DAG、State、Result Index、Insight Index、Event Ledger、通常Interpretationを変更しないでください。既定では対象Roundに新たな成功済みGlobal A014がなければ計算を開始せず、その旨を報告してください。過去RoundのDatabaseは、人間が上記でGlobal A014 Node IDを明示した場合だけ再利用してください。
```
