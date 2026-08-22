# CONDUCTOR 0.1.5 レビュー是正リファクタリング計画

> 状態: 実装・Windows回帰試験完了（2026-08-22）。Linux HPCでのprocess tree実測、共有Pixiによるlock生成、長時間実行を最終受入項目として残す。修正では新しいNode状態や制御正本を追加していない。

## 1. 目的

本修正の目的は、0.1.5の設計思想を変更することではなく、実装をその設計へ一致させることです。特に次を保証します。

1. 署名済みExecution Requestが、実際にSkillへ渡される入力内容まで拘束する。
2. Node成果物、Result Card、Interpretation、Full Auditが同じ正規パスを参照する。
3. Failed Nodeを失敗したまま実行済み扱いにせず、同じNode IDで制御可能に再実行できる。
4. MMPを最大2,000化合物で扱っても、中間表全体をPythonメモリへ複製しない。
5. 長時間Skillのtimeout・中断時に、子孫プロセスとログを確実に回収する。
6. 現役仕様のテストスイートをすべて成功させ、Round開始からInterpretation／AuditまでをEnd-to-Endで検証する。

## 2. 変更しないもの

- Main AgentがOrchestratorであり、人間だけが新しいRoundを開始できる。
- RuntimeはStateの単一Writerである。
- Node ID、同一Node内のAttempt、既存の5状態、DAGを維持する。状態種類を追加しない。
- Executorは署名済みpacketを一回だけ実行し、科学的判断やCLI修正を行わない。
- Description、Clustering、A001～A013の科学計算kernelと一般利用CLIを変更しない。
- MMPの標準探索範囲、Exact Core、Transform方向、Pair identity、CSV／SQLiteの科学的内容を変更しない。
- `--conductor-request`の共通入口と、一般利用時に`--conductor`を自動付与しない原則を維持する。
- 0.1.4以前のRun migration、旧packet protocol、旧action tokenとの後方互換は追加しない。

## 3. 実装原則

- **正本を増やさない**: Control、Ledger、DAG snapshot、Result Indexの役割を維持し、新しい補助Stateを作らない。
- **fail closed**: identity、hash、scope、成果物pathが一致しない処理はSkill起動前またはcommit前に拒否する。
- **同一Node再実行**: 技術的失敗を別Nodeへ置換しない。Node番号を消費して失敗を隠さない。
- **科学値不変**: MMPストリーミング化では処理順序と保存方法だけを変更し、小規模fixtureで旧実装と行集合・集計値を比較する。
- **共通実装優先**: adapterとlauncherはtemplateを一度修正し、同期ツールで各Skillへ配布する。
- **bounded context**: Runtime応答、失敗情報、ログ読込量を上限付きにし、Main AgentとExecutorへ長い標準出力を返さない。

## 4. Phase 1: 成果物パスの正規化

### 修正内容

- Run Root相対pathを生成する共通helperをRuntimeへ一つだけ設ける。
- `result_card.json`へ書く時点で、`artifact_links`をRun Root相対の正規形へ確定する。
- `result_index.jsonl`追加時にNode出力先を再度前置しない。
- 中断後のpromotion recoveryでも通常commitと同じhelperを使用する。
- 絶対path、`..`、Run Root外、存在しない成果物を拒否する。
- Global card、Cluster別card、MMP DB、reference card、detail HTMLを同じ規則で扱う。

### 受入試験

- `analysis/Nxxxx/report.html`が`analysis/Nxxxx/analysis/Nxxxx/report.html`にならない。
- Result Index内の全linkについて`run_root / link`が実在し、Run Root内に解決される。
- 通常commitとrecovery後のResult Cardが同一形式になる。
- Interpretation HTMLから個別Operator HTMLを開け、Full Auditが合格する。

## 5. Phase 2: Execution Requestの内容完全性

### 修正内容

- Runtimeがpacket実行直前に、Request内の全入力について次を検証する。
  - `path`の存在と通常ファイルであること
  - `sha256`と現在内容の一致
  - 上流成果物の`result_path`と`result_sha256`の一致
  - pathが許可されたinputまたはRun Root成果物を指すこと
