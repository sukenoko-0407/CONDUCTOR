# CONDUCTOR 0.1.9 Capability早見表

## Description

| ID | 名称 | 主な表現 |
|---|---|---|
| D001 | RDKit 2D | 解釈可能な物性・トポロジー |
| D002 | Morgan | ECFP4相当の局所構造bit |
| D003 | MACCS | 定義済み構造key |
| D004 | Atom-pair | 原子対とtopological距離 |
| D005 | Topological torsion | 連続する原子型のtorsion pattern |
| D006 | RDKit fragment | 解釈可能な部分構造count |
| D007 | RDKit path | path-based fingerprint |
| D008 | RDKit pattern | 部分構造pattern fingerprint |
| D009 | RDKit layered | 複数layerの構造fingerprint |
| D010 | Avalon | Avalon fingerprint |
| D011 | Gobbi Pharm2D | 2D pharmacophore fingerprint |
| D012 | RDKit 3D | 軽量な3D記述子 |
| D013 | USR/USRCAT | 3D shape・pharmacophore分布 |
| D014 | Basic 3D shape | 慣性・球状性などの形状指標 |
| D015 | Mordred 2D | 広範な2D記述子 |
| D016 | Mordred 3D | 広範な3D記述子 |
| D019 | xTB | 量子化学特徴量 |
| D020 | ChemBERTa | CPUで生成するpretrained embedding |

## Clustering

| ID | 名称 | 主な特徴 |
|---|---|---|
| C001–C004 | Murcko/MCS/BRICS/RECAP | SMILESを直接扱う構造Cluster |
| C005 | Vector Butina | 距離閾値型。閾値はVector空間から校正 |
| C006 | Vector Hierarchical | average-linkage。cutoffを距離空間から校正 |
| C007 | Vector DBSCAN | 密度型。epsを近傍距離から校正 |
| C008 | Vector Louvain | weighted mutual-kNN graph |
| C009 | Vector Leiden | weighted mutual-kNN graph |
| C010 | Vector Connected components | 距離graphの連結成分 |
| C012 | weighted Leiden Series | 濃縮ClusterのJaccard重複graph |

## Analysis

| ID | 名称 | 主な特徴 |
|---|---|---|
| A001 | Cluster profile | 全ClusterのEndpoint/FF |
| A002 | Cluster enrichment | OR、Fisher p、BH q |
| A003 | Descriptor contrast | D001 Global vs Series |
| A004 | Projection panel | D002 PCA/UMAP |
| A005 | Multi-Description model | 固定6表現、OOF低容量model |
| A006 | Landscape | D002 SALI、内部/境界Cliff |
| A007 | Structural signature | 構造由来Cluster、Murcko/MCS fallback |
| A008 | MMP | Type-I/II/III、1-cut |
| A009 | Standard report | 全体・Series別HTML |

## Interpretation / Control

| ID | 名称 | 主な特徴 |
|---|---|---|
| I001 | Lightweight Interpretation | 定型Report後の短い意味抽出 |
| O001 | Runtime | State/DAG唯一のWriter |
| O004 | On-demand | Round外REQ解析 |
| O005 | Orchestrator | Main Agentの固定制御loop |
