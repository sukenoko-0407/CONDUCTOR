# CONDUCTOR 0.1.0 リファクタリング計画・実装記録

## 1. 文書の位置づけ

本書は、alpha系列の実装を基礎としてbeta版`0.1.0`へ移行した作業計画と実装結果を記録する。作業branchは`0.1.0`、旧コードのArchiveは作成しない。本版は、Local LLMによる運用、異常終了からの回復、長期Multi-Round運用を重点に、確定した契約と検証境界を記載する。

## 2. 目的

1. `Grouping`／`Group`を廃止し、`Clustering`／`Cluster`へ完全統一する。
2. package、Skill、schema、State、artifact、文書のVersionを`0.1.0`へ揃える。
3. PCA、UMAP、複数Description統合モデルをAnalysis Capabilityとして追加する。
4. Interpretationの内部管理と人間向け出力を簡潔かつ再現性の高い固定形式へ改める。
5. Local LLMでもOrchestratorが短い状態入力から安全に一つのRoundを完遂できる構造を維持する。
6. 重複文書・不採用画像・旧migration資料を整理し、package容量と監査負荷を下げる。

## 3. 変更境界

### 原則維持するもの

- 既存Description、Clustering、Operatorの科学計算kernelと主要数値結果
- 一般利用をdefault、`--conductor`を明示的opt-inとする契約
- Skill単独コピー可能性とSkill-local Pixi環境／cache
- 各Skillの`env/pixi.toml`、共有Pixi binary優先、Skill-local cache環境変数。未構築SkillはLinux初回起動時にlockと環境を生成し、以後`--locked`で再利用する
- Stateの単一Writer、lease、DAG、Round終端Interpretation、Full Audit gate
- 同一Node内のattempt分離と、遅れて終了した旧attemptの結果を採用しない契約
- `CONDUCTOR_modules/`をruntime read-onlyとする境界
- compound ID、SMILES、分子標準化を人間が担う責務
- DescriptionはCSVまたは一件以上のSMILESを受け付け、構造Clusteringはcompound ID／SMILES列を持つCSV、Vector ClusteringはDescription artifact／vector tableを受け付ける入力境界

### 主な再設計対象

- Clustering／Clusterに関係するState、schema、artifact、path、CLI、Skill名
- Orchestrator briefと決定論的Runtime planner
- Interpretation schema、ID、renderer、HTML theme、Operator summary index
- Catalog、analysis profile、Capability metadata
- 新規Analysis Skill `A003`～`A005`
- `D019` GFN2-xTB拡充と`D020` ChemBERTa embedding
- docs、説明用HTML／PNG／PPTX、生成・検証tool

## 4. 確定事項

### 4.1 用語と識別子

次の対応で旧用語を廃止する。

| 旧 | 新 |
|---|---|
| `grouping` stage/path | `clustering` stage/path |
| `Grouping` | `Clustering` |
| `Group` | `Cluster` |
| `grouping_node` | `clustering_node` |
| `grouping_representation` | `clustering_representation` |
| `target_group_id` | `target_cluster_id` |
| `group_membership` | `cluster_membership` |
| `group_registry` | `cluster_registry` |
| `grouping_manifest.json` | `clustering_manifest.json` |
| Node prefix `NG` | Node prefix `NC` |
| runtime Group ID `G######` | runtime Cluster ID `CL######` |

Capability IDはbeta版で次の機能順へ整理する。

#### Description ID

| ID | Capability |
|---|---|
| D001 | RDKit 2D descriptors |
| D002 | Morgan fingerprint |
| D003 | MACCS keys |
| D004 | Hashed atom-pair fingerprint |
| D005 | Hashed topological-torsion fingerprint |
| D006 | RDKit fragment counts |
| D007 | RDKit path fingerprint |
| D008 | RDKit pattern fingerprint |
| D009 | RDKit layered fingerprint |
| D010 | Avalon fingerprint |
| D011 | Gobbi 2D pharmacophore fingerprint |
| D012 | RDKit 3D descriptors |
| D013 | USR／USRCAT |
| D014 | Basic 3D shape descriptors |
| D015 | Mordred 2D descriptors |
| D016 | Mordred 3D descriptors |
| D017～D018 | 将来の3D／electronic／reactivity Description用予約 |
| D019 | GFN2-xTB quantum descriptors |
| D020 | ChemBERTa-100M-MLM embedding |
| D021以降 | その他のpretrained molecular embedding |

現行`D017`のGobbi Pharm2Dを空いている`D011`へ移し、現行`D020`のxTBを`D019`、現行`D019`のpretrained embeddingをChemBERTaへ固定して`D020`とする。D001～D010とD012～D016は維持する。

#### Clustering ID

現行の並びはすでに、構造Clustering `C001`～`C004`、Vector Clustering `C005`～`C010`、categorical／meta Clustering `C011`～`C012`となっているため維持する。

#### Operator ID

| ID | Capability |
|---|---|
| A001 | Activity distribution |
| A002 | Descriptor-activity correlation |
| A003 | PCA projection |
| A004 | UMAP projection |
| A005 | Multi-Description feature model |
| A006 | Pairwise structure similarity |
| A007 | kNN activity consistency |
| A008 | SALI |
| A009 | Activity cliff detection |
| A010 | Cluster profile |
| A011 | Cluster activity enrichment |
| A012 | Cluster overlap |
| A013 | Cluster structural diversity |

Operatorは、基本統計・feature解析 `A001`～`A005`、landscape解析 `A006`～`A009`、Cluster解析 `A010`～`A013`の順へ再附番する。

現行IDからの対応は、A002→A001、A004→A002、新規PCA→A003、新規UMAP→A004、新規統合model→A005、A003→A006、A005→A007、A006→A008、A007→A009、A001→A010、A008→A011、A009→A012、A010→A013とする。

旧名を含む次のOperator Skill directoryをrenameする。

- `cs-analysis-group-profile` → `cs-analysis-cluster-profile`
- `cs-analysis-group-enrichment` → `cs-analysis-cluster-enrichment`
- `cs-analysis-group-overlap` → `cs-analysis-cluster-overlap`
- `cs-analysis-group-structural-diversity` → `cs-analysis-cluster-structural-diversity`

