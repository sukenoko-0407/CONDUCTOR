---
name: cs-conductor-orchestrator
description: Manually activate the Claude Code Main Agent as the CONDUCTOR 0.2.0 Orchestrator for exactly one human-authorized Round. Use only when the human explicitly requests CONDUCTOR control.
disable-model-invocation: true
allowed-tools: Read, Bash, Glob, Grep, Agent, Skill
---

# CONDUCTOR Main Orchestrator

このSkillはMain Agent内でだけ有効化する。Subagentとして起動せず、既存Projectの`CLAUDE.md`も変更しない。人間が明示した一つのRoundだけを制御し、新しいRoundを自動開始しない。

## 開始時の固定手順

1. 新規Runなら、人間指定のCSV、endpoint、`higher_is_better`、project、parallel limit、Available CPU Cores、出力先でRuntime `init`を一回だけ実行する。CPU未指定時は8。SMILES列が一意でない場合だけ`--smiles-column`を要求する。
2. 既存Runでは、最初に`conductor_control.json`だけを読む。全DAG、Ledger、過去Reportを先読みしない。
3. 人間依頼を`inspect`、`start new Round`、`start cumulative Interpretation Round`、`resume active Round`、`continue current Round`、`revise report`、`accept Round`へ分類する。新Roundは人間が明示したときだけ`prepare-round`と`authorize-round`を行う。
4. `ACTIVE`または`FINALIZING`は同じRoundを`resume-round`する。live leaseがあれば二重起動しない。`AWAITING_HUMAN_REVIEW`では人間の`continue-round`、`revise-report`、`accept-round`以外を行わない。

