# CONDUCTOR 0.1.9 仕様概要

## 1. 文書の位置づけ

本文書はCONDUCTOR 0.1.9の確定仕様を示す。0.1.9は新規Run専用であり、0.1.8以前のRun、State、Node、Artifact、Interpretationとの後方互換性を持たない。旧成果物のMigration機能も実装しない。

本文書と`CONDUCTOR_0.1.9_implementation_plan.md`を0.1.9の仕様・実装計画の正本とする。文書とコードの不一致が見つかった場合は、推測で仕様を拡張せず、確定事項へ合わせて修正する。

## 2. 目的と設計原則

0.1.9では、全Descriptionと全標準Clusteringを先に揃え、EndpointがFavorableな化合物を濃縮したClusterを決定論的に絞り込む。そのCluster群を重複関係からSeriesへ整理し、Global controlとSeriesを比較する定型解析を実行する。

主な設計原則は次のとおりである。

- 有用な解析空間をEndpoint enrichmentで早期に絞り込む。
- 基本計算と定型解析はRuntimeが決定論的に計画し、LLMへ大量の選択判断を委ねない。
- SeriesごとにNodeを増やさず、各Operatorが全Seriesを一括処理する。
- 数値の完全表はCSVへ保存し、人間向けHTMLは重要な結果へ絞る。
- Global controlなしにLocal／Series結果を単独評価しない。
- Endpoint選抜後の結果を独立検証や因果関係とは表現しない。
- 定型解析後の追加解析は、人間の依頼に基づくOn-demand解析へ移す。
- On-demandは通常RoundとDAGから分離し、既存Runを読み取り専用とする。
- 過去Version互換のための分岐やSchema受理範囲を残さない。

## 3. 正式な処理区分

### 3.1 基本計算

基本計算は次を含む。

1. Catalog収載中の全Description
2. 全直接構造Clustering
3. 全Descriptionに対する全標準Vector Clustering
4. Cluster Registryとcompound × Cluster membership正本の構築
5. 全ClusterのA001 profile survey
6. 全ClusterのA002 enrichment survey
7. Favorable Clusterの選抜
8. C012 overlap-weighted LeidenによるSeries形成
9. Series RegistryとSeries membershipの確定

### 3.2 定型解析

定型解析は、Global controlとactiveなSeries／fallback Clusterを対象とする既定Operator panel、MMP Type-I、定型レポート、簡素化したInterpretationを含む。

### 3.3 On-demand解析

On-demand解析は人間の具体的依頼に応える自由解析である。Round状態に関係なく実行でき、通常DAG、Round、State、Interpretationへ影響しない。依頼と結果はRun内へ記録するが、通常Nodeとは別の`REQ######`名前空間で管理する。

## 4. 基本計算

### 4.1 Description

Catalog収載中の全18 Descriptionを計算する。

`D001`～`D016`、`D019`、`D020`

Description Skillの科学計算kernel、一般利用CLI、`--conductor`による出力切替は、0.1.9で必要な出力契約変更を除き維持する。

### 4.2 Clustering

直接構造Clusteringは次の4手法である。

- `C001`: Murcko scaffold
- `C002`: MCS
- `C003`: BRICS fragment
- `C004`: RECAP fragment

Vector Clusteringは次の6手法を全18 Descriptionへ適用する。

- `C005`: Butina
- `C006`: Hierarchical
- `C007`: DBSCAN
- `C008`: Louvain
- `C009`: Leiden
- `C010`: Connected Components

既定の名目Node数は次のとおりである。

| 種別 | Node数 |
|---|---:|
| Description | 18 |
| 直接構造Clustering | 4 |
| Vector Clustering | 108 |
| A001／A002 batch survey | 2 |
| C012 Series形成 | 1 |
| 基本計算合計 | 133 |

Clusterとして登録する最小化合物数は`min_cluster_size=5`を維持する。

### 4.3 Cluster membership正本

各Clustering Nodeはlong形式membershipを出力し、Runtimeが成功結果をGlobal Cluster IDへ変換する。正本はcompoundを行、Global Cluster IDを列、membershipをBoolean値とするCSVである。

列数が一つのCSVとして扱いづらくなった場合は、Global Cluster ID範囲で分割する。

