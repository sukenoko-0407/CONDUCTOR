# CONDUCTOR 4.3.1 リファクタリング計画

## 1. 文書の位置づけ

本書は、CONDUCTOR 4.3.0の実運用で確認されたOrchestrator多重起動、Subagent異常終了後の復旧、Interpretation未作成でのRound終了、Node大量先行登録などを改善するための4.3.1実装計画である。

対象はcontrol plane、Orchestrator／Interpreter連携、内部Skill、監査、State schema、planner、関連文書・試験である。Description、Grouping、Operatorの科学計算Kernelと一般利用時の挙動は原則変更しない。

4.3.0 Stateを暗黙に書き換えない。旧run rootをread-onlyとする一回限りの明示的migrationだけを提供し、`scan → 人間承認 → apply → verify` により別の新run rootを作成する。検証済み科学artifactは移行できるが、旧Interpretationは参照用とし、新Roundで作り直す。

## 2. 改修の目的

1. 一つのRun／Roundを変更できるOrchestratorを常に一つに制限する。
2. Orchestrator Subagentが異常終了しても、再計画やNode再採番ではなく、既存Stateの監査と復旧から継続する。
3. Node identityとexecution attemptを分離し、再試行で新しいNodeを作らない。
4. 成功したOperator EvidenceがあるRoundを、最終Interpretationなしで終了できないようにする。
5. 初期探索の網羅性を維持しながら、数千Nodeを一度に先行登録しない。
6. Planner、実行制御、監査をコード上で分割しつつ、人間が利用する入口は増やしすぎない。
7. Auditを他の解析成果物と同じRun rootへ保存し、別sessionでも状態を短時間で把握できるようにする。
8. Orchestratorが通常読むruntime状態を、固定構造かつboundedな一つのbriefへ集約する。
9. 決定論的なcontrol actionと、Orchestratorが推論すべき科学的decisionを明確に分ける。
10. 特定のLLM、conversation履歴、長文文書の包括的理解へ依存しない制御契約にする。

## 3. 現状の問題

### 3.1 Round全体の書込み所有権がない

`state.json.lock`は一回のState更新を排他するが、Round全体を一つのOrchestratorへ割り当てるものではない。停止したSubagentへの対処として別Orchestratorを起動すると、両者が時間差で同じRoundへ計画を追加できる。

### 3.2 異常終了と計算失敗が区別されない

Nodeには単一の`running`状態と開始時刻しかなく、Agent停止、実行process停止、HPC job継続、成果物生成後のState未登録を区別しにくい。その結果、再起動したAgentが新しいNodeを計画するか、完了済み計算を再実行する可能性がある。

### 3.3 Interpretationは手順上の推奨に留まる

Orchestrator文書はInterpretation作成を指示しているが、`round-end`は成功したOperatorと最終Interpretationの対応を検証しない。`interpretation_iterations`もresource metadataであり、実行回数や終了条件として強制されていない。

### 3.4 Node数増加の原因を判別しにくい

初期local解析は、Grouping Node × 代表Group × applicable Operator × 評価Descriptionの積となる。網羅性を保つと`NO1000`以降へ到達すること自体は異常ではない。一方、複数Orchestratorや複数planning batchによる意図しない追加も同じNode番号増加として見えるため、planning batchの由来と予測件数が必要である。

### 3.5 SkillとAgentが同名である

`cs-conductor-orchestrator` Skillと同名Agentが存在し、人間の「cs-conductor-orchestratorを使う」という指示が、Skill読込みとSubagent起動のどちらを意味するか曖昧である。

### 3.6 再開時のcontextが大きい

現行OrchestratorはPolicy、Design Spec、Catalog、Profile、raw State、State summary、Round briefを再開時に広く読むよう指示されている。また、State summaryのRound、Evidence、Question、failure配列と、Round summaryのNode列挙はRunの成長に伴って長くなる。複数Roundを標準とするsystemでは、Agentへ長文を読ませて状態復元を委ねず、機械的に生成したboundedなresume viewを入口にする必要がある。

## 4. 4.3.1の制御構成

### 4.1 Agent

新しいAgent種別は追加しない。

| Agent | 責務 | State書込み |
|---|---|---|
| `cs-conductor-orchestrator` | 人間の依頼理解、計画方針、Node実行制御、Interpreter呼出し、復旧判断、Round完了 | State Manager経由のみ許可 |
| `cs-conductor-interpreter` | 選択済みEvidenceの意味解釈、Finding／Hypothesis／Question／Relation／Requestの編集 | 禁止 |

