# Similarity Clustering Revision Plan

## 1. Purpose

This document defines the revision plan for similarity-based grouping in the `grouping` Skill.

The current implementation builds a Tanimoto threshold graph and assigns groups by connected components. This is too coarse for SAR grouping because long chains of pairwise-similar compounds can merge chemically distant compounds into one large group.

The revised implementation should support multiple clustering methods, record diagnostics, and keep Similarity grouping as a secondary/reference grouping method behind MCS. Tanimoto thresholds must be configurable and method-specific, not hard-coded. Some graph community methods, especially Leiden, should support weighted graphs without a fixed similarity cutoff.

## 2. Current Problem

Current method:

```text
Morgan fingerprint
-> pairwise Tanimoto similarity
-> edge if similarity >= threshold
-> connected component = group
```

Main failure mode:

```text
A -- B -- C -- D -- E
```

Even when A and E are not similar, they are assigned to the same group if a path exists. In dense chemical datasets this can create giant components.

Conclusion:

```text
connected_components should not be the default Similarity grouping method.
```

It can remain available as a diagnostic or legacy option. Fixed-threshold graph construction should not be assumed for every method.

## 2.1 Threshold Policy

Tanimoto threshold handling must be method-specific.

```text
Butina: uses distance cutoff = 1 - similarity_threshold
Hierarchical: may use distance_threshold = 1 - similarity_threshold
DBSCAN: uses eps = 1 - similarity_threshold
Connected components: uses threshold graph
Louvain: may use threshold graph, top-k graph, or full weighted graph
Leiden: should prefer weighted graph without fixed threshold
```

For Leiden, Tanimoto should be the edge weight. A fixed Tanimoto cutoff is not required. To control graph density, use one of:

```text
full_weighted_graph
top_k_weighted_graph
mutual_top_k_weighted_graph
minimum_weight_floor only as an optional computational guard
```

Default recommendation for Leiden:

```json
{
  "graph_mode": "top_k_weighted_graph",
  "top_k_neighbors": 20,
  "use_similarity_threshold": false
}
```

This keeps the graph computationally manageable without turning the Tanimoto value into a hard chemical cutoff.

## 3. Feasibility Assessment

### 3.1 Butina Clustering

Status:

```text
Highly feasible
```

Dependencies:

```text
RDKit only
```

Method:

```text
Morgan fingerprints
Tanimoto distance = 1 - similarity
RDKit Butina clustering
distance cutoff = 1 - similarity_threshold
```

Strengths:

- Standard cheminformatics clustering method.
- Already available through RDKit.
- Avoids the giant connected-component problem better than plain graph components.
- Produces cluster centers naturally.
- Deterministic if input order is deterministic.

Limitations:

- Hard clustering: each compound belongs to one cluster.
- Still threshold-dependent.
- Cluster quality can vary with fingerprint and cutoff.

Recommendation:

```text
Implement first and make it the default Similarity grouping method.
```

### 3.2 Hierarchical Agglomerative Clustering

Status:

```text
Feasible for small to medium datasets
```

Dependencies:

```text
scikit-learn
```

Method:

```text
Pairwise Tanimoto distance matrix
AgglomerativeClustering with precomputed distance
distance_threshold = 1 - similarity_threshold
linkage = average
```

Strengths:

- Easy to explain.
- More controlled than connected components.
- Average linkage reduces chain-merging relative to single linkage.
- Useful diagnostic comparison against Butina.

Limitations:

- Requires dense distance matrix.
- Memory cost is O(N^2).
- Not ideal for large datasets.

Recommendation:

```text
Implement as optional method with max_compounds guard.
```

Default guard:

```json
{
  "max_hierarchical_compounds": 3000
}
```

### 3.3 DBSCAN on Tanimoto Distance

Status:

```text
Feasible
```

Dependencies:

```text
scikit-learn
```

Method:

```text
Pairwise Tanimoto distance matrix
DBSCAN(metric="precomputed")
eps = 1 - similarity_threshold
min_samples = configured value
```

Strengths:

- Can identify noise/outliers.
- Does not require specifying number of clusters.
- Can handle irregular cluster shapes.

Limitations:

- Parameter-sensitive.
- Also requires O(N^2) distance matrix.
- Some compounds may be noise and receive no Similarity group.

Recommendation:

```text
Implement as optional method after Butina.
```

### 3.4 Louvain Community Detection

Status:

```text
Feasible if NetworkX louvain_communities is available
```

Dependencies:

```text
networkx
```

Method:

```text
Build weighted Tanimoto graph
Run Louvain community detection
Each community = group
```

Strengths:

- Handles complex similarity networks better than connected components.
- Can split giant components into communities.
- Uses edge weights.

Limitations:

- More graph-theoretic and less standard for medicinal chemistry grouping.
- Resolution parameter affects results.
- Requires care for determinism.

Recommendation:

```text
Implement as optional exploratory method if NetworkX supports it.
```

### 3.5 Leiden Community Detection

Status:

```text
Feasible and selected as a first-class supported method
```

Dependencies:

```text
igraph / leidenalg or similar extra packages
```

Strengths:

- Strong community detection method.
- Often more stable and better partitioned than Louvain.
- Attractive when threshold graphs contain large, complex connected components.
- Resolution parameter can control granularity.

Limitations:

- Requires dependencies beyond the original core stack.
- Results depend on graph construction, threshold, edge weights, and resolution.
- Less standard than Butina for medicinal chemistry fingerprint clustering, so it should remain supplementary.

Environment check:

```text
Installed successfully in the project uv environment:
igraph==1.0.0
leidenalg==0.12.0
```

Recommendation:

```text
Implement as a formal supported Similarity clustering method.
Use Tanimoto as edge weight.
Do not require a fixed Tanimoto threshold for Leiden.
```

### 3.6 Spectral Clustering

Status:

```text
Technically feasible but not recommended initially
```

Dependencies:

```text
scikit-learn
```

Reason:

- Requires choosing number of clusters or additional heuristics.
- Less transparent for downstream SAR interpretation.

Recommendation:

```text
Defer.
```

## 4. Proposed Implementation Scope

Implement these methods:

```text
1. butina
2. hierarchical
3. dbscan
4. louvain
5. leiden
6. connected_components legacy fallback
```

Default:

```text
butina
```

Recommended multi-method default for richer diagnostics:

```text
butina + leiden
```

Allowed config:

```json
{
  "similarity_group_builder": {
    "enabled": true,
    "fingerprint": "morgan",
    "radius": 2,
    "n_bits": 2048,
    "method": "butina",
    "methods": ["butina"],
    "similarity_thresholds": {
      "butina": 0.7,
      "hierarchical": 0.7,
      "dbscan": 0.7,
      "connected_components": 0.7
    },
    "graph_construction": {
      "louvain": {
        "graph_mode": "top_k_weighted_graph",
        "top_k_neighbors": 20,
        "use_similarity_threshold": false
      },
      "leiden": {
        "graph_mode": "top_k_weighted_graph",
        "top_k_neighbors": 20,
        "use_similarity_threshold": false
      }
    },
    "min_cluster_size": 2,
    "write_similarity_diagnostics": true
  }
}
```

For multi-method mode:

```json
{
  "similarity_group_builder": {
    "methods": ["butina", "leiden", "hierarchical", "dbscan", "louvain"]
  }
}
```

Each method should produce separate group IDs:

```text
GRP_SIM_BUT_001
GRP_SIM_HCL_001
GRP_SIM_DBS_001
GRP_SIM_LOU_001
GRP_SIM_LEI_001
GRP_SIM_CC_001
```

If current schema pattern does not allow these IDs, either adjust the schema or use:

```text
GRP_SIM_001
```

with method stored in `definition.method`. The first implementation should prefer schema compatibility unless group ID readability is more important.

## 5. Method Details

### 5.1 Butina

Implementation:

```text
RDKit DataStructs.BulkTanimotoSimilarity
RDKit ML.Cluster.Butina.ClusterData
```

