# CONDUCTOR 0.1.4 実装計画書

## 1. 目的

本計画は、[CONDUCTOR_0.1.4_specification_overview.md](CONDUCTOR_0.1.4_specification_overview.md)を実装するための変更境界、作業順序、試験、cutover条件を定める。

実装branchは`0.1.4`とする。現行コードはGitに保持されているため、新しいArchiveは作らない。`0.1.3` Runとの互換性を必須とし、Run migrationは作成しない。

## 2. 優先順位

1. 0.1.3のRun、Node、Artifact、科学Skillを壊さない。
2. MMP全集合を後続Roundから再利用可能なDatabaseとして保存する。
3. Exact CoreとContextを失わず、Spotfireへ渡せる全情報CSVを作る。
4. 全ClusterのScreeningと、限定した詳細解釈を分離する。
5. Main AgentとInterpreterへ渡す情報量をboundedに保つ。
6. 長時間計算を同一Node／Attemptで回復可能にする。
7. MMP科学kernelをSkill内に自己完結させ、既存Moduleと疎結合にする。

## 3. 変更境界

### 3.1 新規追加

```text
.claude/skills/cs-analysis-matched-molecular-pairs/
├── SKILL.md
├── README.md
├── capability.json
├── env/pixi.toml
├── scripts/launch.py
├── scripts/run.py
├── scripts/render.py
└── schemas/
    ├── mmp_result.schema.json
    ├── mmp_reference_card.schema.json
    ├── mmp_query_result.schema.json
    ├── artifact_manifest.schema.json
    ├── execution_event.schema.json
    └── operator_summary.schema.json
```

Capabilityは`A014`、Skill名は`cs-analysis-matched-molecular-pairs`とする。mmpdb、RDKit、pandas、pyarrow等の必要dependencyはこのSkillのPixi環境へ置く。科学計算実装を`CONDUCTOR_modules`の共有packageへ置かない。

### 3.2 変更する制御・Module

- `CONDUCTOR_modules/tools/runtime_controller.py`
- `.claude/skills/cs-conductor-runtime/`の対応するcopy
- `CONDUCTOR_modules/catalog/included_skills.json`
- `CONDUCTOR_modules/catalog/analysis_profile.json`
- `CONDUCTOR_modules/catalog/catalog.json`
- `CONDUCTOR_modules/schemas/analysis_profile.schema.json`
- 必要なMMP固有schemaとRuntime payload validation
- Package verifier、Catalog builder、installer、tests
- Orchestrator、Policy、Interpretation Policy、Output Contract、Catalog、利用文書

Runtime変更はA014 planning、optional payload promotion、MMP固有validation、bounded Result Card選択へ限定する。Node状態、Round FSM、ID allocator、lease、Action token、Executor packetの基本契約は変更しない。

### 3.3 原則変更しないもの

- Description全Skillの科学kernelとCLI
- Clustering全Skillの科学kernelとCLI
- A001～A013の科学kernelとCLI
- `cs-conductor-executor` Subagentの責務
- `cs-conductor-interpreter` Subagentの責務
- Main Agent Orchestratorの役割配置
- `conductor_control.json`、Event Ledger、DAG Snapshotのrequired field
- `analysis_result/1.0.0`、`result_card/1.0.0`
- 一般利用では`--conductor`を付けない原則

MMP対応のためにExecutorやInterpreterという新しいAgentを追加しない。

## 4. 後方互換戦略

### 4.1 Package versionとcomponent version

現行Package verifierが全CapabilityのversionをPackage versionと一致させる制約を見直す。

- Packageは`0.1.4`とする。
- 変更しない科学Skillはcomponent version `0.1.3`を保持できる。
- A014と実際に変更したRuntime／制御Skillだけを`0.1.4`とする。
- Catalogは`conductor_version`と各Capabilityの`version`を別々に検証する。
- Capability schemaの`version`をPackage versionの固定値から有効なSemVerへ変更し、Packageが宣言する互換範囲内であることを検証する。
- Artifact Manifestはproducer contractとして`0.1.3`と`0.1.4`を受理し、Capability versionとの整合を検証する。