### 4.2 Skill

| Skill | 位置づけ | 人間からの通常利用 |
|---|---|---|
| `cs-conductor-runtime` | 現`cs-conductor-orchestrator` Skillを改名。State、planner、lease、execution attempt、recoveryを提供する内部runtime | 原則不要 |
| `cs-conductor-run-audit` | State、DAG、artifact、lease、Interpretation gateを決定論的に監査するread-only Skill | 必要時は明示実行可能 |
| `cs-analysis-interpret-evidence` | Interpretation context作成、機械draft、schema検証、Markdown／HTML rendering | Orchestrator／Interpreter経由 |
| `cs-conductor-state-report` | 人間向けDAG図と状態report | 明示的な依頼時のみ |

PlannerとExecutorは別Agentや多数の人間向けSkillにしない。`cs-conductor-runtime`内部の独立module／CLI subcommandとして分割する。これにより実装の疎結合性を確保しながら、State書込み主体と人間向け入口を増やさない。

### 4.3 外付け機能の上限

Orchestration関連のSkill分割は、内部runtime、read-only audit、既存Interpretationの三系統を上限とする。Planner、Executor、Finalizerをさらに人間向けSkillやAgentへ分割しない。必要なcode分離は`cs-conductor-runtime`内のmodule／subcommandで行う。

- `cs-conductor-runtime`: State mutation、bootstrap、planning mechanics、execution control、recovery、Round finalization
- `cs-conductor-run-audit`: Quick／Full Auditとread-only recovery candidate生成
- `cs-analysis-interpret-evidence`: Interpretation context、draft、validation、rendering

`cs-conductor-state-report`は人間が明示的に要求する可視化であり、通常のOrchestration control flowには入れない。

### 4.4 決定論と推論の境界

次は再現性と安全性を優先し、runtimeが決定論的に処理する。

- ID採番、lease、lock、Node status、execution attempt
- dependency、DAG、signature重複、applicability、metric contract
- phase gate、resource／parallel limit、artifact／hash validation
- 規定済み基本計算・初期探索coverage、seed付き追加探索の候補抽出
- Interpretation完成条件、Round終了可否、summary／brief生成

次はOrchestratorまたはInterpreterへ推論として残す。

- 人間の依頼意図と科学的focus
- 有効な探索候補間の優先順位
- Finding、Question、矛盾、例外、negative resultの重要性
- 追加探索と深掘りの配分、人間確認の要否
- Interpretationの意味解釈、反証方向、次解析候補

Runtimeは科学的focusを決定せず、候補、制約、coverage、概算costを提示する。単一の必須control actionと、複数から選ぶ科学的decisionを別fieldで返す。

### 4.5 Orchestrator状態ファイルの階層

Orchestratorが把握すべきactive状態は、次の三ファイルを中心にする。

```text
results/CONDUCTOR/<project>/<run-id>/
├─ state.json
├─ summaries/
│  ├─ state_summary.json
│  └─ orchestrator_brief.json
├─ audit/
├─ rounds/
├─ indices/
├─ description/
├─ grouping/
├─ analysis/
└─ interpretation/
```

| File | 役割 | Orchestratorの通常読込み |
|---|---|---|
| `state.json` | Run／Round、lease、Node、counter、index pointerを持つcontrol-plane正本 | 原則禁止。runtimeだけが直接扱う |
| `summaries/state_summary.json` | Stateとindexから生成する事実ベースのmaterialized view | briefで不足するときのみ |
| `summaries/orchestrator_brief.json` | 現在mode、必須control action、科学的decision、blocker、少数pointerを持つ固定構造の行動カード | session開始時と各control step後に読む |

`state_summary.json`と`orchestrator_brief.json`はderived artifactであり、Stateとimmutable artifactから再生成できる。配列は上限件数を持ち、超過分はcountとquery pointerだけを記録する。Round数、Node数、Evidence数に比例してOrchestratorの通常contextを増加させない。

Group registry、Evidence digest、Question ledger、coverage cellなどは`indices/`に保持するが、通常起動時の必読物にしない。Round summaryは履歴であり、Agentが過去Markdownを順に読む必要はない。現行`next_round_brief.json`は`orchestrator_brief.json`と重複させず、廃止するか、completed Round時点のimmutable snapshotへ限定する。

