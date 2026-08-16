# CONDUCTOR 0.1.1 Vector Clustering改良計画

## 1. 文書の位置づけ

本書は、Description Vectorを入力とするClustering Capability `C005`～`C010`の距離処理、近傍構築、既定パラメータ選択を再設計するための実装計画である。対象branchは`0.1.1`とする。

今回の実データ確認では、同じ既定値を異なるDescription／Metricへ適用した結果、次の両極端が再現した。

- D001 RDKit 2D、D013 USR／USRCAT、D016 Mordred 3Dでは、Butina、Louvain、Leiden等でClusterが形成されない、または5化合物未満へ過度に断片化する。
- D004 hashed atom-pair count fingerprintをCosineでButina clusteringすると、全化合物が一つのClusterへ収束する。

これは各アルゴリズムの計算失敗を直ちに意味しない。現行実装がEuclidean、Manhattan、Cosine等へ共通の`similarity_threshold=0.55`、DBSCANへ固定`eps=0.5`、Hierarchicalへ固定`distance_threshold=0.7`を適用し、Descriptionごとの距離尺度と各手法の近傍定義を反映できていないことが主因である。現在の既定値で得たVector Clustering結果を、化学空間にClusterが存在しない、または全化合物が同一Clusterであるという科学的結論へ直接利用してはならない。

## 2. 結論と変更境界

主な改良対象は次のVector Clustering Skillである。

| ID | Skill | 主な再設計対象 |
|---|---|---|
| C005 | `cs-compute-clustering-vector-butina` | 距離cutoff |
| C006 | `cs-compute-clustering-vector-hierarchical` | dendrogram切断条件 |
| C007 | `cs-compute-clustering-vector-dbscan` | `eps`と`min_samples` |
| C008 | `cs-compute-clustering-vector-louvain` | Graph構築と`resolution` |
| C009 | `cs-compute-clustering-vector-leiden` | Graph構築と`resolution` |
| C010 | `cs-compute-clustering-vector-connected-components` | radius graphのcutoff |

実装の正本は`CONDUCTOR_modules/tools/templates/clustering_run.py`とSkill generatorに置き、各Skillの自己完結性を維持したまま6 Skillへ同期する。

### 変更するもの

- C005～C010のClustering kernel周辺にある距離校正、近傍構築、パラメータ選択、結果診断
- 各SkillのCLI、`capability.json`、`SKILL.md`、人間向け`README.md`
- `clustering_manifest.json`、`cluster_membership.csv`、Clustering診断出力
- Catalog、標準analysis profileのClustering設定、Orchestrator向け短縮summary
- Vector Clustering関連の正本文書と検証tool／test
- package／Capability versionの`0.1.1`への更新

### 原則変更しないもの

- Description SkillのVector生成kernelと既存Description artifact
- Descriptionごとにmetadataで固定する`value_semantics`、`natural_metric`、`allowed_metrics`の契約
- 構造ベースClustering `C001`～`C004`
- categorical／meta Clustering `C011`～`C012`
- `min_cluster_size=5`のhard floor
- compound ID、SMILES、分子標準化を人間が担う責務
- Stateの単一Writer、DAG、Node／attempt／Cluster ID管理
- Operator、Interpretationの科学計算とschema
- 通常利用をdefault、`--conductor`を明示的opt-inとする契約

Description側のMetric metadataは実装前に整合性を監査するが、今回の距離分布を見てrunごとにMetricを選び直すことはしない。Metricは表現の意味から固定し、データ依存で決めるのは各Clustering手法の近傍・切断パラメータとする。metadata訂正が必要な場合もDescription計算codeは変更せず、Catalog／Capability定義の変更として独立して記録する。

## 3. 設計原則