Capability IDは識別と参照にだけ使用し、科学的挙動の条件分岐へ直接使用しない。現行Runtime／templateにある`if capability_id == ...`型の分岐は、Catalog metadataの`value_semantics`、`allowed_metrics`、`input_contract`、`analysis_role`、`internal_representation`、`cluster_selection_role`へ置換する。Description artifact自身のmanifestは、実際のparameterを反映した`value_semantics`と`natural_metric`を必須出力する。例えばraw binaryとSVD座標を切り替えられる場合、下流はCapability IDではなくartifact manifestの実値を使う。これにより今回の再附番による誤接続を防ぎ、将来のCapability追加でもRuntime変更を最小化する。

CONDUCTORモードではmanifestのsemantics／metricをRuntimeが拘束し、下流Skillによる矛盾した上書きを拒否する。一般利用でmanifestのない任意vector CSVを入力する場合、完全な0/1 matrix等の曖昧でない場合だけ自動判定し、それ以外は`--value-semantics`または適切な`--metric`の明示を要求する。由来不明vectorへEuclidean等を黙って既定適用しない。

Node IDはRuntimeがState lock内の計画時に発行し、worker SkillはNodeを作成しない。Clustering workerが生成するcluster labelはNode-local IDとし、成功eventのcommit時にRuntimeがState lock内でRun-global `CL######`を割り当て、registryとmembership matrixへ反映する。並列workerへGlobal Cluster ID範囲を予約させない。

### 4.2 Version

- package version、Catalogの`conductor_version`、Runtime定数、Skill capability versionを`0.1.0`へ更新する。
- schema versionはデータ契約のVersionとしてpackage versionから独立させ、互換性が壊れるschemaだけmajorを更新する。
- 正本文書のファイル名から`v4`を除き、将来のVersion更新でrenameが連鎖しない名前へ整理する。
- `CONDUCTOR_modules/VERSION`を単一のVersion正本とし、Catalog／schema copy／文書のVersion整合を検証する。

0.1.0で互換性が切れる主要schemaは次のVersionへ固定する。

| Contract | schema version |
|---|---|
| State／execution event | `2.0.0` |
| Catalog／analysis profile | `2.0.0` |
| Description／Clustering manifest | `2.0.0` |
| Operator summary | `1.0.0` |
| Interpretation／Insight／Next Action | `2.0.0` |
| State summary／Orchestrator brief | `2.0.0` |

Runtimeはpackage versionだけでなく各artifactのschema majorを検証し、未知または不一致のmajorを黙って読み替えない。

### 4.3 Cluster最小サイズ

- CONDUCTORモード、一般利用とも`min_cluster_size=5`をhard floorとし、4化合物以下の集合へCluster IDを発行しない。CLIで5未満が指定された場合も明示的に拒否する。
- 5以上は「登録可能」の条件であり、Local統計や予測modelへ利用可能であることを意味しない。Operatorごとに別の適用条件を持つ。
- threshold未満の化合物は削除せず、未割当としてmembership／summaryへ記録する。

### 4.4 新規Analysis Capability

#### A003: `cs-analysis-projection-pca`

- 一つのDescription artifactを入力し、PCA座標、explained variance、loadings、endpoint着色scatter、HTML reportを生成する。
- Local表示でもGlobal fitした座標を使用し、対象Clusterを強調する。Global／Local比較の途中でPCAを再fitしない。
- PCA座標はAnalysis artifactであり、標準DAGではClusteringやSALIの入力へ接続しない。
- 前処理はDescription metadataに従い、continuousはmedian補完・標準化、countは`log1p`・標準化、binaryは低分散列除外後に中心化する。endpointをfitへ使用せず、可視化対象のGlobal datasetへ一度だけfitする。補完値、除外列、seedをmanifestへ記録する。

#### A004: `cs-analysis-projection-umap`

- 一つのDescription artifactを入力し、UMAP座標、endpoint着色scatter、trustworthiness、seed安定性、HTML reportを生成する。
- Description semanticsに応じてmetricを固定する。binary fingerprintはTanimotoと同値のJaccard、count／embeddingはcosine、USR／USRCATはManhattan、その他のdense continuousはEuclideanとする。
- UMAP座標は可視化・探索用Analysis artifactとし、標準DAGではClusteringやSALIへ接続しない。
- seedを固定し、複数seedでの近傍保持の安定性をreportする。Local表示はGlobal座標上の強調だけとし、Clusterごとの再fitはしない。

A003／A004は初期探索のDescription master panelへ適用する。master panelは主要な表現原理を一つ以上含む`D001, D002, D004, D011, D013, D016, D019, D020`とし、人間がCatalog profileを編集して入替可能とする。これは全Description計算を行う基本計算とは別の、初期Operator解析対象の設定である。

DAG上では、Descriptionから座標を作る`projection_fit` Nodeと、成功済projection＋Clusteringから既存座標へClusterを重ねる`cluster_overlay` Nodeを同じCapability内のroleとして区別する。overlayは座標を再計算せず、一つのClustering Nodeに対する対象Clusterをbatch表示する。Analysis→Analysisのedgeはこの座標再利用に限って許可し、projection座標から新しいClusteringを標準計画しない。

#### A005: `cs-analysis-multidescription-feature-model`

入力Description panelを次の6種類へ固定する。

`D001, D002, D006, D013, D016, D019`

処理契約:

1. 各Descriptionを独立blockとして読み込む。
2. 欠損、定数、極端な低頻度、学習fold内の利用不能featureを除外する。binary、count、continuousごとの前処理はmetadataから決める。
3. 各outer training foldの中でDescription別の低成分PLSをfitし、VIPを求める。選択安定性はouter fold間の選択頻度で示す。
4. 各Descriptionから最大5 featureを選択する。ただし統合feature数は各outer training foldで`min(30, max(6, floor(n_train / 3)))`以下とし、signalのないblockから機械的にfeatureを補充しない。
5. Description間の完全重複・強い冗長性を整理する。
6. training mean／medianのconstant baseline、Ridge、PLS、Spline-Ridgeを同じfoldで比較する。
7. 同等性能なら単純なmodelを優先する。

RidgeとPLSを標準候補とし、Spline-Ridgeは`n_train >= 60`かつ統合featureが12以下の場合だけ比較する。適用条件を満たさないLocal Clusterで非線形modelを無理にfitしない。