Nodeの`dependencies`をDAG依存の正本とし、可視化用Edgeはそこから導出する。長いNode差分や履歴をSummary Markdownへ列挙せず、必要ならmachine-readable manifest／ledgerへ分離する。

## 5. OrchestratorとInterpretationの関係

Interpretationは次の順序で制御する。

```text
Human request
    |
    v
cs-conductor-orchestrator Agent       唯一のState writer
    |
    | 1. NI####をStateに計画し、EvidenceとID blockを予約
    v
cs-conductor-runtime
    |
    | 2. exact identityとoutput directoryを渡す
    v
cs-analysis-interpret-evidence Skill  context作成・機械draft
    |
    | 3. draft、Evidence、Operator reportを渡す
    v
cs-conductor-interpreter Agent        意味解釈のみ
    |
    | 4. interpretation.jsonをagent_interpretedへ更新
    v
cs-analysis-interpret-evidence Skill  validate・Markdown/HTML render
    |
    | 5. execution_eventを検証
    v
cs-conductor-orchestrator Agent
    |
    | 6. Stateへrecordし、AuditとRound close gateを確認
    v
Round checkpoint/completed
```

Interpreter Agentは次を行わない。

- State、DAG、ID counter、salience ledgerの直接更新
- 新しいDescription／Grouping／Operator／Interpretation Nodeの計画
- resource承認、Questionの人間判断変更
- 別Agentの起動

InterpreterはState予約済みの一つの`NI####` directoryだけを編集する。Analysis Requestは提案artifactとして返し、OrchestratorがCatalog、重複、予算、Question判断を検証してからNode化する。

### 5.1 Interpreter異常終了

同じ`NI####`、同じID reservation、同じoutput directoryを使って再開する。異常終了だけを理由に新しいInterpretation Nodeや新しいID blockを作らない。

- final JSONとrender済み成果物が有効なら、再解釈せずStateへ登録する。
- draftのみなら、同じNIをInterpreterへ再提示する。
- reportが部分編集状態なら、Audit結果とschema validationを基に再開または再試行する。
- 新しいfocusまたは新しいEvidence集合を意図的に解析するときだけ、別の`NI####`を計画する。

OrchestratorからInterpreter Agentを起動できない環境では、`NI####`内にInterpreter用handoffを生成し、main sessionが同じInterpreter Agentを一度だけ起動できるfallbackを用意する。この場合もInterpreterはStateを書かず、完了後にOrchestratorを再開してrecordする。

## 6. Single Writer Leaseと異常終了復旧

### 6.1 Round lease

active Roundへ論理的な書込みleaseを導入する。

```json
{
  "controller_epoch": 2,
  "orchestration_lease": {
    "round_id": "RND0002",
    "token_hash": "...",
    "acquired_at": "...",
    "heartbeat_at": "...",
    "expires_at": "...",
    "status": "active"
  }
}
```

- State変更commandは有効なlease tokenを要求する。
- read-only status、audit、state reportはleaseを要求しない。
- 期限だけを根拠に計算を自動再実行しない。
- 別Orchestratorへのtakeoverは、停止確認と理由を伴う明示操作とする。
- Round closeまたは明示的releaseでleaseを解放する。
- 長時間処理ではheartbeatまたはHPC job情報により生存状況を記録する。

Claude Code上で二つ目のSubagent processが物理的に起動される可能性まではrepositoryから完全に排除できない。保証対象は論理的Single Writerである。二つ目のOrchestratorはbootstrapで既存leaseを検出し、planning、Node start、record、Round mutationを行わず終了する。leaseがstaleに見える場合も自律的に強奪せず、Auditと人間確認を経てtakeoverする。

### 6.2 Recovery mode

新しいOrchestratorが停止したAgentを引き継ぐ場合、最初は`recovery` modeとする。次を完了するまで新規planningを禁止する。

1. `cs-conductor-run-audit`実行
2. active／stale lease確認
3. `running` Nodeと実process／HPC job／artifactの照合
4. orphan `execution_event.json`の検証
5. pending Nodeと未完了planning batchの確認
6. Interpretation gateの確認
7. 人間承認付きtakeover

### 6.3 Execution attempt

Node IDは科学的な一実行定義を表し、retryはNode内のattempt historyとして管理する。

```json
{
  "node_id": "NO0042",
  "status": "running",
  "execution_attempts": [
    {
      "attempt_no": 1,
      "controller_epoch": 1,
      "status": "interrupted",
      "started_at": "...",
      "finished_at": "...",
      "reason": "orchestrator_terminated"
    },
    {
      "attempt_no": 2,
      "controller_epoch": 2,
      "status": "running",
      "started_at": "..."
    }
  ]
}
```

