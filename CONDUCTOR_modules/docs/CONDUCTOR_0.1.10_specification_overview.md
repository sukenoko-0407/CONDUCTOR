# CONDUCTOR 0.1.10 仕様概要書（承認内容反映版）

## 1. 文書の位置づけ

本書は、CONDUCTOR 0.1.10について事前協議で承認された内容を、実装契約として記録する仕様概要書である。2026-09-04の実装開始指示に基づき、本文の仕様をコード、Skill、Runtime、schema、testへ反映した。

0.1.10の主要な変更点は次の3点である。

1. Description計算結果のDatabase化と再利用
2. A009およびMMPのレポート品質向上
3. Cluster-of-ClustersによるSeries形成手順の改変

本書に未決定の設計事項は残していない。将来この仕様を変更する場合も、コードへ先行反映せず人間へ確認する。

## 2. 互換性方針

- 0.1.10は新規Runを対象とする。
- 0.1.9までに完了したRun、Node、Artifactは書き換えない。
- Description Databaseでは複数のSkill versionの結果を共存可能にする。
- 0.1.9のDatabase未使用Runからの自動移行は行わない。
- CSVなどの完全な科学計算結果は引き続き正本として保存し、HTMLは人間が判断しやすい要約表示に限定する。

## 3. Description Database

### 3.1 目的

化合物集合がほぼ同じでEndpointだけが異なる解析において、同一条件で計算済みのDescriptionベクトルを再利用し、未計算化合物だけを追加計算する。

### 3.2 Databaseの配置

Databaseの論理ルートは次のとおりとする。

```text
data/description_database/<program_name>/
```

`program_name`は既存の`project`と同じ概念であり、Run IDの一つ上の階層を表す。既存の`--project`をProgram名の入力として正式化し、重複する`--program-name`引数は追加しない。ROUND1開始時までに人間が明示する必須値とし、一度指定したらRun内では変更できない。Runtimeのcontrol state、各Description manifestにも記録する。

同一Programから、Endpointなどが異なる複数Runを作成できる。Description DatabaseはProgram間で完全に分離し、同じcompound IDが存在しても別Programの結果を共有しない。

推奨する物理構成は次のとおりである。

```text
data/description_database/<program_name>/
├── database_manifest.json
├── compound_registry.sqlite3
├── D001__cs-compute-description-rdkit-2d/
│   ├── description.sqlite3
│   └── audit.jsonl
├── D002__cs-compute-description-morgan/
│   ├── description.sqlite3
│   └── audit.jsonl
└── ...
```

Database形式はSkillごとのSQLiteとする。想定上限は1 Programあたり5,000化合物であり、Local filesystemだけで使用する。SQLiteはcompound ID検索、transaction、重複防止、複数Runからの安全な更新、複数計算Versionの共存を一つの管理しやすいファイルで実現できる。非常に横長なvectorは列として展開せず、feature column一覧と型付きvector payloadとして保持する。

### 3.3 再利用キー

最初の検索キーは`compound_id`とする。ただし、誤ったベクトルの再利用を防ぐため、再利用には次の全条件の一致を要求する。

1. `program_name`
2. `capability_id`および`skill_name`
3. Description固有の`calculation_version`
4. 計算parameter、環境lockfile、モデル識別子を含む計算条件signature
5. `compound_id`
6. 計算用SMILESのhash（canonicalize可能ならcanonical SMILES、不可ならraw SMILES）
7. feature schema signature
8. 再利用可能な計算status

`skill_version`はパッケージのVersion、`calculation_version`はDescription計算ロジックのVersionを表す。両者をprovenanceとして記録するが、`skill_version`自体はcache再利用条件にしない。レポートだけを変更した将来Versionで不要なcache失効を起こさないため、再利用判定には`calculation_version`を使用する。同じ計算Versionでもfingerprint bit数、radius、chirality、乱数seed、環境lockfile、モデル識別子などが異なれば結果が変わるため、計算条件signatureも照合する。

SMILESはRDKit canonical SMILESへ変換して照合し、stereochemistryを区別する。cache miss時の実際のDescription計算にもcanonical SMILESを渡し、SMILES表記や原子順の違いによる計算結果の揺れを防ぐ。入力された元のSMILESはprovenanceとして別途保存する。canonicalizeできないinvalid SMILESはraw SMILESを計算入力および照合に使用し、そのhashを保存する。塩除去、tautomer統一、中和は行わず、入力前処理は人間の責務とする。

同一Program内で同じcompound IDに異なるcanonical SMILESが与えられた場合は、新規計算や別record登録を行わずfail-fastで停止し、人間へ通知する。ユニークIDに対応するユニーク構造の準備は人間の責務とする。

### 3.4 登録する情報

各レコードまたは関連metadataには、少なくとも次を保存する。

