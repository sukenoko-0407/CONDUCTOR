# CONDUCTOR v4 Skill Catalog

> この文書は`catalog/catalog.json`から生成される。収載対象は人間管理の`catalog/included_skills.json`で指定する。

Generated: `2026-08-03T06:15:58.922183+00:00`

## Description

| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|
| D001 | `cs-compute-description-rdkit-2d` | RDKit 2D descriptors | - | physicochemical | low | stable | False |
| D002 | `cs-compute-description-morgan` | Morgan fingerprint (optional chirality) | standard, chiral (default: standard) | 2d_fingerprint | low | stable | False |
| D003 | `cs-compute-description-maccs` | MACCS keys | - | 2d_fingerprint | low | stable | False |
| D004 | `cs-compute-description-atom-pair` | Hashed atom-pair fingerprint | - | 2d_fingerprint | low | stable | False |
| D005 | `cs-compute-description-topological-torsion` | Hashed topological-torsion fingerprint | - | 2d_fingerprint | low | stable | False |
| D006 | `cs-compute-description-rdkit-fragment` | RDKit fragment counts | - | substructure | low | stable | False |
| D007 | `cs-compute-description-rdkit-path-fingerprint` | RDKit path fingerprint | - | 2d_fingerprint | low | stable | False |
| D008 | `cs-compute-description-rdkit-pattern-fingerprint` | RDKit pattern fingerprint | - | substructure | low | stable | False |
| D009 | `cs-compute-description-rdkit-layered-fingerprint` | RDKit layered fingerprint | - | 2d_fingerprint | low | stable | False |
| D010 | `cs-compute-description-avalon-fingerprint` | Avalon fingerprint | - | 2d_fingerprint | low | stable | False |
| D012 | `cs-compute-description-rdkit-3d` | RDKit 3D descriptors | - | 3d_shape | medium | stable | False |
| D013 | `cs-compute-description-usr-usrcat` | USR and USRCAT | - | 3d_shape | medium | stable | False |
| D014 | `cs-compute-description-shape` | Basic 3D shape descriptors | - | 3d_shape | medium | stable | False |
| D015 | `cs-compute-description-mordred-2d` | Mordred 2D descriptors | - | physicochemical | medium | experimental | False |
| D016 | `cs-compute-description-mordred-3d` | Mordred 3D descriptors | - | 3d_shape | high | experimental | True |
| D017 | `cs-compute-description-gobbi-pharm2d` | Gobbi 2D pharmacophore fingerprint (optional SVD) | folded, svd (default: folded) | pharmacophore | medium | stable | False |
| D019 | `cs-compute-description-pretrained-embedding` | Local pretrained molecular embedding | - | pretrained_embedding | high | experimental | True |
| D020 | `cs-compute-description-tblite-xtb` | GFN2-xTB single-point descriptors | - | quantum | very_high | experimental | True |

## Grouping

| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|
| C001 | `cs-compute-clustering-structure-murcko` | Murcko scaffold clustering | - | structure_rule | low | stable | False |
| C002 | `cs-compute-clustering-structure-mcs` | MCS clustering | - | structure_rule | high | experimental | True |
| C003 | `cs-compute-clustering-structure-brics` | BRICS fragment clustering | - | structure_rule | medium | stable | False |
| C004 | `cs-compute-clustering-structure-recap` | RECAP fragment clustering | - | structure_rule | medium | stable | False |
| C005 | `cs-compute-clustering-structure-butina` | Structure Butina clustering | - | structure_similarity | medium | stable | False |
| C006 | `cs-compute-clustering-structure-hierarchical` | Structure hierarchical clustering | - | structure_similarity | medium | stable | False |
| C007 | `cs-compute-clustering-structure-dbscan` | Structure DBSCAN clustering | - | structure_similarity | medium | stable | False |
| C008 | `cs-compute-clustering-structure-louvain` | Structure Louvain clustering | - | structure_similarity | medium | stable | False |
| C009 | `cs-compute-clustering-structure-leiden` | Structure Leiden clustering | - | structure_similarity | medium | stable | False |
| C010 | `cs-compute-clustering-structure-connected-components` | Structure connected-component clustering | - | structure_similarity | medium | stable | False |
| C011 | `cs-compute-clustering-vector-butina` | Vector Butina clustering | - | vector | medium | stable | False |
| C012 | `cs-compute-clustering-vector-hierarchical` | Vector hierarchical clustering | - | vector | medium | stable | False |
| C013 | `cs-compute-clustering-vector-dbscan` | Vector DBSCAN clustering | - | vector | medium | stable | False |
| C014 | `cs-compute-clustering-vector-louvain` | Vector Louvain clustering | - | vector | medium | stable | False |
| C015 | `cs-compute-clustering-vector-leiden` | Vector Leiden clustering | - | vector | medium | stable | False |
| C016 | `cs-compute-clustering-vector-connected-components` | Vector connected-component clustering | - | vector | medium | stable | False |
| C017 | `cs-compute-clustering-categorical` | Categorical-column clustering | - | human_context | low | stable | False |
| C018 | `cs-compute-clustering-meta-overlap` | Overlap-based meta clustering | - | meta | medium | experimental | False |

## Analysis

| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|
| A001 | `cs-analysis-group-profile` | Group profile | - | group_profile | low | stable | False |
| A002 | `cs-analysis-activity-distribution` | Activity distribution | - | property_profile | low | stable | False |
| A003 | `cs-analysis-pairwise-structure-similarity` | Pairwise structure similarity | - | feature_space | medium | stable | False |
| A004 | `cs-analysis-descriptor-activity-correlation` | Descriptor-activity correlation | - | interpretable_association | low | stable | False |
| A005 | `cs-analysis-knn-activity-consistency` | kNN activity consistency | - | feature_space | medium | stable | False |
| A006 | `cs-analysis-sali` | Structure-activity landscape index | - | landscape | medium | stable | False |
| A007 | `cs-analysis-activity-cliff` | Activity cliff detection | - | landscape | medium | stable | False |
| A008 | `cs-analysis-group-enrichment` | Group activity enrichment | - | group_profile | low | stable | False |
| A009 | `cs-analysis-group-overlap` | Group overlap | - | group_quality | low | stable | False |
| A010 | `cs-analysis-group-structural-diversity` | Group structural diversity | - | group_quality | medium | stable | False |

## Interpretation

| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|
| I001 | `cs-analysis-interpret-evidence` | SAR evidence interpretation | - | evidence_integration | low | stable | False |

## Orchestration

| ID | Skill | Capability | Variants | Family | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|
| O001 | `cs-conductor-orchestrator` | CONDUCTOR v4 Orchestrator | - | graph_orchestration | low | stable | False |