新しいattemptは新しいNode IDを消費しない。不完全な成果物を上書きする必要がある場合は、attempt別の一時領域を使い、検証に成功したartifactだけをNode正本として確定する。

## 7. Audit Skill

### 7.1 出力先

Auditは他のCONDUCTOR成果物と同じRun rootへ保存する。

```text
results/CONDUCTOR/<project>/<run-id>/
├─ state.json
├─ description/
├─ grouping/
├─ analysis/
├─ interpretation/
├─ audit/
│  └─ 20260808T120000000000Z/
│     ├─ audit.json
│     ├─ audit.md                    # Full Auditまたは異常検出時
│     └─ recovery_plan.json       # 復旧候補がある場合
├─ rounds/
├─ indices/
└─ summaries/
```

Auditは科学解析結果ではなくcontrol-plane検査なのでDAG Nodeにしない。各Round manifestは、終了判定に使用したAudit artifactのpathとhashを参照できる。

### 7.2 監査項目

- active Roundとactive leaseがそれぞれ一つ以下であること
- Node ID、entity ID、counter、Edge、dependency、DAG非循環性
- `analysis_signature`の重複
- Node statusとexecution attemptの整合
- `running` Nodeのheartbeat、process／job情報、成果物
- State未登録のexecution event、欠落artifact、hash不一致
- parallel limitとRound resource envelope
- planning batchの由来、件数、重複、未完了状態
- Group／Evidence／Interpretation indexの参照整合性
- Interpretationのdraft／agent_interpreted状態
- 最新成功Operatorを包含する成功Interpretationの有無
- `interpretation.md`と`interpretation.html`の存在
- State summary、Round handoff、indexの再構築可能性
- package snapshot差分とruntime packageへの誤書込み

監査結果は`pass`、`warning`、`error`、`blocked`と安定したcheck codeで記録する。AuditはStateを修正せず、安全な修復候補だけを`recovery_plan.json`に出す。実際の修復はOrchestratorがruntime commandを使って実行し、曖昧な判断には人間確認を要求する。

### 7.3 Quick AuditとFull Audit

毎回の再開で重い監査を行わない。監査を二段階に分ける。

**Quick Audit**は新しいsessionのbootstrapと主要control step前に実行し、短時間で次を確認する。

- State schema／hashとpackage gate
- active Round／lease／controller epoch
- running／interrupted Nodeとparallel limit
- active planning batchとbudget
- Interpretation gateと主要blocker

結果は`orchestrator_brief.json`へ要約し、詳細Audit Markdownを通常読込させない。

**Full Audit**は次の場合に実行する。

- Orchestrator／Interpreter／scientific Skillの異常終了後
- takeover前
- Quick Auditがwarning、error、blockedを返したとき
- Round終了前
- 人間が明示的に依頼したとき

新しいplanning batch作成前はQuick Auditを原則とし、異常がある場合だけFull Auditへ昇格する。

## 8. Planning batchとNode数制御

初期解析の科学的coverageは狭めない。変更するのはNodeの先行登録量と由来管理である。

### 8.1 Planning preview

`plan-basic`、`plan-initial-global`、`plan-initial-local`、`plan-additional`、`plan-deep-dive`は、commit前に次を返せるようにする。

- candidate cell数
- 新規Node予定数
- 既存signatureにより除外される数
- Description／Grouping／Operator／scope別内訳
- 概算cost
- planning batch hash

### 8.2 段階的なmaterialization

`--max-new-nodes`とdeterministic cursorを使い、一回のbatchで登録するNode数を制限する。未登録候補は巨大なDAG Nodeとして保持せず、candidate set hash、cursor、coverage summaryだけをplanning ledgerへ保存する。

初期探索は必要batchを重ねて最終的に必須coverageを満たす。batch化は解析省略ではない。

### 8.3 重複防止と予算

- 同じRound、plan kind、candidate hash、parameter、cursorのbatchはidempotentにする。
- Nodeへ`planning_batch_id`と`controller_epoch`を記録する。
- `max_additional_nodes`を一回のCLI引数ではなくRound累積上限として強制する。
- `state start`のlock内でrunning Node数を再確認し、複数workerでもparallel limitを超えないようにする。
- Recovery modeでは既存pending Nodeを優先し、新しいbatchを作らない。

### 8.4 Planningにおける推論境界

