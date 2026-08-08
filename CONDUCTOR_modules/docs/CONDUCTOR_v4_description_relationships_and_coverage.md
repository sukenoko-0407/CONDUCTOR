# CONDUCTOR 4.3.1 Description間の関係性とカバー範囲

作成日: 2026-08-03  
対象: CONDUCTOR 4.3.1 target Catalogに収載されたDescription Skill 18件

## 1. 要約

現在のDescription群は、Ligand-only SARで一般的に利用する古典的な2D表現を非常に広くカバーしている。一方、18 Skillが18個の独立した情報源を意味するわけではない。厳密な部分集合、同じ原情報の変換、近いfingerprint familyを整理すると、主要な情報軸は概ね次の9系統と考えられる。

1. 2D物性・topological scalar
2. circular/local graph fingerprint
3. curated substructure・fragment
4. atom pair・topological torsion
5. path・subgraph fingerprint
6. 2D pharmacophore
7. 3D shape・3D pharmacophore
8. pretrained molecular embedding
9. semiempirical quantum descriptor

したがって全体像は、**2D classical representationは厚く、一部は重複、3Dはglobal shape中心、learned/quantumは入口を用意した段階**である。

## 2. 関係性の凡例

| 表記 | 意味 |
|---|---|
| A ⊂ B | AのfeatureがBに包含され、新しい情報範囲は基本的に増えない |
| 高類似 | 同じ化学概念を異なる定義や符号化で表す |
| 補完 | 同じ大分類だが、局所性や不変性が異なる |
| 同一原情報 | 同じraw representationを異なる変換で出力する |
| 低類似 | 情報源が異なり、独立evidenceになりやすい |

ここでの関係性はalgorithmとfeature定義に基づく。実データ上の相関や予測上の追加価値はdatasetに依存する。

## 3. 厳密または強い包含関係

| 関係 | 実装上の確認 | 評価 |
|---|---|---|
| D006 RDKit fragment ⊂ D001 RDKit 2D | D006の85 fragment featureは、D001の217 featureにすべて含まれる | D006は情報追加ではなく、解釈しやすいsubsetとして有用 |
| D014 basic shape ⊂ D012 RDKit 3D | D014の10 featureはD012と数値的に同一。D012はさらにPBFを持つ | D014は最も冗長性が高いが、shape限定出力として利用可能 |
| D015 Mordred 2D ⊂ D016 Mordred 3Dの定義集合 | 現環境ではD015が1,613定義、D016が1,826定義で、追加3D descriptorは213 | D016は3D専用表ではなく、Mordred 2D＋3Dの包括表 |
| D013内のUSR ⊂ USRCAT | D013はUSR 12列とUSRCAT 60列を出力するが、USRCAT先頭12列はUSRと同一 | 出力72列のうち、実質的に異なる定義は60 |
| D020 energy Hartree ≡ energy eV | 同じenergyの単位変換 | 2列は独立した情報ではない |

Mordred 2D/3Dはfeature定義上の包含関係である。D016は3D conformer生成後の分子を使用するため、共通名の2D descriptor値がD015と常にbit-identicalであることまでは保証しない。

## 4. 2D graph・substructure family

### 4.1 Local environment

| Skill | 主に表す情報 | 他Skillとの関係 |
|---|---|---|
| D002 Morgan | 原子中心の局所環境 | 2D graph表現の代表。chirality、bit/count、feature invariantをparameterで変更可能 |
| D004 Atom Pair | 原子対の種類とtopological distance | Morganより長距離関係を明示的に表し、比較的補完的 |
| D005 Topological Torsion | 連続する原子列 | local environmentとpathの中間的な情報を持つ |

D002、D004、D005はいずれも2D graph由来だが、局所環境、距離関係、連続原子列という観測単位が異なる。この3件は同じfamily内では比較的直交性が高い。

### 4.2 Curated substructure・fragment

| Skill | 主に表す情報 | 類似性 |
|---|---|---|
| D003 MACCS | 人手定義された167 structural keys | 解釈しやすいが表現範囲は固定 |
| D006 RDKit fragment | 85 fragment count | D001の完全subset |
| D008 Pattern fingerprint | 網羅的なsubstructure pattern | MACCS/fragmentより高次元で、同じ概念を広く符号化 |

この3件は部分構造の有無や頻度を中心に見るため、実データ上の近傍関係が相関しやすい。ただし、curated key、count、generic patternという出力意味の違いがある。

### 4.3 Path・subgraph fingerprint

| Skill | 主に表す情報 | 類似性 |
|---|---|---|
| D007 RDKit path | topological path | path-based fingerprintの代表 |
| D009 RDKit layered | 複数layerのgraph情報 | D007と近いが、符号化するgraph属性が異なる |
| D010 Avalon | hashed subgraph/path | D007/D009と同じ大分類で高類似になりやすい |

初期の広く浅い解析では3件すべてを実行せず、一つを代表とし、局所結果の安定性を確認するときに別方式を追加するのが合理的である。

## 5. Pharmacophore・3D・learned・quantum

| 情報軸 | Skill | 特徴と関係性 |
|---|---|---|
| 2D pharmacophore | D017 Gobbi Pharm2D | graph fingerprintとは異なるfeature typeと距離関係を符号化するため、比較的独立性が高い |
| D017 folded/SVD | D017内variant | どちらも39,972次元raw signatureが起点。foldingとdataset-specific SVDであり、新しい化学情報源が増えるわけではない |
| 3D scalar shape | D012/D014 | D014はD012のsubset。global shapeを少数scalarで表す |
| 3D shape/pharmacophore moment | D013 USR/USRCAT | D012より分布的で、USRCATはatom categoryを加えるため比較的補完的 |
| 多数2D/3D descriptor | D016 Mordred 3D | D015をほぼ包含し、3D descriptorを追加。高コストかつsingle conformer依存 |
| learned representation | D019 pretrained embedding | 実際の直交性はlocal model、training objective、poolingに依存する |
| quantum summary | D020 GFN2-xTB | graph/shapeとは異なる電子状態由来。ただし現出力はenergyとcharge統計に限定される |

