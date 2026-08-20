# CONDUCTOR 0.1.4 仕様概要

## 1. 文書の位置づけ

本書は、CONDUCTOR `0.1.4`で追加するMatched Molecular Pair（MMP）解析と、既存CONDUCTORへ統合するための仕様を定める。

`0.1.4`は`0.1.3`のMain Agent Orchestration、短命Executor、Interpreter、Runtime単一Writer、人間管理のRound、5状態Node、DAG、bounded Working Set、Interpretation終端gateを維持する。Description、Clustering、既存Operator A001～A013の科学計算kernelと一般利用CLIは変更しない。

新機能は一つの疎結合Operator Capabilityとして追加する。

```text
A014  cs-analysis-matched-molecular-pairs
```

現行コードはGitで保持されているため、新しいArchiveは作成しない。

## 2. 結論

MMP結果は一回のHTMLレポートを作るためだけの出力ではなく、同じRunの後続Roundから繰り返し参照する不変の解析データベースとする。

設計を次の三層へ分ける。

```text
網羅的なMMP列挙と保存
  -> 決定論的な全Cluster Screening
  -> 選択された観点の詳細解析とInterpretation
```

- MMP列挙時に、Endpoint効果、統計的有意性、Pair数、注目度で結果を捨てない。
- Exact Core、Transform、Pair、Environmentを再照会可能な形で保持する。
- 全Clusterは軽量Screeningするが、初回から全Clusterの詳細HTMLとResult Cardを作らない。
- 「支持される傾向がない」「該当Pairがない」ことも、照会条件とともに正式な結果として保持する。
- 詳細解析対象を限定しても、Global MMP DatabaseとScreening索引から後続Roundで追加できる。

## 3. 0.1.3との互換性

### 3.1 必須互換範囲

| 対象 | 0.1.4での扱い |
|---|---|
| 既存Capability ID | D001～D020、C001～C012、A001～A013、I001、O001以降を維持 |
| 共通Canonical schema | `description_result/1.0.0`、`clustering_result/1.0.0`、`analysis_result/1.0.0`、`result_card/1.0.0`を維持 |
| Node／Round | `N######`、`RND####`、5状態Node、Round FSMを維持 |
| State正本 | `conductor_control.json`、Event Ledger、DAG Snapshot、Result Indexを維持 |
| 既存Artifact | 書換え、再採番、再計算を行わない |
| 既存Skill | 科学計算kernel、一般利用CLI、`--conductor` opt-inを維持 |
| 既存Run | migrationなしでinspection、Active Round再開、次Round開始を可能にする |

0.1.4固有情報はA014 Artifactと、既存schemaのoptional fieldまたは新規MMP固有schemaへ格納する。共通schemaへ新しい必須fieldを追加しない。

Package versionと個別Capability versionは分離する。変更しない科学Skillは`0.1.3`のcomponent versionを保持でき、0.1.4で追加または変更したcomponentだけを`0.1.4`とする。CatalogはPackage versionと各component versionを別々に記録する。

現行`conductor_control.schema.json`の`schema_version=3.0.0`は維持し、`conductor_version`のsupported setを`0.1.3`と`0.1.4`にする。新規Runは`0.1.4`で作成し、既存Runの値は書き換えない。Artifact Manifestもproducer contractとして`0.1.3`と`0.1.4`を受理する。一方、Execution packet、Failure packet、compact responseは一回限りの制御protocolであるため、0.1.4 Runtimeが新しく発行した`0.1.4` protocolだけを実行する。

### 3.2 既存Runへ導入する場合

- 0.1.3のActive RoundへA014を遡及追加しない。
- Active Roundは既に承認された計画のままInterpretationとAuditまで完了できる。
- Closed Roundや既存Artifactを変更しない。
- 次に人間が開始したRoundで、成功済みA014 Global Nodeがなければ`global-build`候補を追加する。
- 人間の明示指示なしに、Package差替えだけを理由として新Roundを開始しない。
- 実行中processまたは有効leaseがある状態でPackageを差し替えない。停止後に同じRunを再開する。