Runtimeはeligible cell、必須coverage gap、既実施signature、cost、resource残量、balanced candidateを生成するが、深掘りの科学的focusを自律決定しない。

- 基本計算・初期探索: 人間承認済みProfileが定義するため、mechanical planningを許可する。
- 追加探索: Profileとseedに基づくbalanced samplingを許可する。
- 深掘り: OrchestratorがFinding／Question／人間指示を解釈してfocusを選び、Runtimeは選択後の適用可能Nodeだけを構築する。
- 人間指定解析: Orchestratorが依頼を構造化し、RuntimeがCatalog、dependency、重複、予算を検証する。

これにより、候補生成と安全検証は決定論的にしつつ、科学的な着眼点はLLMへ残す。

## 9. Interpretation close gate

Round内に成功したOperator Evidenceがある場合、`checkpoint`または`completed`には次を必須とする。

1. 現Roundに成功したInterpretation Nodeがある。
2. `report_status=agent_interpreted`かつ`agent_review.completed=true`である。
3. `interpretation.json`、`interpretation.md`、`interpretation.html`が存在し、hashがStateと一致する。
4. 最新Interpretationが、最後に成功したOperatorより後に確定している。
5. 最新OperatorのうちInterpretation対象外としたEvidenceが明示されている。

State summaryとAuditに次のviewを追加する。

```json
{
  "interpretation_gate": {
    "required": true,
    "status": "missing",
    "latest_interpretation_node_id": null,
    "uncovered_operator_node_ids": ["NO0042"]
  }
}
```

statusは`not_required`、`missing`、`draft`、`stale`、`ready`を基本とする。条件未達では`round-end`を拒否する。人間中断や外部job待ちは`paused`とし、未完成なのに通常checkpointとして閉じない。Operator Evidenceがない基本計算専用Roundは、理由を記録してInterpretationを`not_required`にできる。

`interpretation_iterations`は単なるmetadataにせず、一つのNIに対する意味レビューpassの上限または目標として定義する。Agent異常終了によるretryは新しいNIや新しい科学的iterationとして数えない。

Agent processの異常終了自体は防止対象としない。保証するのは、異常終了時に未完成Roundを完了扱いにせず、`recovery_required`として同じRound、Node、NI、ID reservationから再開できることである。Orchestratorの完了報告もStateのgateが`ready`になった後だけ許可する。

## 10. Skill／Agent名称と起動契約

人間向けの正式入口は`cs-conductor-orchestrator` Agentとする。現行の同名Skillは`cs-conductor-runtime`へ改名し、Agentへpreloadする内部Skillとする。

推奨指示は次の意味へ統一する。

> `cs-conductor-orchestrator` Agentを一つだけ使用し、指定したstate.jsonのactive Roundを監査してから継続する。既存Orchestratorが停止している場合は、新規計画を作らずrecovery modeで引き継ぐ。

文書、prompt、installer、Catalog、Agent frontmatter、layout verifierから「Orchestrator Skillを人間が直接起動する」表現を除去する。AuditとState reportは補助Skillとして明示的に区別する。

### 10.1 Bounded-context bootstrap

新しいsessionは長いPolicy、Design Spec、Catalog、raw State、過去Round Markdownを一括読込しない。Orchestratorは次の一つの入口から開始する。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" bootstrap \
  --state /path/to/state.json
```

`bootstrap`はQuick Audit、State summary更新、lease確認を行い、`summaries/orchestrator_brief.json`を生成して同じ内容を返す。Orchestratorは通常このbriefだけを読み、必要時に限定queryを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" query-node --state /path/to/state.json --node-id NO0042
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" query-question --state /path/to/state.json --question-id Q0017
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" query-evidence --state /path/to/state.json --evidence-id E000241
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" query-batch --state /path/to/state.json --batch-id PB0012
```

Agent／Skill本文には、role、禁止事項、状態遷移、command contractだけを短く保持する。詳細Policy、Design Spec、Catalogはpackage変更、特殊なpolicy判断、Audit不整合、明示的参照が必要な場合だけ読む。特定LLM名はruntime文書へ記載しない。

### 10.2 Briefのaction contract

Briefは「よしなに次を選ぶ」長文ではなく、機械可読なaction contractを返す。

```json
{
  "mode": "normal",
  "required_control_action": "EXECUTE_PENDING",
  "scientific_decision": null,
  "allowed_action_codes": ["EXECUTE_PENDING", "PAUSE_FOR_HUMAN"],
  "blockers": [],
  "detail_pointers": {}
}
```