- compound ID
- 入力された元のSMILES、計算に用いたcanonical SMILES、および両者のhash
- capability ID、Skill名、Skill version、calculation version
- representation ID、value semantics、natural metric
- 計算条件signature
- feature column一覧またはそのschema signature
- 特徴量vector
- `mol_parse_ok`、`description_error`などの共通品質情報
- 計算日時、登録日時
- source run ID、round ID、node ID
- record status

一時的な外部計算失敗や実行環境エラーは再利用可能レコードとして登録しない。正常な計算結果、および明らかなinvalid SMILESのように入力自体で決まる結果だけを再利用対象とする。

featureの一部欠損はSkillごとに再利用可否を明示する。既定は再利用不可とし、Skill仕様で決定的な部分欠損であることが定義された場合だけ再利用する。

### 3.5 ROUND1の処理フロー

各Description Nodeについて次の順で処理する。

1. RuntimeがRun入力をcompound ID順に読み込み、計算用canonical SMILESを作る。
2. 指定`program_name`配下の該当Description Databaseを検索する。
3. 同一ID・異構造を検出した場合は直ちに停止する。
4. 再利用条件をすべて満たす行をcache hitとする。
5. hitしなかった化合物だけの一時入力CSVをcanonical SMILESで作る。
6. cache missが1件以上なら、該当Skillはmiss行だけを計算する。
7. 新規結果を検証し、cache hitと新規計算結果をRun入力順に再結合する。
8. 全化合物を含むDescription payload、manifest、execution eventを構築し、Run Artifact契約を検証する。
9. 検証成功後にだけ、新規の再利用可能レコードをDatabaseへtransactionalに追加する。
10. 全件の自己完結したDescription ArtifactをRun配下へcommitする。

cache missが0件の場合は科学計算Kernelを起動せず、DatabaseからRun固有Artifactを再構成する。

### 3.6 再現性と監査

Description manifestには次のcache統計を追加する。

- `program_name`
- Database schema version
- hit件数、miss件数、登録件数
- structure mismatch件数
- version/config mismatch件数
- cache source recordのversion内訳

Database更新は、Skill出力とArtifact契約の検証が成功した後にだけcommitする。途中失敗したNodeから不完全なvectorを登録してはならない。

Databaseは計算結果の再利用層であり、Run内Artifactの代替ではない。各Runには従来どおり全件の自己完結した結果を残す。

### 3.7 Databaseの確認と登録無効化

通常の解析実行からDatabase recordを上書きまたは削除することは禁止する。誤登録を修正するため、次の明示的な管理操作を用意する。

- Program、Description、compound IDを指定したrecord内容のread-only確認
- 人間が理由を明示した対象recordのinvalidate
- 操作者、理由、日時、対象record、旧record hashのaudit記録
- invalidate後の次回Runにおける再計算と新record登録

invalidateは物理削除ではなく再利用対象外への状態変更を基本とし、監査履歴を残す。通常実行が既存recordをsilent overwriteしてはならない。

### 3.8 高コスト計算の承認

ROUND1では高コストDescriptionも含めて定型実行し、Database利用によって再計算頻度を下げる。D016、D019、D020を対象としていた高コスト計算の人間承認processはRuntime、profile、promptから撤去する。cache missがある場合も承認待ちにはせず、通常のROUND1 Nodeとして実行する。

### 3.9 バッチ依存Description

化合物単位ではなく入力集合全体へのfitで値が変化する設定は、単純なcompound単位cacheと互換ではない。標準ROUND1ではcompound単位で決定的な設定だけを使用する。バッチ依存設定を使用する場合は、compound IDとcanonical SMILESの集合・順序から作るchemical dataset signatureを再利用キーへ加え、集合と順序が一致する場合だけ全体を再利用する。一部化合物だけのhit／miss再利用は行わない。Endpoint列の違いはchemical dataset signatureへ含めない。

## 4. A009 Standard Summaryレポート

### 4.1 基本方針

- 人間の意思決定に必要な情報を先に示す。
- Agent向けの生成指示や内部実装用語を本文へ表示しない。
- 横長の完全TableをHTMLへ埋め込まない。
- HTMLは厳選列、CSVは完全列という役割分担を守る。
- DescriptionやClusteringのIDには、人間向け名称の凡例を添える。
- 「厳格基準」という曖昧な表現を廃止し、具体的な数値条件を表示する。

### 4.2 新しいSection構成

不要なReport scope、実行状況、Full tables and limitationsを削除し、番号を連続に振り直す。

1. 概要
2. Endpoint分布
3. Selected Cluster
4. Series
5. 標準解析結果
6. PCA / UMAP一覧
7. 個別analysis unitレポート

### 4.3 Section 1: 概要

最上部に、次の数値をSection 3／4と同じmetric cardで示す。Tableと列説明は置かず、各Summary itemの意味だけをcard直下の折り畳み領域で説明する。

