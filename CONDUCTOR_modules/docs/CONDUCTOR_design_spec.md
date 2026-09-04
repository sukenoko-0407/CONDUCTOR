# CONDUCTOR 0.1.10 設計要約

## 責務

| 要素 | 責務 |
|---|---|
| Main Orchestrator | 人間承認済みRoundの進行、Runtime応答の実行 |
| Runtime | State/DAGの唯一のWriter、Request生成、Node実行、監査 |
| Scientific Skill | 一つのRequestを計算し、自己完結した成果物を返す |
| Interpreter | A009後の短いdraftだけを書く |
| On-demand | 通常DAG外で人間依頼を処理しREQ記録を残す |

## 単純化の原則

- Node状態は5種類。
- OperatorはSeriesごとではなくCapabilityごとに一Node。
- Result Card、一次採点、探索wave、Executor Subagentは廃止。
- Skill別CLIはSkill内adapterへ閉じ込め、RuntimeはExecution Requestだけを作る。
- 新Roundは人間だけが開始できる。
- 科学的0件は失敗にしない。
