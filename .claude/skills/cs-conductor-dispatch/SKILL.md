---
name: cs-conductor-dispatch
description: Human-authorized entry point for starting, resuming, continuing, revising, accepting, or inspecting a CONDUCTOR 0.1.2 Round. Main Agent must use this Skill before invoking cs-conductor-orchestrator. It does not make scientific decisions.
allowed-tools: Read, Bash
---

# CONDUCTOR Dispatcher

このSkillはMain Agent専用の入口である。Orchestratorを直接起動しない。

## 判定順序

1. 人間が指定したRun Rootの`conductor_control.json`だけを最初に読む。
2. `ACTIVE`／`FINALIZING`なら新Roundを作らず`resume-round`する。
3. `AWAITING_HUMAN_REVIEW`なら、人間の明示指示に従い`continue-round`、`revise-report`、`accept-round`のいずれかを行う。人間が「次Round開始」まで明示した場合だけ、前Roundの`accept-round`と次項の開始を二つの監査可能な操作として順に行う。
4. Active Roundがなく、人間が新Round開始を明示した場合だけ`prepare-round`で契約案を生成する。契約案と人間依頼が一致することを確認して`authorize-round`する。
5. `resume-round`が返したlease token、Action token、Control、Working Setだけを一つの`cs-conductor-orchestrator`へ渡す。
6. Orchestrator起動時のowner IDとControl revisionを保持する。Subagentが戻った後は必ず`verify-return --confirm-returned --owner-id <owner> --start-revision <revision>`を実行し、発言ではなくControl Stateを確認する。Active／Finalizingの同じRoundで進捗があり、Runtimeが再開推奨を返した場合だけreplacementを一つ起動する。進捗なしの帰還が二回続いた場合は再起動せず人間へ返す。

live leaseがある場合は二つ目のOrchestratorを起動しない。期限切れleaseでActive Roundが残る場合は同じRoundを再開する。新Roundは作らない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare-round --run-root /path/to/run --objective "Round目的" --walltime-minutes 480 --parallel-limit 8 --approve-high-cost
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" authorize-round --run-root /path/to/run --request-file <file> --authorization-token <token>
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" resume-round --run-root /path/to/run --owner-id session-001
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" verify-return --run-root /path/to/run
```

Dispatcherは科学候補、Node ID、Status、Interpretation本文を作らない。