- 登録された全Cluster数
- 一次選抜基準を満たしたCluster数
- 形成されたCandidate Series数
- 通常基準を満たしたSeries数（FF 0.50以上）
- 緩和基準で採用された複数Cluster Series数（FF 0.40以上0.50未満）
- fallbackとなったCluster数
- 最終的なlocal analysis unit数
- 使用した`min_ff_evaluate`とLeiden resolution

`Fallback`という単独の曖昧なラベルは使用せず、`Fallback Clusters`の折り畳み説明で、Candidate Seriesの和集合FFが採用基準を満たさず、構成元Clusterを個別analysis unitへ戻した件数であると定義する。

### 4.4 Section 2: Endpoint分布

Endpoint histogram内の統計値表示は一つだけにする。凡例とannotation boxで同じ値を二重表示しない。

図内の一つの情報boxへ次を表示する。

- Endpoint有効件数
- Mean
- Median
- Favorable側20%のcutoff
- Unfavorable側20%のcutoff
- `higher_is_better`に応じた方向

Histogramの直後に、Globalおよび最終的なlocal analysis unitのEndpoint分布を比較する横長のBoxplotを置く。

HistogramとBoxplotは縦横比を維持したまま本文幅より小さくし、中央揃えで表示する。図の上に分布比較を説明する重複見出しや、図から自明なFavorable判定式の折り畳みは置かない。

- 図全体は横長とし、高さを固定する。
- 縦軸をEndpoint、横軸を各groupとする。
- 横軸はGlobal、採用Series、fallback Clusterの順とする。
- Seriesとfallback Clusterの内部では、Favorable側のmedianが良い順に並べる。
- Globalは灰色、Seriesは青、fallback Clusterは橙とする。
- 各labelにanalysis unit IDとEndpoint有効件数Nを表示する。
- Tukey方式のBoxplot（whiskerは1.5×IQR）とする。
- Favorable cutoffとUnfavorable cutoffを横方向の破線で表示し、凡例で両者を明記する。
- 図全体の横幅はHTMLの表示幅に固定し、group数が多い場合は図や高さを拡張せず、各Boxの幅と横軸labelを調整して一つの横長図へ収める。

ここで表示するClusterは、全一次選抜Clusterではなく、Candidate Seriesが不採用となった結果、最終的に個別解析対象となったfallback Clusterだけとする。採用Seriesの構成元Clusterを重複表示しない。

### 4.5 Section 3: Selected Cluster

TableのDescriptionおよびClustering列は`DXXX`、`CXXX`だけを表示する。Tableの下に、そのページで使われたIDだけを次の形式で説明する。

```text
- D001: RDKit 2D descriptors
- C007: DBSCAN clustering
```

この説明は`特徴量／クラスタリングの説明`という折り畳み領域へ格納する。C001–C004の構造クラスタリングはDescription vectorを使用しないため、Description列を`—`とし、DXXXの説明も表示しない。

各Clusterについて、少なくとも次を表示する。

- Cluster ID
- Description ID
- Clustering ID
- 化合物数
- Favorable count / Favorable Fraction
- 所属するCandidate Series ID
- 最終的に採用されたSeriesまたはfallback Clusterのanalysis unit ID

P値や完全なprovenance列はCSVに残し、Summary Tableからは外す。

### 4.6 Section 4: Series

既存のSeries形成plotは削除する。Candidate Series mapは全Candidateを含むcompact Tableとして残す。Table本体は次の列に限定する。

- Candidate Series ID
- source Cluster数
- 和集合の化合物数
- 和集合Favorable Fraction
- 適用されたSeries FF基準
- 採用／不採用
- 最終的なSeriesまたはfallback先

source Cluster ID一覧は各行の折り畳み領域へ表示し、Tableを横長にしない。完全な対応関係はCSVにも残す。

metric card直下には各itemの意味を説明する折り畳み領域を置く。固定の`Candidate Series map`小見出しと、重複するSeries形成／fallback説明は置かない。

`Active analysis units`という説明なしの見出しは廃止する。必要な場合は`Final local analysis units`とし、「後続のA003–A008が実際に処理した単位」と一文で定義する。

### 4.7 Section 5: 標準解析結果

「基準を満たすhitを優先し、ない場合はnear-missを表示する」といったAgent向け規則や、評価件数・near-miss名を解析内容の折り畳みに表示しない。各解析は主要Tableを先に置き、`解析内容`の折り畳みに目的と具体的な判定条件だけを示す。A005は基準通過の有無にかかわらず、評価可能な各analysis unitの最良modelを1件ずつ表示する。詳細CSVリンクは各operator Sectionの末尾に置く。

#### A003: Interpretable descriptor contrast