科学的選択が必要な場合は、control actionと混在させない。

```json
{
  "mode": "normal",
  "required_control_action": null,
  "scientific_decision": {
    "type": "SELECT_DEEP_DIVE_FOCUS",
    "eligible_options": [
      {"question_id": "Q0017", "coverage_gain": "...", "estimated_cost": "..."}
    ]
  }
}
```

基本action codeは`BOOTSTRAP`、`RECOVER`、`WAIT_RUNNING`、`EXECUTE_PENDING`、`PLAN_REQUIRED`、`PLAN_ADDITIONAL`、`PREPARE_INTERPRETATION`、`FINALIZE_ROUND`、`ASK_HUMAN`とし、曖昧な自由文だけで状態遷移を指示しない。

## 11. 実装対象

### 11.1 主対象

- `.claude/agents/cs-conductor-orchestrator.md`
- `.claude/agents/cs-conductor-interpreter.md`
- `.claude/skills/cs-conductor-orchestrator/`から`cs-conductor-runtime/`への再編
- `.claude/skills/cs-conductor-run-audit/`の新設
- `.claude/skills/cs-analysis-interpret-evidence/`
- `CONDUCTOR_modules/tools/templates/state_manager.py`
- audit／recovery／planning batch用template
- `CONDUCTOR_modules/schemas/`
- `CONDUCTOR_modules/catalog/`
- `CONDUCTOR_modules/tools/install_into_project.py`
- package layout／Catalog生成・検証tool
- prompt、Policy、Design Spec、Output Contract、User Guide、identifier reference
- State Manager、contract、fault recovery、package layoutのtests

### 11.2 原則変更しない対象

- Description Skillの数値計算部分
- Grouping Skillのcluster／membership計算部分
- Operator Skillの数式と主要数値CSV
- MCS sampling、metric dispatchなど検証済み科学Kernel
- 一般利用時の`--conductor`なしの入出力
- 各科学SkillのPixi環境

## 12. 実装工程

### Phase 0: Baselineと変更境界

- 4.3.0の全test、package verifier、Catalog verifierを実行する。
- 保護対象Kernelのhash／golden outputを固定する。
- 現行State、planner、Interpretation workflowのfault pointをfixture化する。

完了条件: control-plane変更による科学数値差を検知できる。

### Phase 1: Runtime名称分離

- Orchestrator Skillを`cs-conductor-runtime`へ改名する。
- Agent preload、Catalog、installer、文書、test参照を更新する。
- 人間向けAgentと内部Skillの起動契約を明確化する。

完了条件: 「Orchestrator」はAgentだけを意味し、内部Skillとの曖昧性がない。

### Phase 2: State階層とbounded bootstrap

- `state.json`、`state_summary.json`、`orchestrator_brief.json`のschemaと生成責務を定義する。
- `bootstrap`と限定query commandを実装する。
- Summary配列へ上限、overflow count、detail pointerを導入する。
- Round summaryの全Node列挙をmachine-readable manifestへ分離する。
- raw State、全Catalog、長文Policyの毎session必読指示をAgent／Skillから除去する。

完了条件: 新Agentが一つのbounded briefだけから通常再開でき、Round／Node／Evidence総数に比例して通常contextが増えない。

### Phase 3: Lease、controller epoch、execution attempt

- State schemaを2.1系へ更新する。
- claim、heartbeat、release、takeover、recovery modeを実装する。
- mutating commandへlease検証を追加する。
- Nodeへexecution attempt履歴を追加する。
- stale command lockの検出と人間承認付き復旧を実装する。

完了条件: 二つ目のOrchestratorが同じRoundを変更できず、停止後は同じNodeで復旧できる。

### Phase 4: Audit Skill

- `cs-conductor-run-audit`を独立Skillとして実装する。
- State／DAG／artifact／lease／Interpretation gate検査を決定論的scriptにする。
- Quick AuditとFull Auditを分離し、bootstrapではQuick Auditだけを実行する。
- `run_root/audit/<timestamp>/`へJSON／Markdown／必要時recovery planを出力する。
- read-only性をState hash比較testで保証する。

完了条件: 異常終了後に、新規Nodeを作らず復旧可否と必要操作を判断できる。

### Phase 5: Planning batch