1. **共通化するのは距離診断までとする。** 全手法へ同じ数値閾値や同じ選択式を適用しない。
2. **各アルゴリズムの本来の構造を維持する。** Butinaはcutoff型、DBSCANは密度型、Hierarchicalは階層切断型、Louvain／LeidenはGraph community型、Connected Componentsは連結性型として扱う。
3. **自動設定を既定とする。** Local LLMやOrchestratorに数値パラメータの推測を要求しない。
4. **人間指定を残す。** `fixed` modeでは各手法固有の値を明示でき、実際に使用した値をmanifestへ記録する。
5. **Endpointを使用しない。** 距離校正、候補選択、品質評価はDescription VectorとCluster membershipだけで完結させる。
6. **Clusterを無理に作らない。** 候補条件がすべて断片化、崩壊、不安定であれば、成功した計算結果として`no_usable_partition`を返す。
7. **一Nodeにつき正式partitionは一つとする。** 候補評価をNode内で行い、正式Cluster IDは選択されたpartitionだけへ発行する。代替候補をDAG Nodeとして大量生成しない。
8. **決定論的であること。** 同じ入力、metadata、parameter mode、seedから同じ候補、同じ選択、同じ出力を得る。
9. **診断と理由を失わない。** invalid Vector、algorithm noise、singleton、小Cluster除外を同じ`unassigned`へ潰さない。

## 4. 共通距離プロファイル

全Vector Clustering Skillは、Description artifactを読み込んだ後に共通仕様で距離プロファイルを作る。この処理はClustering Skill内部に置き、Description Skillや独立DAG stageは追加しない。

### 4.1 入力と前処理

1. CONDUCTORモードではDescription manifestの`value_semantics`と`natural_metric`を必須とする。
2. manifestのMetricとCapabilityの`allowed_metrics`が矛盾する場合は停止する。
3. 一般利用でmanifestがない場合は、完全な0/1 matrix等の曖昧でない表現だけを自動判定し、それ以外はsemanticsまたはMetricの明示を要求する。
4. Endpoint列を特徴量へ混入させない。Description artifactのfeature column契約から列を選ぶ。
5. binaryは0補完、continuousは中央値補完を基本とし、既存metadataに従って前処理する。
6. Euclidean／Manhattan用continuous Vectorは標準化する。Cosine／Tanimoto用の非負疎Vectorは、意味を変える中心化を行わない。
7. 全欠損列、定数列、利用不能列を除外し、除外数と理由を記録する。
8. 異なるcompound IDが同一Vectorを持つことを許容し、距離0の正当な重複として扱う。

### 4.2 距離の正本

内部表現の正本をnative distanceへ統一する。

- Tanimoto: `1 - tanimoto_similarity`
- Cosine: `1 - cosine_similarity`
- Euclidean: 標準化Vector間のEuclidean距離
- Manhattan: 標準化Vector間のManhattan距離

現行のEuclidean／Manhattan距離を`1 / (1 + distance)`へ変換し、すべてを共通`similarity_threshold`へ接続する処理は廃止する。Graph weightが必要な手法だけが、選択済み近傍上でMetricに適したweightを構築する。

### 4.3 算出する診断値

- 入力化合物数、有効Vector数、invalid／missing Vector数
- 元特徴量数、有効特徴量数、定数／全欠損除外数
- off-diagonal距離の最小、平均、標準偏差、中央値、主要分位点
- 距離のIQR、変動係数、距離集中度
- 自分自身を除いた第1、第4、第5、第10近傍距離の主要分位点。ただし標本数に応じて存在するkだけを算出する
- 距離0のcompound pair数
- Metric、前処理、feature selection、seed

全手法で同じ距離行列と診断定義を使うが、パラメータへの変換は手法別に行う。現在も多くの手法が全距離行列を計算しているため、診断の追加による主要な計算量増加は限定的である。k近傍値は全行sortではなくpartition処理を優先し、最大2,000化合物を想定したメモリ試験を行う。全距離行列自体はartifactとして保存しない。

## 5. 手法別パラメータ選択

### 5.1 C005 Vector Butina

- `auto`では、`min_cluster_size - 1`番目の近傍距離を中心に複数のnative distance cutoff候補を作る。
- 各候補で、singleton数、5以上のCluster coverage、Cluster数、最大Cluster比率、隣接候補間のmembership安定性を評価する。
- 全件一Cluster、登録Clusterゼロ、cutoffの微小変化でpartitionが大きく変わる候補へ警告または除外を適用する。
- 候補が複数同等なら、巨大Clusterを作りにくい狭いcutoffを優先する。
- `fixed`では`--distance-cutoff`をnative distance単位で受ける。Cosine／Tanimoto利用時だけ、人間向けの`--similarity-threshold`を明示変換して使えるようにする。
- Butinaが生成したsingleton／小Clusterと、無効Vectorを別理由で出力する。

