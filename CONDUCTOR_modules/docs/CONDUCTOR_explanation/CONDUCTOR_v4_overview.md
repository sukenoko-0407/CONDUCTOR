# CONDUCTOR 全体ガイド

CONDUCTORは、化合物の構造と活性値からSAR（構造活性相関）を幅広く探索する解析システムです。単一のモデルで結論を出すのではなく、異なる表現、異なるGrouping、異なるOperatorの結果を突き合わせ、人間が見落としやすい局所傾向、例外、矛盾、Activity Cliffを発見候補として提示します。

![CONDUCTOR全体像](A1_style_set/CONDUCTOR_overview_A1_style.png)

## 解析の流れ

1. **Description** — 同じ化合物を物性、部分構造、fingerprint、3D形状など複数のVectorで表現します。
2. **Grouping** — SMILESの構造規則、Description空間、実験条件、Group間重複から、複数の局所化合物群を作ります。
3. **Operator** — 全体またはGroup内・Group間で、活性分布、相関、近傍整合性、SALI、Cliff、濃縮などを評価します。
4. **Interpretation** — 多数のEvidenceを比較し、似た結果、独立な一致、矛盾、反証候補、negative resultを整理します。
5. **Orchestration** — 進捗と探索履歴を管理し、次に試す解析branchを選びます。高コスト処理では人間へ確認します。

## 「広く始め、局所へ進む」

初手は低コストだけに限定せず、代表的な2D物性、複数のfingerprint、pharmacophore、3D形状、構造Grouping、Vector Clustering、全Operatorを一定の広さで実行します。MCSも初手に含まれます。

その結果から、次のような場所を深掘りします。

- 全体ではCliff的だが、特定Groupでは滑らかな空間
- 異なるDescriptionでも共通して現れる活性傾向
- 類似したDescriptionでは説明できない不一致
- 小規模でも構造的に強くまとまったGroup
- 有望な説明に対する反証候補

## 疎結合な構成

各Skillは入力と出力の契約を持つ独立部品です。OrchestratorはCatalogから利用可能なSkillを選び、State内のDAGで連結します。DescriptionやGroupingを追加・交換しても、他のSkillへ実装を埋め込む必要はありません。

| 管理要素 | 役割 |
|---|---|
| Catalog | 人間が利用を許可したSkillと入出力・計算コストを示す |
| State | Nodeの状態、依存関係、artifact、探索履歴を記録する |
| Policy | Orchestratorの判断原則と人間確認の境界を示す |
| Group index | Groupの由来とcompound×GroupのBoolean membershipを記録する |
| Evidence graph | Operator結果と対象Group・Descriptionの関係を記録する |

Orchestratorは粗い状態として「初手解析中」「Interpretation準備完了」「反復探索中」を把握し、必要時だけ個別Node、Group、Evidenceを詳しく読みます。見込みの薄いGroupは`discarded`にできますが、監査履歴は削除しません。

## 一般利用とCONDUCTOR利用

- **一般利用**: 個別Skillを単独で呼び出し、主にCSVなど通常の解析結果を得ます。`--conductor`は付けません。
- **CONDUCTOR利用**: Orchestratorが明示的に`--conductor`を付け、主結果に加えてmanifest、warning、execution event、Evidenceなどの機械可読artifactを生成します。

## 人間が担うこと

- compound IDとSMILESの正しさ、分子標準化
- endpointと`higher_is_better`の指定
- 並列数とInterpretation探索budgetの指定
- 高コスト解析の承認
- 発見候補の科学的・実験的な最終判断

## 関連資料

- [Description機能](CONDUCTOR_v4_description_features.md)
- [Clustering機能](CONDUCTOR_v4_clustering_features.md)
- [Operator機能](CONDUCTOR_v4_operator_features.md)
- [Description間の関係性とカバー範囲](CONDUCTOR_v4_description_relationships_and_coverage.md)