- preview、batch hash、ledger、cursor、`--max-new-nodes`を実装する。
- Round累積予算を強制する。
- `state start`でparallel limitを再検証する。
- 初期global／localの必須coverage判定をbatch対応にする。
- Runtimeが候補と制約を返し、科学的focusをOrchestratorへ残すcontractを実装する。

完了条件: coverageを維持したまま、一度の操作で意図せず数千Nodeが登録されない。

### Phase 6: Interpretation制御

- NI作成、draft、Interpreter review、render、recordを明示的な状態遷移にする。
- Interpreter retryでNIとID reservationを再利用する。
- Agent呼出し不能時のhandoff fallbackを実装する。
- `interpretation_iterations`の意味と履歴を実装する。
- Interpretation close gateを`round-end`へ追加する。

完了条件: Operator EvidenceがあるRoundをInterpretationなしで正常終了できない。

### Phase 7: RecoveryとRound handoff

- resume時にbootstrapとQuick Auditを必須化し、異常時だけFull Auditへ昇格する。
- orphan event、partial artifact、外部job継続、interrupted attemptを分類する。
- Round summaryへcontroller epoch、planning batch、Audit、Interpretation gateの集約値とpointerを追加する。
- 次sessionがconversation履歴や過去Markdownなしで復旧できるbounded briefを生成する。

完了条件: Orchestrator／Interpreterの強制停止位置にかかわらず、安全な継続手順が一意に得られる。

### Phase 8: 文書、package、prompt

- Policy、Design Spec、Output Contract、User Guide、identifier referenceを4.3.1へ同期する。
- 新規Run、Round継続、異常終了後の復旧、Interpretationのみ再実行のpromptを更新する。
- 状態管理を「正本の台帳、事実のdashboard、行動カード、監査記録」の四概念で説明する短い人間向け文書を追加する。
- 特定LLM名を記載せず、bounded context、explicit action code、deterministic controlというmodel-neutral契約を記載する。
- installer、included skills、Catalog、layout verifierを更新する。

完了条件: Projectへpackageを配置した後も、一つのAgent入口と補助Skillの役割が理解できる。

### Phase 9: 総合試験

- unit、contract、end-to-end、fault injection、concurrency testを実行する。
- Windowsで全自動試験を実行する。
- Linux共有filesystem、共有Pixi、HPC job継続は配置環境で受入試験する。

完了条件: Definition of Doneを満たし、未検証環境と既知制約が記録される。

## 13. 試験計画

### 13.1 排他・復旧

- 同じStateへ二つのOrchestratorがclaimし、一方だけ成功する。
- 二つのSubagent processが存在しても、非ownerはread-only bootstrap以外のmutating commandを実行できない。
- Agent停止後、takeover前にはplanningが拒否される。
- takeover後も既存pending Nodeを再利用する。
- 同じNodeのretryでNode counterが増えない。
- ID counterが実在最大ID以上であり、重複IDと不正なAgent生成IDが拒否される。
- stale lockを無断削除しない。

### 13.2 Fault injection

次の各時点でprocessを停止し、新sessionから復旧する。

1. Node計画commit前後
2. `state start`直後
3. scientific artifact生成中
4. `execution_event.json`生成後、State record前
5. Interpretation draft生成後
6. Interpreter編集途中
7. Markdown／HTML render後、State record前
8. State record後、Round end前

### 13.3 Planning

- preview件数と実際の新規Node数が一致する。
- 同じbatchの再実行がNodeを増やさない。
- 異なるbatchの由来がNodeとledgerから追跡できる。
- Round累積budgetとparallel limitを超えない。
- batch化後も初期global／localの必須coverageが減らない。

### 13.4 Interpretation

- Operator成功、NIなしでRound closeが拒否される。
- draft NIでRound closeが拒否される。
- Markdown／HTML欠損でRound closeが拒否される。
- NI成功後に新しいOperatorが成功すると`stale`になる。
- 同じNIのInterpreter retryが同じID reservationを使う。
- InterpreterがStateを書こうとするとcontract testで失敗する。

### 13.5 Audit

- Audit前後でStateと科学artifactのhashが変わらない。
- duplicate signature、cycle、counter不整合、orphan event、stale running、missing reportを検出する。
- 正常resumeはQuick Auditだけで完了し、異常時にFull Auditへ昇格する。
- 出力が必ず`run_root/audit/<timestamp>/`に作られる。
- 4.3.0 Stateをread-onlyで検査し、暗黙migrationしない。一回限りのMigration Agent／Skillは、承認済みplanに従って別run rootだけを作成する。

### 13.6 Bounded contextと役割境界