### 5.2 C006 Vector Hierarchical

- 固定`distance_threshold=0.7`を既定から外す。
- `auto`ではaverage-linkage treeを一度構築し、上位linkage距離のgapから切断候補を生成する。
- 各候補についてCluster数、サイズ分布、5以上のcoverage、最大Cluster比率、precomputed distanceに対するsilhouette、隣接切断間の安定性を評価する。
- `--n-clusters`指定時は絶対距離校正を使わず、人間指定を優先する。
- `--distance-cutoff`指定時はnative distanceとして扱う。
- 階層上は全件が配置されることと、5未満を正式Cluster登録しないことを区別して記録する。

### 5.3 C007 Vector DBSCAN

- `auto`の`min_samples`は既定5とし、自分自身を除く第4近傍距離を基本に`eps`候補を作る。
- k-distance curveの変曲候補とrobust分位点を併用し、一つのelbow検出だけへ依存しない。
- 各候補についてCluster数、noise率、5以上のcoverage、最大Cluster比率、近接候補間の安定性を評価する。
- DBSCANの`noise`は正常なアルゴリズム出力として保持し、singleton／small-cluster filteringと区別する。
- 密度が場所ごとに大きく異なり、単一`eps`で安定したpartitionが得られない場合は`weak_structure`または`no_usable_partition`を返す。自動調整で全点を無理に取り込まない。
- `fixed`では`--eps`と`--min-samples`をnative distance／整数として受ける。

### 5.4 C008／C009 Vector Louvain／Leiden

- 全ペアへ固定`similarity_threshold`を適用するGraph構築を既定から廃止する。
- `auto`ではnative distanceからweighted k-nearest-neighbor graphを構築する。
- hubによる過密接続を抑えるためmutual kNNを基本とし、孤立Node数、degree分布、連結成分、最大成分比率を診断する。
- 連続距離のEdge weightは各Nodeのk近傍距離をlocal scaleとして正規化する。距離0、local scale 0、孤立Nodeを明示的に扱い、NaN／無限weightを許さない。
- 標本数と`min_cluster_size`からboundedなk候補を決定論的に作り、近接するkと`resolution`に対するpartition安定性を評価する。
- LouvainとLeidenは同一のGraph構築契約を使うが、community検出kernelはそれぞれ維持する。
- `fixed`では`--n-neighbors`、`--resolution`、`--graph-mode`を受ける。旧式radius graphが必要な場合だけ明示的なcompatibility optionとして残し、既定にはしない。

### 5.5 C010 Vector Connected Components

- native distanceのradius graphを維持し、固定`similarity_threshold=0.55`は廃止する。
- 近傍距離分布からcutoff候補を作り、cutoffごとの連結成分数、singleton率、5以上のcoverage、最大連結成分比率を追跡する。
- Edgeの連鎖で最大成分が急増するpercolation領域を検出し、その前後の候補を比較する。
- 巨大成分を避けることだけを目的にClusterを細分化せず、安定した連結成分が得られない場合は`weak_structure`を返す。
- `fixed`では`--distance-cutoff`をnative distance単位で受ける。

## 6. 共通選択・品質契約

### 6.1 parameter mode

全Vector Clustering Skillへ次を導入する。

```text
--parameter-mode auto   # default
--parameter-mode fixed  # 人間指定値を使用
```

`auto`は手法固有のbounded candidate setだけを評価する。試行数へ上限を設け、データごとに無制限なparameter searchをしない。候補生成式、候補一覧、選択順序、tie-break、seedをmanifestへ保存する。

`fixed`は研究者による再現試験、既知cutoff、strict／broad deep diveに用いる。指定値不足、Metric不一致、範囲外値は黙って補完せず停止する。

### 6.2 選択状態と品質flag

一つの排他的な品質ラベルへ情報を潰さず、次を分離する。

- `selection_status`: `selected`、`no_usable_partition`、`invalid_input`
- `quality_flags`: `fragmented`、`collapsed`、`dominant_cluster`、`sparse_graph`、`dense_graph`、`high_noise`、`unstable`、`weak_distance_contrast`