```text
runtime/cluster_membership/
├─ index.json
├─ Cpd_Cluster_matrix_C000001_099999.csv
└─ Cpd_Cluster_matrix_C100000_199999.csv
```

`index.json`には各shardのCluster ID範囲、列数、行数、hashを記録する。State JSONへBoolean行列を埋め込まない。

### 4.4 Favorableの共通定義

FavorableはGlobalのEndpoint有効値の良好側20%を意図する分位点で定義する。

- `higher_is_better=true`：Global 80%分位点以上
- `higher_is_better=false`：Global 20%分位点以下

境界値を含むため、同値が多い場合の実測Global Favorable Fractionは0.2を超え得る。閾値、比較演算子、理論比率、実測比率をすべて保存する。Endpoint欠損化合物は分位点計算と比率の分母から除外する。

### 4.5 新Operator ID

0.1.9では旧Operator IDに固執せず、役割順に再附番する。

| ID | 役割 | Workflow |
|---|---|---|
| `A001` | 全Cluster profile survey | 基本計算 |
| `A002` | 全Cluster enrichment survey | 基本計算 |
| `A003` | Series descriptor contrast | 定型解析 |
| `A004` | Series projection panel（PCA／UMAP） | 定型解析 |
| `A005` | Series multi-description feature model | 定型解析 |
| `A006` | Series landscape（SALI／Cliff） | 定型解析 |
| `A007` | Series structural signature | 定型解析 |
| `A008` | Matched molecular pair analysis | Type-Iは定型、Type-II／IIIはOn-demand |
| `A009` | Standard Series report | 定型解析 |

旧A007 kNN専用Skillは廃止する。必要なkNN解析はOn-demandで実施できる。旧Skillと旧IDの互換wrapperは残さない。

### 4.6 A001 Cluster profile survey

全Clusterを一つのbatch Nodeで処理し、次を完全CSVへ保存する。

- sample count
- Endpoint mean、median、standard deviation、IQR、range
- Favorable／Unfavorable countとfraction
- Global Favorable／Unfavorable閾値
- Cluster provenance

ClusterごとのNodeは作らない。

### 4.7 A002 Cluster enrichment survey

全ClusterについてCluster内とCluster外を比較し、次を保存する。

- Favorable count／fraction
- Global Favorable fraction
- Odds ratio
- Fisher exact test p-value
- Mann–Whitney U test p-value
- Cluster medianとGlobal medianの差
- Benjamini–Hochberg法によるq値

q値は人間の判断を支援する補助指標とし、自動選抜の必須条件にはしない。raw p-valueも保持する。

### 4.8 FF評価と選抜

Cluster登録下限とは別に`min_ff_evaluate`を設ける。

- 既定値：10
- 人間が明示的に変更可能
- Cluster登録可否には影響しない
- parameter、signature、manifestへ保存する
- 値を変えた再実行は別A001／A002／C012 Nodeとする

後続候補は次の両方を満たすClusterである。

1. `sample_count >= min_ff_evaluate`
2. `favorable_fraction >= 0.5`

期待する候補数は概ね50～150である。多すぎる場合は人間が`min_ff_evaluate`を上げ、新しいNodeとして再解析する。Runtimeが自動的に閾値を変更してはならない。

完全順位は`favorable_fraction`降順、`sample_count`降順、`cluster_id`昇順で決定する。非選抜Clusterも削除せず、完全表とRegistryへ残す。

## 5. C012 Cluster-of-ClustersとSeries

### 5.1 Weighted overlap graph

C012はFF選抜Clusterをvertexとするweighted graphを作る。

- 共通化合物数0：Edgeなし
- 共通化合物数1以上：Edgeあり
- Primary edge weight：Jaccard係数 `|A ∩ B| / |A ∪ B|`
- 補助値：intersection count、A側包含率、B側包含率、overlap coefficient
- community detection：weighted Leiden
- random seed：固定

Jaccardは最初から対称であり、A→BとB→Aの方向差を生じない。双方向包含率の平均は、大小差のある包含Clusterを過大評価し得るためPrimary weightには使わない。初期仕様では人為的なJaccard cutoffを設けず、弱い重複は小さいweightとして扱う。

### 5.2 Series IDと成果物

C012のcommunityをSeries候補として扱い、`S000001`形式のSeries IDを付与する。これはEndpoint濃縮Clusterの重複関係から得た解析単位であり、真正なchemical seriesであると自動断定しない。