Definition fields:

```json
{
  "method": "butina_clustering",
  "fingerprint": "morgan",
  "radius": 2,
  "n_bits": 2048,
  "similarity_threshold": 0.7,
  "distance_cutoff": 0.3,
  "cluster_center_compound_id": "Cpd001",
  "cluster_member_count": 12
}
```

### 5.2 Hierarchical

Implementation:

```text
Build dense pairwise Tanimoto distance matrix
AgglomerativeClustering(metric="precomputed", linkage="average", distance_threshold=cutoff, n_clusters=None)
```

Definition fields:

```json
{
  "method": "hierarchical_agglomerative",
  "linkage": "average",
  "distance_threshold": 0.3,
  "cluster_member_count": 12
}
```

### 5.3 DBSCAN

Implementation:

```text
Build dense pairwise Tanimoto distance matrix
DBSCAN(metric="precomputed", eps=cutoff, min_samples=min_samples)
```

Definition fields:

```json
{
  "method": "dbscan",
  "eps": 0.3,
  "min_samples": 3,
  "noise_compound_count": 18,
  "cluster_member_count": 12
}
```

### 5.4 Louvain

Implementation:

```text
Build weighted graph with edges similarity >= threshold
networkx.community.louvain_communities(graph, weight="weight", seed=random_seed, resolution=resolution)
```

Definition fields:

```json
{
  "method": "louvain_community",
  "similarity_threshold": 0.7,
  "resolution": 1.0,
  "edge_count": 1234,
  "cluster_member_count": 12
}
```

### 5.5 Leiden

Implementation:

```text
Build weighted similarity graph
Convert to igraph.Graph
Run leidenalg.find_partition
Use edge weights where supported
Each partition = group
```

Recommended parameters:

```json
{
  "leiden_resolution": 1.0,
  "leiden_partition_type": "RBConfigurationVertexPartition",
  "graph_mode": "top_k_weighted_graph",
  "top_k_neighbors": 20,
  "use_similarity_threshold": false,
  "random_seed": 42
}
```

Definition fields:

```json
{
  "method": "leiden_community",
  "graph_mode": "top_k_weighted_graph",
  "top_k_neighbors": 20,
  "uses_similarity_threshold": false,
  "resolution": 1.0,
  "partition_type": "RBConfigurationVertexPartition",
  "edge_count": 1234,
  "cluster_member_count": 12
}
```

Fallback behavior:

```text
Because Leiden is a formal supported method, missing igraph or leidenalg should be treated as an environment setup problem when Leiden is requested.
If Leiden is not requested, no error is needed.
```

### 5.6 Connected Components

Keep as:

```text
legacy_threshold_connected_components
```

Use only when explicitly requested.

## 6. Output Artifacts

Add:

```text
similarity_cluster_membership.csv
similarity_cluster_summary.csv
similarity_pair_summary.json
similarity_graph_summary.json
figures/similarity_cluster_size_distribution.png
figures/similarity_method_comparison.png
```

### 6.1 similarity_cluster_membership.csv

Recommended columns:

```text
method
cluster_id
group_id
compound_id
is_center
similarity_to_center
membership_reason
```

### 6.2 similarity_cluster_summary.csv

Recommended columns:

```text
method
cluster_id
group_id
cluster_size
center_compound_id
min_similarity_to_center
median_similarity_to_center
mean_similarity_to_center
max_similarity_to_center
edge_count
```

### 6.3 similarity_pair_summary.json

Recommended fields:

```json
{
  "compound_count": 100,
  "pair_count": 4950,
  "similarity_threshold": 0.7,
  "edge_count_at_threshold": 123,
  "fingerprint": "morgan",
  "radius": 2,
  "n_bits": 2048
}
```

### 6.4 similarity_graph_summary.json

Recommended fields:

```json
{
  "method": "leiden",
  "graph_mode": "top_k_weighted_graph",
  "uses_similarity_threshold": false,
  "top_k_neighbors": 20,
  "node_count": 100,
  "edge_count": 1850,
  "min_edge_weight": 0.21,
  "median_edge_weight": 0.48,
  "max_edge_weight": 1.0
}
```

