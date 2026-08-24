# CONDUCTOR 0.1.6 verification

## 必須確認

- Package、Catalog、Capability、Artifact Manifestのversionが0.1.6として整合する。
- 全科学Capabilityに`conductor_request` metadata、adapter、共通launcherがある。
- 各launcherが同一Skillの並行初回起動を排他し、`pixi.lock`と環境ready markerが一致したときだけ再利用する。
- Request schemaがidentity、input hash、columns、endpoint、scope、parameter、resources、outputをfail closedで検証する。
- packet作成後にinputまたは上流成果物を変更すると、Skill process開始前にSHA-256不一致で拒否される。
- Runtime commandが全Skillで`--conductor-request`固定形となり、Python絶対path差をcommand hashへ混ぜない。
- packetは署名、Control revision、lease hash、Request hash、期限で一回の実行へ固定される。
- Skill output directoryは起動前に存在せず、Runtime管理fileと衝突しない。
- one-use Action token、Executor token、adaptive command recovery、Skill別Runtime CLI builderが残っていない。
- Operator探索は`exploration`一種類で最大50 Node、通常Interpretationも最大50 Result Card、Global優先、履歴バランス、成功済みsignature除外を満たす。
- Local Analysisは対応Global comparatorを持つ。
- Global deliverableはGlobal scopeだけで満たされ、基本計算は計画Node集合すべての完了で判定される。
- Failed Nodeは成功済み探索履歴へ数えられず、再試行時にもNode IDを増やさない。契約・列・path不良は自動反復しない。
- Result Indexの全artifact linkがRun Root相対の正規形で、実在し、Run Root外へ解決されない。
- 長時間processのstdout/stderrは逐次logへ書かれ、timeout時に子孫process treeが残らない。
- RoundはInterpretation JSON／Markdown／HTMLと登録済Full Auditなしにhandoffできない。
- Packetは初回だけRuntime Workerを起動し、再投入時も科学processが二重起動しない。InterpreterはStateを変更しない。
- live Workerは`WAIT_RUNNING`、Worker不在時だけ`RECONCILE_RUNNING`となる。

## MMP確認

- 標準defaultがcuts 2、radius 0～2、core heavy atoms 8、core fraction 0.5、variable heavy atoms 10である。
- 3 cutsまたはradius 3～5が`extended_search`なしに拒否される。
- 全詳細CSV、正規化SQLite、全Summary、reference card、storage profile、HTMLが生成される。
- Native work DBが完成後に削除される。
- Native context JOINを全件DataFrame化せず、SQLite cursorのbounded `fetchmany()`で処理する。
- SQLite fact tableが反復構造文字列を保持せず、joinで詳細行を再構成できる。
- CSV／SQLiteのPair ID集合とrow countが一致する。
- radius contextがpair supportを水増ししない。
- Local screen／detailがGlobal DBを変更しない。
- qualifying pairゼロが正常なnegative resultになる。

## 試験コマンド

```bash
python -m pytest CONDUCTOR_modules/tests/test_runtime_015.py -q
python -m pytest CONDUCTOR_modules/tests/test_runtime_014.py -q
python -m pytest CONDUCTOR_modules/tests/test_mmp_014.py -q
python -m pytest CONDUCTOR_modules/tests -q
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/launch.py catalog --check
```

2026-08-22のWindows全回帰結果は、MMP専用Pixi環境で`105 tests / 85 passed / 20 skipped`、失敗0です。skipは旧0.1.2／0.1.3専用protocolまたは別Skill環境へ分離したscikit-learn／NetworkX試験です。Runtime Worker再接続、失敗Nodeの同一Round再試行、再試行成功時の品質更新、Request、Round、MMP、Interpretation契約は現役試験で検証します。

## Windows縮小E2E

2026-08-22に、実デモCSVから固定seedで抽出したJAK2 50化合物を使い、Run初期化からInterpretation、Full Audit、`AWAITING_HUMAN_REVIEW`まで実経路で確認しました。署名付きExecution Packet、detached Runtime Worker、各Skill固有Pixi環境、Result promotion、Result Card、DAG／Event Ledger、Interpretation品質ゲートを迂回していません。

- 実行: D001 RDKit 2D、C001 Murcko、C005 Vector Butina、A001、A009、A011、A013、Interpretation。
- Interpretation: Operator Result 5件をすべて確認し、Insight 2件をJSON／Markdown／HTMLへ登録。
- Full Audit: 全20項目PASS、error 0、warning 0。
- Round outcome: `partial / human_checkpoint`。E2E時間を抑えるため、残る基本計算67 Nodeを人間権限の`node-cancel`で明示的に対象外とした結果であり、完全解析を装っていない。
- E2Eで検出した不具合: 失敗後の再試行成功時に旧`result_quality`が残り、下流Nodeが不正にblockedとなる問題。成功Attemptの品質で置換するよう修正し、同一条件の回帰試験を追加した。
- HTML視覚確認: 日本語、Global／Cluster scope、Insight階層、個別report導線を確認。長いRun IDの折り返しを共通rendererで補強した。

## 並列Skillの実行確認