主成果物は次である。

- source Cluster × Series対応表
- weighted edge list
- Series Registry
- compound × Series membership
- compoundごとの`support_count`と`support_fraction`
- Series品質診断

Seriesを通常のGlobal Cluster ID空間やCluster membership正本へ混入させない。

### 5.3 Series membership

Seriesの化合物集合は構成source Clusterの和集合とする。各化合物が何個のsource Clusterから支持されたかを補助情報として保持するが、membershipの除外条件には使用しない。

Series形成後にFavorable Fractionを再計算する。

- 再計算FFが0.5以上：Seriesを定型解析単位として採用
- 再計算FFが0.5未満：そのSeriesは採用せず、構成元のFF適格Clusterへ自動fallback
- Seriesが0件：FF適格Clusterを定型解析単位として使用
- FF適格Cluster自体が0件：Global controlだけで定型レポートを作り、Local候補なしと明記

有効Seriesとfallback Clusterが混在する場合、両者を`analysis_unit`として一括管理する。各単位に`scope_kind=series|cluster`を必ず付け、暗黙に混在させない。

### 5.4 analysis unit数とsoft gate

- 採用Seriesとfallback Clusterを合わせた実解析単位数が24以下：自動的に定型解析へ進む
- 実解析単位数が24超：人間の判断を待つ
- Runtimeは`leiden_resolution`や`min_ff_evaluate`を自動変更しない
- 人間がparameterを変更した場合は新revisionとして再計算する

一つのSeriesがGlobalのEndpoint有効化合物数の50%を超える場合は`global_like_series`警告を付けるが、停止条件にはしない。Series数0件でもfallback自体は作るが、その結果の実解析単位数が24を超える場合は定型解析前に人間確認を入れる。

## 6. 定型解析

### 6.1 共通契約

各Operatorは1 Series＝1 Nodeではなく、1 capability／1 parameter set＝1 batch Nodeとして全`analysis_unit`を処理する。

- Global controlを一度だけ計算し、全Local結果から参照する
- 単位ごとの成功、`not_applicable`、失敗を独立記録する
- 一単位の失敗で他の単位を失敗させない
- 結果には`analysis_unit_id`、`scope_kind`、Series revisionを付ける
- Endpoint選抜biasをすべての比較レポートへ明記する

### 6.2 A003 Series descriptor contrast

標準対象は人間が解釈しやすい`D001` RDKit 2D descriptorとする。各特徴量について次を計算する。

- Global Pearson／Spearman correlation
- Series内Pearson／Spearman correlation
- GlobalからSeriesへの絶対相関増分
- Seriesと非Seriesのmedian shift
- robust standardized difference
- sample count、欠損、定数特徴量flag、q値

相関の人間向けhitは次をすべて満たすものに限定する。

1. Series内`abs(PCC)`または`abs(Spearman) >= 0.4`
2. 対応するGlobal絶対相関から0.2以上増加
3. 補正後`q <= 0.05`

median shiftのhitは次をすべて満たすものに限定する。

1. `abs(median_series - median_nonseries) / IQR_global >= 0.75`
2. 補正後`q <= 0.05`

完全表には全特徴量を保存する。基準未達の場合は最も近い候補を一文だけ報告する。

### 6.3 A004 Series projection panel

標準Descriptionは`D002` Morgan ECFP4とする。Global全体でPCAとUMAPをそれぞれ一度だけfitし、同一座標上で対象Series／fallback Clusterを強調する。座標をSeriesごとに再fitしない。

各analysis unitについて次を生成する。

- PCA overlay PNG
- UMAP overlay PNG
- PCAとUMAPを左右に並べたcombined PNG

さらにPCAとUMAPを別々に、Series ID順の`ceil(K/4) × 4` contact sheetへまとめる。画像は詳細HTMLへbase64埋め込みする。

人間が別Descriptionを指定した場合は別Nodeとして処理し、そのDescriptionに対応するmetricと前処理を使う。次元削減座標を標準Clustering入力にはしない。

### 6.4 A005 Series multi-description feature model

- Global OOF modelを一度構築する
- 各Series内でOOF評価する
- feature selectionは各outer training fold内だけで行う
- 同じSeries化合物に対するGlobal OOF予測と比較する
- 既定の最小化合物数は30
- N不足、Endpoint variation不足は`not_applicable`