対象Descriptionは固定panel `D001、D012、D015、D016、D019`とする。D001、D012、D019は利用可能な全数値特徴量を使用する。D015はacid/base、元素組成、芳香族性、ring count、polarizabilityに関する解釈しやすい2D特徴量へ、D016は分子geometryと部分表面積に関する3D特徴量へ厳選する。

相関による候補条件を0.1.10で次のように変更する。

1. localの`abs(Pearson r)`または`abs(Spearman r) >= 0.60`
2. 対応するGlobalの絶対相関より`>= 0.20`大きい
3. 対応するBH補正q値`<= 0.05`

median shiftの条件は次を維持する。

1. `abs(local median - non-local median) / Global IQR >= 0.75`
2. BH補正q値`<= 0.05`

HTML本文の解析内容には目的と相関判定条件だけを記載し、評価件数やnear-miss文は表示しない。全統計とmedian shiftは詳細CSVへ保持する。

#### A005: Multi-description feature model

曖昧な「厳格基準」を使わず、次の条件を表示する。

1. local OOF R² `>= 0.20`
2. 同じ化合物に対するGlobal OOF R²より`>= 0.20`改善
3. local OOF MAEがGlobal comparatorより悪化していない

Standard Summaryでは、条件を満たすmodelが0件でも、評価可能な各analysis unitの最良modelを「参考・基準未達」と明記して1件ずつ表示する。

LocalとGlobalは同じ固定候補panel `D001、D002、D006、D013、D016、D019`から開始する。欠損・定数列の除外とunivariate F-test上位最大24特徴量の選択は、各analysis unit・各outer CV foldのtraining dataだけで独立にfitするため、実際に採用される特徴量はLocalとGlobalで異なる場合がある。

0.1.10ではModel Nが30未満の場合は実施対象外とし、HTMLには空Tableを出さず、理由を一行だけ表示する。Model Nは、analysis unit所属化合物のうち、Endpointが有効でDescriptionとのID結合に成功し、少なくとも一つのmodel featureを利用できる化合物数とする。部分欠損featureはtraining fold内でimputeできるため、それだけでは化合物を除外しない。したがって実施可能な最小Model Nは30である。レポートにはunit所属総数`Member N`と実際の`Model N`を併記する。

#### A006: SALI / activity-cliff landscape

A006は、当該analysis unitが活性enrichmentの境界になっているかを簡易判別する。unit内の化合物とunit外の化合物を一つずつ組にし、構造が類似しているのにEndpointが大きく異なるboundary pairを検出する。各pairでunit内化合物のEndpointが相手よりFavorableかを数え、その方向が複数pairで一貫するかを調べる解析である。これは構造的に近いunit外化合物との局所比較でunit側へのFavorableなactivity cliffが境界上に反復することを示すものであり、unit内の全化合物がunit外より優れることを意味しない。

注目すべきboundary cliffの条件は次のとおりである。

1. D002 ECFP4（Morgan radius 2、2048 bit）のTanimoto similarity `>= 0.75`
2. absolute Endpoint delta `>= 1.0 × Global Endpoint IQR`
3. boundary cliff pairが3件以上
4. そのうちanalysis unit側がFavorableなpairの割合`>= 0.80`

上記を満たす場合は、「よく似た外部化合物に対してEndpointが有利に変化する境界が、複数pairで同じ方向に観測された」と解釈できる。SALIの絶対値単独には汎用的な良否cutoffを置かず、similarity、Endpoint delta、support数、方向の一貫性を併記する。

`internal_cliff_count`はunit内部pairのうち、Tanimoto similarity 0.75以上かつabsolute Endpoint差1.0×Global Endpoint IQR以上を同時に満たす件数である。HTMLの`Boundary favorable direction`は小数割合ではなく、`unit側がFavorableだった件数 / Boundary cliff全件数`で表示する。

Standard Summaryの解析結果はA003、A005、A006だけに限定する。A004はPCA／UMAP Section、A007は個別レポート、A008は専用MMPレポートで扱い、ここには重複表示も導線も置かない。

### 4.8 Section 6: PCA / UMAP一覧

A004が生成したPCAおよびUMAPをanalysis unitごとに一覧表示する。Section 5へ同じ内容を重複表示せず、各図にはanalysis unit IDと個別レポートへのlinkだけを添える。

### 4.9 Section 7: 個別analysis unitレポート

最終的に後続解析を行ったSeriesおよびfallback Clusterを一覧化し、各個別レポートへの導線を置く。候補段階で不採用となったSeriesや、採用Seriesの構成元Clusterを独立したanalysis unitとして重複掲載しない。

## 5. A009 個別analysis unitレポート

### 5.1 Section 1: Analysis unitの定義

Source Clusters TableはIDを中心にコンパクトにし、Table直下に実際のDescriptionとClusteringを語句で説明する。

例:

```text
- D001: RDKit 2D physicochemical descriptors
- C007: DBSCAN using the natural metric of D001
```

全値が1になりやすいMembership Support Tableは削除する。これは人間に新しい判断材料を与えず、画面を占有するためである。`support_count`と`support_fraction`はcanonical CSVには残す。

代わりにanalysis unit所属化合物の2D構造galleryを表示する。

- 最大20化合物
- 4行×5列
- 各構造の下にcompound ID
- 20件未満なら全件
- 再生成で内容が変わらない決定的な疑似random sample
- 「全N化合物のうち、決定的に抽出した最大20化合物を表示」と明記

### 5.2 Section 2: PCA / UMAP

現状のPCAおよびUMAP表示を維持する。analysis unit所属点にはMatplotlib orange `#ff7f0e`を使用し、非所属点の灰色と明確に区別する。

### 5.3 Section 3: A003

HTML Tableは次の6列に限定する。

- Feature
- Description ID
- N
- Pearson r
- Spearman r
- Max absolute correlation

`Correlation BH q`、`Strict hit`、`median_shift_global_iqr`はHTMLから削除する。q値、median shift、および全判定列は詳細CSVに残す。BH qは多数のfeatureを同時評価したときの偽陽性増加を抑える補正済みp値である。HTMLで残す専門列を含め、各Tableの直下には列の意味を説明する折り畳み領域を置く。

各analysis unitについて、相関の絶対値が大きい上位3特徴量の`feature vs Endpoint`散布図を表示する。対象analysis unit内の点だけを簡潔に表示し、Globalとの比較overlayなどの追加装飾は行わない。

### 5.4 Section 4: A005

「本比較は……」という選抜bias説明文はこのSectionから削除する。判定条件は4.7節の具体的な数値で示す。

Model Nが30未満などにより`not_applicable`の場合はTableを表示せず、`Member N`、`Model N`、実施しなかった理由を一行で示す。

評価可能な場合は、基準未達であっても当該analysis unitの最良modelを表示する。

Tableの下に、左をLocal、右を同じ化合物に対するGlobalとした`OOF predicted Endpoint vs Observed Endpoint`散布図を置く。両panelは同じ軸範囲とidentity lineを使う。

### 5.5 Section 5: A006

SALI、internal cliff、boundary cliffの意味を簡潔に説明し、4.7節の具体的な条件を示す。主要Tableを先に置き、`解析内容`の折り畳みに説明と判定条件を置く。評価件数や基準通過件数の定型文は置かない。人間向け表示では「条件を満たしたboundary cliff」「条件未達」「評価対象外」を用い、「strict」という内部ラベルを表示しない。

### 5.6 Section 6: A007

構造文字列だけでなく2D画像を表示する。

- supportの大きい順に最大5構造を表示
- 横一列を基本とし、viewportに応じて折り返す
- captionは由来Cluster IDとし、内部method名やsupport countは表示しない
- gallery下の`N structures`件数captionは表示しない
- C001–C004の構造由来Clusterでは、クラスタリング手法が登録したKey構造だけを表示し、`C001：Murcko scaffold`のようにIDと手法名を説明へ併記する。Murcko／MCSを追加計算しない
- C005–C010のvector由来Clusterだけ、そのSource Cluster所属化合物から代表Murcko scaffoldとMCSの両方を計算して表示する
- 複数ClusterのSeriesでもSeries和集合を代用せず、各Source Clusterのmembershipを使用する
- 構造由来／vector由来と、表示構造をどのように得たかを平易に説明する
- 構造由来／vector由来の説明文は折り畳まず、gallery直下へ常時表示する
- SMARTS queryを描画できない場合は構造文字列と理由を表示する
- 完全な構造一覧はCSVに残す

### 5.7 MMPへの導線

個別レポートの上部に、当該analysis unitでA008 Type-I対象となったTop 1化合物を示す。

- compound ID
- Endpoint値
- MMP pair件数
- 個別MMP HTMLへの相対link

同じ化合物が複数analysis unitのTop 1である場合は、同一のMMPレポートへ複数の個別A009レポートからlinkしてよい。A008は`analysis_unit_id → target compound ID → report path`の小さなindex Artifactを出力し、A009は巨大なMMP pair Tableではなくこのindexだけを受け取る。

個別A009の末尾に独立した`Full tables and limitations` Sectionは作らない。詳細CSVへの小さなlinkが必要な場合は、対応する各Sectionへ`詳細CSVリンク`として配置する。各Sectionは主要Table／画像を見出し直後に置き、説明文と判定条件はその下の折り畳みに置く。

## 6. MMPレポート

### 6.1 既存方針の維持