全Descriptionを一つの巨大なPLSへ直接投入しない。D002やD016のような`p >> n` blockは、各outer training fold内で分散／prevalence filterと単変量screeningにより候補を最大`min(256, 5 * n_train)`へ絞った後にPLS-VIPを求める。補完、scaling、screening、VIP選択、冗長性除去、hyperparameter選択はすべてtraining fold内で完結させ、test foldから情報を漏らさない。固定するのはpanel、前処理、選択上限、評価方法であり、実際に選ばれるfeature名はGlobal／Clusterごとに変化し得る。

GlobalとCluster-localの双方を扱う。Local model surveyでは、30化合物以上かつendpoint変動を持つClusterを同じpanel・設定で網羅評価し、同じtarget test foldに対するGlobal-context modelとLocal modelを比較する。Cluster membershipが同一の対象はhashで重複排除し、重複・包含Clusterの非独立性をprovenanceへ記録する。

Global A005 Nodeはdeterministic outer-fold assignmentと全compoundのOOF予測を保存する。Local survey NodeはGlobal A005 Node、固定6 Description、対象Clusteringへ依存し、各Cluster内で同じfold labelを使用する。各test foldについてGlobal側も当該foldを除外して学習済みのOOF予測だけを使い、Local側も同じcompoundをtestにする。有効test compoundを持つfoldが3未満なら、そのClusterはmodel比較不能としてskipし、別の分割で都合よく再試行しない。

A005は初期探索へ含める。基本計算完了後、初期探索内の専用model survey waveとしてGlobal modelと全適格ClusterのLocal modelを実行する。Globalは一つのNode、Local surveyは一つのClustering Nodeにつき一つのA005 Nodeとしてbatch化し、Node内部で30化合物以上のClusterを個別に評価する。Cluster単位のcheckpoint、失敗分離、結果status、artifact subdirectoryを持たせ、一つのCluster失敗でsurvey全体を失敗させない。特定Clusterの再評価や人間指定deep diveだけを独立A005 Nodeにする。これにより、全適格Clusterを扱いながらDAG Node数とOrchestrator入力を抑える。

標準A005では6種類すべてのDescription blockを必須とする。Description Node全体の失敗、列不足、結合coverage不足がある場合はblockを黙って除外せず、A005を`not_applicable`または`unavailable`として理由を短く記録する。行単位欠損はtraining fold内補完で扱う。比較可能性を壊すため、CONDUCTORモードに「利用可能blockだけで実行する」fallbackは設けない。

30化合物はLocal surveyへ登録する最小条件であり、modelの妥当性を保証しない。全結果を探索的と明記し、baselineとの差、outer-fold予測値、fold間変動、選択安定性をreportする。改善が小さい、不安定、またはnull dataと区別できない場合もnegative resultとして保存し、予測modelとしての採用を勧めない。

RuntimeはA005 Nodeへ複数Description Node／artifactを順序付きで束縛できるよう拡張する。

### 4.5 D019 GFN2-xTB quantum descriptors

現行出力は6列である。

- total energy: Hartree／eVの2列
- atomic partial charge: min／max／mean／standard deviationの4列

energy 2列は単位変換だけの同一情報であり、mean chargeも分子のtotal chargeに拘束されるため、独立した有用情報は6種類より少ない。0.1.0では一回のparent-state GFN2-xTB single-pointから取得できる回転不変のscalarを中心に、約20 featureへ拡充する。parent-stateのchargeは入力分子のformal chargeを既定とし、明示指定時を含めcharge、UHF、電子数をmanifestへ記録する。

core feature:

- total energy、energy per atom
- HOMO energy、LUMO energy、HOMO-LUMO gap
- molecular dipole magnitude
- molecular quadrupole invariant
- Mulliken chargeのmin、max、standard deviation、mean absolute、max absolute
- atom-partitioned energyのmin、max、mean、standard deviation
- Mayer-Wiberg bond orderのmax、mean、standard deviation、sum

重複unit列や回転に依存するdipole／quadrupole raw componentsはmodel featureへ入れない。gradient RMS／maxは入力conformerとxTB面の不整合を示すQC値としてmanifestへ記録し、標準featureから除外する。

実装時の曖昧さを避けるため、dipole magnitudeは3-vectorのEuclidean norm、quadrupole invariantはtraceless quadrupole tensorのFrobenius normとする。bond-order統計は対角を除く上三角だけを一度数え、`1e-3`超を有効pairとしてmean／standard deviationを求め、sumは上三角全体について求める。閾値と定義をmanifestへ固定記録する。

HOMO／LUMOはorbital energiesとoccupationsからclosed-shell／open-shellを区別して求め、定義とspin channelをmanifestへ記録する。取得不能量は行全体を捨てず個別欠損とwarningにする。

parent-stateから±1荷電状態の追加single-pointを必要とするvertical IP、EA、Fukui indexは、計算量と収束失敗が増えるためD019の標準coreへ入れない。将来必要なら予約済みD018等の独立reactivity Descriptionとして追加する。

tbliteの`xtbml` atomistic propertiesはさらに多くのgeometry、density、energy、orbital featureを提供するが、raw値は原子数・原子順序に依存する。0.1.0 coreへ無制限に追加せず、permutation-invariant aggregationと重複評価を行った後の拡張候補とする。

### 4.6 D020 ChemBERTa embedding

現行のpretrained embedding `D019`をChemBERTaへ固定し、`D020`へ移す。

- Skillを`cs-compute-description-chemberta-embedding`へrenameする。
- 対象modelをChemBERTa-100M-MLMへ固定し、汎用adapter機能を除く。
- external modelを自動downloadせず、`local_files_only`とoffline設定を強制する。
- model path解決順を`--model-dir`、環境変数、Skill-local設定fileとする。
- Windowsの既知pathを設定例として扱い、Linuxでは同じ設定fileまたは環境変数だけを差し替えられるようにする。
- CPU推論へ固定し、CUDA／GPU依存を環境から除く。
- pooling、token上限、truncation、CPU thread数、batch size、model/config hash、embedding次元をmanifestへ記録する。
- poolingは最終hidden stateの非special token mean poolingへ固定する。