## 6. カバー範囲

以下は網羅性の相対評価であり、性能scoreではない。

| 情報領域 | カバー状況 | 主なSkill | コメント |
|---|---|---|---|
| 2D物性・topological scalar | 非常に強い | D001、D015 | 低コスト代表と大規模descriptor集合の両方がある |
| fragment・substructure | 強い | D003、D006、D008 | 解釈性と網羅性を複数方式でカバー |
| 2D graph fingerprint | 非常に強い | D002、D004、D005、D007、D009、D010 | 選択肢は多く、やや過密 |
| stereochemistry | 部分的 | D002 chiral、3D系 | すべての2D表現がstereo-sensitiveではない |
| 2D pharmacophore | 強い | D017 | foldedとSVDを選択可能 |
| 3D global shape | 強いが重複あり | D012、D013、D014、D016 | global descriptor中心でsingle conformer依存 |
| conformer ensemble | 弱い | なし | 最良conformer一つを採用し、ensemble統計を出さない |
| explicit 3D pharmacophore/field | 限定的 | D013 | USRCATはあるが、明示的3D pharmacophore fingerprintやmolecular fieldはない |
| pretrained representation | model依存 | D019 | Skillの存在だけでは複数model familyの実効coverageを保証しない |
| electronic/quantum property | 初期的 | D020 | energyとcharge要約のみ。orbital、dipole、polarizability等は未収載 |
| supervised task-specific representation | 未対応 | なし | endpointを使って学習するembeddingは対象外 |
| protein/pocket/interaction | 対象外 | なし | SBDDは将来拡張用schemaのみ |

## 7. 基本計算と初期探索での使用

新仕様では、少数の固定代表だけを「初手」として計算する方式を採らない。人間から明示的な省略指示がない限り、Catalog profileで有効かつ実行可能な**全Description**を`basic_compute`で一度生成する。D016、D019、D020などの高コスト表現も対象に含め、Run開始時に一括bundleとして承認する。

ただし、全Descriptionを生成することと、全Description × 全Grouping × 全Operatorの直積を最初から実行することは別である。初期探索では、生成済み表現から情報familyの異なる共通master panelを選び、全applicable Operator roleを一定の規則で適用する。Vector Clusteringでも、人間管理profileがfamilyごとの代表を宣言し、特定Operator専用のsource集合を埋め込まない。

| 情報family | 初期master panelで必要な観点 | 代表の選択方針 |
|---|---|---|
| 2D scalar | 解釈可能な物性・topology | D001を基準とし、広域表が必要ならD015も使用 |
| local graph | 局所置換と近傍 | D002の互換variantをprofileで指定 |
| substructure | 定義済みkeyとgeneric pattern | D003、D006、D008の冗長性を記録して選択 |
| distance/path | 原子対、torsion、path | D004/D005とD007/D009/D010から異なる観測単位を選択 |
| pharmacophore | 2D機能配置 | D017の出力variantとmetricを明示 |
| 3D | shapeと3D pharmacophore | D012/D013/D014/D016の包含関係を考慮して最低一軸以上を使用 |
| learned/quantum | 学習済み・電子状態 | 利用可能性と承認scope内でD019/D020を比較軸に含める |

代表選択はCatalog／profileの宣言データで変更でき、Orchestrator codeへ固定しない。追加探索では未実施cellをfamily、Grouping、Operator、scopeで層化し、偏りを抑えたseed付きランダム非復元抽出を行う。

## 8. 現時点の総合評価

- 古典的Ligand-only 2D SAR表現のbreadthは高い。
- fingerprintは選択肢が多い。基本計算では全表現を生成し、初期Operator適用ではfamilyの広さと冗長性の両方を管理する。
- D006、D014、D017 SVDは独立情報源ではなく、解釈性、出力粒度、下流処理との相性を変える役割が強い。
- 3Dはglobal shapeとMordredを持つが、conformer ensemble、explicit 3D pharmacophore、electrostatic fieldは不足している。
- D019とD020は異なる情報軸を追加できるが、現在の実効coverageは限定的または外部model依存である。

## 9. Dataset別に直交性を定量化する場合

algorithm上異なる表現でも、対象化合物集合では同じ近傍構造を返すことがある。run単位で次を測定すると、実データ上の直交性を評価できる。

1. pairwise distance/similarity行列間のSpearman相関
2. centered kernel alignment
3. 各Descriptionから得たGrouping間のARI、NMI、variation of information
4. endpoint予測における交差検証済みincremental value
5. activity cliffや局所近傍の一致率・不一致率

これらはCatalog上の静的関係性を置き換えるものではなく、特定runにおけるOrchestratorの選択根拠としてStateまたはInterpretationへ記録する。

## 10. 根拠となる実装

- Description実装: [`tools/templates/description_run.py`](../tools/templates/description_run.py)
- Skill Catalog: [`CONDUCTOR_v4_skill_catalog.md`](CONDUCTOR_v4_skill_catalog.md)
- 設計仕様: [`CONDUCTOR_v4_design_spec.md`](CONDUCTOR_v4_design_spec.md)

feature数は現在のWindows検証環境にあるRDKit/Mordred versionで確認した値であり、library version更新により変化する可能性がある。