目的は予測製品や独立検証ではなく、Series内で埋没していたEndpoint勾配を説明し得る特徴量候補の探索である。

### 6.5 A006 Series landscape

標準Descriptionは`D002`、metricはTanimotoとする。Globalと各analysis unitについて、SALI、internal cliff、boundary cliffを同じbatchで計算する。kNN解析は必須機能に含めない。

注目Cliffの既定基準は次とする。

- Tanimoto `>= 0.8`
- absolute Endpoint delta `>= 1.0 × Global IQR`
- 同傾向の支持pairが3件以上
- boundary cliffではSeries側へFavorableなpair比率80%以上

基準未達のpairも完全表へ保存するが、HTMLでは「明確な反復性Cliffなし」と最大値を一文で示す。

### 6.6 A007 Series structural signature

Seriesのsource ClusterにC001～C004由来が存在する場合は、その構造定義をすべて表示する。恣意的に一つへ絞らない。

構造由来Clusterが一つもない場合だけ、Series全化合物にMurckoとMCSを実行し、両結果を表示する。複雑な追加core探索は行わない。MCS timeoutや自明なcoreも推測で補わず明記する。

### 6.7 A008 MMP Type-I

Type-Iは定型解析として各active Series／fallback Clusterで実行する。GlobalはType-Iの自動Targetに含めない。

- 各Series／fallback Cluster内Top 1を対象
- `higher_is_better`に従って順位を決める
- tieは`compound_id`昇順
- MMPが0件でも次順位を補充しない
- 一つのbatch Nodeで処理する
- 1-cutのみ
- Environment radius 0～2
- Type-III Databaseを前提とせず実行可能

全観測MMPから対象化合物へ接続するPairを漏れなく抽出するため、入力全体のfragmentationとPair抽出は行う。ただしType-I／IIでは包括的なSummary群やSQLiteを保存せず、対象接続成果物だけを永続化する。包括的Databaseを保存する役割はType-IIIに限定する。

各対象について、直接MMP pair、Exact Core、置換fragment、Endpoint差、Favorable方向差、support、反証例を保存する。Databaseと原本CSVはcanonical方向と全Exact Core行を保持する。対象別HTMLだけはTargetを常にTo、NeighborをFromへ正規化し、Favorable deltaもNeighbor→Target方向へ揃える。同一Target–Neighborの複数行は、Coreが別Coreの部分構造なら小さいCore側を除き、最大Coreによる最小変換1件へ決定論的に縮約する。

対象別HTMLは、(1) Target／Neighbor 2D構造、(2) Target全体SMILES、MMP ID、両化合物ID・Endpoint値、Neighbor→Target Favorable delta、(3) MMP ID、Core、Neighbor側置換部分、Target側置換部分、(4) 各MMPについてNeighbor化合物全体、置換前部分、置換後部分を1行3列にした2D変換図、の固定順で表示する。Neighbor全体SMILES文字列は掲載しない。HTMLはこの要約へ限定し、完全列・未縮約行は原本CSVに保持する。MMPを因果的・加算的な活性要因とは断定せず、観測された局所構造差として報告する。

## 7. MMP Type-II／III

### 7.1 共通契約

Type-I、II、IIIはすべて1-cutに限定し、Environment radius 0～2を標準範囲とする。同じPair／directed Transform／Exact Coreのradius違いを独立supportとして数えない。

Radiusは変換点周辺の、変化しないCore側環境をどこまで区別するかを示す。Radius 0は最も一般化され、Radius 1、2と大きくなるほど局所Contextが具体的になるが、supportは減少する。

### 7.2 Type-II Hit-to-Lead

人間がrun内の`compound_id`を一つ以上指定する。外部SMILESだけのHitは0.1.9対象外である。定型Top 1より多い上位K化合物を調べる場合は、人間が対象IDを選びType-IIへ明示する。主成果物はAgentの最終判断ではなく、指定化合物周辺のMMPを人間が探索できるself-contained HTMLと完全CSVである。

Exact Coreの直接MMPを主証拠とし、near-coreは別sectionへ分離する。near-core条件は次である。

- Core Tanimoto `>= 0.70`
- 両CoreのMCS coverage `>= 0.60`
- attachment数とtopologyが一致