既知のWindows model path:

`C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\embed_model\ChemBERTa-100M-MLM`

### 4.7 標準analysis profile

人間が編集できる一つの`analysis_profile.json`を初手のCustomization正本とし、SkillやAgent文書へ初期組合せを重複記載しない。標準profileは次の契約とする。

- 基本計算: 全Description、構造Clustering `C001`～`C004`、Description master panelに対するVector Clustering `C005`～`C010`、適用可能な`C011`～`C012`。
- Description master panel: `D001, D002, D004, D011, D013, D016, D019, D020`。主要な2D continuous、binary、count、pharmacophore、3D shape、high-dimensional 3D、quantum、embeddingを含む。
- 初期Global探索: `A001`～`A013`のうちGlobal scopeと入力契約が適用可能なものをすべて実行する。Cluster専用Operatorへ偽のGlobal実行を作らない。
- 初期Local探索: 各Clusteringから選んだ代表Clusterへ、Local scopeが適用可能なOperatorを特定のDescriptionと恣意的に固定せず実行する。代表選択は5化合物以上を前提に、全体の30%以下を優先、30～50%を補完候補、50%超をglobal-likeとして明示する。小さくてもMCS等で構造凝集性が高いClusterは候補に残す。A005だけは30化合物以上の全適格ClusterをClustering単位surveyで扱う。
- 追加探索: 未実施signatureからDescription family、Clustering family、Operator、scopeの偏りを抑えたseed付き非復元抽出を行う。
- 深掘り解析: Runtimeが依存と実施可否を検証した候補から、Orchestratorまたは人間が比較、反証、別表現、sibling Clusterを選ぶ。

profile変更時は内容hashをStateへ記録し、変更後に新規Node候補だけを再計算する。既存Nodeは入力、parameter、profile依存部分のsignatureが同じ限り再実行しない。profileのsyntaxとCapability参照はRuntimeが実行前に検証する。

## 5. 確定設計

### 5.1 Orchestrator

Agentや制御Skillを増やさず、現行の一つのOrchestrator Agent、Runtime Skill、Audit Skillを維持する。科学的統合を担当するInterpreter Agentも維持するが、controllerにはしない。

#### 維持するもの

- 一つのactive Roundと一つのlogical Writer
- lease、heartbeat、takeover後のFull Audit
- workerはStateを直接変更せず、attempt固有artifactとexecution eventだけを返し、Runtimeだけが成功結果をStateへcommitする境界
- DAG、Node retry、signatureによる重複実行防止
- 基本計算、初期探索、追加探索、深掘り解析の四phase
- 基本計算で全Descriptionとprofile指定Clusteringを揃え、`D016, D019, D020`は一回の高コストbundle承認にまとめる契約。MCSは基本計算の必須項目で、個別の事前承認を要求しない
- `orchestrator_brief.json`を最初に読み、必要な対象だけqueryする手順
- terminal Interpretation、Full Audit、Round closeの順序
- Orchestratorが科学的な優先順位と深掘り方向を判断する役割
- 人間指定による部分的なDescription／Clustering／Operator／Interpretationを、同じRuntime経由でNode登録・状態更新する契約
- `cs-conductor-state-report`と`cs-conductor-result-concierge`を人間明示起動専用のread-only補助機能とし、通常Orchestrationから呼ばない境界

#### 変更・強化するもの

1. briefを固定schemaへ縮小し、`control_status`、実行すべき一つの`required_control_action`、必要な場合だけ`scientific_decision`、残予算、直近Insight、open Next Actionを返す。配列で複数の制御指示を同時提示しない。
2. RuntimeがVersion、Node ID、依存関係、Cluster適用条件、実行済みsignatureを検証し、実行可能候補だけを最大20件のbounded listとして返す。
3. A003／A004の候補、A005の固定Description panel、複数Description依存、30以上のLocal survey候補をRuntimeが機械的に組み立てる。
4. Orchestratorは候補を一から発明せず、妥当な候補集合からscientific contextに基づいて採択、順序、深掘りfocusを決める。
5. Operator Node summary、Insight、Next ActionをNode IDでqueryし、長い全State／全reportを読まない。
6. 最終Operator後のInterpretation、固定report quality gate、Full Auditを通過しなければRound closeを拒否する。

`required_control_action`の優先順位をRuntime内で固定する。概念上の順序は、package／lease異常、running Node回復、Round開始、基本計画、高コストbundle承認、実行可能な必須Node、初期Global計画、初期Local／model survey計画、時間reserveによる科学探索停止、科学的候補選択、Interpretation完了、Full Audit、Round closeである。時間reserveへ入った場合は追加探索／深掘りの未開始Nodeを`deferred`として次Round候補へ残し、Interpretation時間を保護する。`deferred`は未実行かつ非runnableで、元の`requested_round_id`を保持する。後続RoundでRuntimeが選択した場合だけ`execution_round_id`を付けて再活性化し、同一signatureの代替Nodeを作らない。必須計算の未完了はgapとして明示し、黙って完了扱いにしない。

`scientific_decision`は、必須の制御Actionがなく科学的選択だけが残った場合に限って提示する。各candidate cardはNode／Capability／Cluster ID、未充足coverage、短い選択理由、概算costだけを持ち、自由記述の長い候補説明を生成しない。`orchestrator_brief.json`は50 KiB以下を受入条件とし、Node総数が増えても大きくならないことを試験する。

Wall Timeは「必ず使い切る時間」ではなく上限である。必須phaseが完了し、候補poolまたは追加Node予算を使い切った場合は、Wall Time前でもInterpretationへ進める。逆に、単なるOrchestrator判断による早期終了ではterminal gateを迂回できない。

#### 実行attemptと異常終了

一つのDAG Nodeはretryしても同じNode IDを保持し、各実行だけに単調増加する`attempt_id`を付ける。workerはNode directory内のattempt固有staging directoryへ出力し、execution eventにNode ID、attempt ID、入力／設定hash、workerまたはscheduler job識別情報を記録する。Runtimeがcurrent attemptとhashを検証してから正式artifact pointerを切り替える。

