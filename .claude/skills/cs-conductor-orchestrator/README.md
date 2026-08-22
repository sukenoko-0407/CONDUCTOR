# cs-conductor-orchestrator

## SKILLの目的

Claude CodeのMain Agentを、明示的なCONDUCTOR操作中だけOrchestratorとして動作させます。科学判断をMainに残し、計算実行とInterpretationを短命Subagentへ分離します。

## 想定利用シーン

新Round開始、Active Round再開、同一Round継続、Interpretation修正、Round確認・受理に使用します。

## 環境構築

初回CLI実行時にSkill内の軽量Pixi環境を自動構築します。このSkillはRuntime launcherへの薄い入口であり、Pandas等のRuntime依存関係は`cs-conductor-runtime`側のPixi環境で一元管理します。cacheと一時領域は各Skillの`env/`内に置かれます。

## 利用例

```text
/cs-conductor-orchestrator

run_root: /path/to/run_root
request: RND0002を開始し、INS000012を重視しながら追加探索してください
walltime: 8h
parallel_limit: 8
available_cpu_cores: 8
```

`parallel_limit`は同時Node数、`available_cpu_cores`はRunへ割り当てられたCPU総数です。後者を省略すると8です。D019（xTB）、D020（ChemBERTa）、A014 Global MMPは単独Executor packetとなり、Skill内部並列と他Nodeを競合させません。

1 RoundのAnalysis Nodeは最大100件です。探索段階は`exploration`一種類で、成功済み処理を除外しながらGlobalをLocalより優先し、Description／Clustering／Operatorの偏りを抑えて一度に計画します。Wall Timeを長くしても件数は増えません。Description／Clusteringの基本計算は別枠です。

Active Roundの再開では、同じ`run_root`と「同じRoundを再開」を明示します。旧RunでSMILES列を自動認識できなかった場合は、再開依頼に使用するSMILES列名も記載します。

新規RunでSMILES候補列が複数ある場合は、依頼に使用するSMILES列名を明記します。一意に推定できる場合は省略できます。

## 制約事項

人間の明示指示なしに新Roundを開始しません。Main Agentは専門計算Skillを直接実行せず、Runtime Stateを直接編集しません。長時間Roundは専用Claude Code sessionでの実行を推奨します。

Failed Nodeは新しいNodeへ置換しません。Runtimeが`RETRY_FAILED_NODE`を返す一時障害だけを有限再試行し、`FAILED_NODE_REPAIR_REQUIRED`では人間による原因修正と再開指示を待ちます。修正後も同じNode IDへ新Attemptを追加します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | CONDUCTOR 0.1.3でMain Agent Orchestrator方式を導入 |
| 1.0.1 | 新規Runの曖昧なSMILES列を人間指定としてRuntimeへ渡す手順を追加 |
| 1.1.0 | Available CPU CoresとxTB単独・内部並列実行の手順を追加 |
| 1.2.0 | Analysisを1 Round最大200件、最大50件ずつ計画する制御を追加 |
| 1.3.0 | A014をGlobal 1件、全Cluster screening 1件、代表Local detailへ限定して制御する手順を追加 |
| 2.0.0 | 共通Execution Request、lease-only制御、最大100件のGlobal優先explorationへ簡素化 |
| 2.0.1 | 一時障害と人間修正待ちを分離し、同一Node repair retryを明記 |
