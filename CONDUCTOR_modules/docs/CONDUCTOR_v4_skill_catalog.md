# CONDUCTOR 4.3.1 Skill Catalog

> この文書は`CONDUCTOR_modules/catalog/catalog.json`から生成される。収載対象は人間管理の`CONDUCTOR_modules/catalog/included_skills.json`、解析profileは`CONDUCTOR_modules/catalog/analysis_profile.json`で指定する。移行専用maintenance Skillは科学Catalogへ収載しない。

Profile: `comprehensive-multiround-v1`
Generated: `2026-08-08T03:59:13.092255+00:00`

## Description

| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D001 | `cs-compute-description-rdkit-2d` | RDKit 2D descriptors | - | physicochemical | - | csv_or_smiles | dense_continuous | euclidean | low | stable | False |
| D002 | `cs-compute-description-morgan` | Morgan fingerprint (optional chirality) | standard, chiral (default: standard) | 2d_fingerprint | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D003 | `cs-compute-description-maccs` | MACCS keys | - | 2d_fingerprint | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D004 | `cs-compute-description-atom-pair` | Hashed atom-pair fingerprint | - | 2d_fingerprint | - | csv_or_smiles | sparse_count | cosine | low | stable | False |
| D005 | `cs-compute-description-topological-torsion` | Hashed topological-torsion fingerprint | - | 2d_fingerprint | - | csv_or_smiles | sparse_count | cosine | low | stable | False |
| D006 | `cs-compute-description-rdkit-fragment` | RDKit fragment counts | - | substructure | - | csv_or_smiles | sparse_count | cosine | low | stable | False |
| D007 | `cs-compute-description-rdkit-path-fingerprint` | RDKit path fingerprint | - | 2d_fingerprint | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D008 | `cs-compute-description-rdkit-pattern-fingerprint` | RDKit pattern fingerprint | - | substructure | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D009 | `cs-compute-description-rdkit-layered-fingerprint` | RDKit layered fingerprint | - | 2d_fingerprint | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D010 | `cs-compute-description-avalon-fingerprint` | Avalon fingerprint | - | 2d_fingerprint | - | csv_or_smiles | binary_fingerprint | tanimoto | low | stable | False |
| D012 | `cs-compute-description-rdkit-3d` | RDKit 3D descriptors | - | 3d_shape | - | csv_or_smiles | dense_continuous | euclidean | medium | stable | False |
| D013 | `cs-compute-description-usr-usrcat` | USR and USRCAT | - | 3d_shape | - | csv_or_smiles | dense_shape_moment | manhattan | medium | stable | False |
| D014 | `cs-compute-description-shape` | Basic 3D shape descriptors | - | 3d_shape | - | csv_or_smiles | dense_continuous | euclidean | medium | stable | False |
| D015 | `cs-compute-description-mordred-2d` | Mordred 2D descriptors | - | physicochemical | - | csv_or_smiles | dense_continuous | euclidean | medium | experimental | False |
| D016 | `cs-compute-description-mordred-3d` | Mordred 3D descriptors | - | 3d_shape | - | csv_or_smiles | dense_continuous | euclidean | high | experimental | True |
| D017 | `cs-compute-description-gobbi-pharm2d` | Gobbi 2D pharmacophore fingerprint (optional SVD) | folded, svd (default: folded) | pharmacophore | - | csv_or_smiles | binary_fingerprint | tanimoto | medium | stable | False |
| D019 | `cs-compute-description-pretrained-embedding` | Local pretrained molecular embedding | - | pretrained_embedding | - | csv_or_smiles | dense_embedding | cosine | high | experimental | True |
| D020 | `cs-compute-description-tblite-xtb` | GFN2-xTB single-point descriptors | - | quantum | - | csv_or_smiles | dense_continuous | euclidean | very_high | experimental | True |

## Grouping

| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C001 | `cs-compute-clustering-structure-murcko` | Murcko scaffold clustering | - | direct_structure | direct_structure | compound_id_smiles_csv | - | - | low | stable | False |
| C002 | `cs-compute-clustering-structure-mcs` | MCS clustering | - | direct_structure | direct_structure | compound_id_smiles_csv | - | - | high | experimental | False |
| C003 | `cs-compute-clustering-structure-brics` | BRICS fragment clustering | - | direct_structure | direct_structure | compound_id_smiles_csv | - | - | medium | stable | False |
| C004 | `cs-compute-clustering-structure-recap` | RECAP fragment clustering | - | direct_structure | direct_structure | compound_id_smiles_csv | - | - | medium | stable | False |
| C005 | `cs-compute-clustering-vector-butina` | Vector Butina clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C006 | `cs-compute-clustering-vector-hierarchical` | Vector hierarchical clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C007 | `cs-compute-clustering-vector-dbscan` | Vector DBSCAN clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C008 | `cs-compute-clustering-vector-louvain` | Vector Louvain clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C009 | `cs-compute-clustering-vector-leiden` | Vector Leiden clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C010 | `cs-compute-clustering-vector-connected-components` | Vector connected-component clustering | - | description_vector | description_vector | description_vector_csv | - | - | medium | stable | False |
| C011 | `cs-compute-clustering-categorical` | Categorical-column clustering | - | human_context | categorical | categorical_csv | - | - | low | stable | False |
| C012 | `cs-compute-clustering-meta-overlap` | Overlap-based meta clustering | - | meta | meta | group_membership_csv | - | - | medium | experimental | False |

## Analysis

| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A001 | `cs-analysis-group-profile` | Group profile | - | group_profile | - | endpoint_csv, grouping | - | - | low | stable | False |
| A002 | `cs-analysis-activity-distribution` | Activity distribution | - | property_profile | - | endpoint_csv | - | - | low | stable | False |
| A003 | `cs-analysis-pairwise-structure-similarity` | Pairwise structure similarity | - | feature_space | - | endpoint_csv | - | - | medium | stable | False |
| A004 | `cs-analysis-descriptor-activity-correlation` | Descriptor-activity correlation | - | interpretable_association | - | endpoint_csv, description | - | - | low | stable | False |
| A005 | `cs-analysis-knn-activity-consistency` | kNN activity consistency | - | feature_space | - | endpoint_csv, description | - | - | medium | stable | False |
| A006 | `cs-analysis-sali` | Extended structure-activity landscape index | - | landscape | - | endpoint_csv, description | - | - | medium | stable | False |
| A007 | `cs-analysis-activity-cliff` | Activity cliff detection | - | landscape | - | endpoint_csv | - | - | medium | stable | False |
| A008 | `cs-analysis-group-enrichment` | Group activity enrichment | - | group_profile | - | endpoint_csv, grouping | - | - | low | stable | False |
| A009 | `cs-analysis-group-overlap` | Group overlap | - | group_quality | - | endpoint_csv, grouping | - | - | low | stable | False |
| A010 | `cs-analysis-group-structural-diversity` | Group structural diversity | - | group_quality | - | endpoint_csv, grouping | - | - | medium | stable | False |

## Interpretation

| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| I001 | `cs-analysis-interpret-evidence` | SAR evidence interpretation | - | evidence_integration | - | evidence_json, optional_state_json_read_only, interpretation_policy_markdown, conductor_interpretation_id_reservation | - | - | low | stable | False |

## Orchestration

| ID | Skill | Capability | Variants | Family | Grouping kind | Input | Value semantics | Natural metric | Cost | Status | Human approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| O001 | `cs-conductor-runtime` | CONDUCTOR deterministic runtime | - | graph_orchestration | - | catalog_json, analysis_profile_json, policy_markdown, interpretation_policy_markdown, endpoint_csv, round_request | - | - | low | stable | False |
| O002 | `cs-conductor-state-report` | CONDUCTOR State DAG report | - | state_reporting | - | explicit_state_json_read_only | - | - | low | stable | False |
| O003 | `cs-conductor-run-audit` | CONDUCTOR Run Audit | - | run_audit | - | explicit_state_json | - | - | low | stable | False |