Orchestrator leaseが失効しても、worker結果を即座に失敗扱いまたは再実行しない。takeover後のFull Auditは、event、artifact、process／scheduler情報、attempt heartbeatを照合する。currentでない旧attemptが後から終了してもStateへcommitせず、監査可能なorphan attemptとして保持する。これにより、同じNodeの二重計算が遅れてStateや成果物を上書きすることを防ぐ。

#### 決定論と推論の境界

決定論的Runtimeが担当するのは、実行可能性、ID、依存、重複、hard floor、予算、固定panel、artifact検証である。Orchestratorが担当するのは、どの候補が科学的に注目に値するか、矛盾をどう追うか、どのCluster／Description／Operatorを比較するかである。

相関値や固定thresholdだけでRuntimeが深掘り先まで決める設計は採用しない。そのようにすると、低順位だが異原理Description間で一致するsignal、矛盾、例外、反証候補を探索対象から機械的に落とす危険がある。Runtimeは候補を安全に列挙し、科学的rankingはOrchestratorへ残す。

Execution DAGのedgeはartifactまたは実行順序上の依存だけを表す。前RoundのInsight、Next Action、人間commentを根拠に新Nodeを選んでも、Interpretation→Operatorのexecution edgeは作らず、Nodeの`selection_basis`へ参照を記録する。これによりInterpretation Nodeを終端のread-only成果物として保ち、Roundをまたぐ動機づけと計算依存を混同しない。

#### 状態ファイルの階層

Orchestratorが通常読む正規入口は`run_root/summaries/orchestrator_brief.json`の一つだけとする。役割は次のように分離する。

| Path | 役割 | Orchestratorの通常読取 |
|---|---|---|
| `state.json` | DAG、counter、lease、Round、artifact pointerの制御上の正本 | 読まない |
| `summaries/state_summary.json` | Stateから再生成できる事実summary | briefで不足する場合だけ |
| `summaries/orchestrator_brief.json` | 次の一手だけを示す固定長control view | 最初に読む |
| `indices/coverage_index.json` | 実施済／未実施cellの再構築可能index | Runtime query経由 |
| `indices/operator_summary_index.jsonl` | Operator result summaryの再構築可能index | Runtime query経由 |
| `indices/insight_index.jsonl` | Interpretation artifactから再構築するInsight index | Runtime query経由 |
| `indices/next_action_index.jsonl` | Interpretation artifactとState registryから再構築するNext Action index | Runtime query経由 |
| `clusters/cluster_registry.csv` | Cluster由来、件数、status、source Node | 必要時だけ |
| `clusters/compound_cluster_matrix_CL*.csv` | compound×Cluster membership | 必要時だけ |
| `rounds/RND####/` | request、round summary、次Round用historical brief、manifest | 通常は最新summaryだけ |
| `audit/<timestamp>/` | Quick／Full Audit結果 | 異常時・close前だけ |

各index自体は解析数とともに増えるが、一行のschemaと長さを制限し、LLMへ全件を渡さない。Runtime queryがscope、Capability、Cluster、Round、statusで絞り、最大件数を強制する。すべてのsummary／indexは削除してもStateと成功済Node artifactから再生成できる。

StateはINS／ACT counterと、各IDの最新revision、status／attention、source NI artifact pointerだけを軽量registryとして保持する。各revisionの科学的内容の正本は成功済NIのimmutable `interpretation.json`であり、indexはそこから再構築する。これによりStateと独立ledgerを二重に正本化しない。

#### Interpreterとの関係

Orchestratorは対象Operator Nodeとfocusを決め、Runtimeが一つのNI Nodeと出力先を登録する。Interpreterは選択されたsummaryと必要な原artifactを読み、NI directory内のdraft JSONだけを作る。State、DAG、INS／ACT counter、Next Action statusは変更しない。固定rendererとRuntime commitがschema検証、ID付与、Markdown／HTML生成、State event登録を行う。

NIごとにlauncherが排他的なwork lockを持ち、同じNIを複数Interpreterが同時編集できないようにする。中断時は同じNI内の新attemptとして再開し、別NIを作らない。成功済Interpretationが後続Operatorによりstaleになった場合も、同じNIの新attemptで新revisionを作り、旧attemptのJSON／Markdown／HTMLを保持する。Interpreter processを利用できない環境では、Orchestrator session内で同じInterpretation SkillとPolicyを適用してよいが、役割、出力契約、Runtime commit手順は変えない。

Runtime commitはNI attempt directory内の`commit_manifest.json`を使う回復可能な二段階処理とする。State lock内でID割当と期待State revisionを`prepared`として記録し、artifactをatomicに確定してからStateのNode status／counter／entity registry／current Interpretation pointerを更新し、最後に`committed`へ移す。bootstrap／Full Auditは未完了の`prepared` commitを最優先で完了または安全にrollbackし、それ以前に新しいIDを発行しない。

### 5.2 Interpretation

独立したEvidenceエンティティとEvidence IDは廃止する。Operator Nodeが計算結果とprovenanceの正本であり、別IDを付ける必要はない。

各Operator Nodeは、数値CSVとHTMLに加えて短い`operator_summary.json`を生成する。これは別の管理対象ではなく、Node IDで参照する再構築可能な派生artifactである。必須fieldはNode／Capability／Round ID、`scope_context`、sample数、endpoint、metric、主要数値、短いpositive／negative observation、warnings、artifact link、hashとする。`scope_context`はscope modeと、Description／Clustering Node ID、Cluster IDをそれぞれ配列で持つ。Globalや入力非依存Operatorでは空配列を許し、RuntimeがOperatorの入力契約との整合を検証する。文章fieldとtop item数に上限を設ける。

Operator summaryはnavigationと候補抽出のための情報であり、科学的正本ではない。InterpreterがInsightとして採用する場合は、必ずlink先の数値artifactまたは詳細HTMLを確認し、summaryだけから retained claimを作らない。

通常のOperator結果は`NA######@ATT####`を`result_ref`とする。A005 Local surveyのように一Nodeが複数Cluster結果を持つ場合は、集約summaryとは別にClusterごとの短いsummaryを作り、`NA######@ATT####/CL######`形式のcomposite `result_ref`を付ける。これは新しいNode IDではなく、特定の成功attemptに固定されたartifact参照である。`operator_results.jsonl`は`result_ref`を一意key、`node_id`と`attempt_id`をDAG参照として複数行を登録し、Node数を増やさず個別Cluster結果をquery可能にする。stale後に同じNodeを再計算しても、過去Interpretationが参照した旧resultのhashとpathを保持する。