これにより、互換性のためだけに全Skill directoryを機械的に書き換えず、変更範囲を監査しやすくする。

### 4.2 0.1.3 Run読込み

- 0.1.3 `conductor_control.json`、Ledger、DAG、Result Index fixtureを0.1.4 Runtimeで読めることを先にtest化する。
- `conductor_control.schema_version=3.0.0`を維持し、`conductor_version`のsupported setを`0.1.3`と`0.1.4`にする。
- 新規Runだけ`conductor_version=0.1.4`で作り、既存Runの`0.1.3`を更新しない。
- 共通schemaへ新しいrequired fieldを追加しない。
- 既存NodeのCapability version、signature、Artifact hashを変更しない。
- 0.1.3 Active Roundの候補集合へA014を自動挿入しない。
- 既存Roundが終端した後、人間が開始した次RoundでA014不足を候補化する。
- 0.1.3の成功Nodeを0.1.4 Capabilityで置換しない。

### 4.3 Runtime protocol

- 0.1.4で新規生成するpacketは0.1.4 protocolとする。
- Package差替え前から実行中の0.1.3 packetをhot-swapしない。
- live processとleaseがないことをPackage差替えpreflightで確認する。
- stale 0.1.3 packetを成功として再commitしない。
- Run本体の互換性と、一回限りExecutor packetの互換性を分けて扱う。

## 5. 実装Phase

### Phase 0: Baselineと互換fixture

- branchが`0.1.4`であることを確認する。
- worktree差分を記録する。
- 0.1.3の全自動test結果をbaseline化する。
- fresh、Active Round、FINALIZING、CLOSEDの0.1.3 Run fixtureを用意する。
- A001～A013の一般／CONDUCTOR mode smoke出力を保存する。
- Package install、Catalog、Runtime inspectionのbaselineを取得する。
- Linux共有filesystemで実行する受入test項目を確定する。

完了条件は、0.1.4変更前に0.1.3互換性を機械的に判定できることである。

### Phase 1: A014契約とschema

- Capability metadataへA014と三Roleを定義する。
- `global-build`、`local-screen`、`local-detail`の入力と必須Artifactを固定する。
- MMP DB、Reference Card、Query Resultのschemaを作る。
- artifact-local hash IDのcanonicalization規則を固定する。
- Endpoint、`higher_is_better`、SMILES、compound ID、Cluster IDのvalidationを定義する。
- Primary／Extended Core条件とEnvironment radiusをschemaへ記録する。
- Negative Resultを`failed`ではなく成功結果として表現するfieldを定義する。
- query spec hashと重複照会判定を定義する。

MMP固有schemaを共通`analysis_result`のrequired fieldへ混入させない。

### Phase 2: Skill scaffoldと環境

- 自己完結Skill directoryを作る。
- `env/pixi.toml`へCPU版RDKit、mmpdb `3.1.4`、pandas、numpy、scipy、pyarrow、HTML生成に必要な最小dependencyを固定する。
- 共有Pixi binaryとSkill-local cache／environment規則を既存Skillと一致させる。
- LinuxとWindowsで同じlauncher引数を提供する。
- Hugging Face等からの実行時downloadを行わない。
- `SKILL.md`にはMode選択、必須引数、Role、境界、出力を簡潔に記す。
- 人間向け`README.md`には指定された標準sectionとversion `1.0.0`の変更履歴を記す。

### Phase 3: Global MMP engine

Skill内部を次のphaseへ分ける。

```text
preflight -> fragment -> index -> export -> aggregate -> render
```

