# CONDUCTOR 日常運用プロンプト集

対象Version: `0.2.0`

通常のRun／Round運用、状態確認、session引継ぎ、既存結果の閲覧に使うプロンプトをまとめた。`<...>`を実際の値へ置き換えて使用する。

## 目次

- [共通原則](#daily-common)
- [新規Run・Round 1開始](#daily-new-run)
- [長時間のRound 1（基本計算＋広いOperator探索）](#daily-long-round1)
- [状態確認のみ](#daily-status)
- [中断したActive Roundの再開](#daily-resume)
- [人間レビュー後に同じRoundを継続](#daily-continue)
- [Interpretationだけを改訂](#daily-revise)
- [Roundを受理して閉じる](#daily-accept)
- [Round 2以降を開始](#daily-next-round)
- [複数Screening Roundから累積Interpretationを作成](#daily-cumulative-interpretation)
- [新しいClaude Code sessionへの引継ぎ](#daily-handoff)
- [Result Conciergeによる既存結果の確認](#daily-concierge)
- [MMP Global–Local専用解釈](#daily-mmp-interpretation)
- [既存一次評価をHTMLで俯瞰する](#daily-assessment-summary)

<a id="daily-common"></a>
## 共通原則

- 人間が指定した一つの操作だけを実行させる。Round受理と次Round開始は別々に指示する。
- Main Agent自身をOrchestratorとし、科学SkillをMain Agentから直接実行しない。
- State、DAG、Event Ledgerを直接編集しない。Runtimeの単一`required_action`に従う。
- claim済みExecution packetはRuntime Workerが所有する。同じpacketの再接続で二重計算を起こさない。
- `report_mode=screening`ではReview Bundle絶対評価・compact summary・Full Audit、`report_mode=full`ではさらにRuntimeが選抜したBundleの正式Interpretationまで完了し、`AWAITING_HUMAN_REVIEW`で停止する。
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
Operator Node予算: <既定50。広い探索では人間が50超を明示。安全上限500>
Report mode: <screening/full。序盤探索はscreening、正式解釈が必要ならfull>
高コスト基本計算一括承認: <yes/no>

Roundの目的・重視点（任意）:
<人間の観点。未指定なら標準の基本計算とGlobal優先explorationを実施>

既存のconductor_control.jsonがないことを確認した場合だけ初期化してください。Main Agent自身がOrchestratorとして動作し、Runtimeの単一required_actionに従ってください。専門SkillをMainから直接実行せず、Runtimeが生成した署名付きExecution packetだけをexecute-packetへ一回渡してください。

基本計算、人間指定予算内のexploration、boundedなReview Bundle絶対評価を同じRND0001で進めてください。screening modeではcompact summary、full modeでは`design_lead`と`contextual_anomaly`を中心に選抜したBundleのInterpretationを作り、Full Audit後にAWAITING_HUMAN_REVIEWで停止してください。長いWall Timeを理由にNode予算を拡大せず、Roundを自動受理したりRND0002を開始したりしないでください。
```

<a id="daily-long-round1"></a>
## 長時間のRound 1（基本計算＋広いOperator探索）

基本計算を省略せず揃えた後、Globalを優先した広いOperator探索と、代表的なLocal／Cluster比較まで同じRoundで進めるためのプロンプト。0.2.0では「初期探索」と「追加探索」を別状態として管理しないため、単一explorationの中で初期探索相当の広さを確保し、そのまま未実施領域へ進む。

```text
/cs-conductor-orchestrator

操作: 新規Runを初期化し、長時間のRND0001を開始
入力CSV: <absolute path>
SMILES列名（自動推定が曖昧な場合のみ）: <column name>
endpoint: <column name>
higher_is_better: <true/false>
project: <project name>
Run Root出力先: <absolute path>
parallel_limit: <number>
Available CPU Cores: <number; 省略時8>
Wall Time: <推奨1440 minutes。利用可能時間に合わせて変更>
Operator Node予算: <推奨200。150～250程度を目安とし、安全上限500>
Report mode: screening
高コスト基本計算一括承認: yes

Roundの目的:
基本計算を十分に揃えたうえで、初期探索相当の広いGlobal解析と、代表的なLocal／Cluster解析を実施し、さらに予算内で未実施領域を偏りなく探索する。

重視する点（任意）:
<特に確認したいDescription、Clustering、Operator、Cluster、または科学的観点。指定がなければ標準Policyに従う>

既存のconductor_control.jsonがないことを確認した場合だけ新規Runを初期化してください。Main Agent自身がOrchestratorとして動作し、Runtimeの単一required_actionに従ってください。専門SkillをMainから直接実行せず、Runtimeが生成した署名付きExecution packetだけを正規経路で処理してください。

人間から明確な省略指示がない限り、利用可能なDescriptionと標準Clusteringを含む基本計算を完了してからOperator探索を進めてください。高コスト基本計算は上記の一括承認に含まれます。成功済みNodeを再計算しないでください。

Operator探索では、まずGlobal解析の不足を優先して、Description／Operator familyが一部へ偏らない広い解析を行ってください。その後、十分な化合物数を持つ代表的なClusterについてGlobal–LocalおよびSibling Cluster比較が成立するLocal解析へ進み、残りの予算では未実施のDescription、Clustering、Operatorの組合せから全体バランスを保って追加してください。特定の組合せだけを機械的に大量展開せず、同一signatureを重複登録しないでください。

成功Resultから成立するReview Bundleをbounded batchで逐次評価してください。実行可能な承認済み作業、Wall Time、Operator Node予算が残っている間は、明確なblockerなしに早期finalizeしないでください。一方、Wall Timeだけを理由にNode予算を拡大しないでください。

このRoundはscreening modeなので、正式Interpretationは作成せず、Review Bundle評価、result_assessments.csv、compact Screening Summary、Full Auditを完成させてください。最後はAWAITING_HUMAN_REVIEWで停止し、RND0001を自動受理したりRND0002を開始したりしないでください。
```

正式な`interpretation.html`が必要な場合は、RND0001を人間が確認・受理した後、別途`report_mode=full`の次Roundを開始する。RND0001自体で正式Reportまで必要な場合に限り、上記の`Report mode`を`full`へ変更する。

<a id="daily-status"></a>
## 状態確認のみ

```text
/cs-conductor-orchestrator

操作: 状態確認のみ
Run Root: <absolute path>

conductor_control.jsonとcompactなRuntime inspectionだけを確認し、Run ID、現在のRound、report mode、Round状態、required_action、実行中／待機中件数、未評価Result件数、handoff／Audit gate、blockerを簡潔に報告してください。

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

同じRound Contractのreport modeを変更せず、未評価Review Bundleと指定されたhandoff成果物、Full Auditを完成させ、AWAITING_HUMAN_REVIEWになったら停止してください。Roundを自動受理しないでください。
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

新Roundは開始せず、対象Roundをcontinueしてください。必要な科学Nodeだけを追加し、既存の成功Nodeは再計算しないでください。追加Resultから成立するReview Bundleを評価し、対象Roundがfullなら更新Interpretationも作成してください。Full Audit後、再びAWAITING_HUMAN_REVIEWになったら停止してください。
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

この操作は`report_mode=full`のRoundだけに使用する。screening Roundの正式解釈が必要なら、次の人間承認Roundを`full`で開始する。

<a id="daily-accept"></a>
## Roundを受理して閉じる

この操作では次Roundを開始しない。

```text
/cs-conductor-orchestrator

操作: Roundを受理して閉じるだけ
Run Root: <absolute path>
対象Round: RND####
人間のコメント（任意）: <次Roundへの見解、留保事項>

対象RoundがAWAITING_HUMAN_REVIEWで、screening modeならScreening Summary、full modeならInterpretation、およびFull Auditが有効であることを確認してからacceptしてください。Failed Nodeと未解析範囲がある場合はpartial outcomeと引継ぎ事項を保持してください。次Roundのprepare、authorize、開始は行わず、終了後のControl状態とnext Round番号だけを報告してください。
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
Operator Node予算: <number; 既定50、安全上限500>
Report mode: <screening/full>

Roundの目的:
<探索、深掘り対象、人間が求める成果物>

人間の見解・優先事項（任意）:
- INS######: <支持、疑問、代替解釈、反証希望>
- 対象Node／Cluster: <N###### / C###### / 比較したい範囲>
- その他: <偏りを避けたいDescription、Operator等>

Active Roundがなく、前RoundがCLOSEDであることを確認してください。契約案をこの依頼と照合し、人間が明示した新Roundだけを開始してください。過去の成功Nodeは再計算せず再利用参照として扱い、全artifactを読み直さず、Control、bounded Working Set、必要なResult Card／Review Bundleだけから判断してください。

最後に全新規Resultから成立するReview Bundleの評価を完了し、screeningならcompact summary、fullなら選抜BundleのInterpretationを作成してください。Full Audit後にAWAITING_HUMAN_REVIEWで停止し、さらに次のRoundを開始したり、このRoundを自動受理したりしないでください。
```

<a id="daily-cumulative-interpretation"></a>
## 複数Screening Roundから累積Interpretationを作成

複数のScreening Roundを人間が受理してCLOSEDにした後、既報Insightを除く最新一次評価から正式Reportを作る。科学計算は追加しない。

```text
/cs-conductor-orchestrator

操作: 累積Interpretation専用の新Roundを開始
Run Root: <absolute path>
対象Source Round: <RND0001, RND0002, ...。省略時は全CLOSED Round>
Wall Time: <minutes>
Interpretation iterations: <通常3>

重視する視点（任意）:
<活性改善候補、Global–Localの違和感、特定Operator／Clusterなど>

Active Roundがなく、対象Source RoundがすべてCLOSEDであることを確認してください。人間が指定した新Roundについて、通常のprepare／authorize手順を使い、`prepare-round --report-mode full --cumulative-interpretation`を指定してください。対象を限定する場合だけ各Roundを`--source-round-id`で渡してください。

これは報告専用Roundです。Description、Clustering、Operatorを計画・実行せず、Operator Node予算を追加しないでください。Runtimeが全Source Roundの各Bundleの最新一次評価を走査し、過去の正式Insightで使用済みのBundleを除外し、未報告候補をbounded shortlistへ選抜します。

historical re-Screening済みのBundleでは、評価を実施したRoundではなく`source_round_id`に基づいて最新revisionをSource Roundへ帰属させてください。旧revision本文を追加で読み込まないでください。

`PLAN_INTERPRETATION`ではRuntime指定contextだけをcs-conductor-interpreterへsynthesis modeで一回渡してください。過去Report全文や全Result Cardを追加読込しないでください。既報Insightを言い換えて新規Insightにせず、未報告のdesign lead／contextual anomalyだけを正式Reportへ整理してください。

Interpretation commit後にFull Auditを完了し、AWAITING_HUMAN_REVIEWで停止してください。このRoundを自動受理せず、さらに次Roundを開始しないでください。最後にSource Round、一次評価総数、既報除外数、選抜Bundle数、非選抜数、生成Report、Audit結果を報告してください。
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

Main Agent自身がOrchestratorです。通常は全DAG、全Event Ledger、過去全Reportを読まず、追加情報が必要な場合だけRuntimeのbounded queryからResult Card、Review Bundle、またはfailure summaryを取得してください。Tool応答を失ったmutationは推測で再送せず、Control revisionとverify-returnで照合してください。

解析を進める操作では同じRoundのResult Screening、契約済みhandoff成果物、Full Auditを完成させ、AWAITING_HUMAN_REVIEWで停止してください。Roundを自動受理せず、人間の指示なしに次Roundを開始しないでください。
```

引継ぎの運用正本は`run_root/conductor_control.json`である。詳細は必要な場合だけDAG snapshot、Event Ledger、Result Card、Review Bundleへ辿る。0.1.x Run Rootを0.2.0で継続しない。

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
<a id="daily-assessment-summary"></a>
## 既存一次評価をHTMLで俯瞰する

```text
/cs-conductor-assessment-report

次のCONDUCTOR Run Rootについて、既存の一次評価を読み取り専用で集約してください。

- Run Root: <RUN_ROOT>
- 対象Round: 全Round
- Top候補数: 10

DAG、Round、State、科学artifact、Interpretationには一切変更を加えず、
`assessment_reports/<timestamp>/assessment_summary.html`を作成してください。
```