Interpretation内部と人間向け概念を次の2種類へ簡素化する。

1. **Insight (`INS####`)**: 現行FindingとHypothesisを統合する。観察、解釈、任意の説明仮説、支持Operator Node、反証Operator Node、scope、限界を一recordに持つ。`attention`は`priority`／`watch`／`background`の三値とし、revisionまたは人間指定でいつでも変更できる。
2. **Next Action (`ACT####`)**: 現行QuestionとAnalysis Requestを統合する。状態は`open`／`closed`だけとする。人間はいつでもcloseでき、実行完了時はRuntimeが対応Nodeを記録してcloseする。

INS／ACT番号はRun全体でRoundをまたいで単調増加させる。Interpreterへ番号範囲を事前予約せず、Interpreterは既存IDまたは一時keyを返し、RuntimeがState lock内のcommit時に新規IDを一件ずつ付与する。既存概念の更新は同じIDにrevisionを追加する。これにより、Agent中断や再起動による大きな欠番・衝突を防ぐ。

`background`は削除や永久除外を意味しない。別の深掘り結果から関連が生じた場合、Runtime queryで元Operator Nodeを再取得し、同じInsightを新revisionで`watch`または`priority`へ戻せる。Orchestrator briefはhuman-pinned、priority、直近更新を優先してbounded表示する。

Next Actionの`open`は「検討余地がある」ことだけを表し、次Roundでの実行義務を意味しない。人間またはRuntimeが`closed`へ変更できる。`closed`から`open`への再開は明示的な人間指示だけを許し、完了Node IDまたは人間判断理由をrevisionへ記録する。

独立したRelation IDは廃止し、支持、反証、関連Insight／ClusterはInsightまたはNext Action内のNode／entity参照として保持する。

旧Skill名`cs-analysis-interpret-evidence`は`cs-analysis-interpret-results`へrenameし、Operator Node summaryからInsight／Next Actionを生成する役割を明示する。

Interpretation Policyは、少なくともGlobal対Local、sibling Cluster間、Clusteringに使ったDescription対別Description、同一scopeの異Operator、異原理Description間の一致、矛盾、Cliff、例外、negative result、反証候補を比較観点として保持する。Runtime／Interpretation Skillは既存resultから比較可能な組合せをboundedなcandidate queueとして作り、Interpreterが科学的な注目度を判断する。Orchestratorがfocusを指定した場合は候補範囲だけを狭め、結論を事前指定しない。

各Interpretation attemptは、確認した`result_ref`集合とcomparison signatureを記録する。後続Roundでは未確認組合せを優先し、同一比較を理由なく繰り返さない。一方、関連する新resultが追加された場合は新しいsignatureとして再比較できる。注目Insightを作る際は、支持だけでなく利用可能な反証、境界例、代替説明を必ず探索し、見つからない場合も探索範囲を記載する。

InterpreterはHTMLやMarkdownの構成を自由記述せず、schema検証済みJSONだけを完成させる。固定rendererが次の順で毎回生成する。

1. エグゼクティブサマリー
2. 主要Insight
3. 矛盾と限界
4. Cluster別Insight
5. Next Action
6. Operator結果／Methods appendix

人間向けMarkdown／HTMLの`report_language`は`ja`へ固定し、見出し、説明文、Insight、Next Action、警告を日本語で生成する。Capability名、ID、metric、file名等の技術識別子は英語のままでよい。Renderer内の固定文言も日本語を正本とし、Agentの自由な言語選択へ委ねない。

Round終端gateは、各Insightに具体的な解析context、Operator、sample数、数値観察、意味、限界、source `result_ref`があることを検証する。Description、Clustering、Clusterはsource Operatorの入力契約とscopeで該当する場合だけ必須とし、Global解析や入力非依存Operatorへ架空のIDを要求しない。存在しないNode／Cluster／result参照、空の数値観察、source link欠落、固定section欠落をhard errorとする。固定された低彩度palette、見出し、card、table、並び順をrendererが所有する。

注目に値する結果がないRoundではInsight 0件を許す。件数を満たすための仮説生成を要求せず、代わりに「保持したInsightなし」、確認したcoverage、主要なnegative result、限界、未実施領域を明示する。Next Actionも0件を許容する。

Interpretation Nodeは、そのRoundで最後に成功したOperator Nodeより新しいcurrent artifactでなければならない。生成途中で失敗した場合は新しいNIを追加せず、同じNIをretryする。schema JSON、Markdown、HTML、report quality manifestのすべてが成功し、Full Auditがそのhashを確認するまでRoundを閉じない。

### 5.3 旧alpha Run

用語、Node prefix、runtime Cluster ID、Capability ID、Interpretation schemaが変わるため、0.1.0 Runtimeによる旧Stateの再開・migrationはサポートしない。旧run rootはread-only参照とし、新規beta Runを開始する。bootstrap時に旧schema／package versionを検出した場合は明瞭なerrorを返し、暗黙変換しない。旧migration Agent／Skill／promptは通常packageから除去する。

## 6. 文書・説明資料の整理方針

### 維持・更新する正本文書

- design specification
- orchestration policy
- interpretation policy
- output contract
- identifier reference
- user guide
- skill catalog
- verification record
- 本リファクタリング計画

ファイル名はVersion非依存へ統一する。

### 統合・削除するもの

- `CONDUCTOR_refactoring_plan.md`と`CONDUCTOR_v4.3.1_refactoring_plan.md`は旧完了記録としてGit履歴へ委ね、working treeから除去する。
- v4.3.0→v4.3.1 migration prompt、migration Agent／Skill説明を除去する。
- Description関係性資料のroot側と`CONDUCTOR_explanation/`側の重複を一つへ統合する。
- `CONDUCTOR_explanation/`の説明用HTML、PNG、CSSは削除する。必要な概念説明だけを簡潔なMarkdown overviewへ統合する。
- `CONDUCTOR_internal_overview.pptx`を削除する。将来必要になった時点で正本文書から改めて作成する。
- base64画像を含む大容量HTML snapshotをpackageへ残さない。

