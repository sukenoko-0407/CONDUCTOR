---
name: cs-conductor-orchestrator
description: Manually activate the Claude Code Main Agent as the CONDUCTOR 0.1.3 Orchestrator for one human-authorized Round. Use only when the human explicitly requests CONDUCTOR control.
disable-model-invocation: true
allowed-tools: Read, Bash, Glob, Grep, Agent, Skill
---

# CONDUCTOR Main Orchestrator

このSkillはMain conversation内でだけ有効化する。Subagentとしてforkしない。既存projectの`CLAUDE.md`を変更せず、人間が明示したCONDUCTOR操作だけを処理する。

## 最初の判定

1. 新規Runで`conductor_control.json`がまだ無い場合は、人間が指定した入力CSV、endpoint、`higher_is_better`、project、parallel limit、出力先を使ってRuntime `init`を一回だけ実行する。SMILES列を一意に推定できない場合だけ人間指定の`--smiles-column`を渡す。既存Runでは指定された`run_root/conductor_control.json`だけを最初に読む。
2. 人間依頼を`inspect`、`start new Round`、`resume active Round`、`continue current Round`、`revise report`、`accept Round`のいずれかへ分類する。
3. 新Roundは人間が明示した場合だけ`prepare-round`と`authorize-round`を別操作として行う。曖昧ならStateを変更しない。
4. `ACTIVE`／`FINALIZING`は同じRoundを`resume-round`する。期限切れleaseでも新Roundを作らない。live leaseがあれば二重起動しない。旧RunにSMILES列metadataがなく自動推定もできない場合だけ、人間が示した`--smiles-column`をresume時に記録する。既存値は変更しない。
5. `AWAITING_HUMAN_REVIEW`では、人間が明示した`continue-round`、`revise-report`、`accept-round`以外を行わない。

Runtime操作は必ずこのSkillの`scripts/launch.py`を使う。この薄いlauncherは全Control commandを`cs-conductor-runtime`のPixi環境へ委譲するため、MainがRuntime Controllerを別のPythonから直接起動しない。Runtime JSON／JSONLを直接編集しない。

project rootをworking directoryとし、次の固定形だけを使う。`<LEASE>`と`<ACTION>`は直前のcompact responseが返した値へ毎回置き換える。前のAction tokenを再利用しない。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py <COMMAND> --run-root <RUN_ROOT> --lease-token <LEASE> --action-token <ACTION> <COMMAND固有引数>
```

例外は`init`、`prepare-round`、`authorize-round`、`resume-round`、read-only queryだけである。`authorize-round`と`resume-round`のcontrol authorityはlauncherがRun Rootから注入するため、Mainがkey fileを読んだり引数へ展開したりしない。

## 固定ループ

Runtimeのcompact responseにある`protocol_version`が`0.1.3`であることを確認し、単一の`required_action.code`へ従う。

| required action | Main Agentの操作 |
|---|---|
| `PLAN_BASIC` | Runtime `plan-basic` |
| `PLAN_INITIAL_GLOBAL` | Runtime `plan-initial-global` |
| `PLAN_INITIAL_LOCAL` | Runtime `plan-initial-local` |
| `EXECUTE_RUNNABLE_BATCH` | Runtime `prepare-execution-packet`後、`cs-conductor-executor`を一つだけ起動 |
| `WAIT_OR_RECONCILE_RUNNING` | Runtime `reconcile-running`。別Nodeや別Executorを作らない |
| `RETRY_FAILED_NODE` | failure codeだけを確認し、Runtime `retry-node`。続くpacketは当該Nodeだけに限定してExecutorへ渡し、同一Node IDを維持 |
| `SCIENTIFIC_DECISION` | bounded Working Setから候補を選びRuntime `scientific-decision` |
| `ENTER_FINALIZING` | Runtime `enter-finalizing` |
| `PLAN_INTERPRETATION` | Runtime `prepare-interpretation` |
| `WRITE_INTERPRETATION` | Mainから`cs-conductor-interpreter`を一つ起動し、Runtime `commit-interpretation` |
| `RUN_FULL_AUDIT` | Runtime `audit --mode full --register` |
| `COMPLETE_FINALIZING` | Runtime `complete-finalizing` |

`HUMAN_APPROVAL_REQUIRED`、`HUMAN_REVIEW_REQUIRED`、`INTERPRETATION_BLOCKED`、`AWAIT_HUMAN_ROUND`では停止し、人間へ返す。

`prepare-execution-packet`には`--run-root`、最新の二token、必要なら`--node-ids`だけを渡す。`prepare-interpretation`が返した`node_id`、`context_path`、`draft_path`をそのままInterpreterへ渡し、`commit-interpretation`には同じ`node_id`と`draft_path`を渡す。`audit`は必ず`--mode full --register`とする。これらのpathやIDをMainが再生成しない。

Main sessionを意図的に終了する必要があり、まだlive leaseと現在のAction tokenがある場合は`release-lease`してから返す。Tool応答喪失により最新Action tokenが不明な場合、同じmutationを推測で再送しない。Control revisionを確認し、previous ownerと開始revisionを指定した権限付き`verify-return --confirm-returned`でleaseを回収してから、同じRoundを`resume-round`する。

## Executor契約

- Mainは専門Skillの`launch.py`／`run.py`を直接実行しない。
- Mainは`prepare-execution-packet`が返した`packet_path`と`executor_token`だけを`cs-conductor-executor`へ渡す。lease tokenとAction tokenは渡さない。
- 同じRunに対するExecutorは一時点で一つだけとする。科学Nodeのprocess並列性はRuntimeの`parallel_limit`へ委ねる。
- packet内の論理commandをMainまたはExecutorが再構築・直接実行しない。Runtimeだけが検証後に自身のPythonへ解決する。
- Executorがpacketをstale、expired、invalid、consumedとして拒否された場合、同じpacketや同じExecutorを再起動しない。最新Controlをread-only確認し、単一の`required_action`へ戻る。
- Executorの文章ではなく、Runtimeのcompact resultとControl revisionを確認する。
- Tool call失敗のraw logを通常は読まない。科学判断に必要な場合だけfailure pointerまたはResult Cardをbounded queryする。

## Interpreter契約

- InterpreterはExecutorの子ではなく、Mainが直接起動する兄弟Subagentである。
- `context_path`、`draft_path`、現在のhuman focusだけを渡す。
- Interpreterは固定された既存Evidenceを読み取り、個別結果と横断関係を解釈する。新しい科学計算、Node作成、State更新は行わない。
- draft拒否時は同じInterpretation Nodeを有限回修正する。別Roundや別Interpretation Nodeを勝手に作らない。

## 科学判断

推論が必要なのは`SCIENTIFIC_DECISION`だけである。Global／Cluster-local、兄弟Cluster、異なるDescription family、異なるOperatorのバランスと、人間のpriority、未確認領域、反証候補を考慮する。Node ID、依存関係、Status、Round gateはRuntimeへ委ねる。

Wall Timeは上限であり、早期終了の目標ではない。eligible workがなくなるか契約・budgetが終端を許すまで進め、必ずInterpretation、Full Audit、`AWAITING_HUMAN_REVIEW`まで完了する。人間の明示指示なしに次Roundを開始しない。

## 参照境界

通常読むのは現在の人間依頼、compact response、bounded Working Set、選択したResult Cardだけとする。全DAG、全Ledger、過去全Reportを通常ループで読まない。詳細な科学方針が必要なときだけ`CONDUCTOR_modules/docs/CONDUCTOR_policy.md`の該当箇所を参照する。
