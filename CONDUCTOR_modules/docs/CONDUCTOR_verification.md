# CONDUCTOR 0.1.4 verification

## Package

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/launch.py catalog --check
```

全schemaのJSON parse、CatalogのID一意性、Skill／Agent参照、Version統一を確認します。

## Runtime

`CONDUCTOR_modules/tests/test_runtime_013.py`は維持したMain Agent制御境界を、`test_runtime_014.py`はA014 Round guard、Role別command、CPU排他を検証します。

- 人間authorizeなしにRoundを開始できない。
- live leaseとone-use Action tokenが二重Writerを防ぐ。
- Node IDがRun全体の単調連番で、状態が5種類に限定される。
- 中断後も同じRoundを再開し、勝手に次Roundを作らない。
- InterpretationとFull Auditなしにhuman reviewへ移行できない。
- Cluster scopeをGlobalとするdraft、誤ったCluster ID、sample不整合を拒否する。
- partial Ledgerを伴うpending transactionとstale writer lockを復旧できる。
- Working Setが設定上限を超えない。
- 過去Roundの成功Nodeが次Roundの明示的な再利用参照となる。
- Interpretation review contextがScope／Operatorを偏らせず上限内に収まる。
- OrchestratorがAgentではなく手動起動Main Skillとしてだけ存在する。
- Executor packetが署名、revision、Action token、期限へ結び付けられ、二重利用できない。
- ExecutorへMain lease tokenを渡さず、Runtime応答が16 KiB以下に収まる。
- Interpretation quality失敗が同じNodeの有限Attemptとして記録され、正常終了扱いにならない。
- Analysis Nodeが1 Round最大200件、1回の計画登録最大50件、初期Global最大100件に制限され、Local解析用容量が残る。
- 未Node化候補が次の人間承認Roundで成功済みsignatureを除外して決定論的に再構成される。

## Scientific Skills

既存のDescription、Clustering、Operatorテストにより一般利用CLIと計算結果を確認します。Vector Clusteringは手法別auto calibration、endpoint非依存、minimum Cluster size、negative partition保持を確認します。

`test_mmp_014.py`はmmpdbによるGlobal end-to-end、CSV／Parquet／SQLiteのPair行一致、radius contextとPair supportの分離、全Cluster screening、Local detail、Global DBのbyte-level不変性を確認します。

### D019 Linux CPU受入確認

D019はLinuxのSkill専用Pixi環境で小規模入力を使い、`available_cpu_cores=4`と`8`をそれぞれ確認します。

- 4 CPUでは1 worker × 4 CPU、8 CPUでは2 workers × 4 CPUとなる。
- D019と別Nodeが同時実行されない。
- `description_manifest.json`の`maximum_cpu_cores`が宣言予算以下である。
- 各`worker_observations[].affinity_cpu_count`が4以下で、worker間の`affinity_cpu_ids`が重複しない。
- `OMP_THREAD_LIMIT=4`、`OMP_MAX_ACTIVE_LEVELS=1`、`OPENBLAS_NUM_THREADS=1`が記録される。
- `top`の瞬間使用率ではなく、worker affinityとNode全体のCPU集合を合格基準とする。
- Scheduler/cpusetの許可数より大きいCPU予算は、xTB計算開始前に明示的なerrorとなる。

### C002 Linux CPU・出力互換確認

C002は同一の小規模入力とseedを旧逐次実装、新並列実装で実行して比較します。

- `cluster_membership.csv`、`cluster_summary.csv`、`clustering_diagnostics.csv`の列、行、値が一致する。
- MCS pair抽出とCluster順位が同一seedで再現する。
- C002と別Nodeが同時実行されない。
- RunのCPU予算が8以上なら最大8 Worker、8未満なら割当数以下となる。
- 各MCS Workerのnative thread上限が1であり、Node全体が最大8 CPUを超えない。

### D016 Mordred 3D CPU・出力互換確認

- 同一入力・`num_confs`・`random_seed`について、1 Worker実行と最大8 Worker実行の主CSVを比較する。
- 行順、feature列、値、row-level errorが一致することを確認する。
- RuntimeがD016を単独packetとし、Worker数がAvailable CPU Coresと8の小さい方を超えないことを確認する。
- 各Workerのnative thread上限が1であることを確認する。
- 2,000化合物でも部分構造検索の`maxResults`上限によるmembership欠落がない。

## Human report

Interpretation HTMLは日本語、固定section、低彩度配色、print CSS、scope fact panel、evidence link、coverage、未確認範囲を持つことを確認します。scope、Cluster ID、sample count、Operator、Result別sample数はResult Cardから再計算して照合し、artifact linkはFull Auditで存在確認します。Operator reportとState reportの表示は導入先smoke testでも目視確認します。

配布前にWindows開発環境の自動testに加え、Linux共有filesystem上で小規模RunをDescriptionからInterpretation／Full Auditまで通すsmoke testを行います。

## 0.1.3実装時の履歴

- Windows開発環境: `35 tests OK`、`1 skipped`
- skip対象: Leiden（共通開発環境に`igraph`／`leidenalg`がないため。Skill専用Pixi環境が正本）
- Package layout: PASS
- Catalog: allowlist 47件を検証、PASS
- Installer: 空のProjectへのdry-runおよび実copy後のPackage検証、PASS
- Python compile、全JSON Schema parse、`git diff --check`: PASS

Linux共有filesystem上での一Round end-to-end smokeは、配布先での受入試験として残します。

## 0.1.4確認項目

- Windows開発環境: `73 passed`、`1 skipped`、`5 subtests passed`
- skip対象: Leiden（共通開発環境に`igraph`／`leidenalg`がないため。Skill専用Pixi環境が正本）
- Package layoutと48件のhuman allowlist Catalog
- 0.1.3 Runtime回帰25件
- A014 Global／Screen／Detailの一般・CONDUCTOR mode
- A014 Globalのfragment jobが最大8かつAvailable CPU Cores以下で、全Pair・全Summary・Database・HTMLの出力項目が省略されないこと
- Stable SQLite、全情報CSV、Parquetの行数とID整合
- 0.1.3 Control／Artifact受理と、旧Active RoundへのA014非注入
- Interpretation／PolicyのMMP scope、Exact Core、Environment区別

Linux共有filesystemでの最大想定2,000化合物MMP性能smokeと、一Roundを通した目視HTML確認は配布先での受入試験として残します。
