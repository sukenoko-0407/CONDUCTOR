# CONDUCTOR 0.1.5 実装計画・受入基準

> 実装状況: 2026-08-22にコード実装、静的検証、Windows小規模回帰試験まで完了。Linux HPCでの共有Pixi bootstrap、6時間実行、MMP実データ規模の性能・容量確認を最終受入項目として残す。

## 変更境界

科学kernelを変更するのはA014 MMPだけです。Description、Clustering、A001～A013は既存計算を維持し、共通Request adapter、launcher入口、version metadataだけを変更します。旧Run互換、Archive、migrationは作りません。

## Phase 1: 共通Request

- 中央`execution_request.schema.json`を追加する。
- Capability metadataへadapter profileと必要input roleを追加する。
- 共通launcherへ`--conductor-request`入口を追加する。
- 同一Skillの並行初回起動に備え、Pixi環境bootstrapをlockfile hashと排他lockで一回だけ行う。
- 自己完結性のためadapterを各科学Skill directoryへ配置する。
- 一般利用CLIを維持する。
- Description、structure／vector／meta Clustering、通常Operator、projection、multi-description model、MMPのadapter testを作る。

完了条件は、Runtime commandにSkill固有optionがなく、全科学Skillが同じ固定command形で起動できることです。

## Phase 2: Runtime／Executor簡素化

- RuntimeがNode、上流Artifact、Run columns、scope、parameters、CPUからRequestを生成する。
- Request path／hashと環境非依存command hashをpacketへ記録する。
- one-use Action token、Executor token、adaptive command recoveryを削除する。
- lease、Control revision、packet署名、atomic transactionで二重実行を拒否する。
- Executorを`run_root`と`packet_path`だけの一回実行へ更新する。
- leaseから直接科学計算を起動する公開`execute-batch`経路を廃止し、署名済packet経路へ一本化する。
- 同一Node再試行を最大3 Attemptに制限する。
- scratch管理fileと未作成`skill_output/`を分離する。

## Phase 3: 単一exploration

- Initial／Additional planner commandとflagを削除する。
- 一RoundAnalysis上限を100にする。
- 50件単位のmaterializationを削除する。
- 履歴横断without replacementと固定seed tie-breakを実装する。
- Global約2／3、Local約1／3のGlobal優先quotaを実装する。
- Local comparator prerequisiteを実装する。
- human／interpreter follow-upは`selection_reason`だけで区別する。

試験では100件超過なし、成功済みsignature再選択なし、Global優先、Local comparator、Round 2以降の同一selectorを確認します。

## Phase 4: A014再設計

- defaultをcuts最大2、radius 0～2、core heavy atoms 8、core fraction 0.5、variable heavy atoms 10にする。
- 3 cuts／radius 3～5は`extended_search`必須にする。
- Exact Core、Transform方向、Pair identity、endpoint deltaを維持する。
- DBをdimensionとfactへ正規化する。
- 全詳細CSVとSummary CSVを維持する。
- native work DBをexport後に削除し、Parquetをcanonicalから外す。
- storage profileを生成する。
- Global DBをLocal screen／detailがread-onlyで再利用する。

試験では標準／拡張境界、CSV／DB ID整合、Context非独立性、Global DB byte不変、Negative Resultを確認します。

## Phase 5: Orchestrator／Interpreter

- Main Orchestrator Skillを0.1.5 required action表へ更新する。
- Executor agentを共通Requestの一回実行へ更新する。
- Interpreterのread-only境界とGlobal／Local fact確認を維持する。
- Interpretation HTMLのscope、Cluster、Description、Clustering、Operator、sample factsをRuntime rendererで確定する。
- InterpretationとFull AuditなしにRoundをhandoffできないことを試験する。

## Phase 6: Catalog／文書／検証

- Package、Catalog、変更Componentを0.1.5へ更新する。
- 現役overview、design、policy、output contract、user guide、promptを更新する。
- Package verifierへRequest schema、adapter、version、旧制御語の検査を追加する。
- Catalogを再生成し、diffを確認する。
- Python compile、JSON parse、focused unit test、full regression、`git diff --check`を行う。

## Fault test

- 同一packet二重実行
- stale revision／expired lease／expired packet
- Executor／Runtime中断と`reconcile-running`
- scratch事前汚染
- Execution Event欠損
- Artifact hash／identity不一致
- Skill timeout／kill
- 3 Attempt上限
- Interpretation draft不合格

いずれもState破損、Node番号飛躍、別Round開始、二重promotion、無限retryを起こしてはいけません。

## Cutover条件

- 全Catalog科学Skillに共通Request contractとadapterがある。
- Runtime command builderにSkill別CLI optionがない。
- 一般利用CLIとA001～A013科学値が維持される。
- exploration上限100、Global優先、履歴バランス、Local comparatorが合格する。
- A014の標準条件、正規化DB、全詳細CSV、Local queryが合格する。
- Interpretation JSON／Markdown／HTMLとFull Audit gateが合格する。
- Main Agent手順にAction token、Executor token、旧planner phaseが残らない。
- 新規RunをLinux HPC上で複数Round完遂できる。

Windowsではschema、adapter、small fixture、Runtime制御を検証します。Linux HPCの実計算時間、共有Pixi、6時間process、最大CPU割当は本番環境で最終確認します。

## 詳細レビュー後の是正実装

0.1.5の初回実装後レビューで、設計を変えずに次の不整合を是正しました。

- Execution Requestのpathだけでなく、入力・上流成果物の現在SHA-256をSkill起動直前に再検証する。
- Result Card、Result Index、Interpretation、Full Auditのartifact linkをRun Root相対の単一形式へ統一する。
- Failed Nodeを成功履歴から除き、一時障害と決定論的契約不良を分離する。再実行は同じNode IDの新Attemptとする。
- 基本計算を計画Node集合、Global deliverableをGlobal scopeで評価する。
- subprocess出力を逐次logへ流し、timeout時に子孫process treeを回収する。
- MMP native DBの大規模JOINをstreaming処理し、高コスト中間DBの削除を全成果物生成後へ遅らせる。
- Pixi bootstrapに環境fingerprint、owner metadata、stale lock回収を追加する。

詳細な受入基準と残余リスクは[CONDUCTOR_0.1.5_review_remediation_plan.md](CONDUCTOR_0.1.5_review_remediation_plan.md)を正本とします。