この互換性は、MMPを既存段階へ埋め込まず、追加Capabilityと追加Artifactとして接続することで実現する。

## 4. CapabilityとRole

A014は一つのSkill directoryに科学kernel、CLI、schema、Pixi環境、HTML rendererを自己完結して配置する。Runtimeや共有Python packageへMMP科学計算を移さない。

### 4.1 `global-build`

- canonical input CSVの全valid SMILESをfragment化する。
- 全MMP Pair、Transform、Exact Core、Environment radiusを構築する。
- Endpoint欠損化合物も構造DBには保持し、効果統計からだけ除外する。
- Global集約表、CONDUCTOR安定query DB、Spotfire用CSV、HTMLを生成する。
- Run内で同一signatureを一回だけ成功させ、後続Roundでは再利用する。

### 4.2 `local-screen`

- 成功済み`global-build` Artifactと、現在のCluster Registry／Membership snapshotを読む。
- 登録済み全Clusterを決定論的かつ軽量にScreeningする。
- Clusterごとの詳細Nodeや長いHTMLを大量生成せず、一つの索引表へまとめる。
- Cluster Registryが増えた場合は、元DBを変更せず、新しいsnapshot hashのScreening Nodeを作る。

### 4.3 `local-detail`

- Global DB、Screening結果、人間またはOrchestratorが選んだClusterを入力とする。
- Global対Local、Local間、反証Pair、Context依存性を詳しく比較する。
- MMP列挙は再実行しない。
- 注目傾向がない場合も成功したNegative Resultとしてレポートする。

## 5. MMP列挙仕様

### 5.1 基本設定

| 項目 | 仕様 |
|---|---|
| Engine | mmpdb `3.1.4`をSkill Pixi環境へ固定 |
| Cut数 | 1、2、3箇所の非環結合切断 |
| Smallest transformation | 使用しない |
| Variable size | `max-variable-heavies=none`。Core下限で制御 |
| Environment radius | 0～5をすべて保存 |
| 方向 | symmetric複製は作らずCanonical方向を一件保存 |
| Favorable方向 | `higher_is_better`から派生列として計算 |
| 分子標準化 | Scope外。mmpdbのsalt removerを無効化 |
| Network | 実行時downloadを禁止 |
| Platform | Linuxを主対象、Windowsでも同一CLIを提供 |

Canonical方向だけを保存しても、逆方向は符号反転により完全に導出できるため、科学情報は失われない。

### 5.2 Core下限

Coreの評価には分子量ではなくHeavy atom数を主に使う。

```text
core_fraction = min(
  core_heavy_atoms / molecule_1_heavy_atoms,
  core_heavy_atoms / molecule_2_heavy_atoms
)
```

初期設定は二層とする。

| Tier | 条件 | 用途 |
|---|---|---|
| Extended | `core_fraction >= 0.40`かつ`core_heavy_atoms >= 6` | 後続Roundから再照会できる広いDB |
| Primary | `core_fraction >= 0.50`かつ`core_heavy_atoms >= 6` | 通常の集約、Reference Card、初期Interpretation |

Extended未満はCanonical MMP Databaseへ登録しない。Primary未満でもExtendedを満たすPairは保存し、`eligibility_tier=extended`を付ける。

CLIは次を提供する。

```text
--extended-min-core-fraction 0.40
--primary-min-core-fraction 0.50
--min-core-heavy-atoms 6
```

解決済み値、分布、除外件数をManifestとCoverageへ記録する。Endpointを閾値調整へ使用しない。

### 5.3 Environment

Environment radiusはTransformの結合点周辺にあるCore側環境の具体性を表す。

