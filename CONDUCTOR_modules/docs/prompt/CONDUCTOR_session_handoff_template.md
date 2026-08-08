# CONDUCTOR Session Handoff

このMarkdownは人間向けnavigationである。正本は`state.json`、各Round artifact、各科学計算artifactとする。Orchestratorの通常入口は`orchestrator_brief.json`であり、この長文handoffを必須入力にはしない。

## Run identity

- State:
- Run ID:
- Project:
- Input:
- Endpoint:
- Higher is better:
- Package／profile snapshot:

## Round

- Activeまたは直近Round:
- Status:
- 次に期待するRound:
- 開始時の人間指示:
- Stop reason:

## Coverage

- Basic compute:
- Initial global:
- Initial local:
- Additional exploration:
- Deep dive:
- Failed／unavailable／waived:

## Knowledge frontier

- Priority Finding:
- Active Hypothesis:
- Active Question:
- Human-skipped／deferred Question:
- Unresolved contradiction:
- Human-pinned Evidence:

## Pending work

- Runnable Node:
- Approval待ち:
- HPC job:
- Coverage gap:
- Reopen recommendation:

## 参照artifact

- Latest `orchestrator_brief.json`:
- Latest `state_summary.json`:
- Latest `round_summary.json`:
- Latest `next_round_brief.json`:
- Latest `interpretation.html`:
- Operator report:

## 次のセッション

```text
`cs-conductor-orchestrator` Agentを使用して、既存CONDUCTOR Runの解析Round <RND####>を開始してください。
同Roundがactiveなら再開してください。
State: <ABSOLUTE_STATE_JSON_PATH>
今回の重点: <任意>
最初にbootstrapで単一Writer leaseを取得し、Round close前にInterpretationとFull Auditを完了してください。
```
