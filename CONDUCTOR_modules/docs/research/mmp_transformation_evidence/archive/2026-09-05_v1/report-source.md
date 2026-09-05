# CONDUCTOR MMP Transformation evidence 調査・設計案

- 対象Version: 0.1.10以降
- 作成日: 2026-09-05
- 状態: 議論用。未承認事項を含み、実装仕様ではない
- 対象: A008 MMP解析、A008全体／個別Report、A009 analysis unitとの接続

## 1. 結論

現在のA008は、Targetを中心にMMPを見つけ、Exact Coreごとに整理して構造変換を視覚的に読むところまで改善されている。一方、個々のTarget–Neighbor差が、そのTargetだけの観測なのか、同じ変換がほかの化合物対でも再現するのかを分けていない。

Transformation evidenceへの発展では、次を中核にする。

1. **Direct target observation**: Targetに直接つながるMMP。事実として表示する。
2. **Target-excluded recurrence**: Targetを含まない別の化合物対で、同じ方向付き変換が再現するかを調べる。
3. **Analysis unit scope**: 再現例を、source unit内部、境界、ほかの採用unit、source unit外へ分ける。
4. **Chemical context**: 同一変換でもattachment point周囲のcontext radius 0–2を区別する。
5. **Evidence transparency**: 単一scoreへ潰さず、件数、方向一致、効果量、ばらつき、context間矛盾を併記する。

この構成により、relationship mapは「Targetが何とどのように違うか」を、Transformation evidenceは「その変換効果がほかでも支持されるか」を担当できる。

## 2. 現行仕様の評価

### 2.1 維持すべき点

- MMP探索母集団をRun全体とする。
- Mode Iはanalysis unit Top 1、Global Top 1、On-demand Targetを同じ処理へ正規化する。
- 同じTargetが複数unitから選ばれても、MMP抽出と個別HTMLはTarget単位で一度だけ作る。
- Targetを常に`To`、Neighborを`From`として、`Favorable delta`の方向を統一する。
- Database／詳細CSVは全接続行を保持し、HTMLだけを最大Exact Coreへ整理する。
- Target中心、Exact Core中間、Neighbor外周のrelationship mapを個別Report最上部に置く。
- `pair_count`、`mmp_instance_count`、Exact Core数、median、IQR、MAD、direction consistency、leave-one-core-out sign stabilityを区別する。

### 2.2 現状で不足する点

- Target直結pairと、同じ変換の別pairによる支持が区別されていない。
- Analysis unitはTarget選抜元として記録されるが、MMP evidenceの集計軸にはなっていない。
- 同じ化合物、pair、Exact Core、context radiusが重複して見える場合に、何が独立な支持数かが読み取りにくい。
- 同じ変換がcontextまたはunitにより逆方向へ動く場合を、明示的な矛盾として示していない。
- TargetはEndpoint Top 1として選ばれるため、Target直結deltaがFavorableに見えやすい。この観測だけを変換の一般的効果とは呼べない。

最後の点はCONDUCTORの選抜手順から導かれる設計上の推論である。source unit内部の再現例もEndpoint選抜後の集合なので完全な独立検証ではない。したがって、source unit外またはTarget除外後の支持を別枠で示す必要がある。

## 3. 推奨する情報モデル

### 3.1 四層構造

```text
Canonical MMP facts
  └─ compound pair × directed transform × Exact Core
       └─ compound ↔ analysis unit membership
            └─ transform × context × evidence scope summary
                 └─ overall / target HTML views
```

Canonical MMP Databaseは化学的事実を保持し、Analysis unit情報やEndpoint統計で上書きしない。unitとの関係とevidence summaryは派生tableとして追加する。

### 3.2 Evidence key

同じevidenceとして集約する最小単位を、次の組合せで定義する。

- 方向付きvariable transformation: `Neighbor fragment → Target fragment`
- attachment point数、対応番号、結合topology
- context radius: 0、1、2
- EndpointのFavorable方向へ正規化したdelta

Exact CoreはTarget直結MMPの表示groupであり、transform再現性の集約keyそのものにはしない。同じ変換が複数のExact Coreで観測されることを、core diversityとして別に数える。