- canonical inputからcompound ID、SMILES、Endpointを読み込む。
- 重複IDをhard errorとし、invalid SMILESをCoverageへ残す。
- 分子標準化を行わず、mmpdb salt removerを無効化する。
- 1～3 cut、radius 0～5、全Transform、非symmetric Canonical方向を実行する。
- `smallest-transformation-only`を使用しない。
- Extended／Primary Core条件を適用する。
- Endpoint欠損化合物を構造DBへ保持し、効果統計だけを欠損扱いにする。
- `higher_is_better`に基づくFavorable deltaを派生する。
- Native mmpdb DBからCONDUCTOR安定schemaのSQLiteを構築する。
- 同一Pair × Transform × Coreにradius Contextを関連付け、radius重複を独立Pairとして数えない。

各phaseはinput hash、parameter hash、Engine version、完了markerをAttempt scratchへ保存する。hash一致時だけ同じAttemptで再利用する。

### Phase 4: 全情報Exportと集約

- 非圧縮`mmp_pair_detail.csv`を必須出力にする。
- 同内容のParquetをRuntime／高速再集計用に出力する。
- 化合物Pairごとの小さい検索索引`pair_summary.csv`を作る。
- `transform_summary.csv`を作る。
- `core_summary.csv`を作る。
- `transform_core_summary.csv`を作る。
- `context_summary.csv`を作る。
- `coverage_summary.csv`を作る。
- `mmp_reference_cards.jsonl`とCSV版を作る。
- SQLite、CSV、Parquetのrow count、ID集合、Endpoint delta、hashを照合する。
- 出力容量が大きいことを理由にCSVを省略しない。

集約ではPair-weightedとCore-weightedを分け、median、IQR、MAD、方向一致率、独立Core数、leave-one-core-out安定性を計算する。

### Phase 5: Reference Card抽出

決定論的抽出器は次のカテゴリーを別々に作る。

- portable Transform
- Core-dependent／sign reversal
- Context-dependent
- Pair-specific Cliff
- SAR hotspot Core
- flat／tolerated Transform
- contradiction／counterexample
- coverage／negative result

全候補はMMP固有Reference Cardへ保持する。CONDUCTOR Result Indexへはカテゴリーquotaとsupport／qualityを使ったbounded subsetだけを昇格する。抽出器は観察候補を整理するだけで、最終的な科学的Insightを確定しない。

### Phase 6: 固定HTML report

- 日本語の固定section順をtemplate化する。
- Scope、Endpoint、Core条件、Engine、件数をfact panelへ表示する。
- Core、before／after fragment、代表PairをRDKitで描画する。
- Global effect対Core effectの図を作る。
- Context radiusの親子推移を図示する。
- Support対効果、反証Pair、Negative Resultを表示する。
- 全CSVとSQLiteへの相対linkを付ける。
- 外部CDN、外部font、network accessを使わない。
- 該当候補ゼロでも各sectionを省略せず、その旨を表示する。

### Phase 7: Runtime Artifact adapter

- `analysis_result.payloads`の既存optional fieldを使い、A014の複数payloadをCanonical directoryへ昇格する。
- Capabilityが宣言したbasenameだけを許可し、path traversalとscratch外参照を拒否する。
- Runtimeが各Artifact hash、schema、row count、内部参照を検証する。
- 一部Artifactだけを成功昇格しない。
- 既存Operatorの単一primary payload adapterを変更せず残す。
- A014固有分岐を最小にし、optional multi-payload promotionを再利用可能な追加契約として実装する。
- Result Card数とMain／Interpreter working setへの流入数へ上限を設ける。

### Phase 8: Local Screening

- 成功済みGlobal A014 NodeとCluster Registry／Membership snapshotを入力にする。
- 全登録Clusterについてwithin-cluster Pairを抽出する。
- Pair両端が同じClusterに属する場合だけwithin-clusterとする。
- 片端だけ所属するPairをboundary countへ分離する。
- 重複Clusterの結果を独立再現として数えない。
- `mmp_local_screening.csv`を一Nodeで生成する。
- ClusterごとにNode、HTML、Result Cardを大量生成しない。
- Screening済みと詳細解析済みを別Booleanで記録する。
- Cluster Registry／Membership hashが変わった場合は新しいScreening Nodeを作り、旧結果を変更しない。