## 7. 実装工程

### Phase 0: baselineとrename map固定

- clean worktree、branch、現行test、主要artifactを確認する。
- 旧語→新語の機械的rename表と、意味変更が必要な箇所を分離する。
- 科学kernel保護範囲を記録する。
- 現行の代表入力に対するDescription／Clustering／Operator数値出力をgolden fixture化し、adapter変更で科学kernelが変わっていないことを確認できるようにする。
- 現行code内のCapability ID直接分岐を全数inventoryし、metadata化対象を固定する。

### Phase 1: VersionとClustering schema

- package Version正本を導入する。
- schema、State、ID counter、path、artifact typeをClustering／Clusterへ変更する。
- Node `NC`、commit時Cluster `CL`附番、DAG、retry、stale伝播を試験する。
- 新State、Operator summary、Insight、Next Actionのschemaを先に確定し、Evidence等の旧schemaとの混在を許さない。

### Phase 2: Clustering／既存Operator Skill移行

- 全Clustering Skillのdefault／CONDUCTOR floorを5へ更新する。
- 旧`group-*` Operator Skillを`cluster-*`へrenameする。
- scientific kernelを維持し、adapter、manifest、report、CLIだけを新契約へ変更する。
- Description semantics、metric、Operator applicability、内部表現、Cluster選択roleをCatalog metadataへ移し、IDによる挙動分岐を除去する。

### Phase 3: D019 xTB／D020 ChemBERTa

- xTBのparent-state single-point core feature、orbital境界判定、回転不変summary、QCを実装する。
- ChemBERTa Skill rename、path設定、offline loader、CPU固定、固定pooling、manifestを実装する。
- tblite、transformers、PyTorchの解決VersionをPixi lockへ固定し、実際に使用したpackage／model hashをmanifestへ記録する。
- Windowsローカルweightでdimension、再現性、batch一致をsmoke testする。
- Linux path差替えとCPU-only Pixi解決を静的検証する。

### Phase 4: A003／A004

- PCA／UMAP Skillを自己完結directoryとして作る。
- projection fit／Cluster overlay role、analysis-to-analysis依存、metric dispatch、座標CSV、SVG、HTML、Operator summaryを実装する。
- reproducibility、seed安定性、missing value、small-N、invalid input、binary metric mappingを試験する。

### Phase 5: A005

- 複数Description入力契約とfixed panel validatorを実装する。
- fold内前処理、training-only候補screening、block別PLS-VIP、adaptive feature上限、outer-fold OOF評価を実装する。
- Global OOF／fold manifest、Clustering単位Local survey、同一test fold比較、Cluster別checkpoint／失敗分離、重複Cluster除外、negative result summary、HTMLを実装する。
- leakage、null endpoint、p≫n、constant endpoint、small Cluster、block欠落、部分欠損を試験する。

### Phase 6: Orchestrator／Runtime

- brief、planner、signature、multi-input Node、Local surveyを追加する。
- 単一`required_control_action`と優先順位、metadata-driven candidate planner、bounded queryを実装する。
- 単一Writer、lease、attempt staging／promotion、Interpretation reserve、terminal gate、deferred Nodeを回帰試験する。
- Audit SkillをState 2.0.0、prepared commit、attempt、再構築可能index、terminal Interpretation gateへ対応させる。
- Local LLMが長いMarkdownを読まずにRoundを進められるfixtureで検証する。

### Phase 7: Interpretation

- 独立Evidence IDを廃止し、Operator Node summary→Insight→Next Actionへ整理する。
- Finding、Hypothesis、Question、Relation、Analysis Requestの独立ledger／counterを廃止する。
- Runtime commit時のINS／ACT逐次附番とrevision、Next Actionの`open`／`closed`、人間closeと実行完了closeを実装する。
- NI commit manifest、prepared transaction回復、composite Operator `result_ref`を実装する。
- bounded comparison queue、comparison signature記録、未確認組合せ優先、反証探索contextを実装する。
- 固定rendererと日本語HTML themeを実装する。
- report language、Insight 0件、report quality gate、run-global ID継続、revision、human decisionを試験する。
- Orchestrator／Interpreter Agent文書からEvidence、Finding、Hypothesis、Question、Groupの旧契約を除き、新Skill名、summary navigation、原artifact確認、Runtime commitへ揃える。

### Phase 8: docsとpackage cleanup

- 正本文書と説明資料を0.1.0仕様へ更新する。
- 重複文書、説明用HTML／PNG／PPTX、旧migration資料を削除する。
- installer、catalog generator、package verifierを更新する。
- State ReportをClustering、deferred／attempt status、State 2.0.0へ対応させる。Result ConciergeはINS／ACT／Operator `result_ref`を対象に更新し、read-only境界と専用出力先は維持する。
- 初回Run、Round継続、人間feedback、部分解析、Concierge用promptを新ID／新State契約へ更新し、migration専用promptだけを除去する。
- user requirementに従い、全Skillの`SKILL.md`と同階層に簡潔な`README.md`を維持し、新規／rename Skillにも作成する。
- 全SkillのPixi lockをLinux／Windows対象で生成し、launcherは共有Pixi binaryを優先してlocked installを行う。環境構築の同時実行をSkill-local lockで直列化する。packageへ含めるのは`pixi.toml`／`pixi.lock`であり、`env/cache/`、`.pixi/`、一時fileは含めない。lock生成とLinux実行確認は指定の共有Linux Pixi binaryで行い、PixiのないWindows環境でlockを手書きしない。

Skill単独コピー可能性を守る一方、同じruntime／schemaを手作業で複数箇所へ編集しない。`CONDUCTOR_modules/tools/templates/`とgeneratorを編集元とし、各Skill directoryへ再生成する。package verifierは、生成対象fileのhash／内容同期、必須README、Pixi cache設定、旧Skill名残存を検査する。State／Interpretationの切替は旧Evidence schemaとの混在期間を作らず、一つのschema cutoverとして行う。

Phase番号は作業順を示すが、Phase 1の新schemaを現行Runtimeだけへ先行適用しない。新Operator summary、Runtime、Interpreter、renderer、Auditが揃った時点でgeneratorから全Skill copyを再生成し、0.1.0 contractへ一括切替する。切替直後にpackage verificationとend-to-end smokeを行い、不完全な旧新混在状態を成果物にしない。

