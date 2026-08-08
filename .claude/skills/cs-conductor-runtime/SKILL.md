---
name: cs-conductor-runtime
description: Deterministically initialize, resume, inspect, plan, execute, audit-gate, and close a CONDUCTOR multi-Round DAG. Use internally from the cs-conductor-orchestrator Agent, or when a human explicitly requests a partial CONDUCTOR State update. Do not use as a scientific analysis method or for general non-CONDUCTOR execution.
---

# CONDUCTOR Runtime

このSkillは推論を代替せず、Orchestratorが選んだ科学的行動を安全にStateへ反映する。Node ID、署名、依存関係、lease、parallel limit、Wall Time、実行attempt、Interpretation終端条件は必ずCLIに判定させる。

## 最短の開始・再開手順

1. 新規Runだけ `state init ...` を実行する。
2. セッションごとに一意な短い `owner-id` を決め、`state bootstrap --state <state.json> --owner-id <id>` を1回実行する。
3. `lease_acquired=false` なら別のWriterが稼働中である。Stateを変更せず終了する。
4. `lease_acquired=true` なら返された `lease_token` を保持し、以降の全変更コマンドへ `--lease-token` を渡す。tokenをファイルへ保存しない。
5. 通常は `summaries/orchestrator_brief.json` の `required_control_action` を上から処理する。科学的選択だけ `scientific_decision` を根拠にOrchestratorが判断する。
   移行済みStateの`MIGRATION_HANDOFF_REQUIRED`は実行要求ではない。現在の人間メッセージが移行後Roundの開始を明示した場合だけ、`round-start --accept-migration`を実行する。
6. 長時間処理中は `heartbeat` でleaseを更新する。
7. Round終了前にInterpretationを成功記録する。`checkpoint` / `completed` はJSON・Markdown・HTMLが揃わなければ拒否される。
8. 正常終了時は `release-lease` を実行する。

すべてのコマンドは次のlauncher経由で実行する。

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state <command> ...
```

launcherは共有Pixiを優先し、`PIXI_CACHE_DIR`、`UV_CACHE_DIR`、一時DirをすべてSkillの `env/` 配下へ設定する。

## 制御アクション

- `MIGRATION_HANDOFF_REQUIRED`: 人間の明示的な移行後Round開始指示がある場合だけ`round-start --accept-migration`
- `PLAN_BASIC`: `plan-basic`
- `REQUEST_BASIC_BUNDLE_APPROVAL`: 人間に一括承認を求め、`approve-basic-bundle`
- `PLAN_INITIAL_GLOBAL`: `plan-initial-global`
- `PLAN_INITIAL_LOCAL_BATCH`: 指定batch sizeで`plan-initial-local`を反復する
- `PLAN_BALANCED_ADDITIONAL`: 未実施cellからseed付き`plan-additional`を実行する。科学的に妥当な深掘りを同時候補として比較できる
- `EXECUTE_RUNNABLE_BATCH`: `runnable`で対象を確認し、Nodeごとに `start` → 専門Skill → `record`
- `CREATE_OR_COMPLETE_INTERPRETATION`: `add-interpretation`後、`cs-conductor-interpreter`へ同じNI Nodeの完成を依頼し、`record`
- `ROUND_CLOSE_READY`: Full Auditを実行してから `round-end`
- `STOP_SCIENTIFIC_EXPANSION`: 新規科学Nodeを増やさずInterpretationと監査へ移る

Node失敗後の再試行は新Nodeを追加せず、同じNodeを `start --retry` する。Interpreterの再試行も同じNIを完成させる。最終Interpretationは最後の成功Operatorより後に完成している必要があり、後発Operatorがある場合はRound終端用としてstaleになる。

## 事故復旧

期限切れleaseは通常の `bootstrap` で引き継げる。まだ有効なleaseの強制取得は、人間が重複Writerでないことを確認した場合だけ `--force-takeover --takeover-reason <理由>` を使う。取得後はFull Auditを実行し、`running` Nodeを無条件で再実行せず、artifact/eventの有無を確認する。

## 部分実行

人間が特定のDescription、Grouping、Operator、Interpretationを指示した場合も、先にbootstrapしてから `add` または `add-interpretation` でDAGへ登録する。出力Dirを手作業で決めたりNode IDを手入力したりしない。

## 読み込み規律

通常再開時に長いPolicy全文や全Stateを読む必要はない。順序は `orchestrator_brief.json` → 必要なら `state_summary.json` → `query`で指定Node/Evidence/Question。Full EvidenceとPolicyは科学的判断に必要な範囲だけ読む。

## 禁止事項

- `state.json` の直接編集
- lease tokenなしの変更、tokenの共有ファイル保存
- 複数Orchestrator Writerの並列実行
- Round終端ゲートの回避
- retryのための別Node生成
- Wall Timeを「必ず使い切る時間」または単なるメモとして扱うこと