### Phase 9: 詳細Local選択と解析

- 構造、Fingerprint／topology、2D continuous、3D shape、Quantum／embeddingから代表Clusteringを選ぶ。
- 初期詳細対象は原則4～6 Clustering familyに抑える。
- MMP coverage、Cluster size balance、構造凝集性、membership非重複を選択材料にする。
- Endpoint効果だけで詳細対象を選ばない。
- 人間指定Clusterを優先できる。
- Global対Local、Local間、sibling Cluster、反証Pairを比較する。
- 詳細対象外は`skipped`にせず、Screening結果から後続Roundで追加可能にする。
- Localに該当Pairがない場合や差がない場合もNegative Resultとして成功させる。

### Phase 10: PlannerとAnalysis Profile

- A014をInitial Globalへ追加する。
- A014 Globalは`preauthorized_initial`のhigh-cost capabilityとし、別個の事前承認を要求しない。
- 成功済み同一signatureがあれば再利用する。
- `local-screen`は基本Clustering完了後に一つだけ候補化する。
- `global-build`、`local-screen`、`local-detail`を既存どおり一Round200 Analysis Node上限へ算入する。ScreeningはClusterごとにNodeを作らず一件だけを消費する。
- Screeningは全Clusterを表に含めるが、Working Setへ全行を入れない。
- Active 0.1.3 RoundにはA014を注入しない互換guardを実装する。
- 次の人間承認Roundで不足A014を候補化する。
- Wall Timeを詳細対象数へ変換しない。

Analysis ProfileのMMP設定は追加optional blockとし、旧profileを読み込めるDefaultをRuntime側に持たせる。

### Phase 11: Interpretation連携

- Interpretation PolicyへMMPの比較視点を追加する。
- Exact Core、Environment、CONDUCTOR Cluster-localを明確に区別する。
- Pair数と独立Core数を併記させる。
- radius親子や重複Clusterを独立再現として数えない。
- Global対Local claimには両scopeのResult参照を必須にする。
- Negative Resultと反証を省略しない。
- MMP Reference Card全件をInterpreterへ渡さず、Runtimeが選んだbounded subsetだけを渡す。
- InterpreterはDBへ自由SQLを書き込まず、追加照会をfollow-upとして提案する。

Interpretation schemaとInsight ID体系は変更しない。

### Phase 12: Catalog、Package、文書

- `included_skills.json`へA014を人間allowlistとして追加する。
- Catalogを再生成し、A014だけを新規Operator IDとして追加する。
- Package versionとRuntime protocolを`0.1.4`へ更新する。
- verifierをPackage／component version分離へ更新する。
- installerがA014をproject直下`.claude/skills/`へ配置することを確認する。
- `CONDUCTOR_overview.md`、`CONDUCTOR_user_guide.md`、`CONDUCTOR_policy.md`を更新する。
- `CONDUCTOR_output_contract.md`へMMP payloadを追加する。
- `CONDUCTOR_interpretation_policy.md`へMMP比較原則を追加する。
- `CONDUCTOR_identifier_reference.md`へartifact-local IDを追加する。
- 英文Catalogと日本語早見表へA014を追加する。
- Version historyへ0.1.4を追加する。
- prompt例は通常Round起動形式を変えず、必要ならMMP deep-dive指定例だけを追加する。
- 現行文書を直接更新し、新しいArchiveを作らない。

## 6. 試験計画

### 6.1 Unit test