全有効化合物が一Cluster、または有効化合物が十分あるのに正式Clusterがゼロである候補は、少なくとも`collapsed`／`fragmented`として扱う。最大Cluster比率等の連続値も必ず残し、単一の硬い比率だけで科学的価値を否定しない。

候補選択はEndpoint、活性分散、下流Operator結果を使用しない。良い活性相関が得られるparameterを選ぶことは禁止する。

### 6.3 未所属理由

`cluster_membership.csv`の未所属行は少なくとも次を区別する。

- `invalid_smiles`
- `missing_description_vector`
- `algorithm_noise`
- `singleton_cluster`
- `filtered_small_cluster`
- `no_usable_partition`

これにより、Clusteringが化合物を評価できなかった場合と、評価後に小Cluster／noiseとなった場合を区別する。

## 7. 出力契約

### 7.1 通常利用

通常利用では従来の主成果物を維持する。

- `cluster_membership.csv`
- `cluster_summary.csv`
- `clustering_diagnostics.csv`

`clustering_diagnostics.csv`にはMetric、parameter mode、採用値、selection status、Cluster数、coverage、未所属内訳、最大Cluster比率、主要quality flagを一行で記録する。

### 7.2 CONDUCTOR利用

CONDUCTORモードでは上記に加えて次を出力する。

- `distance_profile.json`
- 拡張した`clustering_manifest.json`
- `cluster_registry.json`
- `warnings.json`
- `execution_event.json`

`clustering_manifest.json`へ、Description provenance、固定Metric、前処理、候補parameter、採用parameter、selection basis、距離profile summary、品質指標、未所属内訳を追加する。変更は既存必須fieldを保持する加算的変更とし、State schema majorは変更しない。`distance_profile.json`をexecution eventのartifact一覧へ登録する。

正式partitionが得られない場合も、入力と計算が正常ならNodeは`succeeded`とする。ただし`selection_status=no_usable_partition`、Cluster数0、理由、診断artifactを必須とする。Runtime／Orchestratorはこれを実行失敗と混同せず、このClusteringを起点とするCluster-local Operatorを計画しない。

## 8. OrchestratorとDAGへの影響

- Orchestratorは通常、数値cutoff、`eps`、Graph thresholdを決定しない。基本計算では各Skillを`auto`で計画する。
- `orchestrator_brief.json`には全距離分布を入れず、selection status、quality flags、Cluster数、coverage、最大Cluster比率だけを短く掲載する。
- `no_usable_partition`はnegative resultとして保持し、別のDescription／Clusteringへ探索範囲を広げる判断材料にする。
- 人間がstrict／broad条件や既知parameterを指定した場合は、同じDescriptionを入力とする別Clustering Nodeとして`fixed`実行する。
- Node signatureへparameter mode、Metric、手法固有parameter、選択仕様Versionを含める。自動選択仕様が変わった結果を同一signatureとして再利用しない。
- State、Node ID、Cluster ID、attempt、lease、Round terminal gateの仕組みは変更しない。

## 9. 既存結果の扱い

- 0.1.0からは成功済みDescription artifactだけを専用の決定論的Migration Patchで再利用し、Descriptionの高コスト計算をやり直さない。
- 0.1.0既定値で生成したC005～C010の結果は、距離校正後の結果と同等とは見なさない。
- 旧Clustering、Analysis、Interpretation、Cluster、Insight、Next Actionは移行しない。
- 移行先のRND0001は成功済みDescriptionだけを持ち、`partial_basic_compute`／`version_migration_during_basic_compute`として閉じる。
- MigrationはRND0002を作成せず、Orchestratorも起動しない。人間がRND0002を明示的に開始した時点で、RuntimeはDescriptionをsignatureで再利用し、未完了の構造／Vector Clustering以降を計画する。
- 元0.1.0 Runはread-onlyとし、移行先は存在しない新規directoryへatomicに作成する。

## 10. 実装工程

### Phase 0: baselineとMetric監査