2026-08-22にJAK2デモデータを用い、`available_cpu_cores=8`として署名付きPacket、detached Runtime Worker、`launch.py --conductor-request`、各Skill固有Pixi環境を通る本番相当コマンドを実行しました。単なる関数呼出しではなく、OS上のprocess／threadとCPU時間増分を監視しています。

| Capability | 結果 | 並列利用の観測 |
|---|---|---|
| D016 Mordred 3D | 50化合物、成功 | 同時に8 Python workerを確認。各workerのCPU時間が並行して増加した。 |
| C002 MCS | 50化合物、成功 | pair探索で8 Python workerを確認。後段の部分構造照合は、このWindows観測では持続的な8-core利用を示さなかった。 |
| A014 MMP | 50化合物、成功 | 本体は正常完了。native fragment工程を同一optionで拡大観測し、親1＋worker 8のpeak 9 Python processを確認した。index／集約工程は常時並列ではない。 |
| D020 ChemBERTa | 50化合物のRuntime経路および231化合物の補助試験、成功 | 8 thread指定で最大6.84 core相当、Python process群合計27 OS threadを観測した。Windowsのlegacy `MAX_PATH`でTransformers importが失敗する問題を検出し、`site-packages`のextended path化で修正した。 |
| D019 xTB | 50化合物、失敗 | 2 worker×4 coreの起動までは確認したが、Windowsのtblite native processがstack smashingで終了した。1 worker×1 coreおよびethanol 1件でも同じため、並列分割ではなく当該Windows native環境の問題と判定した。Linux HPCで別途受入が必要。 |

以上より、D016、C002のpair探索、A014のfragment工程、D020は実並列を確認しました。D019はコード上のworker起動だけを確認でき、科学計算の完走可否はLinux受入へ残します。MCSやMMPは一部に直列工程を含むため、処理時間全体を通じて8 coreを占有する仕様ではありません。

## Windows拡大最終E2E

2026-08-22に`chemble_jak2_download_01.csv`の全231化合物を用い、別のクリーンRunで最終受入を行いました。入力は`SMILES`、Endpointは`pIC50`、`higher_is_better=true`、`parallel_limit=4`、`available_cpu_cores=8`です。

| 区分 | 実行内容 | 結果 |
|---|---|---|
| Description | D016 Mordred 3D、D020 ChemBERTa | 2件成功 |
| Clustering | C001 Murcko、C002 MCS | 2件成功 |
| Global Operator | A009 Activity Cliff、A011 Cluster enrichment、A013 Cluster structural diversity | 3件成功 |
| Local Operator | C002由来C000004に対するA009 | 1件成功 |
| Interpretation | 4 Resultを比較し、Insight 3件をJSON／Markdown／HTMLへ登録 | 同一N000077の2回目commitで成功 |
| Full Audit | Interpretation後に登録 | error 0、warning 0 |

最終Controlは`round_state=AWAITING_HUMAN_REVIEW`、`required_action=HUMAN_REVIEW_REQUIRED`、`closure.contract_satisfied=true`、`interpretation_ready=true`、`audit_ready=true`、`outcome=complete`です。受入範囲外の基本計算66 NodeとAnalysis 2 Nodeは実行前に明示的にcancelしており、成功へ偽装していません。

実地で次も確認しました。

- `execute-packet`呼出し側の待機上限を超えてもdetached Runtime WorkerはD016を継続し、同一Packetへの再接続で保存済みterminal結果を返した。
- C002 MCSは231化合物で約3分以内に完了し、成果物昇格とCluster Registry登録に成功した。
- Local A009はRuntime由来scopeを`single_cluster`、Cluster IDをC000004として保持した。C000004が母集団100%を占めるためGlobalと同一結果になることをInterpretationがnegative resultとして記録した。
- Interpretation初回commitは、Global scope Resultの説明にpayload内Cluster IDを不用意に書いたdraftを品質ゲートが拒否した。scope整合文へ直した次Attemptだけが正式成果物になった。
- HTMLをヘッドレスEdgeで描画し、日本語、Global／Cluster比較、Insight階層、長いIDの折返し、主要数値一覧の非表示を確認した。

全回帰はRuntime環境で`81 passed / 26 skipped`、MMP環境で対象11件が`11 passed`、Package Layoutと48 Capability Catalog検証もPASSしました。環境固有dependencyを必要とする試験は、その依存を持つPixi環境へ分離して実行します。

診断Runでは、Windows／OneDriveが`worker_status.json`の原子的置換を一時的に拒否する事象を検出しました。Runtimeは`PermissionError`だけを最大5秒再試行するよう修正し、初回失敗・次回成功の回帰試験を追加しました。また、空き容量約3.4 GBの状態で複数のSkill固有Pixi環境を同時に初回構築すると容量不足になりました。これは科学Nodeの不具合ではありませんが、Windows受入では事前空き容量確認、Linux HPCでは共有storage上のSkill環境容量確認が必要です。

Linux受入では、Pixi共有binary、read-only network条件、複数Round再開、Main Tool call中断後のWorker継続、6時間実行、CPU上限も確認します。Windows試験は契約・schema・small fixtureを中心とし、HPC性能の代替にはしません。
