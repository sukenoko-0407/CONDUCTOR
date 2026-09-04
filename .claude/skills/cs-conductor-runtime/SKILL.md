---
name: cs-conductor-runtime
description: Deterministic CONDUCTOR 0.1.10 state, DAG, execution-request, Series gate, reporting, audit, and Round controller.
allowed-tools: Read, Bash
---

# CONDUCTOR Runtime 0.1.10

Runtimeだけが`conductor_control.json`と`runtime/dag.json`を更新する。Node状態は`pending/running/succeeded/failed/cancelled`の5種類。Main AgentはJSONを直接編集しない。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state <command> ...
```

## 一意の制御順序

`PLAN_BASIC` → `plan-basic` → `EXECUTE_RUNNABLE_BATCH`を反復 → 必要なら`HUMAN_SERIES_REVIEW_REQUIRED` → `PLAN_STANDARD` → `plan-standard` → 実行反復 → `PREPARE_INTERPRETATION` → `WRITE_INTERPRETATION` → `RUN_FULL_AUDIT` → `COMPLETE_FINALIZING` → `AWAITING_HUMAN_REVIEW`。

`prepare-execution-packet`の返す`packet_path`は次の固定形で渡す。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" state execute-packet --run-root <RUN_ROOT> --packet <PACKET_PATH>
```

SkillごとのCLIをRuntimeやAgentが推測せず、共通`execution_request.json`を`<skill>/scripts/launch.py --conductor-request`へ渡す。独立して実行可能なNodeを先にすべて試行し、残った失敗は同じNode IDを`retry-node`するか、人間理由付きで`waive-node`する。科学的な0件・非適用はSkillが正常結果として返す。

基本計算は全18 Description、C001-C004、全18×C005-C010、A001/A002、C012。定型解析はA003-A009。Descriptionは`project`をProgram名として`data/description_database/<project>/`から再利用し、未計算化合物だけを計算する。Descriptionごとの高コスト承認分岐は設けない。

C012はまず`min_ff_evaluate=10`のままLeiden resolutionを1.0から3.0まで段階評価し、最初に最終unit数が24以下となる条件を自動採用する。該当がなければ`min_ff_evaluate=10,15,20,25,30`との全Matrixを返し、人間が`select-series-configuration`で選ぶ。25–100件は人間承認で進行でき、101件以上は不可。Runtimeは新Roundを自動開始せず、Wall Time終了時は同じRoundをpauseする。

人間が定型解析の計画前に`min_ff_evaluate`またはLeiden resolutionを独自指定した場合は、`revise-series`で同じRoundへ新しいC012 revisionだけを作る。成功済みDescription、C001-C010、A001/A002は再計算しない。再計算結果が24件を超えた場合は改めて人間gateを置く。

On-demandはRuntime/DAG/Roundの外にあり、Runtime Leaseを要求しない。

Runtime processが強制終了して`running`だけが残った場合、期限切れLeaseからの`resume-round`はそのNodeを`INTERRUPTED_ATTEMPT`へ変換する。旧processが残っていないことを確認してから、同じNode IDをretryする。