- 検証後にのみ科学Skillを起動する。入力不一致をSkillの通常エラーとして扱わない。
- Request schemaに記録済みのhash fieldを利用し、新しいtokenやsidecar Stateを追加しない。
- ArtifactをNodeごとに複製する方式は採用しない。大容量成果物を不必要にコピーしないため、起動直前照合を採用する。
- Request自身のhash、packet署名、identity検証は現行どおり維持する。

### 受入試験

- packet作成後に入力CSVを変更すると、Skill process開始前に拒否される。
- 上流`result.json`または主成果物を変更しても拒否される。
- pathだけ同じ別内容への差し替えを検出する。
- 正常なRequestでは既存の全adapter profileが同じCLIへ変換される。
- test fixtureで偽hashを成功扱いにしない。

## 6. Phase 3: Failed Node、retry、探索履歴

### 修正内容

- 探索バランスの履歴集計対象を、原則としてdownstream利用可能な`succeeded` Analysis Nodeに限定する。
- 重複除外は、成功済みsignatureと現在`pending`／`running`のsignatureへ適用する。
- `failed` Nodeと同一signatureを再度扱う場合は、新しいNodeを作らず既存Node IDのAttemptを追加する。
- 自動retryはtimeout、一時的process failure、明示的に回復可能と分類した失敗だけに限定する。
- schema／argument／column／artifact contract不一致は同一Requestを自動反復しない。Runtime summaryへ修正待ちとして短く提示する。
- コードまたは入力設定を人間が修正した後は、既存の明示的`retry-node`経路から同一Round・同一Nodeを再実行可能にする。
- `cancelled`を自動的に再投入しない。再開は人間の明示指示を必要とする。

### 受入試験

- Failed Nodeが成功済み探索履歴として数えられない。
- 同じsignatureのFailed Nodeを再開してもNode IDが増えない。
- 非回復性エラーが自動で3回繰り返されない。
- 一時的timeoutは上限内で同一Nodeへretryされる。
- Round 2以降も成功済みsignatureは再選択されず、失敗だけを理由に科学的セルが永久消失しない。

## 7. Phase 4: DeliverableとRound完了判定

### 修正内容

- `DELIV_GLOBAL`はCapability IDだけでなく、`scope.mode == global`を必須にする。Local結果で代替させない。
- 基本計算はCapabilityの一件成功ではなく、そのRoundで確定した基本計算Node集合を基準に完了判定する。
- Vector Clusteringは計画されたDescription表現との組合せ単位で判定する。
- human-approved omissionは明示的契約としてのみ除外し、Failed／Skipped相当を暗黙の成功として扱わない。
- Interpretation freshness、Full Audit、human Round開始権限は現行gateを維持する。

### 受入試験

- Local AxxxだけではGlobal deliverableが満たされない。
- 同じClustering capabilityの一表現成功だけでは、計画済みの他表現を完了扱いにしない。
- 必須Node失敗中にRoundが`AWAITING_HUMAN_REVIEW`へ進まない。
- 人間が新Roundを明示しない限り、RuntimeもMain Agentも次Roundを作らない。

## 8. Phase 5: 長時間processとログの頑健化

### 修正内容

- 標準出力を`PIPE`へ全量保持せず、Attempt logへ逐次書き込む。
- Runtimeがfailure分類に読むログは末尾の上限付き領域だけにする。
- LinuxではSkill launcherを新しいprocess sessionで起動し、timeout／中断時にprocess groupへTERM、猶予後KILLを送る。
- Windowsでは新しいprocess groupを使用し、利用可能な安全なtree terminationを実装する。
- Node timeout、Executor lease、最大6時間の関係を一箇所のRuntime定数／Request resourceへ整理する。
- timeout後にcommit、scratch書込み、CPU消費を続ける子孫processを残さない。

### 受入試験

- launcherが孫processを作るfixtureをtimeoutし、Linuxで全子孫が終了する。
- 大量stdoutを出すfixtureでもRuntime RSSが出力量に比例して増えない。
- timeout後のNodeは一つのFailure Packetと一つのAttemptだけを記録する。
- 6時間許可Nodeが3時間でlease切れ扱いにならない。

## 9. Phase 6: MMPストリーミング化

### 修正内容