[mmpdb](https://github.com/rdkit/mmpdb)も、変換ruleとattachment point周囲のrule environmentを分離し、radiusが大きいほど化学的にspecificなcontextとして、各property changeの分布統計を保持している。

### 3.3 Analysis unit relation

各MMP pairを各source analysis unitに対して次のように分類する。

| relation | 定義 | 解釈 |
|---|---|---|
| `direct_target` | Targetを含むpair | Targetについての直接観測 |
| `unit_internal_ex_target` | Targetを含まず、両化合物がsource unit内 | unit内部での再現 |
| `unit_boundary_ex_target` | Targetを含まず、片方だけがsource unit内 | unit境界をまたぐ再現 |
| `other_unit_ex_target` | Targetを含まず、別の採用unit内で観測 | 採用unit間の支持 |
| `source_unit_external_ex_target` | Targetを含まず、両化合物がsource unit外 | Run内の外部支持 |

同じpairが複数unitに属し得るため、unit relationはmany-to-manyで保持する。`other_unit_ex_target`と`source_unit_external_ex_target`も同時成立し得るscope tagであり、排他的な単一分類にはしない。ただし全体の`pair_count`ではcanonical pairを一度だけ数え、unit別件数の単純合計を支持数として扱わない。

### 3.4 Cross-representation Coreとの接続

TargetとNeighborについて、所属unit内のmember classを次のtagとして表示できる。

- Cross-representation Core
- Core
- Fringe

ただし、複数Descriptionから支持されたことはrepresentation間の整合性であり、独立した生物学的測定が増えたことではない。したがって、evidenceの重みやpair数は増やさない。Reportでは解釈用tag、層別集計、PCA/UMAPとの導線に限定する。

## 4. Transformation evidenceの指標

### 4.1 最低限示す指標

各`transform × radius × scope`について次を保持する。

- unique compound-pair count
- unique compound count
- Exact Core count
- analysis unit count
- endpoint available / missing pair count
- Favorable direction: `favorable pair数 / endpoint pair数`
- median Favorable delta
- Q1、Q3、IQR、MAD
- direction consistency
- Target-excluded statistics
- source-unit-excluded statistics
- context radius間の符号一致／反転
- leave-one-core-out sign stability
- leave-one-unit-out sign stability

方向一致を先に、変化量を次に読む構成がよい。Lukacらは変換方向を二項的に扱う解析と効果量解析を組み合わせ、化学的specificityの高い小集合にも価値があることを示している。[Turbocharging Matched Molecular Pair Analysis](https://pubmed.ncbi.nlm.nih.gov/28967750/)

### 4.2 統計上の注意

- 一つの化合物が多数のpairに使われると、pairは互いに独立ではない。`N pairs`だけで確信度を大きく見せない。
- radius 0–2は入れ子のcontextであり、三つの独立な再現例ではない。
- Endpointが異なるassayから混在する場合、deltaにも測定noiseがある。可能ならassay metadataとreplicate由来noiseを併記する。
- `<`、`>`などのcensored値は単純差から除外するか、intervalとして扱い、除外数を示す。
- MMPは局所置換の寄与が概ね加算的という前提を持つ。強いnonadditivityは重要なSAR signalである一方、単一変換の一般化を壊す。[Strong nonadditivity](https://pubmed.ncbi.nlm.nih.gov/25760829/)

公開bioactivityのmatched pair差は絶対測定値よりassay間変動に強い場合があるが、metadata curationで一致性がさらに改善することも報告されている。したがって、MMPだからassay差を無視できるわけではない。[Matched pairs demonstrate robustness against inter-assay variability](https://pmc.ncbi.nlm.nih.gov/articles/PMC11748845/)

### 4.3 単一の総合scoreを作らない

0.1.10では、任意の重みを混ぜた`evidence_score`や機械的な合否判定を導入しない。代わりに次の状態labelを事実から決定する。

- `Direct observation only`: Target除外後の同一変換pairなし
- `Recurrent in source unit`: source unit内にTarget除外pairあり
- `Corroborated outside source unit`: source unit外にTarget除外pairあり
- `Context conflict`: radiusまたはunit間でmedianの符号が反転
- `Endpoint unavailable`: quantitative deltaを評価できない

「支持が強い」の数値基準は、複数Runで分布を確認してから決める。初期Versionではraw countsと区間を表示し、恣意的な閾値でEvidenceを強く見せない。

## 5. 推奨Report構成

### 5.1 MMP個別Report

```text
Header / Target selection provenance
MMP relationship map                         必須・現行案を維持
1. Target / Neighbor structures              現行
2. Transformation evidence at a glance       追加
3. Evidence by analysis-unit scope            追加
4. Favorable delta distribution               追加
5. Basic information                          現行
6. Detailed transformations                   現行
7. Visual transformations                     現行
```

説明文は主要dataの後ろに折り畳む。

#### Transformation evidence at a glance

各変換について、一行cardまたはcompact tableで次を示す。

```text
Before → After | Direct Δ | Target-excluded N | Favorable/N
Median Δ [Q1, Q3] | Exact Cores | Context | Evidence label
```

Relationship mapはExact Core単位、Evidence cardはdirected transformとcontext単位である。双方に同じtransform anchorを持たせ、clickで相互移動できるようにする。

#### Evidence by analysis-unit scope

横長の小さなmatrixを用いる。

| Transformation | Direct Target | Source unit内 | Boundary | Other units | Source unit外 |
|---|---:|---:|---:|---:|---:|
| `R1→R2` | `+1.18` | `2/3; +0.54` | `1/2; +0.10` | `4/5; +0.42` | `7/10; +0.31` |

cellは`Favorable数/Endpoint pair数; median Favorable Δ`とし、正方向をmagenta、負方向をblue、欠測をgrayとする。unit名をrelationship mapへすべて書き込むより、重複所属を正確かつcompactに表せる。

#### Favorable delta distribution

- Target直結pairを大きい点で強調する。
- Target除外pairはscope別の色で示す。
- pair数が少なければstrip plot、多ければbox/violin + raw pointsとする。
- before/after Endpointのpaired slope plotを切替表示してもよい。
- 平均だけではなくmedianとIQRを主表示する。

### 5.2 MMP全体Report

- Mode Iで選ばれたTarget数、Global Top 1を含むか、重複Target統合数。
- 各Targetの2D画像、Endpoint、selection source、source analysis units、個別Report link。
- `Externally corroborated`な変換を上位に置くTransformation table。
- rankingはDirect Target deltaだけでなく、Target-excluded pair数、direction consistency、median delta、context conflictを並列に示す。
- 全体tableは初期折り畳み、列sort可、詳細CSV linkをsection末尾に置く。

### 5.3 条件付き追加View

常に出すのではなく、dataが揃った場合だけ追加する。

1. **SAR Matrix / R-group Matrix**
   同じCore・attachment siteに3種類以上の置換基がある場合に、行をCore、列を置換基、cellをEndpointとする。空cellは未合成候補として見える。[SAR Matrix](https://pmc.ncbi.nlm.nih.gov/articles/PMC4215758/)
2. **Matched Molecular Series network**
   同一siteの置換系列が連鎖する場合に、単一pairではなく活性gradientとして示す。MMS networkは偶然のpair相関を減らし、SAR translationに利用されている。[Matched molecular series networks](https://pubmed.ncbi.nlm.nih.gov/30108724/)
3. **Multi-endpoint heatmap**
   同一Program内で比較可能な複数Endpointが存在する将来仕様で、変換ごとのpotency、logD、clearance等の方向を並べる。Endpoint定義とassay互換性を確認できる場合だけ使う。
4. **3D binding-site map**
   実験または信頼できるprotein–ligand poseがある場合だけ、変換部位を3D上に表示する。OOMMPPAAはMMP変化位置とpharmacophore差をbinding siteへ投影しているが、CONDUCTOR標準Runで3D根拠がない場合は作らない。[OOMMPPAA](https://pubmed.ncbi.nlm.nih.gov/25244105/)

## 6. 先進事例から取り込める要素

| 事例 | 優れている点 | CONDUCTORへの採用案 |
|---|---|---|
| [mmpdb](https://github.com/rdkit/mmpdb) | ruleとrule environment、radius別統計、raw pairへの説明導線 | radius 0–2別summary、選択contextの根拠、詳細pair link |
| [Matcher](https://github.com/Merck/matcher) | 変換／environment query、高レベル統計からscatter・構造pairへのdrill-down | Evidence card → delta plot → MMP rowの一貫した導線 |
| [Papadatos et al.](https://pubmed.ncbi.nlm.nih.gov/20873842/) | contextにより隠れた正負trendを分離 | context符号反転を警告し、global transform平均だけを採用しない |
| [Turbocharging MMPA](https://pubmed.ncbi.nlm.nih.gov/28967750/) | direction-first、化学的specificity、fragment/indexとMCSの相補性 | Favorable/Nを主指標化。MCS engineは将来の感度分析候補 |
| [SAR Matrix](https://pmc.ncbi.nlm.nih.gov/articles/PMC4215758/) | Core×substituentを一目で比較し、欠けたanalogも見える | 条件付きR-group matrix |
| [CAS BioFinder MMPA](https://cas-biofinder.zendesk.com/hc/en-us/articles/37303631485965-March-2025-Matched-Molecular-Pair-Analysis-MMPA) | R-group交換によるpActivity変化をcolor matrix化し、hoverで完全構造へ移動 | 条件付きmatrixのcellから実MMP pairへdrill-down |
| [MMS network](https://pubmed.ncbi.nlm.nih.gov/30108724/) | pairを系列へ拡張し、SAR gradientとtransferabilityを評価 | 変換が連鎖する場合だけseries networkを生成 |
| [Nonadditivity analysis](https://pubmed.ncbi.nlm.nih.gov/31508950/) | 同じ変換効果が背景置換で変わる例をsystematicに検出 | 2×2 cycleが形成できる場合の将来警告機能 |
| [OCHEM prediction-driven MMP](https://pmc.ncbi.nlm.nih.gov/articles/PMC4272757/) | 観測deltaとmodel予測deltaの比較、変換graph、multi-property optimization | 将来のA005×A008 model audit |
| [Playbooks of Medicinal Chemistry Design Moves](https://pubs.acs.org/doi/10.1021/acs.jcim.0c01143) | 頻出変換を設計ruleとして再利用 | Mode II DBを将来のcompound proposalへ使う際の候補。現時点では観測Evidenceと混ぜない |

## 7. 0.1.10へ推奨する範囲

### 必須候補

1. 既決定の2 Mode化、Global Top 1、relationship mapを実装する。
2. `compound_analysis_unit_membership`とTarget selection provenanceを保持する。
3. Canonical pairへunit relationを付ける派生tableを作る。
4. Direct TargetとTarget-excluded recurrenceを分離する。
5. 既存radius 0–2、pair/core summaryを利用し、scope別にcount、Favorable/N、median、IQR、MADを計算する。
6. 個別ReportへEvidence cardとanalysis-unit scope matrixを追加する。
7. 同一Targetを複数unitが選んだ場合はHTMLを複製せず、unit別summaryを同じReport内に持つ。
8. 件数監査でcanonical pair数、表示数、scope別deduplicate数、詳細CSV行数を確認する。

### 0.1.10では避ける候補

- 単一の総合Evidence score
- 未校正のhard pass/fail threshold
- MCSとfragment/index結果の自動混合
- prospective compound generation
- 3D poseなしの3D visualization
- 複数Endpoint／複数Runを無条件に統合した統計

## 8. 0.1.11以降の候補

1. compound-pair graphのconnected component単位bootstrapによる依存性を考慮した区間推定。
2. MCS-based engineを第二経路として追加し、1-cut fragment/indexとの感度分析を行う。
3. 2×2 matched-pair cycleによるnonadditivity検出。
4. MMS／SAR Matrixの自動発火条件と未合成analog提示。
5. 複数Run／Endpointのassay互換性を管理したmulti-property transformation profile。
6. A005予測deltaと観測MMP deltaを比較するmodel audit。
7. synthesis-aware／retrosynthetic transform provenance。
8. 十分な3D根拠がある場合のbinding-site transformation map。

## 9. 次に合意すべき点

1. **Primary contextの選択**
   推奨は、Target-excluded pairが一定数ある最大radiusを主表示し、radius 0–2を折り畳みで併記すること。ただし最低pair数は実Run分布を見て決める。
2. **Evidence labelの強度基準**
   0.1.10では存在／矛盾を示す記述labelに限定し、強・中・弱の閾値は設けないことを推奨する。
3. **Source unit外の定義**
   同じRun内でsource unitに属さないpairを外部支持と呼ぶ。ただし独立assay検証ではないため、Reportでは`Run-internal external support`と明記する。
4. **条件付きViewの優先順位**
   0.1.10はEvidence matrixとdelta plotまでとし、SAR Matrix、MMS network、nonadditivityは0.1.11以降を推奨する。

## 10. 参考資料

- Dalke A, Hert J, Kramer C. [mmpdb: An Open-Source Matched Molecular Pair Platform for Large Multiproperty Data Sets](https://pubs.acs.org/doi/10.1021/acs.jcim.8b00173). JCIM, 2018.
- Hussain J, Rea C. [Computationally Efficient Algorithm to Identify Matched Molecular Pairs](https://pubs.acs.org/doi/10.1021/ci900450m). J Chem Inf Model, 2010.
- Papadatos G et al. [Lead optimization using matched molecular pairs](https://pubmed.ncbi.nlm.nih.gov/20873842/). J Chem Inf Model, 2010.
- Lukac I et al. [Turbocharging Matched Molecular Pair Analysis](https://pubmed.ncbi.nlm.nih.gov/28967750/). J Chem Inf Model, 2017.
- Kramer C et al. [Matched Molecular Pair Analysis: Significance and the Impact of Experimental Uncertainty](https://pubmed.ncbi.nlm.nih.gov/24738976/). J Med Chem, 2014.
- Dossetter AG et al. [Matcher](https://github.com/Merck/matcher) and its [open manuscript](https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/63586c15aca19850f7e53e55/original/matcher-an-open-source-application-for-translating-large-structure-property-datasets-into-insights-for-drug-design.pdf).
- Gupta-Ostermann D, Bajorath J. [The use of matched molecular series networks for cross target SAR translation](https://pubmed.ncbi.nlm.nih.gov/30108724/). MedChemComm, 2018.
- Wawer M et al. [Structure–Activity Relationship Anatomy by Network-like Similarity Graphs and Local Structure–Activity Relationship Indices](https://pubmed.ncbi.nlm.nih.gov/17958407/). J Med Chem, 2008.
- Kramer C et al. [Strong nonadditivity as a key SAR feature](https://pubmed.ncbi.nlm.nih.gov/25760829/). J Chem Inf Model, 2015.
- Kramer C. [Nonadditivity Analysis](https://pubmed.ncbi.nlm.nih.gov/31508950/). J Chem Inf Model, 2019.
- Leach AR et al. [Matched molecular pairs as a medicinal chemistry tool](https://pmc.ncbi.nlm.nih.gov/articles/PMC5198793/). Comput Struct Biotechnol J, 2017.
- CAS BioFinder. [Matched Molecular Pair Analysis visualization](https://cas-biofinder.zendesk.com/hc/en-us/articles/37303631485965-March-2025-Matched-Molecular-Pair-Analysis-MMPA). 2025.
- Sushko I et al. [Prediction-driven matched molecular pairs to interpret and optimize models](https://pmc.ncbi.nlm.nih.gov/articles/PMC4272757/). J Cheminform, 2014.
- Awale M et al. [The Playbooks of Medicinal Chemistry Design Moves](https://pubs.acs.org/doi/10.1021/acs.jcim.0c01143). J Chem Inf Model, 2021.
- Nittinger J et al. [Matched pairs demonstrate robustness against inter-assay variability](https://pmc.ncbi.nlm.nih.gov/articles/PMC11748845/). J Cheminform, 2025.
