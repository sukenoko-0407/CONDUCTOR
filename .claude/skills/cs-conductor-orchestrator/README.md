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
```

Active Roundの再開では、同じ`run_root`と「同じRoundを再開」を明示します。旧RunでSMILES列を自動認識できなかった場合は、再開依頼に使用するSMILES列名も記載します。

新規RunでSMILES候補列が複数ある場合は、依頼に使用するSMILES列名を明記します。一意に推定できる場合は省略できます。

## 制約事項

人間の明示指示なしに新Roundを開始しません。Main Agentは専門計算Skillを直接実行せず、Runtime Stateを直接編集しません。長時間Roundは専用Claude Code sessionでの実行を推奨します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | CONDUCTOR 0.1.3でMain Agent Orchestrator方式を導入 |
| 1.0.1 | 新規Runの曖昧なSMILES列を人間指定としてRuntimeへ渡す手順を追加 |