### Phase 9: 総合受入試験

- 新規Runをbootstrapし、Description→Clustering→Operator→Interpretation→Audit→Round closeを完走する。
- A003／A004のGlobal／Cluster reportを確認する。
- A005のGlobal／Local surveyとouter-fold leakage testを確認する。
- 一般利用で`--conductor`が暗黙付与されないことを確認する。
- manifestなし一般vector入力で、binary自動判定、semantics明示、曖昧入力の拒否、矛盾metricの拒否を確認する。
- Linux／Windows path、共有Pixi、Skill-local cacheを確認する。
- `Grouping`／`Group`と旧Version文字列の残存をallowlist付きでゼロ検証する。
- package gate、同時Orchestrator起動、lease期限切れ、実行途中のOperator停止、Interpretation途中停止、同一NI retry、stale伝播、壊れたartifact hashをfault-injectionで試験する。
- 同一Nodeの旧attemptとretry attemptを意図的に前後して完了させ、current attempt以外がStateと正式artifactを上書きできないことを確認する。
- 成功済Operatorをstale化して再実行し、旧`result_ref`を使う過去Interpretationと新`result_ref`の双方が正しいattempt artifactへ到達することを確認する。
- 並列Clustering完了順を入れ替え、CL番号、registry、membership matrixに重複や部分更新が起きないことを確認する。
- `state_summary.json`／再構築可能indexを削除して再生成し、StateとNode artifactから同一内容へ戻ることを確認する。
- 1,000 Node以上のsynthetic multi-Round Stateでもbriefが50 KiB以下、候補20件以下で、Agentが`state.json`や全Markdownを読まずに次Actionを選べることを確認する。
- 最終Operator後にInterpretationが古い、HTMLまたはquality manifestが欠落、Full Audit未実施の各ケースでRound closeが拒否されることを確認する。
- INS／ACTの同時commit、Agent停止後retry、Round継続で番号衝突・飛躍的予約欠番が起きないことを確認する。
- NI commitの各段階で強制停止し、bootstrap／Full Auditがprepared transactionを重複IDなしで回復することを確認する。
- 成功済NIを後続Operatorでstale化し、同じNIの新attemptがcurrentになり、旧Interpretation reportと旧Insight revisionが保持されることを確認する。
- Global、単一Cluster、A005 multi-Cluster surveyの各`scope_context`と`result_ref`が、index再構築後も一意にqueryできることを確認する。

## 8. 実装前レビュー結論

実装前baselineとして、repository内`.venv`を用いて現行alpha testをmodule別に実行し、State Manager 14件、repository contract／runtime smoke 26件、Result Concierge 4件、旧migration 4件の計48件がすべて成功した。`verify_package_layout.py`も成功した。0.1.0実装では旧migration 4件を除去し、同等以上の新State／fault-injection testへ置き換える。

上記の設計で実装可能である。特に、次の条件を実装完了判定の必須条件とする。

1. Orchestratorの通常入力は固定長brief一つであり、State全体の読解を要求しない。
2. Runtimeは一回に一つの制御Actionだけを返し、ID／依存／metric／重複／terminal gateを決定論的に守る。
3. 科学的な着目点、比較、反証、深掘り優先順位はOrchestratorへ残し、閾値だけで自動決定しない。
4. Evidence廃止、Capability再附番、Clustering用語移行はatomicに行い、旧新schemaを混在させない。
5. 既存科学kernelはgolden testで保護し、新規A003～A005とD019／D020以外へ不要な数値変更を加えない。
6. 旧alpha Runは0.1.0で再開せず、beta Runを新規作成する。

実装上の最大リスクは、Capability ID再附番後も残るhard-coded ID分岐、Evidence廃止の部分適用、A005のfeature leakage／Node爆発、異常終了後のInterpretation未完了である。本計画はそれぞれmetadata化、atomic schema cutover、fold内処理とsurvey batch化、terminal gateとfault-injection testで抑制する。

## 9. 実装・検証結果

0.1.0へのschema cutover、Capability再附番、Clustering用語統一、新規A003～A005、D019拡充、D020 ChemBERTa固定、Runtime／Interpretation／Audit更新、文書整理、Package installer更新を実装した。Catalog allowlistは47 Capability、配布対象Skillは48件（47 allowlist対象とResult Concierge）であり、全Skillに`SKILL.md`、`README.md`、`capability.json`、launcher、`env/pixi.toml`を配置した。

Windows上のrepository検証では、Catalog生成／整合性検査、Package layout検査、全Python sourceの構文検査、独立Projectへの試験導入と導入先layout検査が成功した。自動testは17件すべて成功した。主な検証対象は次のとおりである。

- 新ID、用語、Description semanticsとmetric、MCSのseed付きrandom sampling／上限／Cluster最小数
- PCA／UMAPのAnalysis契約、Global fitを再利用するCluster overlay依存
- A005の固定6 Description、Global OOF、30化合物以上のLocal survey、composite result参照
- lease、current attemptだけのcommit、deferred Nodeの同一ID再開、同一NI retry、Interpretation終端gate
- INS／ACTのRun-global連番、固定日本語renderer、Operator reportへのdrill-down link
- Cluster registry／membership matrix、Operator result、Insight、Next Action indexの再構築
- `orchestrator_brief.json`の上限と、一度に一つだけの`required_control_action`

### Linux／HPCで完了させる受入項目

現在のWindows環境には指定共有Pixi binaryと本番Linux環境がないため、次は実環境で確認する。

- `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`による各Skillの初回lock生成と、二回目以降の`--locked`再利用
- Skill-local cache／temporary directory、共有環境の同時初期化lock、Linux pathの確認
- 実weightを用いたD020 CPU推論、実tbliteを用いたD019量子化学計算、UMAP依存解決
- 代表的な実データによるDescription→Clustering→全Operator→Interpretation→Full Audit→Round closeのHPC end-to-end実行
- 1,000 Node超の長期Runと、worker中断／lease期限切れを含む負荷・fault injection検証

これらは環境依存の受入試験であり、未検証環境を自動的に成功扱いしない。初回lock生成後は生成された`pixi.lock`を配布対象へ含めて再現性を固定する。
