# cs-conductor-runtime

## SKILLの目的

CONDUCTORの小さなControl、5状態Node、DAG、単一Writer lease、署名付きPacket、冪等なRuntime Worker、実行attempt、事故復旧、Interpretation終端条件を決定論的に管理します。

CPU資源は`available_cpu_cores`（既定8）で、同時Node数は`parallel_limit`で別々に管理します。RuntimeはC002 MCS、D016 Mordred 3D、D019 xTB、D020 ChemBERTa、A014 Global MMPを単独実行し、Skill内部並列と全体CPU予算の競合を防ぎます。C002とD016は最大8個、A014 fragmentも最大8個の単一thread workerを使います。

Operator予算は人間指定の`max_additional_nodes`（既定50、安全上限500）で、Runtimeは最大25 Nodeずつ計画します。成功Result Cardは既定4件ずつ絶対評価し、Run-wide JSONLとRound CSVへ複数軸の得点と独立した信頼性を保存します。`screening` Roundはcompact summaryで、`full` Roundは評価上位と多様性から最大50件を選抜したInterpretationで終了します。全候補はDAGへ保存せず、次の人間承認Roundで再構成します。基本Description／Clusteringはこの予算の対象外です。A014はGlobal DBだけを定型計画し、Global–Local比較は人間起動のread-only専用Skillへ分離します。

人間承認のhistorical re-Screening Roundでは、複数のCLOSED Source Roundを指定できます。元Roundと旧Assessmentを変更せず、Operator Nodeを作らず、最新revision、Summary、Auditだけを新Roundへ追加します。Interpreter評価は最大4小batchを並列化できますが、Runtimeへのcommitは常に直列です。

## 想定利用シーン

人間が開始したRoundの計画登録、専門Skill実行、同一Node再試行、中断後再開、Interpretation commit、監査ゲートに使用します。通常はOrchestratorから内部利用します。

## 環境構築

launcherがSkill内Pixi環境を再利用または自動構築し、cacheも`env/`内へ置きます。Runtime Controllerが必要とするJSON SchemaとPandas等の依存関係はこの環境へ集約されています。

## 利用例

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state query --run-root /path/to/run --kind control
```

## 制約事項

人間の代わりにRoundを開始・受理しません。Runtime JSON/JSONLの直接編集と複数Writerは許可しません。正式Interpretationを省略できるのは、人間がRound Contractで`report_mode=screening`を選んだ場合だけです。新規RunではSMILES列を一意に確定し、共通Execution Requestを介してDescription、構造ベースClustering、構造を直接読むOperatorへ引き渡します。候補が複数の場合は`init --smiles-column <column>`が必要です。

RequestはSkill起動直前に入力・上流成果物のSHA-256を再照合します。自動retryはtimeout等の一時障害だけを最大3 Attemptとし、argument、column、path、schema等の決定論的失敗は`FAILED_NODE_REPAIR_REQUIRED`として人間へ返します。再開は同じNode IDで行います。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Control／Event Ledger／5状態DAG Runtimeを実装 |
| 1.1.0 | 0.1.3のcompact protocol、Executor packet、有限Interpretation retryを追加 |
| 1.1.1 | SMILES列をRun入力契約へ記録し、DescriptionとC001～C004へ明示的に引き渡す処理を追加 |
| 1.1.2 | 記録済みSMILES列をA006・A009・A013へも明示的に引き渡す処理を追加 |
| 1.2.0 | Available CPU Cores、CPU上限、xTB/ChemBERTa単独packetを追加 |
| 1.3.0 | Round Analysis上限200件と50件単位の遅延Node化を追加 |
| 1.4.0 | A014 Global DB／全Cluster screening／代表Local detailの計画と複数Artifact原子的昇格を追加 |
| 2.0.0 | 共通Execution Request、lease-only制御、最大100件のGlobal優先explorationへ簡素化 |
| 2.0.1 | Request内容再照合、Failed Node分類、同一Node repair retry、artifact link正規化を追加 |
| 2.1.0 | 科学process所有権をLLM Executorから冪等なOS Runtime Workerへ移し、WAITとreconcileを分離 |
| 2.2.0 | 0.1.7の逐次Result Screening、可変Operator予算、screening／full Roundを追加 |
| 2.3.0 | 一次評価guard、累積Interpretation、CLOSED Roundのhistorical re-Screeningを追加 |
| 2.3.1 | 再Screening限定のbounded parallel waveと直列commitを追加 |