- 定型Type-Iは各Seriesまたはfallback ClusterのTop 1化合物だけを対象とする。
- より多いTop KはOn-demandで実行する。
- ReportingではTargetを常に`To`側へ正規化し、Favorable deltaの符号もNeighbor→Target方向へ揃える。
- 同一Target–Neighborに複数coreがある場合、包含関係において最大のcoreを持つ最小変換だけをHTMLへ表示する。
- Databaseおよび詳細CSVは縮約しない。

### 6.2 個別レポートの基本情報

タイトルにはtarget compound IDを残す。冒頭に、このtargetをTop 1として参照するanalysis unit ID一覧を示し、A009個別レポートへ戻るlinkも置く。MMPが0件でも対象targetを省略せず、`MMP該当なし`と示すレポートとA009からの導線を生成する。

個別MMP HTMLは次の4 Sectionで構成する。

1. TargetおよびNeighbor化合物の2D構造
2. 基本情報Table
3. 変換詳細Table
4. Exact Core別Visual transformations

MMP全体レポートのSection 2には、各analysis unitで選ばれたTargetの2D構造を4列で並べる。同じTarget化合物が複数unitでTop 1の場合も、unitとの対応が分かるよう各unitを個別に表示する。

個別MMP HTMLのSection 1ではTargetを単独の1行として表示し、その下にNeighbor構造を4列で並べる。Neighbor領域は初期状態で折り畳む。Targetの2D座標を固定した基準とし、各Neighborを共通構造によってTargetへalignする。

基本情報Tableは次の列に限定する。

- MMP ID
- Neighbor compound ID
- Target compound ID
- Neighbor Endpoint
- Target Endpoint
- Favorable delta

変換詳細Tableは次の列に限定する。

- MMP ID
- Exact Core SMARTSまたはSMILES
- Before fragment（Neighbor側）
- After fragment（Target側）
- Target全体SMILES

Neighbor全体SMILESはHTML Tableへ掲載しない。完全な列は詳細CSVで確認できるようにする。

個別MMPレポートでも各Sectionの主要Table／画像を先に配置し、説明文、方向の説明、掲載範囲はその下の折り畳みに置く。Section 4では`表示内容`と`掲載範囲`を別々の折り畳みにし、CSV linkは`詳細CSVリンク`としてSection末尾に置く。

HTML内のTableは初期状態で折り畳み、列headerの操作で昇順・降順sortできるようにする。各Table直下の折り畳み領域には列の意味を記載する。

### 6.3 Visual transformations

各変換行の構造画像は左から次の順とする。

1. Neighbor全体
2. Target全体
3. Before fragment（Neighbor側）
4. After fragment（Target側）

各行にはMMP ID、Neighbor ID、Endpoint値、Favorable deltaを併記する。

NeighborとTargetは共通coreを基準に2D描画方向を揃える。Exact Coreのgroup headerではcore画像を小さめに左へ置き、`MMP rows`と`Max Favorable Δ`のcardを右側へ縦に並べる。

### 6.4 同一coreのgrouping

MMP IDが異なってもExact Coreが同じ行は、一つの`Core group`としてまとめる。Core識別は処理を過度に複雑化せず、可能ならcanonical SMILES相当の表現へ揃えた上で、構造とattachment pointが同一かを判定する。canonical化できない場合は、attachment pointを保持した正規化文字列の一致を使う。

1. group header: Core group番号、Exact Core SMARTS、MMP数、Neighbor数、Target数
2. 共通coreの2D画像を一度だけ大きく表示
3. その下に各MMPを1行ずつ、Neighbor全体 → Target全体 → Before → Afterの4画像で表示
4. 同一core内は方向を正規化したFavorable delta降順、次にNeighbor ID、MMP IDで決定的にsort
5. Core groupは最大Favorable delta、core heavy atom数、core SMARTSの順で決定的にsort
6. 各groupはFavorable delta上位5件を展開し、6件目以降を同じHTML内の折り畳み領域に入れる

レポート末尾には、検出した一意MMP件数、最小変換への整理後の掲載件数、各coreで初期表示する件数と折り畳み件数を実数で記載する。全件を掲載した場合、上位だけを初期表示した場合、MMPが0件の場合で文言を切り替える。

これにより、共通core画像の重複を減らしつつ、「同じ骨格上でどの置換がどちら向きにEndpointを変えたか」を縦方向に比較できる。

## 7. Series形成手順

### 7.1 現状の問題

0.1.9では、一次選抜Clusterをoverlap graph上でLeiden clusteringし、各communityの和集合Favorable Fractionが0.50未満ならSeriesを不採用として、構成元Clusterへfallbackする。

大きなcommunityでは和集合によりFavorable Fractionが低下しやすい。その結果、多数のSeriesが不採用となり、元のClusterが個別analysis unitとして復活して、最終unit数が24を超える事例がある。

### 7.2 複数Cluster SeriesのFF基準

採用基準は次のとおりである。