- native SQLiteのcontext JOINを全件`pandas.read_sql_query()`しない。
- identityと安定した副キーでORDERし、SQLite cursorの`fetchmany()`でchunk読込する。
- 一つのidentityに必要な行だけをメモリに保持し、Pair／Contextを逐次正規化する。
- canonical SQLiteへbatch insertし、`mmp_pair_detail.csv`へ順次追記する。
- Summary作成に必要な件数、分布、上位候補はbounded accumulatorまたはcanonical DB queryから計算する。
- 最終出力名、column、ID、row-order規則、reference card、Negative Result、Local read-only queryを維持する。
- native work DBはcanonical exportと検証がすべて成功した後だけ削除する。report生成失敗時に高コスト計算を即座に失わない順序へする。

### 受入試験

- 小規模fixtureで現行実装とPair集合、Transform、Core、Context、endpoint delta、Summary値が一致する。
- CSVとSQLiteのID・行数が一致する。
- 入力行順を変えてもcanonical結果が同じになる。
- synthetic large fixtureでPythonメモリ使用量がnative context行数に比例して全量増加しない。
- Global DBを使うLocal screen／detailがGlobal成果物を一byteも変更しない。
- zero-pairは失敗ではなくNegative Resultとして完了する。

## 10. Phase 7: Pixi環境の再現性とbootstrap復旧

### 修正内容

- `.environment-ready`のfingerprintを`pixi.toml + pixi.lock + platform`から計算する。
- `.bootstrap.lock`へowner、PID、host、作成時刻を記録し、死んだownerのstale lockだけを安全に回収する。
- 同一Skillの並行初回起動では一つだけがinstallし、他は完成した環境を再利用する。
- Release用の`pixi.lock`をLinux環境で生成し、各Skillの自己完結packageへ含める方針とする。`.gitignore`の一律除外を見直す。
- lock生成前の開発実行を許す場合でも、その成果をRelease受入済みとは扱わない。

### 受入試験

- 二つのlauncherを同時起動してinstallが一回だけ行われる。
- bootstrap中断後、stale lockを手動削除せず再開できる。
- `pixi.toml`変更後に古いready markerが再利用されない。
- LinuxとWindowsの対象platformがlockfileに含まれる。
- Linux共有Pixi binaryを使い、Skill directory外へcacheを書かない。

## 11. Phase 8: テスト再編とEnd-to-End試験

### 現役テストの整理

- 0.1.2／0.1.3のaction token、Executor token、旧packet protocol、旧200／50件探索を要求するテストを現役suiteから除く。
- 旧テストに含まれる有効な不変条件は、0.1.5仕様のversion-neutralなテストへ移植する。
- 「古い期待値に合わせて現行コードを戻す」修正は行わない。

### 必須End-to-End経路

1. Run初期化と人間指示によるRound開始
2. 基本計算計画
3. Request／packet生成
4. Executorによる科学Node実行
5. Artifact promotionとResult Index登録
6. Global優先exploration
7. Interpretation JSON／Markdown／HTML生成
8. Full Audit
9. `AWAITING_HUMAN_REVIEW`
10. 新しいAgent sessionからの状態再取得

### Fault test

- packet二重実行、stale revision、expired packet
- Request作成後のinput／upstream artifact差し替え
- Runtime／Executor／Skillの各中断点
- promotion直後・Result Index追加前の中断とrecovery
- Failed Nodeの一時的／非回復性分類
- 子孫processを伴うtimeout
- Pixi bootstrap中断
- MMP大規模streaming
- 不正scope、存在しないResult link、ClusterをGlobalと誤記したInterpretation draft

## 12. 主な変更対象

| 領域 | 主なファイル |
|---|---|
| Runtime／Planner／commit／audit | `CONDUCTOR_modules/tools/runtime_controller.py` |
| Execution Request | `CONDUCTOR_modules/schemas/execution_request.schema.json`、必要な場合のみpacket／failure schema |
| 共通adapter | `CONDUCTOR_modules/tools/templates/conductor_request_adapter.py`、各科学Skillの同期コピー |
| 共通launcher／Pixi | `CONDUCTOR_modules/tools/templates/launch.py`、各科学Skillの同期コピー、`.gitignore` |
| adapter同期・package検証 | `CONDUCTOR_modules/tools/sync_execution_request_adapters.py`、`verify_package_layout.py` |
| MMP | `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/mmp_engine.py`、`mmp_outputs.py`、`run.py` |
| Runtime Skill | `.claude/skills/cs-conductor-runtime/`、必要な同期コピー |
| Tests | `CONDUCTOR_modules/tests/`のRuntime、Request、Round lifecycle、MMP test |
| Docs | 仕様概要、実装計画、design、output contract、verification、version history |