- Round数、Node数、Evidence数を増やしても`orchestrator_brief.json`の配列と構造が上限を超えない。
- overflowはcountとdetail pointerで表現される。
- 新sessionがbriefだけからnormal、recovery、blocked、interpretation requiredを判別できる。
- Orchestrator Agent／Runtime Skillにraw State、全Catalog、複数長文Markdownの毎session必読指示が残っていない。
- `required_control_action`と`scientific_decision`が同一fieldへ混在しない。
- Runtimeが深掘りfocusやFindingの重要性を自動決定しない。
- 人間向け状態管理説明が、三つのactive状態fileとAuditの関係を一枚の図または短い表で説明する。

## 14. リスクと抑制策

| リスク | 抑制策 |
|---|---|
| leaseが残り、新Agentが継続できない | Auditと明示的takeoverを用意し、無断強奪はしない |
| 長時間HPC jobを停止と誤判定する | heartbeatだけでなくjob ID、host、process情報、artifactを照合する |
| Skill数増加で人間操作が複雑になる | 通常入口はOrchestrator Agent一つ。runtimeは内部、Auditは自動＋任意手動に限定する |
| Runtimeが巨大な万能Skillになり理解しにくい | 人間向けSkillは増やさず、内部module／subcommandと明示的action codeで責務を分ける |
| control actionが科学的判断を置き換える | `required_control_action`と`scientific_decision`をschemaで分離し、深掘りfocusはOrchestratorへ残す |
| SummaryとbriefがRun成長に伴い長文化する | array cap、overflow count、query pointer、bounded-context testを必須化する |
| 新Agentが長文Policyや全Catalogを再読する | bootstrap briefを唯一の通常入口とし、詳細文書は例外時の限定参照にする |
| Auditが新たなState writerになる | read-onlyを設計・testで強制し、repairをruntimeへ分離する |
| batch化が解析省略として働く | phase completionを必須coverageで判定し、未登録候補のcursorを保持する |
| Node番号が依然大きくなる | 網羅解析では許容し、batch／由来／予測件数を可視化する。番号の大きさ自体を異常判定に使わない |
| Interpretation Agent停止でRoundが閉じない | 同一NI retry、handoff fallback、close gate、paused状態を用意する |
| control plane変更が科学Kernelへ波及する | Kernel golden testと変更境界をPhase 0で固定する |
| 4.3.0 Stateの不完全migration | source非変更、別target、dry-run、明示承認、artifact hash検証、旧Interpretation除外を強制する |

## 15. Definition of Done

- `cs-conductor-orchestrator` Agentが唯一のState writerとして動作する。
- 同じRoundで複数Orchestratorが書込み権を同時取得できない。
- 二つ目のOrchestrator processが起動されても、lease非ownerとしてStateを変更せず終了する。
- Agent異常終了後、Auditとtakeoverを経て同一Round／同一Nodeを再開できる。
- retryで新しいNode IDを消費せず、attempt履歴を保持する。
- ID採番、signature、counter、planning batchがRuntimeとAuditで一貫して管理され、AgentがIDを合成しない。
- 計画のpreview、batch、由来、予算、coverageを監査できる。
- 初期解析の科学的な広さを維持する。
- 成功Operator Evidenceを含むRoundは、最終Interpretationなしでcheckpoint／completedにならない。
- Agent異常終了時はRoundを完了扱いにせず、同一NIとID reservationからInterpretationを再開できる。
- Interpreter Agent、Interpretation Skill、Orchestratorの責務境界が実装と文書で一致する。
- Auditが`run_root/audit/<timestamp>/`へ出力され、Stateと科学artifactを変更しない。
- 人間向け通常入口はOrchestrator Agent一つであり、補助Skillを意識せず通常運用できる。
- active状態は`state.json`、`state_summary.json`、`orchestrator_brief.json`の三層で説明できる。
- Orchestratorは通常`orchestrator_brief.json`だけを読み、raw State、全Catalog、複数長文Markdownを再読しない。
- Briefはboundedであり、`required_control_action`と`scientific_decision`を分離する。
- Runtimeは決定論的な候補生成・制約検証を担当し、科学的focusと重要性判断をOrchestrator／Interpreterへ残す。
- Description、Grouping、Operatorの保護対象Kernelが4.3.0のgolden regressionを維持する。
- `CONDUCTOR_modules/`へruntime結果を書き込まない。
- Windows自動試験が合格し、Linux HPC受入項目が明記される。
