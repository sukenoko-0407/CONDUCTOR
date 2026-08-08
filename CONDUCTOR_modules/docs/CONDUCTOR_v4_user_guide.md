# CONDUCTOR 4.3.1 利用手順

## 1. 前提

- Claude Code project rootに`.claude/skills/`と`.claude/agents/`を配置する。
- `CONDUCTOR_modules/`はproject root直下に配置し、解析中はread-only packageとして扱う。
- 解析結果は`results/CONDUCTOR/`または明示`--output-dir`へ保存する。
- 1 Runは一つのinput、endpoint、`higher_is_better`を扱う。
- compound ID、SMILES、分子標準化は人間が準備する。

## 2. 新しいRun

人間は少なくとも次を指定する。

- input CSV
- endpoint column
- `higher_is_better`
- project名
- parallel limit
- 既定Round envelope
- 高コスト基本計算bundleの承認

Orchestratorはinputを検査し、新しいState、Catalog／profile／Policy snapshot、`RND0001`を作る。Runtimeのbootstrapで単一Writer leaseを取得し、別Orchestratorが同じRunを変更できないようにする。

```text
`cs-conductor-orchestrator` Agentを使用して、新しいCONDUCTOR Runを開始してください。

Input: /absolute/path/input.csv
Endpoint: activity
Higher is better: true
Project: example
Parallel limit: 16
Round envelope: walltime 8 hours, additional nodes 300, Interpretation iterations 3
高コスト基本計算bundleを一括承認します。
```

Wall Timeは最大予算であり、必ず8時間使い切る指示ではない。ただし、時間と実行可能な解析が残る間は、初期探索、balanced追加探索、妥当な深掘りを継続する。終盤はInterpretationと監査の時間を予約する。

## 3. 初回実行

Orchestratorは原則として次の順に進む。

1. `basic_compute`: 全Descriptionとprofile指定Grouping
2. `initial_global`: 全applicable global Operator role
3. Grouping-wide screenと代表Group選択
4. `initial_local`: 代表Groupの全applicable local Operator role
5. Interpretation（JSON、Markdown、HTML）
6. Full Audit、Round summary、`orchestrator_brief.json`

失敗・利用不能Capabilityは無言で除外しない。再試行・代替が不可能な場合は人間が`waived`を判断する。計算が長時間に及ぶ場合は同じRoundをpause/resumeできる。

## 4. Round 2以降

State path、期待Round番号、任意の重点だけで開始できる。

```text
`cs-conductor-orchestrator` Agentを使用して、既存CONDUCTOR RunのRND0002を開始してください。
同Roundがactiveなら再開してください。

State: /absolute/path/to/state.json
今回の重点: Q0007はスルーし、G000124のcross-Description比較を重視してください。
```

重点を省略した場合、Orchestratorは `orchestrator_brief.json` の制御action、未完了mandatory coverage、active Question、balanced random追加探索に基づいて進める。新sessionでも長いMarkdown群を最初から読む必要はない。

Round番号がStateと一致しない場合は、Stateを変更せず報告する。承認応答やsession再開は新Roundとして数えない。

## 5. Questionの人間判断

Questionはすべて深掘りする必要がない。人間は`allow/skip/defer`を指定できる。

```text
State: /absolute/path/to/state.json
RND0003で次を反映してください。
- Q0007: skip
- Q0011: allow
- Q0013: defer
```

`skip`中は自動深掘りしない。後のEvidenceから再検討価値が生じた場合、Interpreterはreopenを提案できるが、人間decisionを変更しない。

## 6. 人間指定の部分解析