- source Clusterが2件以上のCandidate Series: `Favorable Fraction >= 0.40`
- source Clusterが1件のCandidate Seriesまたは一次選抜Cluster: `Favorable Fraction >= 0.50`

#### Pros

- 和集合による自然な希釈だけでSeriesが棄却されるケースを減らせる。
- fallback Clusterの急増を抑え、後続解析単位数を減らせる可能性がある。
- Global Favorable Fractionがおおむね0.20であるため、0.40でもGlobalより十分濃縮された集合になりやすい。
- 複数のDescription／Clustering手法が支持する重複構造を、一つの解析単位として保ちやすい。

#### Cons

- 0.50基準よりEndpoint濃縮の弱いSeriesを後続解析へ含める。
- 単独Clusterと複数Clusterで異なる基準となり、説明が複雑になる。
- 大きなSeriesを残すための便宜的な緩和に見える可能性がある。
- DatasetによってGlobal Favorable Fractionがtieの影響で0.20を超えるため、0.40の相対的な強さは一定ではない。
- unit数が減る保証はなく、Leiden partitionとの相互作用は非単調である。

#### 採用時の安全策

- 0.40を適用したSeriesには`multi_cluster_ff_threshold=0.40`を明記する。
- source ClusterごとのFF、和集合FF、source平均からの低下量を保存・表示する。
- 0.40以上0.50未満のSeriesを「高濃縮」と表現せず、「緩和基準で採用」と識別する。
- Global Favorable Fractionとの比または差も診断値として残す。

0.40は固定値として扱い、Global FFに連動する追加条件は設けない。

### 7.3 自動parameter search

C012は一つの条件だけでなく、決定的なparameter gridを評価する。Descriptionおよび元のClusterを再計算せず、既存のCluster membershipとA001/A002統計からSeries形成だけを再評価する。

`min_ff_evaluate`の候補はユーザー指定どおり次とする。

```text
10, 15, 20, 25, 30
```

Leiden resolutionは次の固定gridとし、上限は3.00とする。

```text
1.00, 1.25, 1.50, 2.00, 2.50, 3.00
```

上限を3.00とする理由は、初期値から十分な細分化を試しつつ、極端にsingleton化したpartitionを際限なく探索しないためである。

### 7.4 探索順と半自動選択

まず`min_ff_evaluate=10`を維持し、resolutionを1.00から3.00まで小さい順に評価する。この範囲で最初にfinal local analysis unit数が24以下となった条件を自動採用する。

resolution変更だけでは24以下にならない場合に限り、`min_ff_evaluate=10, 15, 20, 25, 30`と全resolutionの30組合せを評価する。この段階ではRuntimeが条件を自動採用せず、AgentがSession内にMarkdown TableとしてMatrixを表示し、人間の選択を待つ。Matrixの行を`min_ff_evaluate`、列をresolutionとし、各セルを`final unit数 / Cluster coverage / Compound coverage / fallback数`の順で表示する。Matrixは解析結果ではなく途中判断情報であるため、HTMLレポートやA009には掲載せず、図や装飾も作らない。中断・再開時の監査に必要な数値はRuntime内部stateへ保持できるが、科学結果Artifactとして扱わない。

C012は二段階で処理する。探索段階では候補条件の要約だけを作り、人間判断が必要ならcanonical Series Artifactを確定しない。人間が条件を選んだ後、その条件でC012を再実行し、最終的なSeries／analysis unit Artifactを生成する。全30条件分のmembershipを保持せず、選択条件だけを決定的に再計算する。

人間へ提示するときの優先順位は次のとおりとする。

1. 小さい`min_ff_evaluate`
2. 低いresolution
3. final local analysis unit数が24以下
4. 同順位ならfallback Cluster数が少ない
5. さらに同順位ならSeries FF中央値が高い

各条件について次をRuntime内部のdecision stateに保持し、AgentがSession内のTableへ整形する。

- min FF evaluation count
- Leiden resolution
- 一次選抜Cluster数
- Candidate Series数
- accepted Series数
- 0.40緩和基準でのみ採用されたSeries数
- rejected Series数
- fallback Cluster数
- final local analysis unit数
- Seriesのcompound coverage
- Default選抜Clusterに対するCluster coverage
- Default選抜Cluster和集合に対するCompound coverage
- FF中央値およびsource平均からの低下量
- 24件以下か否か

### 7.5 24件を超える場合のhuman gate

- `min_ff_evaluate=10`のresolution探索で24件以下: 定型解析へ自動進行できる。
- resolution探索だけでは24件以下にならない: AgentがSession内で全gridのMatrixを提示し、人間の選択を待つ。
- 人間は提示された条件を選ぶ、カスタム条件で再計算する、またはDefault条件を含む現状のunit数を承認して進行できる。
- 人間がSession内Matrixから25件以上100件以下の条件を明示選択した場合、その操作をparameter選択とunit数超過承認の両方として扱い、同じ結果に対する二度目の確認は行わない。
- 人間が条件変更を選び、再計算後も24件を超えた場合は、以前の承認を流用せず再度確認する。
- 承認は特定のC012 Node、parameter signature、unit countに結び付ける。

