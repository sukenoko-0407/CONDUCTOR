# CONDUCTOR_v2 Phase1 出力ガイド

このドキュメントでは、`cs-conductor-analysis-sal` が生成するファイルを簡潔に説明します。

デフォルトの出力ディレクトリ:

```text
analysis/<input_csv_stem>/structure_activity_landscape/
```

## 推奨確認順

1. `figures/primary_representation_comparison.png`
2. `sal_representation_summary.csv`
3. `figures/local_variance_vs_local_property.png`
4. `figures/sali_distribution_by_representation.png`
5. `sal_warnings.json`

最初の比較には、raw `median_sali` ではなく `primary_comparison_rank` を使用してください。

## CSVおよびJSON出力

### `sal_representation_summary.csv`

descriptor representationごとに1行を持つ、メインの要約テーブルです。

重要な列:

- `primary_comparison_rank`: representationの総合rank。小さいほど良好です。
- `primary_comparison_rank_score`: 主要なkNN property consistency metricsにおけるrankの平均値。小さいほど良好です。
- `median_abs_delta_property_among_knn`: 各化合物とその最近傍化合物群とのproperty差の中央値。小さいほど良好です。
- `median_local_property_variance`: 各化合物周辺のlocal property varianceの中央値。小さいほど良好です。
- `neighbor_property_autocorrelation`: 各化合物のpropertyと近傍化合物のpropertyの相関。大きいほど良好です。
- `median_normalized_sali`: 距離percentileで正規化したSALI。補助的な診断指標です。
- `median_sali`: raw SALI。同一representation内での確認を主目的とし、representation間の第一比較には使いません。

### `sal_knn_edges.csv`

directed kNN edgeごとに1行を持つテーブルです。

個別の化合物と近傍化合物の関係を確認するときに使用します。

重要な列:

- `compound_id`: 起点となる化合物。
- `neighbor_compound_id`: 最近傍化合物。
- `neighbor_rank`: 起点化合物に対する近傍順位。
- `distance`: representation固有のraw距離。
- `distance_percentile_within_representation`: 同一representation内におけるedge距離のpercentile rank。
- `abs_delta_property`: 2化合物間のproperty差の絶対値。
- `sali`: raw SALI。
- `normalized_sali`: 距離percentileで正規化したSALI。

### `sal_local_metrics.csv`

化合物ごと、representationごとに1行を持つテーブルです。

各化合物の局所近傍が平坦か、またはruggedかを確認するときに使用します。

重要な列:

- `local_mean_property`: 局所近傍のproperty平均値。
- `local_median_property`: 局所近傍のproperty中央値。
- `local_property_variance`: 局所近傍におけるproperty値の分散。
- `median_abs_delta_property_among_knn`: その化合物とk個の最近傍化合物とのproperty差の中央値。
- `max_abs_delta_property_among_knn`: 最近傍化合物とのproperty差の最大値。

### `sal_sali_distribution.csv`

representationごとに、raw SALIとnormalized SALIの分布統計量をまとめたテーブルです。

SALI診断に使用します。raw SALI単独をrepresentation rankingの第一基準として使わないでください。

重要な列:

- `median`, `p90`, `p95`, `p99`: raw SALIの分布統計量。
- `normalized_median`, `normalized_p90`, `normalized_p95`, `normalized_p99`: normalized SALIの分布統計量。

### `sal_metric_ranking.csv`

各metricごとのrankingをlong formatでまとめたテーブルです。

あるrepresentationのrankが高い、または低い理由を確認するときに使用します。

重要な列:

- `metric_name`: ranking対象のmetric。
- `direction`: 低い値と高い値のどちらが良好か。
- `representation_id`: descriptor representation。
- `metric_value`: 実際の値。
- `rank`: そのmetric内でのrank。

### `sal_manifest.json`

実行メタデータです。

何を解析したかを確認するときに使用します。

含まれる内容:

- input CSV path
- descriptor directory
- output directory
- ID columnおよびproperty column
- kNN `k`
- 処理されたdescriptor fileとskipされたdescriptor file
- primary comparison basis
- output file list

### `sal_warnings.json`

実行時の警告です。

結果を解釈する前に、このファイルを確認してください。warningsが空であれば、検出された実行上の問題はありません。

想定される警告例:

- descriptor fileがskipされた
- descriptor IDがinput IDと完全には一致しなかった
- non-numeric property rowが除外された
- 図の生成に失敗した

## 図出力

### `figures/primary_representation_comparison.png`

descriptor representationを比較するためのメイン図です。

距離スケールに依存しにくいkNN property consistencyに基づいてrepresentationをrank付けします:

- median absolute property delta among kNN
- median local property variance
- neighbor property autocorrelation

scoreは小さいほど良好です。

### `figures/local_variance_vs_local_property.png`

property範囲全体にわたるlocal property ruggednessの散布図です。

軸:

- x: local median property
- y: local property variance

ruggednessが高活性域・中間域・低活性域のどこに出やすいかを確認するために使用します。

### `figures/auxiliary_metric_summary.png`

補助指標をコンパクトにまとめた図です。

主要指標と補助指標を横並びで比較するために使用します。

### `figures/sali_distribution_by_representation.png`

representationごとのnormalized SALI分布です。

cliff診断として使用します。上側tailが高い場合、近い化合物間で大きなproperty jumpが存在する可能性があります。

### `figures/sali_ranking.png`

medianおよびp90 normalized SALIによるrankingです。

第一のrepresentation比較ではなく、補助的な診断として使用します。

### `figures/distance_vs_abs_delta_property.png`

neighbor distanceとabsolute property differenceの散布図です。

距離が大きくなるほどproperty差も大きくなる傾向があるかを確認するために使用します。平坦なrepresentationでは、非常に短い距離で大きなproperty jumpが大量に発生する状況は避けられるべきです。

## 解釈上の注意

raw distanceはrepresentation metric間で直接比較できません。例えば、Tanimoto、cosine、standardized Euclideanでは、距離の意味と分布が異なります。

したがって:

- first-passのrepresentation比較には `primary_comparison_rank` を使用する
- raw `sali` は主に同一representation内で使用する
- `normalized_sali` は補助的なcliff診断として使用する
- 結論を出す前に必ず `sal_warnings.json` を確認する