effectの補助labelは三種類に限定する。

- `favorable_observed`
- `mixed`
- `no_favorable_observed`

観測量が不足する場合は別軸の`underexplored`を付ける。これらは入力データ内の観測要約であり、Agentによる最終見解ではない。

### 7.3 Type-III comprehensive database

Type-IIIは人間が明示した場合だけ実行する。

- 全データを1-cut、radius 0～2で網羅計算
- canonical evidenceは完全CSV
- SQLiteは検索用の再生成可能な派生index
- pair、transform、core、transform × core、context、coverageの表を生成
- HTMLはDatabase件数、coverage、欠損、探索条件を示す管理レポート
- Type-I／IIのレポートや標準Interpretationを自動生成しない

Type-IはType-IIIを自動探索・再利用しない。Type-IIで既存Type-IIIを使う場合は、人間が明示的にDatabase pathを指定する。

### 7.4 MMP成果物

Type-Iはsummary HTML、対象別HTML、target／pair／transform／core-context CSV、SVG／PNGを生成する。Type-IIは対象中心map、ranked transform view、site × replacement matrix、near-core reference、完全Pair表を一つのHTMLとCSV群へまとめる。Type-IIIは完全CSV群、SQLite、coverage HTMLを生成する。

HTMLの初期表示edge数は可読性のため制限してよいが、計算、CSV、filter対象は省略しない。MMPが0件の場合は成功したNegative Resultとして検索範囲と0件を明示する。

## 8. 定型レポート

### 8.1 A009 Standard Series report

A009はcanonical artifactだけを読む決定論的rendererであり、自由生成型Interpretationではない。固定HTMLテンプレートの必須sectionへ値を差し込み、表示列を固定する。一回の実行を一つのNodeとし、次を生成する。

- 全体Summary HTML：1件
- Series／fallback Cluster詳細HTML：analysis unitごとに1件
- PCA contact sheet：1件
- UMAP contact sheet：1件

### 8.2 全体Summary

主報告対象はEnrichment条件を満たした全Clusterである。Cluster一覧には次を含める。

- Cluster ID
- Description ID／名称
- Clustering ID／手法
- sample count
- Favorable count／fraction
- Odds ratio
- p値、q値
- Series IDまたはfallback状態

レポート冒頭には、全Cluster数、選抜Cluster数、基準合格Series数、fallback Cluster数、active解析単位数だけの簡略表を置く。続く定型情報は次の二種類とする。

1. Endpoint overview：入力数、Endpoint有効数、方向、Favorable閾値、実測Global FF、ヒストグラム。ヒストグラム内にMean、Median、方向依存のFavorable top-20% cutoffとUnfavorable bottom-20% cutoffを具体値で描画する
2. Compact Series map：Series ID、source Cluster数、union compound数、再計算FF、品質警告

処理時間、成功／`not_applicable`／失敗数は簡潔な実行メタデータとして表示する。

### 8.3 Series詳細

各詳細レポートには次を含める。

- Series定義、source Cluster、membership support、FF
- GlobalとのD001特徴量差とSeries内相関
- PCA／UMAP combined画像
- A005 model結果と選抜bias
- Global vs Series SALI、internal／boundary cliff
- 構造由来とkey structure
- 完全表へのlink

MMPは含めない。MMPは専用HTMLへ分離する。

### 8.4 厳格基準とnear-miss

人間向けhitは各Operatorの厳格基準を満たすものだけ表示する。hitが0件でもsectionを省略せず、評価件数、非検出、最も基準へ近い候補1件、未達基準を一文で示す。

near-missはOperatorが決定論的に選び、LLMに選ばせない。hitやInsightと異なるlabel／配色にする。評価可能な候補がなければ、候補を捏造せず理由を表示する。

HTMLは低彩度で視認性の高い配色とし、画像、CSS、必要な軽量JavaScriptをbase64／inlineで埋め込んだoffline self-contained形式とする。
幅の広い表はページ全体からはみ出さないscroll containerへ収める。HTMLには定義済みの要約列だけを掲載し、省略列と完全行はA009成果物内のCSVへのlinkで提供する。

## 9. Interpretation

0.1.9では定型レポートを主成果物とし、従来型Interpretationを軽量化する。

