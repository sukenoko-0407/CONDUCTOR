# CONDUCTOR Operator機能ガイド

Operatorは、Description空間、構造、活性値、Group membershipを使ってEvidenceを作る解析単位です。全化合物だけでなく、Group内、二Group間、明示的に切り出したcompound集合にも適用できます。

![Operator機能の概念図](A1_style_set/CONDUCTOR_operator_A1_style.png)

## 機能一覧

| ID | Operator | 主な問い | 主な出力 |
|---|---|---|---|
| A001 | Group profile | 各Groupの活性水準とばらつきはどう違うか | 件数、平均、中央値、分位点 |
| A002 | Activity distribution | endpoint全体はどのような分布か | 分布統計、欠損、外れ値候補 |
| A003 | Pairwise structure similarity | 全体・局所の構造類似性は高いか | Tanimoto分布、上位pair |
| A004 | Descriptor–activity correlation | 解釈可能な特徴量と活性は関連するか | 相関係数、順位、符号 |
| A005 | kNN activity consistency | 近傍化合物は似た活性を持つか | 近傍活性差、近傍整合性 |
| A006 | Extended SALI | 空間の活性Landscapeは平滑かCliff的か | SALI分布、upper tail、focus pair |
| A007 | Activity cliff detection | 高構造類似・大活性差のpairはどこか | Cliff候補、密度、score |
| A008 | Group enrichment | 高活性化合物は特定Groupに濃縮するか | enrichment、odds ratio、検定値 |
| A009 | Group overlap | Group同士はどの程度重なるか | intersection、union、Jaccard |
| A010 | Group structural diversity | Group内部は構造的にまとまっているか | 平均類似度、多様性score |

## 全体と局所の比較

同じOperatorを異なるscopeで実行すると、Groupingによって解釈がどう変わるかを確認できます。

例として、Morgan空間の全体SALIが高くても、別のDescriptionで作った複数Group内ではSALIが低い場合があります。これは「全体はCliff的だが、局所領域ごとには滑らか」という有力な発見候補です。

## SALIの読み方

- 大きいSALI: 近いVector間で活性差が大きく、局所Cliffの可能性があります。
- 小さいSALI: その表現空間では活性Landscapeが比較的平滑で、propertyをよく配置できている可能性があります。
- raw値はendpoint scaleとMetricに依存するため、異なるMetric間で単純比較しません。
- median、p75、p90、p95、上位pair、近傍活性相関を併せて見ます。

## Operatorの組合せ

- A001、A008でGroupの活性上の意味を確認する
- A009、A010でGroupの重複と構造的まとまりを確認する
- A004で解釈可能な連続傾向を探す
- A005、A006、A007で近傍整合性、Landscape、Cliffを別角度から見る
- A002、A003を全体の基準として局所結果と比較する

## EvidenceからInterpretationへ

Operatorは結論ではなくEvidenceを出力します。Interpretationは次を区別します。

- 類似Descriptionに由来する当然の一致
- 独立性の高いDescription間での一致
- 全体と局所の反転
- Group間の矛盾や例外
- 発見候補に対する反証
- 有意な傾向が見つからなかったnegative result

発見候補が多い場合は削除せず、Orchestratorが追加のDescription–Grouping–Operator branchを作り、識別力や再現性を比較します。