既存Run内のDescription、Grouping、Operator、Interpretationを追加する場合も、Skillを直接CONDUCTOR modeで起動せずOrchestratorへ依頼する。

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: /absolute/path/to/state.json
Round: RND0004
G000124に対してD013空間のA006を追加し、globalと比較してください。
```

OrchestratorはQuestionまたは`human_directed` requestとしてNodeを登録し、既存signatureと依存artifactを検証する。

## 7. Interpretationだけを再実行する

同じEvidenceでも別の視点で再解釈できる。新しいInterpretation Nodeを作り、既存HTMLを上書きしない。

```text
`cs-conductor-orchestrator` Agentを使用してください。
State: /absolute/path/to/state.json
Round: RND0005
新しいOperator計算は行わず、Q0011と矛盾Evidenceを重点にInterpretationを再実行してください。
```

Finding、Hypothesis、Question、RelationはRun内IDを引き継ぐ。既存entityの変更はrevisionとして記録する。

## 8. 状態確認

Orchestratorは`orchestrator_brief.json`を入口とし、必要時だけ`state_summary.json`とfocused queryを使う。完全DAG図は人間がState pathを指定して明示依頼した場合だけ`cs-conductor-state-report`を使う。

確認項目は次である。

- active／next Round
- phase別coverage
- pending、running、failed、unavailable、waived
- approval待ち
- active Questionとhuman decision
- untriaged／priority／human-pinned Evidence
- package／profile hash差分

## 9. 一般利用

個別Skillを一般用途で使う場合は`--conductor`を付けない。DescriptionはCSVまたはSMILES、direct structure Clusteringはcompound-ID/SMILES CSV、vector ClusteringはDescription CSV、Operatorは契約に合うCSVを入力する。

一般利用結果はCONDUCTOR Stateへ登録されない。後から同じ結果を自動importする機能は提供しない。

## 10. Package更新

Round開始時にRun snapshotと現在のCatalog、profile、Policy、Skill versionを比較する。差分があればOrchestratorは停止して提示する。人間承認なしに同一Runへ異なる仕様を混在させない。

`state resume`または`round-start`で差分を検出すると、`package_change_gate`が`approval_required`となり、新規Nodeの計画・実行は停止する。人間が差分を確認して同一Runでの継続を許可した場合だけ、次を実行する。

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state approve-package-change \
  --state <STATE_JSON> --approve --rationale "確認した差分と継続理由" --lease-token <SESSION_TOKEN>
```

承認時は以前のsnapshotをhistoryへ保持し、新Packageを別snapshotとして保存する。却下時は`--reject`を使用し、旧Packageを復元するか新規Runを開始する。

## 11. 成果物の読み方

1. `interpretation.html`: 人間向けの主成果物
2. `round_summary.md`: 今回変更された点と次Roundへの引継ぎ
3. `operator_report.html`: Findingの根拠となる個別解析
4. `state_summary.json`: Agent向けの粗い状態
5. CSV／Evidence JSON: 数値と機械可読な正本

routine分類は無価値や削除を意味しない。新しいRelation、Question、人間指示により再昇格できる。

## 12. Auditと事故復旧

bootstrap時はQuick Auditを行う。Agent停止、lease takeover、Quick Audit error、Round終了前、人間の明示依頼では `cs-conductor-run-audit` のFull modeを使う。結果は `<run_root>/audit/<timestamp>/` に保存され、科学DAG Nodeにはしない。

失敗Nodeの再実行は同じNode IDに新しいexecution attemptを追加する。別Nodeを作って番号を消費しない。`running` Nodeを残してAgentが停止した場合は、event／artifactを照合してから再試行可否を決める。

## 13. 完了済み結果を詳しく確認する

Round完了後、既存解析を動かさずにFinding、仮説、Question、Evidence、Node、Group、Operator結果を詳しく確認する場合は`cs-conductor-result-concierge`を使う。出力は`<run_root>/concierge/CRQ######/`に限定され、State、DAG、科学artifactを変更しない。

コンシェルジュが提示した追加解析案は自動実行されない。採用する内容と人間の見解を、次Round開始時のOrchestrator依頼へ添付する。これにより見解と依頼全文がRound requestとしてState側へ正式に引き継がれる。依頼例は`docs/prompt/CONDUCTOR_result_concierge_prompt.md`を参照する。

## 14. v4.3.0 Runの一回限り移行

通常Orchestratorで旧Stateを開かない。`cs-conductor-v430-migrator` にsourceと未作成targetを指定し、scan結果を人間が確認した後だけapplyする。Migrationは`RND0001` checkpoint、active Roundなし、明示的handoff待ちで終了する。Migration AgentはbootstrapやOrchestratorを起動しない。別の人間指示を受けたOrchestratorがRND0002を開始し、移行済み基本計算を再利用して不足分だけを計画する。詳細は `docs/prompt/CONDUCTOR_v430_to_v431_migration_prompt.md` を参照する。
