# CONDUCTOR Clustering機能ガイド

CONDUCTORでは、解析対象となる局所化合物群を作る処理をGroupingと呼びます。一般利用時の処理名はClusteringです。Groupは排他的である必要はなく、一つの化合物が複数Groupへ所属できます。

![Clustering機能の概念図](A1_style_set/CONDUCTOR_clustering_A1_style.png)

## 二つの中心的な入口

1. **Direct structure** — SMILESを直接読み、scaffold、MCS、fragmentで分類します。
2. **Description vector** — 別のDescription Skillが生成したVectorを入力し、その空間内で分類します。

この二つは入力も意味も異なるため、別のSkillとして明確に分離されています。

## 機能一覧

| ID | Clustering | 入力 | 役割・特徴 |
|---|---|---|---|
| C001 | Murcko scaffold | SMILES | 中心骨格が同じ化合物をまとめる |
| C002 | MCS | SMILES | 共通部分構造を核に重複可能なGroupを作る。初手必須 |
| C003 | BRICS | SMILES | 合成上意味のある切断規則からfragment Groupを作る |
| C004 | RECAP | SMILES | 反応規則に基づくfragment Groupを作る |
| C005 | Vector Butina | Description CSV | 類似度閾値に基づく代表中心型partition |
| C006 | Hierarchical | Description CSV | 距離の階層構造を切ってGroup化する |
| C007 | DBSCAN | Description CSV | 密度の高い領域を抽出し、noiseを許容する |
| C008 | Louvain | Description CSV | 近傍graphのcommunityを検出する |
| C009 | Leiden | Description CSV | 安定性を重視したgraph community検出 |
| C010 | Connected components | Description CSV | 類似度graphの連結成分をGroupとする |
| C011 | Categorical | Category CSV | assay条件など人間由来のカテゴリで分ける |
| C012 | Meta-overlap | Group membership | Group同士の重複関係から上位Groupを作る |

## MCSの位置づけ

MCSは構造Groupingの中心的手法です。複数のparameter設定により異なる共通構造Groupを形成でき、重複所属を保持します。pair数が上限を超える場合は、先頭からではなくseed付き一様ランダム非復元抽出を行います。

- 最小Group size: 既定3
- pair上限: 最大1000
- 生成Group上限: 既定300
- 初手実行: 必須、事前承認不要

## Vector ClusteringのMetric

ClusteringのMetricはalgorithm名ではなく入力Descriptionの性質から決定します。

- binary fingerprint: Tanimotoのみ
- USR / USRCAT: Manhattan
- embedding、SVD、疎なcount: Cosine
- dense continuous descriptor: 標準化Euclidean

## Group管理

各Groupには一意なGroup IDが付与されます。由来は`group_registry.csv`、所属はcompoundを行、Group IDを列とするBoolean CSVに集約されます。Groupを探索対象から外す場合も削除せず`discarded`として履歴を残します。

Group数、全体に占める割合、構造類似性、活性傾向を見ながらOperatorの局所scopeを選択します。大きすぎるGroupだけを優先せず、小規模でも構造的にまとまり、人間の解釈へ接続しやすいGroupを候補に残します。