Runtime操作は必ずこのSkillの`scripts/launch.py`を使う。JSON／JSONLを直接編集せず、Runtime Controllerを別Pythonで直接起動しない。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py <COMMAND> --run-root <RUN_ROOT> --lease-token <LEASE> <COMMAND固有引数>
```

`init`、`prepare-round`、`authorize-round`、`resume-round`、`request-result-rescreening`、read-only queryは例外である。Round authorization tokenはRound開始承認専用であり、通常ループでは使わない。

人間が現在のRoundの一次評価を明示的にやり直す場合だけ、Control Authorityを付けて`request-result-rescreening`を一回実行できる。既定4、最大8 Review Bundleずつ、通常の`PREPARE_RESULT_SCREENING`／`WRITE_RESULT_SCREENING`ループで処理する。旧評価を削除せずrevisionを追加する。`CLOSED` Roundを再開したり、別RoundのBundleを混在させたりしない。

人間が複数の完了済みScreening Roundから正式Reportを求めた場合は、通常解析Roundへ混ぜず、`prepare-round --report-mode full --cumulative-interpretation`で新しい報告専用Roundを提案し、通常どおり一回限りのauthorizationを受ける。必要なら`--source-round-id`を繰り返す。RuntimeがOperator予算0、既報Bundle除外、過去Round最新Assessmentの選抜を固定するため、Mainは過去Reportや全Resultを列挙しない。このRoundでDescription、Clustering、Operatorを計画しない。

## 固定ループ

Runtime compact responseの`protocol_version=0.2.0`と、一つの`required_action.code`だけを信頼する。

| required action | Main Agentの操作 |
|---|---|
| `PLAN_BASIC` | `plan-basic` |
| `PLAN_EXPLORATION` | `plan-exploration` |
| `EXECUTE_RUNNABLE_BATCH` | `prepare-execution-packet`後、MainからRuntime `execute-packet`を一回だけ呼ぶ |
| `WAIT_RUNNING` | Runtime Workerまたは科学processが生存中。再投入・reconcile・短間隔pollをせず待機 |
| `RECONCILE_RUNNING` | Worker不在が確定したため`reconcile-running`を一回だけ実行 |
| `RETRY_FAILED_NODE` | failure pointerを必要最小限確認し、同じNodeを`retry-node` |
| `FAILED_NODE_REPAIR_REQUIRED` | 自動retryを止め、人間へfailure pointerと修正対象を返す。実装修正で同じ科学的Nodeが成立する場合だけ同じNodeを`retry-node`。Planningしたscope自体が無効なら、人間承認後に`cs-conductor-node-review cancel` |
| `SCIENTIFIC_DECISION` | bounded Working Setから候補を選び`scientific-decision` |
| `ENTER_FINALIZING` | `enter-finalizing` |
| `PREPARE_RESULT_SCREENING` | `prepare-result-screening` |
| `WRITE_RESULT_SCREENING` | Runtime指定contextをInterpreterの`screening` modeへ一度渡し、`commit-result-screening` |
| `WRITE_SCREENING_SUMMARY` | `write-screening-summary` |
| `PLAN_INTERPRETATION` | `prepare-interpretation` |
| `WRITE_INTERPRETATION` | Interpreterを一つ起動し、`commit-interpretation` |
| `RUN_FULL_AUDIT` | `audit --mode full --register` |
| `COMPLETE_FINALIZING` | `complete-finalizing` |

`FAILED_NODE_REPAIR_REQUIRED`、`RESULT_SCREENING_BLOCKED`、`HUMAN_APPROVAL_REQUIRED`、`HUMAN_REVIEW_REQUIRED`、`INTERPRETATION_BLOCKED`、`AWAIT_HUMAN_ROUND`では停止して人間へ返す。Runtimeが許可していない処理へ読み替えない。

人間が失敗Nodeの修正と優先再実行を明示した場合だけ、`EXECUTE_RUNNABLE_BATCH`中でも、running Nodeがゼロであることを確認し、Main leaseとControl Authorityを付けた`retry-node`を使える。これは自動探索の優先順位変更ではない。Wall Time終了により`ENTER_FINALIZING`へ移った場合はpartial RoundとしてInterpretation／Auditを完成させ、人間へ「受理して次Roundで補完」または「同じRoundをcontinue」の選択を返す。自動的にcontinueや新Round開始をしない。

## Runtime Worker契約

- Mainは専門Skillを直接実行しない。
- `prepare-execution-packet`が返す`packet_path`を、そのままRuntime `execute-packet`へ一回だけ渡す。lease tokenは渡さない。
- 正式な実行形は次の一つである。応答キー`packet_path`から別の引数名を推測せず、`--packet`へ値を渡す。

  ```bash
  python .claude/skills/cs-conductor-orchestrator/scripts/launch.py execute-packet --run-root <RUN_ROOT> --packet <packet_path>
  ```

- `execute-packet`はPacketを原子的にclaimし、独立した決定論的OS Workerを起動して完了を待つ。科学Nodeの並列数とCPU配分はRuntimeが決める。
- MainのBash Tool callまたはsessionが失われても、claim済みWorkerは継続する。同じPacketを再度`execute-packet`へ渡す操作は既存Workerへの再接続であり、科学processを二重起動しない。
- 各科学Skillには共通`execution_request.json`が渡る。MainとRuntime Workerは個別Skillの長いCLIを組み立てない。
- 失敗時もcommandを即席修正しない。Runtimeは回復可能な一時障害だけを同じRequest契約で有限再試行し、引数・列・schema・実装欠陥は人間修正待ちにする。
- 未claimのstale、expired、invalid packetは再送せず、Controlを再確認する。claim済みPacketはPacket IDで冪等に追跡する。
- `WAIT_RUNNING`中はMainが科学processを監視・代行しない。異常終了後にRuntimeが`RECONCILE_RUNNING`を返した場合だけ一回reconcileする。

## Interpreter契約

- InterpreterはMainが必要なときだけ直接起動する短命の専用Subagentである。通常の科学計算を所有するのはSubagentではなくRuntime Workerである。
- Runtimeが返す`context_path`、`draft_path`、mode、必要な場合だけ`node_id`と人間focusを渡す。
- `screening`では一回のbounded Review Bundle batchだけを絶対評価させ、Mainへ個別評価本文を展開しない。`synthesis`ではRuntime shortlistだけを横断比較させる。
- Interpreterは科学計算、Node作成、State更新、評価索引更新をしない。
- draft拒否時は同じInterpretation Nodeを有限回修正する。別Roundや別Nodeを作らない。

## 探索規則

基本計算後のOperator探索は`exploration`一種類だけである。Runtimeが履歴を除外し、Capability、入力Description／Clustering、scopeの偏りを抑えたseed付き選択を行う。Globalを優先し、人間が`max_additional_nodes`で承認した件数まで同一Round内で25 Node以下ずつ計画する。Wall Timeは件数上限を暗黙に増やさない。

成功Result Cardが発生すると、RuntimeはGlobal、Global–Local、sibling ClusterのReview Bundleを決定論的に作り、次の科学計算前に既定4件の一次評価を要求する。Mainはshort-lived Interpreterへ一batchだけ渡し、評価本文を会話へ転載せずcommit成否だけを受け取る。評価軸は0～3の絶対基準で、合計点を作らない。

Round開始時の`report_mode`は`screening`または`full`である。`screening`はBundle評価索引、Round CSV、compact summary、Auditだけで終了する。`full`はさらに`design_lead`と`contextual_anomaly`から選抜した最大50 Resultで正式Interpretationを作る。0.1.x Runは継続せず、0.2.0では新規Runを開始する。

科学的推論が必要なのは`SCIENTIFIC_DECISION`である。人間priority、Global／Cluster-local変化、兄弟Cluster、独立したDescription family、異なるOperator、反証候補を評価する。Node ID、依存関係、Status、再試行、Round gateはRuntimeへ委ねる。

A014の定型フローは再利用可能なGlobal DBを一件作るだけで、Local screening／detail Nodeを自動計画しない。通常InterpretationへはcompactなGlobal Result Cardだけを渡す。Clusteringと連携したGlobal–Local MMP解釈はRound終了後に人間が`cs-analysis-interpret-mmp`を明示起動する。標準計算範囲は1～2 cuts、radius 0～2、core heavy atoms 8以上、両分子に対するcore fraction 0.5以上、variable heavy atoms 10以下である。

Wall Timeは上限であり早期終了目標ではない。許可済み作業を完了後、`screening`ではcompact summary、`full`では正式Interpretationを作り、いずれもFull Auditと`AWAITING_HUMAN_REVIEW`まで進む。人間の明示指示なしに次Roundを開始しない。

## 読み取り境界

通常読むのは人間依頼、compact response、bounded Working Set、選択したResult Cardだけとする。詳細科学方針が必要な場合だけ`CONDUCTOR_modules/docs/CONDUCTOR_policy.md`の該当箇所を読む。
