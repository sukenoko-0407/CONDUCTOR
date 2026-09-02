---
name: cs-conductor-orchestrator
description: Activate the Claude Code Main Agent as the CONDUCTOR 0.1.9 Orchestrator for exactly one human-authorized Round.
disable-model-invocation: true
allowed-tools: Read, Bash, Agent
---

# Main Agent Orchestrator 0.1.9

このSkillはMain Agentでだけ有効化する。Subagentとして起動せず、Projectの`CLAUDE.md`を変更しない。人間が明示した一つのRoundだけを進め、新しいRoundを勝手に開始しない。

## 開始

新規Runは`init`、`prepare-round`、人間承認後の`authorize-round`、`resume-round`の順。既存Runは最初にRuntime `query`だけを呼び、DAGや過去Reportを全読込しない。CPU未指定は8。高コストDescriptionは一括承認を一回だけ求める。

期限切れLeaseを再取得する際、同一hostで実行中のRuntime processが検出されたら再取得しない。異なるhostまたは旧形式の`running` Nodeが残る場合も自動回収せず、旧process停止を人間が確認した場合だけ`resume-round --confirm-interrupted-running`を使う。

すべてのRuntime操作は次のLauncher経由とし、JSONを直接編集しない。

```bash
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py <COMMAND> ...
```

## 固定ループ

Runtime応答の`required_action.code`を一つだけ実行する。

| code | 実行 |
|---|---|
| `AWAIT_HUMAN_ROUND` | 停止する。人間から新Roundの明示指示があるまで`prepare-round`しない |
| `AUTHORIZE_ROUND` | `request_file`の目的、資源、Parameter、高コスト承認状態を人間へ示す。明示承認後だけ`authorize-round`する |
| `AWAIT_HUMAN_REVIEW` | 停止する。Interpretationと監査の完了を報告し、人間のAccept指示後だけRoundを閉じる |
| `ROUND_PAUSED` | 停止する。人間が追加Wall Timeを指定した場合だけ同じRoundを`continue-round`する |
| `PLAN_BASIC` | `plan-basic` |
| `HUMAN_APPROVAL_REQUIRED` | 人間へ一括承認を求める |
| `EXECUTE_RUNNABLE_BATCH` | `prepare-execution-packet`後、返されたpathを`execute-packet --packet`へ一回渡す |
| `WAIT_RUNNING` | 再投入せず待つ |
| `FAILED_NODE_REPAIR_REQUIRED` | 他の独立Nodeを試行し終えた後、diagnosticを人間へ示し、修正後は同じNodeをretryする。推測CLIで代行しない |
| `HUMAN_SERIES_REVIEW_REQUIRED` | accepted Series数が24を超えたことと、参考値として実解析単位数を示す。人間が現条件を承認したら`approve-series`、変更指示なら`revise-series` |
| `PLAN_STANDARD` | `plan-standard` |
| `PREPARE_INTERPRETATION` | `prepare-interpretation` |
| `WRITE_INTERPRETATION` | `cs-conductor-interpreter`を一つ起動し、draft完成後`commit-interpretation` |
| `RUN_FULL_AUDIT` | 現在のLease tokenを渡して`audit --mode full --register` |
| `COMPLETE_FINALIZING` | `complete-finalizing` |
| `PAUSE_ROUND` | `pause-round`。新Roundを作らない |
| `BLOCKED_BASIC` / `BLOCKED_STANDARD` | 停止する。Runtime応答と未完了Nodeを報告し、推測でNodeや依存関係を追加しない |
| `INTERPRETATION_BLOCKED` | 停止する。I001の診断を報告し、同じInterpretation Nodeの修復方針を人間へ確認する |

表にないcodeでは停止して応答をそのまま人間へ示す。MainはDescription、Clustering、Operatorを直接Bash実行しない。`execute-packet`は同期的に完了まで待つため、短間隔pollや独自実行fileは不要である。

Interpretationは定型Report完成後の一回だけ。On-demand依頼は本Round loopへ入れず、`cs-conductor-on-demand-analysis`を使う。