- 1、2、3 cutの既知MMP fixtureを検出する。
- smallest-onlyが無効で複数の妥当な分解を保持する。
- Core fraction 0.40／0.50境界と6 Heavy atom境界を検証する。
- radius 0～5のContext親子を保持する。
- Canonical方向とFavorable deltaを検証する。
- `higher_is_better=false`でFavorable方向が反転する。
- salt removerが無効で入力構造を暗黙変更しない。
- invalid SMILES、Endpoint欠損、重複IDを契約どおり扱う。
- artifact-local hash IDが並び順とOSで変化しない。

### 6.2 Database／Export整合性

- Native DB、Canonical DB、CSV、ParquetのPair集合が一致する。
- `mmp_pair_detail.csv`が非圧縮で必ず存在する。
- `pair_summary.csv`から全詳細MMP IDを参照できる。
- Pair × Transform × Coreの重複規則が一定である。
- radius行の重複をPair supportとして数えない。
- Core、Transform、Context外部Keyが孤立しない。
- 全CSVをSpotfire互換のUTF-8、単一header、安定型で出力する。
- 大容量CSVをTop-N化または省略しない。

### 6.3 集約科学fixture

- Globalでは相殺され、特定Clusterで一方向となるTransformを検出する。
- Core間sign reversalを検出する。
- radiusを上げた場合だけ一貫するContextを検出する。
- flat TransformをPositive effectと混同しない。
- 同じ化合物の反復を独立Coreとして数えない。
- Pair数は多いが独立Coreが少ない候補へQuality flagを付ける。
- 支持傾向がないfixtureをNegative Resultとして成功させる。

### 6.4 Local Screening

- 構造ClusterとVector Clusterの双方をScreeningできる。
- Pair両端が同じClusterの場合だけwithin-clusterに入る。
- boundary Pairを別集計する。
- overlapping Clusterの独立性を過大評価しない。
- 全Clusterを一つのScreening tableへ出力する。
- 代表詳細対象が4～6 familyへ分散する。
- 詳細対象外をNode `skipped`や`failed`にしない。

### 6.5 Runtime／DAG

- A014 Globalを一Run一回だけ成功させる。
- 後続RoundでGlobal DBを再利用する。
- Cluster snapshot更新で新Screening Nodeを作り、Global DBを変更しない。
- MMP queryのNegative Resultを成功Nodeとしてcommitする。
- 部分Artifactをatomic promotionしない。
- bounded Result Card上限を超えない。
- Main向けcompact responseへ全MMP行を混入させない。
- Interrupted phaseを同じNode／Attemptでreconcileする。

### 6.6 0.1.3互換性

- 0.1.3 fresh Run fixtureを0.1.4 Runtimeでinspectできる。
- 0.1.3 Active Roundを同じRound IDで再開できる。
- Active RoundへA014が自動追加されない。
- 0.1.3 FINALIZINGから既存Interpretation／Auditを完了できる。
- 0.1.3 CLOSED Runは人間指示なしに変化しない。
- 次の人間開始RoundでA014 Global候補を追加できる。
- A001～A013、Description、Clusteringの既存一般CLI試験が通る。
- 既存Canonical schema versionとNode IDを変更しない。
- Package verifierが混在component versionを正しく検証する。
- Control schemaが0.1.3／0.1.4 Runを受理し、それ以外をfail closedにする。
- 0.1.4 Runtimeが0.1.3 Artifact Manifestを受理し、Capability不一致は拒否する。

### 6.7 General／CONDUCTOR mode

- 一般依頼では`--conductor`を自動付与しない。
- 通常モードでDB、CSV、HTMLを生成し、State fileを生成しない。
- CONDUCTOR context不足時にIDを捏造または通常モードへ黙って降格しない。
- Runtime scratchから全必須ArtifactだけをCanonical directoryへ昇格する。
- `--output-dir`がModeを変更しない。

### 6.8 Fault injection

- mmpdb fragment途中停止
- index途中停止
- SQLite破損
- CSV export中のdisk不足
- Executor／Main session停止
- Artifact hash不一致
- Cluster Registry更新中のstale Screening packet
- malformed MMP Reference Card
- HTML生成失敗