- clean worktree、branch、package Version、現行testを確認する。
- C005～C010の現行CLI、defaults、距離変換、Graph構築、small Cluster filteringをfixture化する。
- D001～D020の`value_semantics`、`natural_metric`、`allowed_metrics`と実artifact manifestの一致を監査する。
- 実データで確認された断片化／崩壊を、機密情報を含まないsynthetic fixtureとして再現する。

### Phase 1: 共通距離基盤

- native distance計算、feature validation、距離profile、k近傍summaryをtemplateへ実装する。
- `1 / (1 + distance)`による共通similarity変換をVector Clustering既定経路から除去する。
- invalid、missing、duplicate Vectorの扱いと未所属理由を実装する。
- 共通診断出力とmanifest拡張を実装する。

### Phase 2: radius／density／hierarchical手法

- C005 Butinaのcutoff候補と選択を実装する。
- C007 DBSCANのk-distance候補、noise契約、`min_samples=5`既定を実装する。
- C006 Hierarchicalのlinkage gap候補と切断評価を実装する。
- C010 Connected Componentsのpercolation診断とcutoff選択を実装する。

### Phase 3: community手法

- C008／C009共通のweighted mutual-kNN graph builderを実装する。
- local scale weight、k候補、Graph診断、partition安定性を実装する。
- Louvain／Leiden固有kernelとseed契約を維持して接続する。

### Phase 4: Skill・Catalog・Orchestrator同期

- generatorからC005～C010のscripts、Capability metadata、SKILL／READMEを同期する。
- Catalog、標準analysis profile、Skill catalogを再生成する。
- Orchestrator／RuntimeのClustering summary取得と`no_usable_partition`分岐を最小変更する。
- package version／Capability versionを`0.1.1`へ揃える。

### Phase 5: 文書・検証

- overview、design spec、output contract、user guide、policy、verificationへ新しい責務境界を反映する。
- package layout、Catalog生成、全Python構文、一般利用／CONDUCTOR利用を検証する。
- Linux／WindowsでPixi環境の再利用を確認する。依存package追加がない場合は既存`env/pixi.toml`／lockを保持する。

### Phase 6: Description限定Migration

- `scan`、`apply`、`verify`を持つ0.1.0→0.1.1決定論的Patchを追加する。
- Description CSVのhashとcompound順序を検証し、CSV本体をbyte-identicalにcopyする。
- 新しいmanifest／execution event／Stateだけを0.1.1契約で構築する。
- 専用Agentを追加し、自由記述によるState編集、RND0002作成、Orchestrator起動を禁止する。
- Migration fixtureでDescription以外が除外されること、RND0001が基本計算途中として閉じること、次Round番号が2であることを検証する。

## 11. 受入試験

### 共通契約

- 同じ入力、Metric、mode、seedで距離profile、候補、正式partitionが一致する。
- Endpoint列や活性値を変えてもClustering結果が変化しない。
- manifestのMetricと明示Metricが矛盾する場合に停止する。
- 異なるIDの同一Vectorを距離0として保持する。
- invalid、missing、noise、singleton、小Cluster除外を正しく区別する。
- `min_cluster_size=5`未満を拒否し、4以下へGlobal Cluster IDを発行しない。
- `fixed` modeで人間指定値をそのまま再現する。
- `auto`で正式partitionが得られない場合、失敗ではなく診断付き`no_usable_partition`になる。

### 再現fixture

- RDKit2D相当の高次元continuous／Euclidean synthetic clusterで、固定0.818相当の過剰断片化を再現し、新Butina／Graph系が非退化partitionを選べることを確認する。
- USR／USRCAT相当の多次元Manhattan synthetic clusterで、距離加算による断片化を解消できることを確認する。
- Mordred 3D相当の高次元・相関・部分欠損continuous fixtureで、前処理と距離校正が安定することを確認する。
- D004相当の疎count／Cosine fixtureで、過密近傍による全件一Clusterを検出し、非退化候補または`no_usable_partition`を返すことを確認する。
- Cluster構造を持たない一様データでは、都合のよいClusterを強制せず`weak_structure`を記録する。

### 手法別

