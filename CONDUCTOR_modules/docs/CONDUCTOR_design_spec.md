# CONDUCTOR 0.1.3 design spec

## 権限境界

| Component | 担当 | 禁止 |
|---|---|---|
| Human | Round開始・継続・レポート改訂・受理、資源承認 | なし |
| Main Orchestrator | 人間依頼の契約化、一つのRoundの科学的選択、Executor／Interpreter起動 | 専門Skill直接実行、JSON直接編集、自動新Round開始 |
| Executor | 署名付きpacket一つの科学process実行、Tool failure隔離 | 科学候補選択、Round操作、別Subagent起動 |
| Runtime | ID、FSM、lease、Action token、DAG、packet署名、commit、audit | 科学的価値判断 |
| Interpreter | bounded evidenceの個別精査、横断比較、ID-free draft | scope／ID発行、新規計算、State変更 |

Main AgentのOrchestrator役は手動起動Skillで一時的に有効化し、既存projectの`CLAUDE.md`へ常駐させません。ExecutorとInterpreterはMainから直接起動する短命な兄弟Subagentです。

## 正本と派生情報

`conductor_control.json`は小さな運用正本です。Run設定、active Round、FSM、lease、件数、単一`required_action`、closure gate、詳細fileへのpointerを持ちます。通常の再開で最初に読むのはこれだけです。

`runtime/event_ledger.jsonl`はchecksum chain付きappend-only監査履歴、`runtime/dag_snapshot.json`はRuntime専用の詳細Node記録です。Control、DAG snapshot、Eventを同一transaction journalで同期します。DAGは有向非巡回で、上流由来、実行可能性、再計算範囲、provenanceを表しますが、LLMは直接編集しません。

Execution packet、failure packet、Attempt scratch、compact responseは新しいState正本ではありません。packetは署名、Run／Round、Control revision、lease hash、Action-token hash、有効期限へ結び付けられ、一回のExecutor実行にだけ使用できます。packetが署名する科学Skill commandは環境非依存のRuntime Python tokenを先頭に持つ論理commandであり、検証後に実行側Runtimeだけが自身のPython絶対pathへ解決します。

## Round FSM

`ACTIVE -> FINALIZING -> AWAITING_HUMAN_REVIEW -> CLOSED`です。`CLOSED`から新Roundへ進むには人間の明示指示が必要です。`AWAITING_HUMAN_REVIEW`では人間が同じRoundを継続、report revision、acceptのいずれかを指定します。

過去Roundで成功した同一signatureのNodeは再実行せず、現在Roundの`reused_node_ids`へ参照だけを登録します。Main sessionやExecutorが中断しても同じRound、Node、AttemptをRuntimeが照合し、勝手に次Roundや置換Nodeを作りません。

## NodeとAttempt

Node IDはRun全体で`N######`です。状態は`pending / running / succeeded / failed / cancelled`だけです。再試行は同じNodeの新Attemptであり、status語を増やしません。技術的失敗には最大3 Attemptの有限budgetを設けます。`not applicable`や利用不能partitionは成功resultのquality field、実行しない判断はcancel reasonとして保持します。

Description、Clustering、Operatorの科学計算kernelと一般利用CLIは維持します。CONDUCTORではRuntimeが入力、metric、scope、Cluster、parameter、seed、出力schema、artifact hashを検証してから正本へatomic promotionします。

失敗はbounded failure packetへ分類します。Attempt rootはRuntime管理file用、`output/`はSkill成果物専用に分離し、Skill起動前の`output/`は存在させません。回復可能な一Node retryに限り、Executorは割当Attemptの`recovery/`内でoption alias、path、format adapter等を補正できます。Runtimeはlauncherの置換、既存parameter値、protected科学引数、Node signature、artifactを検査し、回復manifestを監査用に保存します。科学parameterを変える補正や一時scriptによるアルゴリズム再実装は拒否します。

## Main向け情報

`runtime/working_set.json`はサイズと候補数に上限があり、現在必要なResult Card、candidate、human priorityだけを含みます。Runtime mutationは16 KiB以下のcompact responseを返し、raw log、完全DAG、完全Auditはpointer先へ保持します。Mainは`SCIENTIFIC_DECISION`にだけ推論を使い、Node生成、依存判定、状態遷移、再試行、commit、終端判定はRuntimeへ委ねます。

## Interpretation

RuntimeはInterpretation対象、canonical scope、Result Card、比較batch、未確認範囲、人間のfocusを固定します。Interpreterは各Resultを個別に確認した後、Global／Cluster、兄弟Cluster、独立Description family、異なるOperator、Round間の比較、矛盾、反証、negative resultを探索します。新規計算が必要ならfollow-upとして提案するだけです。

RuntimeがInsight ID、scope、sample factを確定し、固定templateでJSON／Markdown／HTMLを生成します。品質拒否は同じInterpretation Nodeの有限Attemptとして記録し、InterpretationとFull Auditが合格するまでRoundを人間レビュー状態へ移しません。
