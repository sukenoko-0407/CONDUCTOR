# CONDUCTOR Skill Catalog

> 収載対象は人間管理の`included_skills.json`、実行範囲は`analysis_profile.json`を正本とする。

CONDUCTOR: `0.1.10`

## Description

| ID | 名称 | 主な役割 | Cost |
|---|---|---|---|
| D001 | RDKit 2D descriptors | Use when Claude Code needs to run RDKit 2D descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D002 | Morgan fingerprint (optional chirality) | Use when Claude Code needs to run Morgan fingerprint (optional chirality) from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D003 | MACCS keys | Use when Claude Code needs to run MACCS keys from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D004 | Hashed atom-pair fingerprint | Use when Claude Code needs to run Hashed atom-pair fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D005 | Hashed topological-torsion fingerprint | Use when Claude Code needs to run Hashed topological-torsion fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D006 | RDKit fragment counts | Use when Claude Code needs to run RDKit fragment counts from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D007 | RDKit path fingerprint | Use when Claude Code needs to run RDKit path fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D008 | RDKit pattern fingerprint | Use when Claude Code needs to run RDKit pattern fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D009 | RDKit layered fingerprint | Use when Claude Code needs to run RDKit layered fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D010 | Avalon fingerprint | Use when Claude Code needs to run Avalon fingerprint from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | low |
| D011 | Gobbi 2D pharmacophore fingerprint (optional SVD) | Use when Claude Code needs to run Gobbi 2D pharmacophore fingerprint (optional SVD) from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | medium |
| D012 | RDKit 3D descriptors | Use when Claude Code needs to run RDKit 3D descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | medium |
| D013 | USR and USRCAT | Use when Claude Code needs to run USR and USRCAT from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | medium |
| D014 | Basic 3D shape descriptors | Use when Claude Code needs to run Basic 3D shape descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | medium |
| D015 | Mordred 2D descriptors | Use when Claude Code needs to run Mordred 2D descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | medium |
| D016 | Mordred 3D descriptors | Use when Claude Code needs to run Mordred 3D descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | high |
| D019 | GFN2-xTB quantum descriptors | Use when Claude Code needs to run GFN2-xTB quantum descriptors from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | very_high |
| D020 | ChemBERTa-100M-MLM embedding | Use when Claude Code needs to run ChemBERTa-100M-MLM embedding from CSV or compatible CONDUCTOR artifacts with a self-contained Pixi environment. | high |

## Clustering

| ID | 名称 | 主な役割 | Cost |
|---|---|---|---|
| C001 | Murcko scaffold clustering | Cluster compounds from a compound-ID/SMILES CSV with Murcko scaffold clustering, without generating a hidden descriptor vector. | low |
| C002 | MCS clustering | Cluster compounds directly from SMILES by maximum common substructure as a mandatory initial CONDUCTOR axis, without generating a hidden descriptor vector or requiring per-run human approval. | high |
| C003 | BRICS fragment clustering | Cluster compounds from a compound-ID/SMILES CSV with BRICS fragment clustering, without generating a hidden descriptor vector. | medium |
| C004 | RECAP fragment clustering | Cluster compounds from a compound-ID/SMILES CSV with RECAP fragment clustering, without generating a hidden descriptor vector. | medium |
| C005 | Vector Butina clustering | Apply Vector Butina clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C006 | Vector hierarchical clustering | Apply Vector hierarchical clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C007 | Vector DBSCAN clustering | Apply Vector DBSCAN clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C008 | Vector Louvain clustering | Apply Vector Louvain clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C009 | Vector Leiden clustering | Apply Vector Leiden clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C010 | Vector connected-component clustering | Apply Vector connected-component clustering to a numeric vector artifact produced by a Description Skill; do not accept SMILES or generate descriptors internally. | medium |
| C012 | Overlap-weighted Leiden Series clustering | FF適格ClusterのJaccard重複graphをweighted LeidenでSeries化する。 | medium |

## Analysis

| ID | 名称 | 主な役割 | Cost |
|---|---|---|---|
| A001 | All-Cluster profile survey | 全ClusterのEndpoint分布とFavorable Fractionを一括計算する。 | low |
| A002 | All-Cluster enrichment survey | 全ClusterのFavorable enrichmentと単純な多重比較補正を一括計算する。 | low |
| A003 | Interpretable descriptor contrast | D001・D012・D015・D016・D019の解釈可能特徴量についてGlobalと各analysis unitの相関を一括比較する。 | low |
| A004 | Series PCA and UMAP projection panel | Global座標上へ各Seriesを重ね、PCA／UMAP画像とcontact sheetを生成する。 | medium |
| A005 | Series multi-Description feature model | 固定6 Description panelでGlobalと全SeriesのOOFモデルを一括比較する。 | high |
| A006 | Series SALI and Cliff landscape | D002 ECFP4/Tanimoto空間でGlobal、SeriesのSALIとinternal／boundary Cliffを一括評価する。 | medium |
| A007 | Series structural signature | 構造由来Clusterは登録済みKey構造を使い、vector由来ClusterだけMurcko／MCSを導出する。 | medium |
| A008 | Human-centered matched molecular pair analysis | 1-cut MMPをType-I top compound、Type-II Hit-to-Lead、Type-III databaseとして提供する。 | high |
| A009 | CONDUCTOR standard Series report | 7 Section Summary、中央配置のEndpoint図、analysis unit構造gallery、A003／A005図、MMP導線を決定論的HTMLへ描画する。 | low |

## Interpretation

| ID | 名称 | 主な役割 | Cost |
|---|---|---|---|
| I001 | Lightweight Series interpretation | 定型Summaryだけを読みGlobalとSeriesの変化を簡潔に解釈する。 | low |

## Orchestration

| ID | 名称 | 主な役割 | Cost |
|---|---|---|---|
| O001 | CONDUCTOR deterministic runtime | 固定された基本計算、定型解析、Report、Interpretation、Auditを管理する単純なRuntime。 | low |
| O004 | CONDUCTOR On-demand Analysis | Roundと通常DAGに干渉せず、人間依頼をREQ recordとしてRun内で解析・報告する。 | low |
| O005 | CONDUCTOR Main Agent Orchestrator | Main Agentを一つの人間承認RoundのOrchestratorとして有効化する。 | low |
