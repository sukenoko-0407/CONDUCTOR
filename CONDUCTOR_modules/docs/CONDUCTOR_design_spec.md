# CONDUCTOR 0.1.2 design spec

## 権限境界

| Component | 担当 | 禁止 |
|---|---|---|
| Human | Round開始・継続・レポート改訂・受理、資源承認 | なし |
| Dispatcher | 人間依頼の契約化、単一Orchestrator起動、return検証 | 科学判断、Node生成 |
| Orchestrator | 一つの既存Roundの科学的選択 | Round作成、JSON直接編集、別Orchestrator起動 |
| Runtime | ID、FSM、lease、Action token、DAG、実行、commit、audit | 科学的価値判断 |
| Interpreter | bounded evidenceからID-free draftを作る | scope／ID発行、計算、State変更 |

## 正本と派生情報

`conductor_control.json`は小さな運用正本です。Run設定、active Round、FSM、lease、件数、単一`required_action`、closure gate、詳細fileへのpointerを持ちます。通常の再開で最初に読むのはこれだけです。

`runtime/event_ledger.jsonl`はchecksum chain付きappend-only監査履歴、`runtime/dag_snapshot.json`はRuntime専用の詳細Node記録です。Control、DAG snapshot、Eventを同一transaction journalで同期し、途中書き込みを復旧します。Ledger単体へ全Node内容を複製せず、状態肥大化を避けます。DAGは有向非巡回で、上流由来、実行可能性、再計算範囲、provenanceを表します。

## Round FSM

`ACTIVE -> FINALIZING -> AWAITING_HUMAN_REVIEW -> CLOSED`です。`CLOSED`から新Roundへ進むには人間の新しい依頼が必要です。`AWAITING_HUMAN_REVIEW`では人間が同じRoundを継続、report revision、acceptのいずれかを指定します。

過去Roundで成功した同一signatureのNodeは再実行せず、現在Roundの`reused_node_ids`へ参照だけを登録します。これにより、充足判定とInterpretationは既計算を利用しつつ、Nodeの由来と元Result Cardを改変しません。

## Node

Node IDはRun全体で`N######`です。状態は`pending / running / succeeded / failed / cancelled`だけです。再試行は同じNodeの新Attemptであり、status語を増やしません。技術的失敗には同じNode IDで一回だけ自動経路の再試行を許し、二回目の失敗は明示的に残します。`not applicable`や`usableでないpartition`は成功resultのquality field、実行しない判断はcancel reasonとして保持します。

## 並列・中断制御

一つのlive leaseとwriter lockで同時Writerを防ぎます。各変更は一回限りのAction tokenを消費します。Skill実行はRuntimeが検証済みcommandとして開始し、Run内scratchへ出力した後、hashとschemaを確認して正本へatomic promotionします。hard kill後はstale lock、pending transaction、停止したprocessの成果物を照合し、同じAttemptを成功または失敗へ確定します。

Main Agentが同期的に起動したOrchestratorの帰還を確認した場合、Dispatcherはowner IDと起動時revisionを指定してleaseを回収できます。進捗があれば同じRoundをreplacementへ引き継ぎ、進捗なしが二回連続した場合は自動再起動を止めます。これはlease期限切れを待つための代替であり、別Orchestratorのlive leaseを奪う操作ではありません。

## LLMへ渡す情報

`runtime/working_set.json`はサイズと候補数に上限があり、現在必要なResult Card、candidate、human priorityだけを含みます。長いDAGや全Interpretationを毎Round読みません。Runtimeが機械判断を担い、Orchestratorは候補の科学的価値判断へ集中します。

入力はRun開始時に`runtime/input.csv`へ固定し、`compound_id`を一意に確定します。元CSVの後日の変更やID列名の違いが、Cluster membershipとDescription resultの対応を崩さないようにします。