- 固定されたSummaryとSeries比較表だけを読む
- Enriched Cluster／Seriesの全体傾向を短く説明する
- GlobalとSeriesで変化した点、明らかな一致・不一致を少数示す
- 詳細調査が必要な視点はOn-demand候補として記載する
- 完全CSVをLLM contextへ投入しない
- 定型レポートと同じ数表を重複掲載しない

旧Result Assessment、一次採点、再Screening、累積Screening、正式Insight Registry、`INS######`通し番号管理は廃止する。旧Schema、prompt、互換readerも残さない。

Interpretationが失敗している間は定型workflowを完了扱いにしない。ただし、科学的に適用不能な定型結果は`not_applicable`として正常にレポートできる。

## 10. On-demand解析

### 10.1 通常DAGからの分離

On-demandは通常Roundを開始せず、Round状態に関係なく実行できる。通常Node ID、DAG edge、Lease、State status、Interpretation、Orchestratorの自動planningを変更しない。

`REQ######`をOn-demandの記録Node IDとして使用し、別の`N######`を発行しない。これにより、active Roundと同時に実行しても通常Node番号とStateを競合させない。

### 10.2 保存構造

```text
run_root/on_demand/
├─ index.jsonl
└─ REQ000001/
   ├─ request.json
   ├─ source_manifest.json
   ├─ method.md
   ├─ result.md
   ├─ result.html
   ├─ record.json
   ├─ artifact_manifest.json
   ├─ artifacts/
   └─ scratch/
```

`index.jsonl`はappend-onlyとし、On-demand専用lockで更新する。通常Runtimeのsingle-writer leaseを取得しない。一つのREQ内では重複実行防止用lockを使用する。

### 10.3 実行境界

- Run内のcommitted artifactだけを読み取る
- 参照path、hash、filter、scopeを`source_manifest.json`へ保存する
- 既存Description、Clustering、Analysis、Interpretation、State、Registryを変更しない
- 書込みを当該REQ directory内へ限定する
- 依頼に必要な一時Python等は`REQ/scratch/`へ作成可能
- OS tempが不可避な外部toolは使用理由とpathを記録する
- 固定された広めのPixi環境を用意する
- 実行中のnetwork installは禁止する

一依頼を一つのREQとして扱い、複数の図表や小解析をartifactとしてまとめる。同じ依頼を再実行しても新しいREQを作り、過去結果を上書きしない。

### 10.4 Type-II／IIIとの関係

A008 Type-IIとType-IIIはOn-demandから人間が明示的に起動する。成果物はREQ directoryへ保存し、通常DAG Nodeにはしない。Type-III DBをType-IIで再利用する場合は、人間がsourceとして明示する。

On-demand結果はTerminalな記録であり、標準Interpretation、Insight、後続自動planningへ投入しない。人間が後の依頼で明示した場合だけsourceとして再利用できる。

## 11. Runtimeと失敗時の契約

### 11.1 基本計算・定型解析

- Runtimeは計画されたNodeをすべて試行する
- 科学的な適用不能、0件、MMP neighborなしは成功または`not_applicable`として理由を記録する
- 実装不具合、引数不整合、成果物欠損は失敗としてrepair対象にする
- repair不能な失敗は人間が明示的にwaiveしない限り完了扱いにしない
- wall time到達時は同じRoundをpauseし、勝手に閉じたり次Roundを開始したりしない
- 再開時は成功済Nodeを再計算せず、未完了／repair対象だけを処理する
- 高コストDescriptionを含む基本計算はRun開始時に一括承認する

### 11.2 人間管理

人間だけがRound開始、継続、waive、終了を指示できる。RuntimeやMain Agentが、残作業を理由に新しいRoundを自動開始してはならない。

## 12. 完了条件

基本計算と定型解析の完了条件は次のとおりである。

1. 計画Nodeが成功、`not_applicable`、または人間waive済みである
2. Cluster／Series Registryとmembershipが検証済みである
3. A009 Summaryと全analysis unit詳細HTMLが生成済みである
4. 軽量InterpretationのMarkdown／HTMLが生成済みである
5. auditが整合性を確認済みである

完了後は`AWAITING_HUMAN_REVIEW`とし、自律的な追加探索や次Round開始を行わない。人間は定型レポートを確認し、必要な追加解析をOn-demandで依頼する。