科学Skillの大量差分は、共通adapter／launcher同期による機械的変更に限定します。各Skillの科学計算`run.py`は、MMPを除いて原則変更しません。

## 13. 実装順序とcommit境界

1. **Runtime artifact integrity**: path正規化、Request hash検証、関連unit test
2. **State semantics**: Failed Node、retry、history、deliverable、Round lifecycle test
3. **Process lifecycle**: streaming log、process tree termination、timeout test
4. **MMP streaming**: engine、output、equivalence／large fixture test
5. **Environment bootstrap**: ready fingerprint、stale lock、lockfile方針
6. **Full regression**: 現役test再編、End-to-End、package/catalog/schema検証
7. **Documentation**: 実装結果とLinux HPC実測結果を反映

各境界でテストを通し、Runtime、MMP、環境構築を一つの巨大な変更として同時にdebugしません。

## 14. Cutover条件

- 現役テストスイートが失敗ゼロである。
- Package layout、Catalog、JSON、TOML、Python compile、`git diff --check`がすべて合格する。
- Result Indexの全artifact linkが実在し、InterpretationとFull Auditから参照できる。
- 改変された入力／上流成果物をSkill起動前に拒否できる。
- Failed Nodeの一時失敗が科学的探索から永久消失せず、Node IDも増殖しない。
- Local結果でGlobal完了を偽装できない。
- MMP小規模同値試験と大規模bounded-memory試験が合格する。
- Linuxでprocess tree timeout、6時間許可、共有Pixi bootstrapを確認する。
- Round終了にInterpretationとFull Auditが必須であり、人間指示なしに次Roundを開始しない。

## 15. 実装結果

- Result CardとResult IndexはRun Root相対pathへ一度だけ正規化し、commit、recovery、Full Auditで同じ検証関数を使う。
- packet実行直前に、入力と上流成果物の現在SHA-256をExecution Requestと照合する。差し替え時は科学Skillを起動しない。
- Failed Nodeは成功済み探索履歴へ数えず、再実行時も同じNode IDへAttemptを追加する。一時障害だけを最大3回まで自動再試行し、契約・列・pathエラーは人間修正待ちにする。
- 基本計算は計画Node集合、Global解析は`scope.mode=global`で完了判定する。Local結果による代替を許さない。
- 科学processのstdout/stderrはAttempt logへ逐次書き込み、timeout時はprocess group/treeを回収する。失敗分類はログ末尾12 KiBだけを読む。
- MMPのnative context JOINはcursorの`fetchmany(10000)`で処理し、全JOIN表をDataFrameへ複製しない。native work DBはreportとcontract生成後にだけ削除する。
- Pixi ready fingerprintは`pixi.toml + pixi.lock + platform`で決まり、bootstrap ownerのPID・host・時刻からstale lockを回収する。
- 2026-08-22時点のWindows全回帰試験は`92 passed, 9 skipped, 5 subtests passed`、Catalog検証は48 capabilityすべて合格した。

## 16. 実装後に残る制約

- 起動直前hash検証からSkillによるfile openまでの極小のTOCTOU窓は残る。完全排除にはArtifactのread-only content-addressed storeまたはNodeごとのcopyが必要だが、大容量データのコストが高いため本修正には含めない。
- Windowsの子孫process終了はOS機能差があるため、主要受入環境をLinux HPCとし、Windowsでは可能な範囲のtree terminationとrecoveryを検証する。
- Pixi lockfileはLinux側の共有pixi binaryで生成・検証する必要があり、WindowsだけではRelease受入を完結できない。

これらは文書化した残余リスクとし、StateやAgent手順を複雑化して隠蔽しません。
