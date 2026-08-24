# CONDUCTOR Skill Catalog 日本語早見表

現行Catalogに収載された科学解析機能の簡易一覧です。詳細な入出力、引数、計算コスト、安定性は[`CONDUCTOR_skill_catalog.md`](CONDUCTOR_skill_catalog.md)および各Skillの`README.md`を参照してください。

## Description

化合物を数値ベクトルで表現する機能です。

| ID | 名称 | 主に表すもの | 主な特徴 |
|---|---|---|---|
| D001 | RDKit 2D descriptors | 分子サイズ、物性、結合・環などの2D特性 | 解釈しやすい連続値の基本記述子 |
| D002 | Morgan fingerprint | 原子近傍の部分構造 | 局所構造を表す代表的なバイナリFingerprint。キラリティ対応可 |
| D003 | MACCS keys | 定義済み部分構造の有無 | 次元が比較的小さく、意味が明確な構造キー |
| D004 | Atom-pair fingerprint | 原子対とトポロジー距離 | 離れた原子間の構造関係を表す疎なカウントVector |
| D005 | Topological-torsion fingerprint | 連続する4原子の結合パターン | 局所的なトポロジー配列を表す疎なカウントVector |
| D006 | RDKit fragment counts | 官能基・部分構造の個数 | 人間が化学的に解釈しやすいFragment記述子 |
| D007 | RDKit path fingerprint | 結合Pathに沿った部分構造 | 分子グラフのPath情報を表すバイナリFingerprint |
| D008 | RDKit pattern fingerprint | 一般化された部分構造Pattern | 部分構造検索に近い観点のバイナリFingerprint |
| D009 | RDKit layered fingerprint | 原子・結合・環など複数層のグラフ特徴 | 異なる構造情報を層別に取り込むバイナリFingerprint |
| D010 | Avalon fingerprint | ハッシュ化された部分構造 | Morgan等とは異なる構造符号化を与えるバイナリFingerprint |
| D011 | Gobbi Pharm2D | 2D上の薬理学的特徴配置 | Donor、Acceptor等の特徴間関係を表すPharmacophore Fingerprint |
| D012 | RDKit 3D descriptors | 立体形状・幾何学的性質 | 3D配座から連続値の形状記述子を算出 |
| D013 | USR / USRCAT | 分子形状と薬理学的特徴の空間分布 | 少数のMomentで3D形状を要約。USRCATは化学的特徴も区別 |
| D014 | Basic 3D shape descriptors | 慣性主軸、球状性、扁平性など | 比較的少数で解釈しやすい3D形状指標 |
| D015 | Mordred 2D descriptors | 多様な2D物性・トポロジー指標 | 高次元で広範囲を覆う汎用記述子集合 |
| D016 | Mordred 3D descriptors | 多様な3D形状・幾何学指標 | 高次元かつ高コストな3D記述子集合 |
| D019 | GFN2-xTB quantum descriptors | 電荷、軌道、エネルギーなどの電子状態 | 半経験的量子化学計算に基づく高コストな連続値記述子 |
| D020 | ChemBERTa-100M-MLM embedding | SMILESから学習された潜在的な化学表現 | Download済みLocal WeightをCPUで使用する高次元Embedding |

`D017`と`D018`は現行Catalogでは使用していない欠番です。FingerprintやEmbeddingの比較・Clusteringでは、表現の意味に適したMetricを用います。

## Clustering

化合物集合をClusterとして切り出す機能です。構造を直接扱う手法と、Description Vectorを扱う手法があります。