- radius 0: 結合点環境を実質的に区別しない。
- radius 1: Core側の直接結合原子を考慮する。
- radius 2以降: より遠い周辺原子を順次含める。
- radiusが大きいほど具体的になるが、Supportは小さくなる。

同じMMPをradiusごとに独立した再現として数えない。Pair詳細表では一つのMMP instanceへradius 0～5のContext IDを関連付け、Context集約表では親子関係を保持する。

参考: [mmpdb公式リポジトリ](https://github.com/rdkit/mmpdb)、[mmpdb schema](https://github.com/rdkit/mmpdb/blob/master/mmpdblib/schema.sql)

## 6. MMP Databaseと出力

### 6.1 Canonical Artifact

`global-build`のCanonical directoryは既存Operatorと同じ場所を使う。

```text
<run_root>/analysis/N######/
├── result.json
├── result_card.json
├── report.html
├── detail.html
├── mmp_database.sqlite
├── mmpdb_native.sqlite
├── mmp_pair_detail.csv
├── mmp_pair_detail.parquet
├── pair_summary.csv
├── transform_summary.csv
├── core_summary.csv
├── transform_core_summary.csv
├── context_summary.csv
├── coverage_summary.csv
├── mmp_reference_cards.jsonl
└── mmp_reference_cards.csv
```

`mmpdb_native.sqlite`はEngine由来の再現用DB、`mmp_database.sqlite`はCONDUCTORが保証する安定query schemaとする。後続Nodeは原則`mmp_database.sqlite`をread-onlyで使用する。

### 6.2 Spotfire用全情報CSV

`mmp_pair_detail.csv`は非圧縮CSVとして必ず生成する。一行は次の単位とする。

```text
compound pair × transform × exact core
```

主な列は次とする。

- MMP、Pair、Transform、Coreのartifact-local ID
- 両化合物のID、SMILES、Endpoint、Canonical delta、Favorable delta
- variable fragment before／after、cut数、attachment mapping
- Exact Core SMILES、Heavy atom数、分子量、両親分子に対するCore比率
- Primary／Extended tier
- radius 0～5のContext ID、SMARTS、pseudo-SMILES
- Pair、Compound、Core単位のSupport情報
- missing endpoint、invalid structure、low support等のQuality flag
- Global source Node、input hash、parameter hash、Engine version

SQLite、CSV、Parquet間の行数、ID集合、hash対応をRuntime validationで照合する。CSVが大きくても黙って省略またはTop-N化しない。

`pair_summary.csv`は化合物Pairを一行とし、同じPairに存在するTransform数、Exact Core数、Endpoint delta、Primary／Extended内訳、詳細MMP IDを集約する。網羅性の正本は`mmp_pair_detail.csv`とし、`pair_summary.csv`は検索用の小さい索引とする。

### 6.3 Artifact-local ID

MMP内のIDはRuntime global IDと分離し、正規化内容のhashから決定論的に生成する。

| Prefix | 意味 |
|---|---|
| `MMP-<hash>` | Pair × Transform × Exact Core instance |
| `TRF-<hash>` | Canonical Transform |
| `CORE-<hash>` | Exact Core |
| `CTX-<hash>` | Transform Environment |
| `MRC-<hash>` | MMP Reference Card |

並び順やRoundが変わっても同じ正規化内容は同じIDとなる。`C######`のCONDUCTOR Cluster IDとは混同しない。

### 6.4 不変性と再照会

- 成功昇格したGlobal MMP Artifactを後続処理が更新しない。
- Local解析、Concierge、後続RoundはSQLiteをread-onlyで開く。
- 照会結果は別Analysis Nodeまたは`concierge/REQ######/`へ保存する。
- 同じ照会条件はcanonical query spec hashで識別し、重複計算を避ける。
- 該当Pairなし、Support不足、Globalとの差なしも`negative_result`として保存する。

## 7. 集約と知見候補

Endpoint効果の大きさだけで一つの総合ランキングを作らない。少なくとも次のカテゴリーを独立に抽出する。

1. 複数Coreで方向が揃うportable Transform
2. Coreによって効果が変化または反転するTransform
3. Environment radiusで結論が変化するTransform
4. 強いPair-specific Cliff
5. 多数のTransformとEndpoint変動を持つSAR hotspot Core
6. 多様なCoreで影響が小さいflat／tolerated Transform
7. 有望傾向に対する反証、例外、矛盾
8. MMP coverage、Endpoint欠損、Support不足などの限界

統計は次を併記する。

- MMP instance数、一意な化合物Pair数、独立化合物数を分離したPair-weighted効果とCore-weighted効果
- median、IQR、MAD、方向一致率
- Compound数、Pair数、独立Exact Core数
- leave-one-core-out安定性
- Global Endpoint IQRまたはMADで標準化した効果量
- 元のEndpoint単位の効果量

同じ化合物、同じPair、radius親子を独立標本として過大評価しない。p値だけでReference Card採否を決めない。

## 8. GlobalとCluster-local

CONDUCTORでの用語は次に限定する。

- Global: RunのEndpoint-valid全化合物を対象とする集約。
- Local: 一つ以上のCONDUCTOR Clusterに限定した集約。
- Exact CoreとEnvironmentはMMP内部の構造Keyであり、Localというscope名には使わない。

within-cluster MMPは、Pairの両化合物が同じClusterへ所属する場合に限る。片方だけが所属するPairは`cluster_boundary_pair`として別に数える。重複Clusterに同じPairが現れても、独立した再現とはみなさない。

### 8.1 全Cluster Screening

`mmp_local_screening.csv`は全登録Clusterを一行ずつ保持し、少なくとも次を含む。

- Clustering Node／Capability、Cluster ID、由来Description Node／Capability、input kind
- Cluster sizeとGlobal比率
- within-cluster MMP Pair数、独立Core数、Transform数
- Global対Localの効果差、方向反転候補数
- Localで一貫性が改善した候補数
- MMP coverageとQuality flag
- `screened=true`、`detailed_analysis=true/false`

ScreeningされただけのClusterを`skipped`、`failed`、`completed detailed analysis`として扱わない。

### 8.2 初回詳細対象

構造由来だけへ限定しない。初回は原理が異なるClustering familyから4～6種類程度を選ぶ。

- MCS／Scaffold系
- Fingerprint／トポロジー系
- 2D物性・連続記述子系
- 3D shape系
- QuantumまたはPretrained embedding系

選択はMMP coverage、Cluster size balance、構造凝集性、他候補とのmembership重複を使い、Endpoint効果そのものだけでは決めない。人間は任意のClusterを追加できる。

## 9. DAGとOrchestration

```text
canonical input --------------------> A014 global-build
                                             |
Description -> Clustering -------------------+--> A014 local-screen
                                                    |
                                                    +--> A014 local-detail
                                                              |
                                                              v
                                                       I001 Interpretation
```

- `global-build` signatureはinput hash、Endpoint、`higher_is_better`、fragmentation／Core parameter、mmpdb versionで固定する。
- `local-screen` signatureはGlobal MMP NodeとCluster Registry／Membership hashで固定する。
- `local-detail` signatureはGlobal MMP Node、Screening Node、対象Cluster ID、比較parameterで固定する。
- 依存NodeとsignatureはRuntimeが決定し、Main、Executor、InterpreterはIDやEdgeを直接編集しない。
- A014 GlobalはInitial Globalで一回実行するpreauthorized high-cost Operatorとする。
- Screeningは一つのcompact Nodeとして扱い、ClusterごとにDAG Nodeを大量生成しない。
- `global-build`、`local-screen`、`local-detail`はいずれもAnalysis Nodeとして一Roundの上限200件に含める。ただしScreeningはClusterごとにNodeを作らず一件に集約する。

長いWall Timeは列挙完了のための資源であり、Reference Card数を増やす指定ではない。

## 10. Result CardとInterpretation

Global Nodeは一つの通常`result_card.json`を持つ。全候補は`mmp_reference_cards.jsonl`へ保存し、その中からカテゴリー間の均衡を取ったbounded subsetだけをCONDUCTOR Result Cardへ昇格する。

Interpreterは次を必ず区別する。

- GlobalとCONDUCTOR Cluster-local
- Exact Core依存性とCluster依存性
- Pair数と独立Core数
- PrimaryとExtended
- 支持結果と反証結果
- Positive patternとNegative Result
- 観察事実と化学的説明仮説

MMPだけから作用機序、結合様式、因果を断定しない。既存A009 Activity Cliff等との照合はstable compound ID／MMP IDで行い、A014にA009を必須依存させない。

## 11. 人間向けHTML

固定templateを使用し、少なくとも次を同じ順序で表示する。

1. 対象Endpoint、Global／Local scope、Core条件、Engine／parameter
2. MMP coverageと除外理由
3. portable Transform
4. Core-dependent／sign-reversal Transform
5. Context radius依存性
6. Pair-specific Cliffと反証Pair
7. SAR hotspot Coreとflat Transform
8. Global対Local比較
9. Negative Resultと未確認範囲
10. 詳細CSV、SQLite、各集約表へのリンク

Core、variable fragment、代表PairをRDKitで描画し、外部CDNやnetwork resourceへ依存しない。Top候補だけをHTMLへ表示しても、全情報CSVとDBは必ず残す。

## 12. 一般利用とCONDUCTOR利用

通常モードをdefaultとし、CONDUCTOR利用が明示された場合だけ`--conductor`を付ける既存原則を維持する。

- 通常モード: 入力CSVからMMP DB、詳細CSV、集約CSV、HTMLを生成する。State、Node、Execution Eventは生成しない。
- CONDUCTORモード: project、run、round、node、attemptを必須とし、Runtime scratchへManifest、Event、summaryを含めて生成する。
- `--output-dir`は出力先だけを変更し、モードを変更しない。
- 重複compound IDはhard error、invalid SMILESはCoverageへ残す。

## 13. 長時間実行と失敗

Skill内部を`preflight -> fragment -> index -> export -> aggregate -> render`の決定論的phaseへ分ける。Nodeは一つのまま、Attempt scratch内にphase checkpointとinput／parameter hashを置く。

- Executorやtool callの中断後も、同じNode／AttemptをRuntimeがreconcileする。
- hashが一致する完了phaseは再利用できる。
- 一部CSVやSQLiteだけが存在する状態を成功昇格しない。
- 全必須Artifact、schema、行数、参照整合性、hashが合格してからatomic promotionする。
- 事前に予想Pair数、disk、memoryを報告するが、科学的結果を黙って打ち切らない。
- 利用可能資源では完遂不能な場合は`resource_preflight_blocked`として人間へ返す。

## 14. Scope外

- 分子標準化、tautomer、protonation、salt処理の自動修正
- MMPからの新規SMILES生成
- MMP効果だけを使った自動合成優先順位決定
- 0.1.3 Artifactの書換えまたはmigration
- 全Reference CardをInterpreter contextへ投入すること
- MMP Local結果だけから因果関係を断定すること

## 15. 受入要約

0.1.4は次を同時に満たした場合だけ完成とする。

- 0.1.3 Runをmigrationなしで再開できる。
- A001～A013と既存科学Skillの回帰試験が通る。
- A014 Global DBがPair、Transform、Exact Core、radius 0～5を再照会できる。
- 非圧縮の全情報CSVを必ず生成する。
- 全Cluster Screeningと限定された詳細Local解析を分離できる。
- Negative Resultを成功Artifactとして保持できる。
- Interpretationへ渡す情報量がboundedである。
- 既存RoundへMMPを勝手に追加せず、人間のRound権限を維持する。