24件は自動進行上限であり絶対上限ではない。25件以上100件以下は人間の明示承認により進行できる。50件は運用上の目安とし、強制停止条件にはしない。100件を絶対上限とし、101件以上では承認があっても標準解析へ進めない。

### 7.6 注意点

Leiden resolutionを上げると一般にはcommunityが細かくなるが、Candidate Series数自体は増える場合がある。一方、巨大Seriesの棄却による多数fallbackを減らす場合もあるため、final analysis unit数は単調には変化しない。このため、特定方向へblindに調整するのではなく、全gridを比較して結果で選ぶ。

## 8. 新規・変更Artifact

0.1.10では少なくとも次を追加または拡張する。

```text
data/description_database/<program_name>/...

run_root/runtime/
├── selected_clusters_effective.csv
├── series_parameter_search.json     # 途中判断用の内部state。A009には掲載しない
└── series_summary.json              # chosen parameterと探索要約を追加

A008 result/
└── mmp_report_index.csv             # analysis unitからMMP HTMLへの導線
```

`series_parameter_search.json`は中断・再開と判断監査のためのRuntime内部stateであり、解析結果ArtifactやHTMLレポートには含めない。AgentはこのJSONからSession内にMarkdown Tableを表示する。`selected_clusters_effective.csv`は、人間または自動処理が最終的に採用した条件における一次選抜Clusterの正本とする。A009は0.1.9の初期条件列ではなく、このeffective結果を表示する。

## 9. 事前協議で確定した設計判断

次の個別設計事項は事前協議で確定した。文書全体に対する実装開始承認は別途必要である。

1. 既存`project`を`program_name`として正式化し、Program間のDatabaseを完全分離する。
2. Description DatabaseをSkillごとのSQLiteとし、Localで最大5,000化合物を扱う。
3. `skill_version`はprovenanceだけに使い、`calculation_version`、計算条件signature、canonical SMILESを再利用判定に使い、同一ID・異構造はfail-fastとする。
4. 高コスト計算の人間承認processを撤去する。
5. 複数Cluster SeriesだけFF基準を0.40へ緩和する。
6. Leiden resolution gridを`1.00–3.00`の6段階とする。
7. resolutionは自動探索し、`min_ff_evaluate`変更時はSession内Matrixから人間が選択する。
8. 24件以下は自動進行、25～100件は人間承認、101件以上は進行不可とする。
9. A005は30件未満で実施対象外、30件以上で実施する。
10. A007をStandard Summaryから完全に外し、個別レポートだけで扱う。
11. Endpoint比較は横長Boxplotとし、縦軸をEndpoint、横軸をGlobal／Series／fallback Clusterとする。
12. MMPをExact Core group card形式で表示し、Favorable delta上位5件を展開する。
13. Description実計算にもcanonical SMILESを使用し、元SMILESはprovenanceとして残す。
14. Database誤登録は上書きせず、監査付きinvalidate操作で再利用対象外にする。
15. A005の30件判定にはModel Nを使い、Member Nと併記する。
16. 基準通過0件時は最上位near-missを「参考・基準未達」として1件表示する。
17. Candidate Series mapは全候補をcompact Tableへ残し、source Cluster ID一覧を折り畳む。
18. Matrix上の25～100件の条件選択は、parameter選択と超過承認を兼ねる。

## 10. 完了条件

0.1.10は次をすべて満たしたとき完了とする。

- 同一`program_name`、同一calculation version、同一計算条件、同一ID／canonical SMILESの2回目RunでDescriptionがcache hitする。
- 一部だけ新規化合物を含むRunで、新規化合物だけを計算し、全件Artifactを正しい入力順で生成する。
- calculation version、条件、canonical SMILESのいずれかが異なるレコードを誤再利用せず、同一ID・異構造をfail-fastにする。
- A009 Standard Summaryが指定Section構成、明示的基準、compact Tableを満たす。
- A009に横長のEndpoint Boxplotがあり、Global、採用Series、fallback Clusterを色分けして比較できる。
- 個別A009に20化合物gallery、A003散布図、A007構造画像、MMP linkが表示される。
- MMP visual transformationが4画像順であり、同一coreがgroup化される。
- MMP 0件のtargetにも`MMP該当なし`レポートとA009からのlinkが生成される。
- C012のparameter候補をRuntime内部stateからSession内Matrixとして提示でき、選択規則を決定的に再現できる。
- parameter変更またはC012再計算後にhuman approvalが誤って引き継がれない。
- package verification、unit test、integration test、report renderer testがすべて成功する。