| ID | 名称 | 主に表すもの | 主な特徴 |
|---|---|---|---|
| C001 | Murcko scaffold clustering | 共通の骨格Scaffold | 中心骨格が同じ化合物をまとめる構造ベース手法 |
| C002 | MCS clustering | 最大共通部分構造 | 多様な共通Coreを探索でき、1化合物の複数Cluster所属も許容 |
| C003 | BRICS fragment clustering | BRICS規則で切断したFragment | 合成上意味のある結合切断に基づく構造ベース手法 |
| C004 | RECAP fragment clustering | RECAP規則で切断したFragment | 代表的な合成反応規則に基づく構造ベース手法 |
| C005 | Vector Butina clustering | 距離閾値内の近傍集合 | 中心化合物を基準に類似Vectorをまとめる手法 |
| C006 | Vector hierarchical clustering | Vector間距離の階層構造 | 樹状のまとまりを距離基準で切り出す手法 |
| C007 | Vector DBSCAN clustering | 局所密度の高い領域 | Cluster数を事前指定せず、疎な点をNoiseとして分離 |
| C008 | Vector Louvain clustering | 類似度Graph上のCommunity | 近傍Graphの結合密度を基にCommunityを検出 |
| C009 | Vector Leiden clustering | 類似度Graph上のCommunity | Louvainを改善し、より整合したCommunity分割を志向 |
| C010 | Vector connected components | 閾値Graphの連結成分 | 類似度閾値でつながるVectorを同一Clusterとして扱う |
| C011 | Categorical-column clustering | Assay条件などのCategory | 指定したカテゴリ列が同じ化合物をまとめる人間文脈ベース手法 |
| C012 | Overlap-based meta clustering | 既存Cluster間の重なり | Membershipの重複からCluster同士を再編するMeta手法 |

Vector ClusteringのMetricと近傍・距離設定は、入力Descriptionの値の性質に合わせて選択します。小さすぎるClusterはCONDUCTORへの登録対象から除外します。

## Operator

Description、Clustering、Endpointを入力として、関係性や局所的変化を評価する解析機能です。

| ID | 名称 | 主に表すもの | 主な特徴 |
|---|---|---|---|
| A001 | Activity distribution | Endpoint値の分布 | 件数、中心、ばらつき、外れ値などを把握する基本解析 |
| A002 | Descriptor–activity correlation | 各特徴量とEndpointの単変量関係 | 線形・単調な関連を特徴量ごとに広く探索 |
| A003 | PCA projection | Descriptionの主要な線形変動 | 低次元座標とEndpoint着色によりGlobal／Local構造を可視化 |
| A004 | UMAP projection | Descriptionの非線形な近傍構造 | 局所的なまとまりを2次元等へ投影して可視化 |
| A005 | Multi-Description feature model | 複数Descriptionを横断したEndpoint説明 | 固定6種から特徴量を選び、簡潔なGlobal／Local modelを検証 |
| A006 | Pairwise structure similarity | 化合物Pair間の構造類似度 | データ集合やCluster内の構造的な近さを評価 |
| A007 | kNN activity consistency | 近傍化合物間のEndpoint整合性 | 特徴空間で近い化合物の活性が似るかを評価 |
| A008 | Extended SALI | 特徴空間における活性Landscape | 類似化合物間の活性差からCliff、起伏、平滑さを評価 |
| A009 | Activity cliff detection | 高類似・大活性差の化合物Pair | 個別のActivity Cliff候補を抽出 |
| A010 | Cluster profile | ClusterごとのEndpoint・構成の要約 | Local分布をGlobalや他Clusterと比較する基礎情報 |
| A011 | Cluster activity enrichment | 良好活性化合物のCluster内偏在 | Favorable化合物が特定Clusterに濃縮するかを評価 |
| A012 | Cluster overlap | Cluster間のMembership重複 | 異なるClustering結果の一致・包含・重なりを評価 |
| A013 | Cluster structural diversity | Cluster内部の構造多様性 | Clusterが構造的に均質か多様かを評価 |
| A014 | Matched molecular pair analysis | 置換、Exact Core、周辺環境とEndpoint差 | 定型フローでは再利用可能なGlobal MMP Databaseを網羅構築 |

OperatorはGlobalだけでなく、十分な化合物数を持つClusterにも適用できます。数値結果は因果関係の確定ではなく、比較・反証・深掘りの起点として扱います。

## Interpretation

| ID | 名称 | 主に表すもの | 主な特徴 |
|---|---|---|---|
| I001 | SAR result interpretation | 複数Operator結果から得られる注目点 | Global／Local差、一致、矛盾、例外を横断比較し、Evidence付きInsightと次の解析候補を人間向けMarkdown／HTMLに整理 |
| I002 | Read-only MMP Global–Local interpretation | ClusteringによるTransform効果の変化 | 人間起動でGlobal DBをClusterへ投影し、分散縮小、Cluster固有效果、方向反転をDAG外で比較 |

Interpretationは新しい科学計算を直接実行せず、既存結果を比較して意味づけします。正式なscope、Insight ID、State更新はRuntimeが管理します。