## 7. Diagnostics and Figures

### 7.1 Cluster Size Distribution

File:

```text
figures/similarity_cluster_size_distribution.png
```

Content:

```text
x-axis: cluster size
y-axis: number of clusters
series: method
```

### 7.2 Method Comparison

File:

```text
figures/similarity_method_comparison.png
```

Content:

```text
x-axis: method
y-axis: cluster count / assigned compound count / noise count
```

### 7.3 Threshold / Graph Construction Sensitivity

Optional:

```text
figures/similarity_threshold_sensitivity.png
figures/similarity_graph_construction_sensitivity.png
```

Evaluate thresholds:

```text
0.5, 0.6, 0.7, 0.8, 0.9
```

For Leiden/Louvain weighted graph modes, evaluate graph construction rather than only fixed thresholds:

```text
graph_mode: full_weighted_graph, top_k_weighted_graph, mutual_top_k_weighted_graph
top_k_neighbors: 5, 10, 20, 30, 50
resolution: 0.5, 1.0, 1.5, 2.0
```

## 8. Interaction with Final Grouping

Similarity groups remain supplementary.

Priority:

```text
MCS > Human CSV grouping > Murcko reference > Similarity > Meta
```

Similarity should not overwrite MCS definitions. It should add additional group rows to:

```text
group_registry.json
group_membership.csv
group_relations.json
selected_groups.json
```

When multiple similarity methods are enabled, the same compound may belong to multiple similarity groups from different methods. This is acceptable and should be recorded in long format membership.

## 9. Performance Considerations

Pairwise similarity is O(N^2).

For the planned 100-compound test:

```text
100 * 99 / 2 = 4,950 pairs
```

This is small and should be fast.

For larger datasets:

- Butina is preferred.
- Hierarchical and DBSCAN should have `max_compounds` guards.
- Louvain can operate on sparse threshold, top-k, or weighted graph.
- Leiden should use weighted graph construction and avoid fixed threshold by default.
- In this project uv environment, Leiden dependencies are installable and have been smoke-tested.

Proposed guards:

```json
{
  "max_hierarchical_compounds": 3000,
  "max_dbscan_compounds": 3000,
  "max_louvain_compounds": 10000
}
```

## 10. Acceptance Criteria

Implementation is acceptable when:

1. Butina clustering is implemented and becomes default.
2. Connected components is no longer the default.
3. Hierarchical clustering is available when dataset size is under guard.
4. DBSCAN is available when dataset size is under guard.
5. Louvain is available when NetworkX supports it.
6. Leiden is implemented as a formal supported method using `igraph` and `leidenalg`.
7. Tanimoto threshold is method-specific and configurable where used.
8. Leiden does not require a fixed Tanimoto threshold and can use Tanimoto as edge weight.
9. Each method records cluster definitions in `group_registry.json`.
10. Each method records membership in `group_membership.csv`.
11. Diagnostics are written to `similarity_cluster_membership.csv` and `similarity_cluster_summary.csv`.
12. Figures are generated when `matplotlib` is installed.
13. Multi-method mode works and keeps method labels clear.
14. The 100-compound post-revision test completes successfully and records runtime.

## 11. Post-Revision Test Plan

After implementation, run the previously requested test:

```text
sample size around 100 compounds
```

Test goals:

1. Confirm the full Grouping pipeline runs.
2. Confirm MCS mining runs on the sampled set.
3. Confirm Similarity clustering runs with the revised methods.
4. Confirm outputs are generated as intended.
5. Measure total runtime.

Preferred input:

```text
Use a real public compound set if convenient.
Fallback: generate a chemically plausible synthetic set from scaffold/R-group combinations.
```

Runtime report should include:

```text
input compound count
valid compound count
MCS sample count
MCS pair count
Similarity pair count
Similarity methods enabled
number of groups by source
key output files generated
total elapsed time
```