- Butina: cutoff順序に対してCluster統合傾向が整合し、singleton理由を保持する。
- Hierarchical: linkage tree、gap候補、固定`n_clusters`、固定distance cutoffが再現する。
- DBSCAN: noiseとsmall Clusterを区別し、k-distance候補が再現する。
- Louvain／Leiden: 空Graph／過密Graphを診断し、同じweighted kNN graph入力を使用する。
- Connected Components: cutoff増加に対するcomponent統合とpercolation検出が整合する。
- 2,000化合物fixtureで実行時間、距離行列メモリ、候補探索上限が許容範囲内である。

### DAGと下流

- `selected` ClusteringだけがCluster registry／membership matrixへcommitされる。
- `no_usable_partition`からCluster-local Operatorが計画されない。
- Vector Clusteringをstale化した場合、依存Operator／Interpretationだけがstaleになる。
- 構造ベースClusteringの出力とState commitが変化しない。
- 一般利用で`--conductor`が暗黙付与されず、CONDUCTOR利用で診断artifactとexecution eventが揃う。

## 12. リスクと抑制策

### データセット依存性

自動parameterは同じDescriptionでも入力集合によって変化する。これは局所密度へ適応するために必要だが、異なるRun間でcutoff数値を直接比較できなくなる。距離profile、選択式Version、候補、採用値を保存して追跡可能性を担保する。

### 自動選択による見かけのCluster生成

coverageやCluster数だけを最大化すると、構造のない空間にもClusterを作り得る。Endpointを完全に除外し、距離contrast、parameter近傍での安定性、退化判定を併用し、適切な候補がなければ`no_usable_partition`を許容する。

### DBSCANの異質密度

単一`eps`では複数密度を同時に扱えない。今回の改良はその限界を隠さず`weak_structure`として報告する。HDBSCAN等の追加は本計画へ混在させず、必要性を実データで評価して独立Capabilityとして検討する。

### Graph communityのparameter依存

kと`resolution`でpartitionが変化する。近接parameter間の安定性を記録し、一つの結果を絶対的分類として扱わない。候補を大量の正式Nodeへ展開せず、primary partitionと診断だけを保存する。

### 実装重複

Skill単独コピー可能性のため実行codeは各Skill directoryに必要である。手編集による不一致を避けるため、template／generatorを唯一の編集元とし、package verifierで生成先の同期を検査する。

## 13. 実装開始条件

次を満たした時点で実装を開始できる。

1. 改良対象をC005～C010に限定し、Description kernelと構造Clusteringを保護する。
2. MetricはDescription表現ごとに固定し、parameter自動選択と混同しない。
3. 共通距離profileと手法別parameter selectorを分離する。
4. `auto`を既定、`fixed`を人間overrideとして残す。
5. `min_cluster_size=5`を維持し、Clusterを強制作成しない。
6. 既存Vector Clustering結果を新仕様と同等扱いせず、再計算境界を明示する。

この境界であれば、主変更はClustering Skill群へ局所化できる。Runtime／Orchestratorの変更は、品質summaryの読取りと`no_usable_partition`から下流を計画しない制御に限定され、状態管理やInterpretationを再設計する必要はない。

## 14. 実装・検証結果

0.1.1ではC005～C010へ共通native-distance profileと手法別bounded selectorを実装し、各Skillへgeneratorから同期した。Description計算kernelは変更せず、0.1.1 manifest Versionへの更新だけを行った。RuntimeはClustering manifestの短い品質summaryをNodeへcommitし、`no_usable_partition`を下流Cluster-local計画から除外する。

Migrationは`CONDUCTOR_modules/tools/migrate_description_010_to_011.py`と`cs-conductor-description-migrator` Agentで実装した。fixtureでは、0.1.0のClustering Nodeが存在してもDescriptionだけが移り、RND0001が基本計算途中として閉じ、RND0002を人間が開始して`plan-basic`した際に移行済みDescriptionが重複生成されないことを確認した。

repositoryの26 testは全件成功し、package layout、Catalog、全Python構文も成功した。2,000化合物×32次元のsynthetic fixtureでは距離行列は約30.5 MiB、6手法のbounded候補数は4～9であり、同一process上の各partition選択は約0.5～5.6秒だった。この実測はWindows開発環境での計算境界確認であり、実Descriptionの科学的なCluster品質を保証するものではない。実データでは`clustering_diagnostics.csv`と`distance_profile.json`を必ず確認する。