いずれもState破損、Global DBの部分上書き、別Round自動開始、無限retryを起こさないことを確認する。

### 6.9 Performance smoke

- 小規模fixtureでWindows／Linuxのend-to-endを確認する。
- Linux HPCで最大想定2,000化合物のpreflight、fragment、index、CSV export、DB size、Wall Timeを計測する。
- `available_cpu_cores`内でfragment並列数を制御する。
- indexが単一processで長時間になってもlease、heartbeat、6時間Executor契約と矛盾しないことを確認する。
- 6時間を超える見込みではNodeを分割せず、同じNodeのprocess継続／reconcile方針を確認する。必要なら人間へ資源checkpointを返す。

## 7. 実装順序

```text
0.1.3 compatibility fixtures
  -> A014 contract / schema
  -> self-contained Global engine
  -> Database / full CSV / aggregation
  -> fixed HTML / Reference Cards
  -> Runtime multi-payload adapter
  -> Local Screening / Local Detail
  -> Planner / Interpretation integration
  -> Catalog / Package / docs
  -> regression / fault-injection / HPC smoke
```

既存Runtime plannerを先にA014へ接続しない。A014の一般モード、CONDUCTOR scratch出力、schema、Artifact整合性を完成させてからRuntimeへ収載する。

## 8. リスクと抑制策

| リスク | 影響 | 抑制策 |
|---|---|---|
| 共通Coreが小さくPair数が爆発 | disk／時間超過 | Extended下限、事前件数・disk見積り、黙った打切り禁止 |
| 長時間Nodeの途中停止 | 全再計算 | phase checkpoint、process reconcile、atomic promotion |
| radius重複の過大評価 | 偽のSupport増加 | Pair instanceとContext親子を分離 |
| 同じCompound／Coreの擬似反復 | 効果の過信 | Core-weighted統計、独立Core数、leave-one-core-out |
| Vector Clusterを除外して知見を失う | 条件依存効果の見落とし | 全Cluster Screening、代表family詳細、後続Round照会 |
| 全Local結果をLLMへ渡す | Interpretation品質低下 | compact Screening、bounded Result Card、詳細対象制限 |
| MMP固有payload対応が既存Operatorを壊す | 0.1.3回帰 | optional additive adapter、旧adapter維持、回帰fixture |
| component version一括書換え | 不要な差分と監査困難 | Package／component version分離 |
| Negative Resultをfailure扱い | 無限retry／重複解析 | schema上の成功結果として明示 |
| HTMLだけが知識正本になる | 後続再利用不能 | SQLite、全CSV、Parquetを正本Artifactとして保持 |

## 9. Cutover条件

次をすべて満たすまで`CONDUCTOR_modules/VERSION`を`0.1.4`へ変更しない。

- 0.1.3互換fixtureがすべて合格する。
- A014一般モードとCONDUCTORモードが合格する。
- MMP DB、CSV、Parquet、集約表の整合性が合格する。
- Global、全Cluster Screening、詳細Local、Negative Resultの統合testが合格する。
- Runtime、Interpretation、AuditがMMP Nodeを処理できる。
- Main／Interpreter contextがboundedである。
- Package installer、Catalog、verifierが合格する。
- Python compile、JSON Schema parse、`git diff --check`が合格する。
- Linux共有filesystemで一RoundのMMP end-to-end smokeが合格する。

## 10. 完成時の変更一覧方針

実装完了時は次の単位で報告する。

- 新規Skill: `cs-analysis-matched-molecular-pairs`
- 変更した制御Skill: Runtime／Orchestrator等のSkill名
- 変更したSubagent: 原則なし。変更した場合だけ名称を明示
- `CONDUCTOR_modules/`内: Runtime、schema、Catalog、Policy、docs、testsの分類別
- 既存科学Skill: 変更なしであることを明示

科学kernelへ意図しない差分がないことをGit diffで最終確認する。
