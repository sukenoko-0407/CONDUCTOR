# CONDUCTOR 0.1.5 仕様概要

## 位置づけ

0.1.5は、複数Round運用における頑健性を優先し、科学Skill実行、Operator探索、MMP保存を簡素化するVersionです。旧Runのmigrationと後方互換は提供せず、新規Runと再計算を前提にします。

目標は次の三点です。

1. Main AgentがRoundを跨いでも短い同一手順で制御できる。
2. Runtime WorkerとSkill間の引数不一致を構造的に減らす。
3. 科学情報を失わず、利用価値の低い重複保存と制御状態を減らす。

## 維持するもの

- Main AgentがOrchestrator、人間だけがRound開始権限を持つ。
- RuntimeはStateの単一Writerで、Node ID、5状態、DAG、Attempt、commit、auditを管理する。
- 決定論的なOS Runtime Workerは科学process担当、Interpreterはread-onlyの解釈担当である。
- Round終了前にInterpretation JSON／Markdown／HTMLとFull Auditを必須とする。
- Description、Clustering、A001～A013の科学kernelと一般利用CLIを維持する。
- Conciergeは`run_root/concierge/`だけへ書き、解析Stateを変更しない。

## 共通Execution Request

Runtimeは1 Node × 1 Attemptごとに、中央schemaへ従う小さい`execution_request.json`を作ります。

```json
{
  "schema_version": "1.0.0",
  "identity": {
    "project": "project",
    "run_id": "run",
    "round_id": "RND0001",
    "node_id": "N000001",
    "attempt_id": "ATT0001",
    "capability_id": "A001",
    "skill_name": "cs-analysis-sali"
  },
  "inputs": [],
  "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "pIC50"},
  "endpoint": {"higher_is_better": true},
  "subject": {"mode": "global"},
  "parameters": {},
  "resources": {
    "available_cpu_cores": 8,
    "node_cpu_cores": 1,
    "native_thread_limit": 1,
    "skill_options": {}
  },
  "output": {"directory": "/run/runtime/scratch/.../skill_output", "overwrite": false},
  "created_at": "..."
}
```

各Capabilityは`capability.json`の`conductor_request`でadapter profileと必要input roleを宣言します。共通adapterはSkill directoryへ自己完結して配置され、Requestを既存科学CLIへ変換します。Runtime commandは全Skillで次の固定形だけです。

```text
<CONDUCTOR_RUNTIME_PYTHON> <skill>/scripts/launch.py --conductor-request <request.json>
```

Runtimeは入力Artifactのpath／hash、identity、scope、CPU、出力境界を確定します。packet実行直前に入力と上流成果物の現在SHA-256をRequestへ再照合し、不一致ならSkillを起動しません。SkillはRequestと自分のCapability identityを検証し、未知parameterや不足入力を既存CLI validationでfail closedにします。一般利用は従来のCLIを使い、`--conductor-request`を付けません。

## 排他制御

one-use Action tokenとExecutor tokenは使用しません。排他性は次で担保します。

- live Main Agent lease
- monotonic Control revision
- Run／Round／lease hash／Request hash／command hash／期限を含む署名済packet
- Packetのatomic claim、`batch_started`、結果commitのState transaction

未claim Packetは発行時revisionでのみ受理されます。初回claimでAttemptへPacket IDを結び付け、実行開始commitでrevisionを進めます。以後、同じPacketの再投入は既存Workerへ接続し、二つ目の科学processを起動しません。Workerへlease tokenを渡しません。

Mainはpacket pathをRuntime `execute-packet`へ一回渡します。Runtimeは独立OS Workerを起動し、Main sessionやTool callが終了しても計算を継続します。`WAIT_RUNNING`と`RECONCILE_RUNNING`を分け、live processをreconcileで失敗扱いしません。引数修正、補助adapter生成、Skill source変更は行いません。timeout等の一時障害だけを同一Node・同一Requestで最大3 Attemptまで自動再試行します。契約や実装の欠陥は`FAILED_NODE_REPAIR_REQUIRED`として人間へ返し、Round外で修正した後に同じNode IDへ新Attemptを追加します。

## Operator探索

初期探索、初期Global、初期Local、追加探索という別々の進行状態を廃止し、`exploration`へ一本化します。基本計算が完了した後、一Round最大100 Analysis Nodeを一度に計画します。50件単位の再materializationは行いません。

選択規則は次です。

1. 既存の全Roundに同じ成功signatureがある候補を除外する。Failed Nodeは成功履歴へ数えず、再実行時もNode IDを増やさない。
2. 約3分の2をGlobal、3分の1をLocalに割り当て、Globalを優先する。
3. 履歴上少ないOperator、scope、入力Description／Clusteringを優先する。
4. 同順位は固定seed hashで決める。
5. Localは互換するGlobal comparatorが成功済み、または同じ計画に含まれる場合だけ作る。

候補全体をStateへ保存せず、次Roundで成功済みsignatureを除外して再構成します。人間またはInterpreter起点の深掘りは`selection_reason`で区別しますが、Node statusや探索phaseを増やしません。Wall Timeは100件上限を増やしません。

## MMP A014

Global buildの標準条件は次です。

| 項目 | 標準値 |
|---|---|
| Engine | mmpdb 3.1.4 |
| cuts | 1～2相当（最大2） |
| smallest transformation only | 使用しない |
| max variable heavy atoms | 10 |
| min exact core heavy atoms | 8 |
| min core fraction | 両分子で0.50 |
| Environment radius | 0～2 |
| 最大化合物数 | 2,000 |
| 分子標準化／salt除去 | 実施しない |

3 cutsまたはradius 3～5は`extended_search`を明示した別signatureだけで使用できます。標準DBへ混在させません。

`mmp_database.sqlite`は`metadata`、`compounds`、`transforms`、`cores`、`mmp_pairs`、`mmp_contexts`へ正規化します。Pair factは整数keyと数値・flagを中心とし、SMILES、Transform、Core、Context文字列を繰り返しません。派生Summary tableもDBへ重複保存しません。

一方、人間利用用の`mmp_pair_detail.csv`は全採用Pair × Transform × Exact Core行を非圧縮で保持します。Summary CSV、reference card、HTML、`mmp_storage_profile.json`も生成します。mmpdb native work DBはcanonical export後に削除し、Parquetは必須出力にしません。

Local screenとLocal detailはGlobal DBをread-onlyで再利用し、再fragmentしません。該当Pairゼロも成功したNegative Resultです。

## InterpretationとRound終端

Runtimeはbounded Result Card集合、canonical scope、比較batch、未確認範囲、人間focusをInterpreterへ渡します。Interpreterは個別結果、Global／Cluster、兄弟Cluster、独立Description、Operator間、Round間、矛盾、反証、negative resultを比較します。

RuntimeがInsight ID、scope、sample factsを確定し、固定rendererでJSON／Markdown／HTMLを作ります。Cluster resultをGlobalと記載したdraft、存在しないResult参照、不十分な必須節は拒否します。InterpretationとFull Auditが合格しない限り`AWAITING_HUMAN_REVIEW`へ進めません。

## 非対応

- 0.1.4以前のRun／State／Packet／Artifact migration
- MainまたはRuntime Workerによる即席CLI修正
- MMP native work DBまたはParquetのcanonical保持
- 人間指示なしの自動新Round開始
