# CONDUCTOR MMP 現行仕様・課題・外部調査

- 対象: A008 MMP
- 対象Version: 0.1.11
- 基準日: 2026-09-05
- 状態: ①現行仕様、②課題、③外部調査結果を整理する議論資料
- 非対象: ④改良設計方針、採用機能、実装順序、判定閾値。後続設計は[`../../CONDUCTOR_0.1.11_specification_overview.md`](../../CONDUCTOR_0.1.11_specification_overview.md)と[`../../CONDUCTOR_0.1.11_implementation_plan.md`](../../CONDUCTOR_0.1.11_implementation_plan.md)に分離する
- 旧案: [`archive/2026-09-05_v1/report-source.md`](archive/2026-09-05_v1/report-source.md)

## 0. 本書の整理方針

本書では、次の二つを独立した論点として扱う。

| 論点 | 問い |
|---|---|
| Analysis unitとの接続 | Target／Neighbor／MMP変換と、Series・Clusterの関係をどう記録し、どう解釈するか |
| MMP自体の高度化 | MMPの検出、統計、化学的context、可視化、知識抽出の質をどう上げるか |

両者はReport上で交差し得るが、MMP解析そのものはAnalysis unitがなくても成立する。逆に、Analysis unitとの接続はMMP検出algorithmを変更しなくても追加できる。したがって、課題と外部事例を混ぜずに整理する。

また、以下を明確に区別する。

- **現行実装**: 2026-09-05時点のA008 Skill、contract、`run.py`、`mmp_engine.py`に存在する挙動
- **0.1.11へ移管した方向**: 協議で方向性を合意したが、現行codeにはまだ反映されていない挙動
- **調査候補**: 外部事例から得た選択肢。採用は未決定

# ① 現行仕様

## 1. A008の目的

A008は、Run内化合物から1-cut MMPを検出し、局所的な構造変換とEndpoint差を提示するSkillである。主な用途は次の三つである。

1. 採用されたSeries／fallback ClusterのTop化合物周辺を調べる。
2. 人間が指定した化合物周辺をOn-demandで調べる。
3. Run全体のMMP Databaseと集計dataを構築する。

## 2. 現行の3 Type

| Type | Target | 探索母集団 | 主な出力 |
|---|---|---|---|
| Type-I | 各active Series／fallback ClusterのEndpoint Top 1 | Run全体 | Target接続MMP CSV、全体HTML、Target個別HTML、index |
| Type-II | 人間が指定した1件以上のRun内compound ID | Run全体 | Target接続MMP、near-core参照、全体／個別HTML、index |
| Type-III | Targetなし | Run全体 | 全MMP CSV、SQLite、transform/core/context等の全体Summary |

### Type-I

- `analysis_unit_membership`を必須入力とする。
- `GLOBAL`を除く各analysis unitからEndpoint最良の1化合物を選ぶ。
- Global Top 1は現行実装では自動Targetに含まれない。
- MMPが0件でも次順位化合物へ自動補充しない。
- 複数unitで同一化合物がTop 1の場合、unit別Target rowを保持する。

### Type-II

- `target_compound_ids`で明示したRun内化合物だけをTargetとする。
- 上位K化合物を調べる場合も、実際のcompound IDを明示する。
- 同一RunのType-III Databaseは、人間が明示した場合だけ再利用する。
- 再利用時は入力CSV hash、Endpoint列、Favorable方向、schema、1-cut、radiusの一致を検証する。
- Exact Coreに近い別Coreを、core TanimotoとMCS coverageで探索する補助出力を持つ。

### Type-III

- Run全体のeligible MMPを保存する。
- `mmp_database.sqlite`、全pair、transform、core、transform×core、context、coverageのSummaryを出力する。
- Type-I/IIのようなTarget個別Reportは作らない。

## 3. MMPの計算範囲と化学的制約

| 項目 | 現行値・挙動 |
|---|---|
| pair探索範囲 | Run全体 |
| fragmentation | 1-cutのみ |
| environment radius | 0–2 |
| minimum constant-core heavy atoms | 8 |
| minimum constant-core fraction | 両化合物で0.50 |
| maximum variable-fragment heavy atoms | 10 |
| Endpoint方向 | higher/lower is betterに応じてFavorable deltaへ正規化 |

mmpdbのcanonical rule方向について、`endpoint_delta = endpoint_to - endpoint_from`を計算する。Favorable deltaはEndpointの良化方向が正になるように符号を変換する。

## 4. 保存単位と重複の扱い

Canonical Database上の1 MMP instanceは、概念的に次の組合せである。

```text
compound pair × directed transform × Exact Core
```

- 同じcompound pairが複数Exact Coreで成立する場合、Databaseと詳細CSVには全行を残す。
- `mmp_instance_count`は未縮約のMMP行数である。
- `pair_count`はcompound pairを重複除去した数である。
- Exact Coreの多様性は`independent_core_count`として別に数える。
- radius 0–2は入れ子のcontextであり、独立した三つのMMPとして数えない。

HTMLでは、同じTarget–Neighborに複数Coreがある場合、包含される小さいCoreを除き、最大Coreに対応する最小変換を示す。包含関係にないCoreは両方残す。この縮約は表示だけに適用される。

## 5. 現行の統計情報

Type-IIIの全体Summaryでは、transform、core、transform×core、compound pair、contextごとに次を計算する。

- MMP instance数
- unique compound-pair数
- Endpoint利用可能pair数
- unique compound数
- Exact Core数
- median Favorable delta
- Q1、Q3、IQR、MAD
- direction consistency
- core-weighted median
- leave-one-core-out sign stability

context summaryはtransformとradius、environment SMARTSの組合せで作られる。

Type-I/IIでは、Targetに直接接続したMMPだけを用いて、Target別、transform別、core別の件数、median delta、Favorable fractionを計算する。Run全体のtransform再現性Summaryは保存しない。

## 6. Analysis unitとの現行接続

現行の接続は、基本的にTarget選抜provenanceである。

```text
Analysis unit
  └─ Endpoint Top 1 Target
       └─ Run全体からTargetに直接接続するMMPを抽出
```

- `analysis_unit_id`は、どのSeries／fallback ClusterがTargetを選んだかを示す。
- 同じTargetが複数unitから選ばれた場合、CSV上はunitごとの接続行を持つ。
- Target個別HTMLはTarget ID単位で一つだけ作り、選抜元unitを併記する。
- Neighborがどの採用analysis unitに属するかは、MMP evidenceとして集計していない。
- MMP pairがunit内部、unit境界、unit外のどこに位置するかも分類していない。
- Cross-representation Core／Core／Fringe情報はA008の計算やTarget選択に使用していない。

## 7. 現行Report

### MMP全体Report

- Target数、Target接続MMP数、Environment radius等の概要
- analysis unitごとのTarget情報
- Targetの2D構造gallery
- Target個別HTMLへのlink
- 詳細CSVへのlink

### MMP個別Report

最上部にrelationship mapを置く。

```text
Target（中央）
  └─ Exact Core（中間）
       └─ Neighbor（外周）
```

- Targetは紺、Exact Coreは緑、Neighborはオレンジ。
- Neighbor cardには置換前fragment、Endpoint、Favorable deltaを示す。
- mapはExact Core上位3件、各CoreのNeighbor上位3件まで表示する。
- Section 1はTargetを単独行、その下にTargetへ2D alignmentしたNeighborを4列で示す。
- 詳細変換はExact Coreごとにcard化する。
- 各CoreのFavorable delta上位5件を展開し、残りを折り畳む。
- 各変換はNeighbor全体、Target全体、Before fragment、After fragmentの4列で示す。
- Target全体SMILESは表示するが、Neighbor全体SMILES文字列は表示しない。
- 全列と整理前の接続行は詳細CSVへ残す。

## 8. 0.1.11へ移管した確定方向（未実装）

0.1.10追補からMMP追加改修を外し、次を0.1.11へ移管した。

- Type-IとType-IIを`Mode I: Target analysis`へ統合する。
- Type-IIIを`Mode II: Database build`とする。
- Mode Iの定型TargetへGlobal Top 1を必ず追加する。
- analysis unit Top 1、Global Top 1、On-demand Targetを共通Target tableへ正規化する。
- 同じTargetを複数のselection sourceが選んでも、MMP抽出と個別HTMLは一度だけ作る。
- EndpointがFavorableになる向きをA → Bとし、表示上のFavorable Δを正値へ揃える。
- Direct／Transferredを接続性、explanation／improvementをTargetのA/B位置による役割として独立に扱う。

| 接続 | Target対応位置 | 解釈 |
|---|---|---|
| Direct | A | Target → 実測Neighbor BというObserved improvement |
| Direct | B | 実測Neighbor A → TargetというTarget explanation |
| Transferred | A | Target → Virtual Candidate BというProposed improvement |
| Transferred | B | 別CoreのA → Target類似BによるTransferred explanation |

Transformation evidenceの具体的仕様は仕様概要書と実装計画書の承認前Draftであり、未実装である。

# ② 現行仕様の課題

## 9. Analysis unit接続の課題

### AU-1. Analysis unitはTargetの選抜元としてしか使われていない

現行から分かるのは「どのunitがTargetを選んだか」である。次は分からない。

- Neighborが同じunitに属するか。
- MMP pairがunit内部なのか、unit境界をまたぐのか。
- 同じ変換が別unitでも観測されるか。
- その変換が特定unit固有なのか、Run全体で一般的なのか。

つまり、analysis unitとMMPはlinkされているが、Transformation evidenceとして統合されていない。

### AU-2. 複数unitから同じTargetが選ばれた意味を評価していない

現行は選抜元unit名を列挙するだけである。各unit内で同じNeighbor／transformが支持されるか、unitごとに効果方向が異なるかは比較しない。

### AU-3. unit別接続行とEvidence件数を区別する必要がある

同じTargetが三つのunitから選ばれると、同じMMPが三つのunit接続行として現れ得る。これはprovenanceとしては正しいが、三つの独立したMMP evidenceではない。現行Reportは表示時に整理するが、unit接続数とcanonical pair数の意味を十分に分けていない。

### AU-4. Target選抜による偏りがある

Type-I TargetはEndpoint Top 1である。そのため、Target直結pairのNeighbor→Target deltaはFavorableに見えやすい。これは現行選抜規則から生じる構造的な偏りであり、同じ変換の一般的効果を示すものではない。

source unit内部の化合物もEndpointで選抜された集合なので、unit内部の再現だけで完全な独立検証とは言えない。これはMMP検出algorithmの問題ではなく、Analysis unitとの接続・解釈上の問題である。

### AU-5. Cross-representation Core等のmember classとの関係が未定義

Cross-representation Core、Core、FringeはSeries内部の支持構造を表すが、A008では記録・層別していない。一方で、これらをMMP件数の重みとして使うと、Description間の支持を独立MMP evidenceと誤認する危険がある。

## 10. MMP解析自体の課題

### MMP-1. Type-I/IIはTarget直結MMPだけで評価している

同じ`Before → After`変換がTargetを含まない別化合物対で再現するかを評価していない。したがって、現行のFavorable fractionやmedian deltaは「Target周辺で何が観測されたか」であり、「変換効果が再現するか」ではない。

### MMP-2. radius 0–2を計算しているが、Target Reportで活用していない

同じ変換でもattachment point周辺が異なれば効果方向が変わり得る。現行engineはenvironment contextを保存できるが、個別Reportではcontext別件数、delta分布、符号反転を示していない。

### MMP-3. Type-IIの効果方向が成果物間で一致しない

現行codeでは、Type-I summaryは`Neighbor → Target`のFavorable deltaを用いるが、Type-IIのtarget／transform summaryは`Target → Neighbor`を用いる。一方、個別HTMLはTargetを常に`To`として`Neighbor → Target`へ再正規化する。

したがって、Type-IIではCSV summaryと個別HTMLで効果方向が逆になる可能性がある。これは高度化以前に解消すべきcorrectness課題である。

### MMP-4. Type-I/IIでRun全体情報を計算しても、Evidenceとして残さない

Type-I/IIも内部ではRun全体をfragment/indexしてからTarget接続pairを抽出する。しかし、包括的transform/context SummaryとSQLiteはType-IIIだけに限定され、Type-I/II終了時には保持されない。そのため、Target直結変換がRun全体で何回再現したかをReportへ利用できていない。

### MMP-5. pairの統計的依存性を扱っていない

一つの化合物が多数のpairに使われる場合、それらは独立観測ではない。現行の`independent_compound_count`はunique compound数であり、統計的独立性を保証する数ではない。名称も誤解を招く。

### MMP-6. Endpoint測定noiseとassay heterogeneityを扱っていない

現行はEndpoint deltaをそのまま効果量として扱う。replicate variability、assay ID、測定条件、censored値（`<`、`>`）はTransformation evidenceの不確実性へ反映しない。

### MMP-7. 1-cutだけでは拾えない変換がある

1-cutは解釈性が高く、標準解析として合理的である。一方、ring replacement、linker変更、複数attachmentを持つ置換などは2/3-cutまたはMCS-based手法でなければ捉えにくい。これはbugではなく、現行scopeの限界である。

### MMP-8. additivityを暗黙に仮定している

同じ置換でも別の置換基や立体・配座環境によって効果が変わるnonadditivityを検出しない。現行のtransform medianだけでは、背景構造依存の重要なSARを平均化する可能性がある。

## 11. Report・情報抽出の課題

### REP-1. relationship mapは関係を示すがEvidenceの強さを示さない

現在のmapからは、Target、Core、Neighborの関係を理解できる。しかし次は分からない。

- その変換がTarget以外でも観測されたか。
- 何pair、何Core、何化合物で支持されたか。
- 効果方向が一貫しているか。
- chemical contextによって逆転しないか。

### REP-2. 高レベル要約から根拠pairまでのdrill-downが弱い

Target個別Reportには構造pairがあるが、Run全体のtransform ranking、context別統計、個々の根拠pairを一つの導線で移動できない。

### REP-3. data形状に応じた可視化を持たない

現行は全Targetへ同じ基本構成を適用する。同じCore・attachment siteに多数の置換基がある場合、連続するmatched seriesがある場合、複数Endpointがある場合でも、より適したMatrix／network／heatmapへ切り替えない。

### REP-4. 観測結果と設計知識を分けていない

現行は観測MMPを提示するところで終わる。再現性の高い変換rule、context依存性、矛盾、未探索analogなどを、再利用可能なknowledge objectとして整理していない。

## 12. 課題の優先度

| 優先度 | 課題 | 理由 |
|---|---|---|
| Correctness | MMP-3 Type-II方向不一致 | 同じ結果の意味が成果物間で逆転し得る |
| 基礎仕様 | 3 Typeと承認済み2 Mode、Global Top 1の差 | 現行実装と合意仕様が一致していない |
| Evidence | MMP-1、MMP-2、AU-1～4 | 直接観測を再現性Evidenceと誤解し得る |
| 統計品質 | MMP-5、MMP-6、MMP-8 | 支持数、noise、背景依存性を過大評価し得る |
| 表示・活用 | REP-1～4 | 人間が変換の有用性と限界を判断しにくい |
| 拡張coverage | MMP-7 | 標準1-cutで対象外となる化学変換がある |

# ③ 外部調査結果

## 13. 調査の見方

外部事例について、単に機能を列挙せず、次を比較する。

1. どのような方法でMMPを高度化しているか。
2. 何が優れているか。
3. 現行CONDUCTORに何が不足していると分かるか。

外部事例の多くにはCONDUCTOR固有のAnalysis unit概念がない。したがって、Analysis unit接続は既存製品をそのまま模倣する問題ではなく、外部のcontext層別・cohort比較・drill-downの考え方をCONDUCTORへ適用する問題である。

## 14. 化学的contextと統計の高度化

### 14.1 mmpdb: Rule environment別の変換統計

**方法論**

[mmpdb](https://github.com/rdkit/mmpdb)は、variable fragmentの変換ruleと、attachment point周辺のrule environmentを分ける。environment radiusが大きいほど周辺構造をspecificに表す。propertyごとにcount、平均、標準偏差、quartile、median等を保持し、transform/predict時には採用ruleと根拠pairを保存できる。

**優れている点**

- 同じ置換でも周辺構造が違う場合を区別できる。
- 高レベルの予測値から、採用contextと実pairまで説明できる。
- 変換effectを単一pairではなく分布として扱う。

**現行CONDUCTORとの差**

CONDUCTORもradius 0–2とcontext summaryを計算できるが、Target Reportとanalysis-unit比較には使っていない。基盤はあるが、情報抽出と表示が未接続である。

### 14.2 Papadatosら: Context-dependent MMP

**方法論**

[Lead optimization using matched molecular pairs](https://pubmed.ncbi.nlm.nih.gov/20873842/)では、変換の周辺contextを考慮してproperty changeを解析する。

**優れている点**

- context-independent集計では相殺される正負のtrendを分離できる。
- 変換の適用可能領域を具体化できる。

**現行CONDUCTORとの差**

現行はTarget直結pairをCore単位で見せるが、同じtransformのcontext別方向一致や符号反転を報告しない。

### 14.3 Kramerら: 実験誤差を考慮したMMP significance

**方法論**

[Matched Molecular Pair Analysis: Significance and the Impact of Experimental Uncertainty](https://pubmed.ncbi.nlm.nih.gov/24738976/)は、MMP effectを実験的不確実性とともに評価する。

**優れている点**

- 小さいdeltaを化学変換効果と断定しにくくする。
- sample sizeと測定誤差に応じた慎重な解釈ができる。

**現行CONDUCTORとの差**

現行はdeltaのmedian、IQR、MADを持つが、Endpoint測定noiseとの相対関係を示さない。

### 14.4 Turbocharging MMPA: Direction-firstと複数検出法

**方法論**

[Turbocharging Matched Molecular Pair Analysis](https://pubmed.ncbi.nlm.nih.gov/28967750/)は、変換がpropertyを上げるか下げるかというdirectionを先に評価し、その後にeffect magnitudeを扱う。またfragment-and-indexとmaximum common substructure系の検出法を比較・併用する。

**優れている点**

- 外れ値に左右されやすい平均deltaだけに依存しない。
- 化学的specificityの高い小規模変換にも価値を認められる。
- algorithmにより拾えるMMPが違うことを感度分析できる。

**現行CONDUCTORとの差**

現行にもdirection consistencyはあるがType-III中心で、Target Reportの主情報ではない。MMP検出は1-cut fragment/indexの単一路である。

### 14.5 WizePairZ: Coreを事前指定しないMCS-based MMP

**方法論**

[WizePairZ](https://pubmed.ncbi.nlm.nih.gov/20690655/)はmaximum common substructureを利用し、事前にCoreを指定せずMMPを抽出・encodeする。

**優れている点**

- fragment cutだけでは捉えにくいring／linker置換を拾える場合がある。
- 変換archiveやvirtual enumerationへ展開できる。

**現行CONDUCTORとの差**

CONDUCTORは1-cutの解釈性を優先するためcoverageが限定される。ただし、MCS-based結果は定義が広くなり得るので、単純に混合するとMMPの意味が不均一になる。

## 15. PairからSeries・非加算性への高度化

### 15.1 Matched Molecular Series

**方法論**

[Matched molecular series networks](https://pubmed.ncbi.nlm.nih.gov/30108724/)は、二化合物のpairだけでなく、同じ位置の置換系列をnetworkとして扱い、SARの順序や別系列へのtransferabilityを調べる。

**優れている点**

- 一つの大きなdeltaではなく、複数置換の一貫したgradientを読める。
- 偶然の1 pairに依存しにくい。
- 系列間で置換順位が再現するか評価できる。

**現行CONDUCTORとの差**

現行A008はTarget中心のstar型表示であり、Neighbor同士を含む置換系列や順序を抽出しない。なお、ここでいうMatched Molecular SeriesはCONDUCTORのanalysis unitとしてのSeriesとは別概念である。

### 15.2 SAR Matrix

**方法論**

[SAR Matrix](https://pmc.ncbi.nlm.nih.gov/articles/PMC4215758/)は、analogous Coreを行、置換基を列、化合物またはactivityをcellに配置する。空cellは未観測のCore×substituent組合せになる。

**優れている点**

- 多数のMMPを一つずつ読むより、置換patternを把握しやすい。
- 系列間で置換効果を比較できる。
- 未合成analogを自然に認識できる。

**現行CONDUCTORとの差**

現行Reportは各MMPを縦に並べる。Core・site・置換基が増えた場合、全体patternを読むViewがない。

### 15.3 Nonadditivity analysis

**方法論**

[Strong nonadditivity](https://pubmed.ncbi.nlm.nih.gov/25760829/)および[Nonadditivity Analysis](https://pubmed.ncbi.nlm.nih.gov/31508950/)は、pairs of matched pairsから、同じ変換のeffectが別の背景置換によって変わるかを調べる。

**優れている点**

- 単純な加算modelが失敗するSARを検出できる。
- assay artifact候補と、配座・結合mode等の重要な構造変化候補を識別する手掛かりになる。
- 平均化すると消える重要なactivity cliffを抽出できる。

**現行CONDUCTORとの差**

現行transform Summaryは背景構造をまたいだmedianとdirection consistencyを示すが、2×2 cycleとしてnonadditivityを定量化しない。

## 16. 可視化・Reportの高度化

### 16.1 Matcher: Queryからraw pairまでのdrill-down

**方法論**

[Matcher](https://github.com/Merck/matcher)はmmpdbを基盤とし、変換とenvironmentをqueryし、transform統計、property-change plot、個別MMP構造へ段階的に移動できる。二つのpropertyを同時に扱う比較や、many-to-many fragment groupingも提供する。

**優れている点**

- Summary値の根拠となる実化合物をすぐ確認できる。
- 構造queryとproperty filterにより、目的に合う変換へ絞れる。
- 高レベルSummaryとraw evidenceが分断されない。

**現行CONDUCTORとの差**

CONDUCTORはTarget Reportから詳細CSVへ移れるが、Run全体のtransform → context → delta plot → individual pairという統一された導線を持たない。

### 16.2 CAS BioFinder: R-group replacement matrix

**方法論**

[CAS BioFinder MMPA](https://cas-biofinder.zendesk.com/hc/en-us/articles/37303631485965-March-2025-Matched-Molecular-Pair-Analysis-MMPA)は、交換前R-groupを一方の軸、交換後R-groupを他方の軸に置き、pActivity変化を色付きMatrixで示す。cellから完全構造とactivity changeを確認できる。

**優れている点**

- 多数の置換方向と効果をcompactに比較できる。
- 色でFavorable／Unfavorable patternを認識できる。
- Matrixから実構造へ移れる。

**現行CONDUCTORとの差**

現行はTarget単位の関係図に優れるが、Run全体の置換ruleを横断比較するViewを持たない。

### 16.3 Multi-property transformation heatmap

**方法論**

[Changらの6-membered heterocycle解析](https://pubmed.ncbi.nlm.nih.gov/27840138/)は、ring変換がlogD、microsomal metabolism、passive permeability、P-gp effluxへ与える影響を複数propertyのheatmapとして比較する。connecting atomによるcontextも調べる。

**優れている点**

- potencyだけでなく、多目的最適化上のtrade-offを一つの変換profileとして読める。
- 一方のpropertyを改善して別propertyを悪化させる変換を把握できる。

**現行CONDUCTORとの差**

現行A008は一つのEndpointを前提とし、別Run／別EndpointのMMP evidenceを同一変換へ統合しない。

### 16.4 OOMMPPAA: 3D binding-site visualization

**方法論**

[OOMMPPAA](https://pubmed.ncbi.nlm.nih.gov/25244105/)は、MMPの変更部分をbinding site中の位置へ投影し、activity differenceとpharmacophore differenceを3D表示する。

**優れている点**

- どの空間領域への置換がFavorableかを構造的に理解できる。
- 2D変換とprotein環境を接続できる。

**現行CONDUCTORとの差**

現行は2D構造だけである。ただし、信頼できるprotein–ligand poseがないRunへ3D表示を適用すると、見た目だけが高度で根拠の弱いReportになる。

## 17. 知識抽出・設計利用への高度化

### 17.1 Playbooks of Medicinal Chemistry Design Moves

**方法論**

[Playbooks of Medicinal Chemistry Design Moves](https://pubs.acs.org/doi/10.1021/acs.jcim.0c01143)は、大規模MMP Databaseから再利用可能な変換ruleを抽出し、新規構造生成へ利用する。

**優れている点**

- 過去dataの解析を、次に作る化合物候補へ接続する。
- 変換頻度や適用contextをmedicinal chemistry knowledgeとして蓄積できる。

**現行CONDUCTORとの差**

現行Type-IIIはDatabaseを作るが、変換ruleの優先順位付け、適用可能性、生成候補、根拠pairへのtraceabilityを一体化していない。

### 17.2 Retrosynthetic MMP

**方法論**

[Matched molecular pair-based data sets for computer-aided medicinal chemistry](https://pubmed.ncbi.nlm.nih.gov/24627802/)で扱われるretrosynthetic MMPは、reaction ruleに基づいてsynthetically meaningfulな変換を定義する。

**優れている点**

- 単なるgraph cutより、合成化学的に実行可能な変換へ近づけられる。
- 観測SARをdesign moveへ変換しやすい。

**現行CONDUCTORとの差**

現行は構造fragmentation由来であり、反応class、合成可能性、反応provenanceを持たない。

### 17.3 Prediction-driven MMP

**方法論**

[Prediction-driven matched molecular pairs](https://pmc.ncbi.nlm.nih.gov/articles/PMC4272757/)は、観測されたproperty deltaとmodelが予測したdeltaを比較し、modelが局所変換を正しく学習しているかを評価する。

**優れている点**

- 通常のGlobal予測指標だけでは見えない局所的model failureを発見できる。
- activity cliffや系統的な過小／過大予測を変換単位で説明できる。

**現行CONDUCTORとの差**

A005とA008は別々にReportされ、予測deltaと観測MMP deltaを接続していない。

## 18. 外部事例から明確になった比較結果

### Analysis unit接続に関係する知見

- 外部事例のcontext層別は、「同じ変換を異なる化学環境で比較する」方法として成熟している。
- CONDUCTORではchemical contextとは別に、analysis unit内／外というdata-defined contextを持てる。
- ただしAnalysis unitはEndpoint選抜後の集合なので、外部検証datasetと同じ意味にはならない。
- よって、unit情報はMMP件数を増やす重みではなく、変換supportを層別するmetadataとして扱うのが自然である。

### MMP自体の高度化に関係する知見

現行CONDUCTORより明確に優れている点は次である。

1. Direct pairだけでなく、同一変換の再現pair分布を調べる。
2. attachment周辺context別に変換効果を分ける。
3. direction、effect magnitude、uncertaintyを分けて評価する。
4. transform Summaryから根拠pairへdrill-downできる。
5. pairをMatched Molecular SeriesやSAR Matrixへ展開する。
6. 背景構造によるnonadditivityを検出する。
7. 複数propertyのtrade-offを変換profileとして示す。
8. 十分な3D根拠がある場合だけbinding-site情報へ接続する。
9. 観測MMPを予測model監査やcompound designへ再利用する。

一方、現行CONDUCTORがすでに優れている点もある。

- Targetを中心にExact CoreとNeighborを人間が読めるrelationship mapへ整理している。
- Target／Neighbor方向をReport上で統一する設計を持つ。
- Databaseの全行とHTMLの最小変換表示を分離している。
- pair数、Core多様性、robust effect statisticsの基盤をすでに持つ。
- analysis unitという独自の解析文脈へMMPを接続できる余地がある。

したがって、全面的に別のMMP systemへ置き換える必要はない。まず現行基盤の未利用情報とcorrectness課題を整理し、その後に外部事例のどこまでを採用するか議論するのが妥当である。

## 19. 参考資料

- Dalke A, Hert J, Kramer C. [mmpdb: An Open-Source Matched Molecular Pair Platform for Large Multiproperty Data Sets](https://pubs.acs.org/doi/10.1021/acs.jcim.8b00173). JCIM, 2018.
- Hussain J, Rea C. [Computationally Efficient Algorithm to Identify Matched Molecular Pairs](https://pubs.acs.org/doi/10.1021/ci900450m). JCIM, 2010.
- Papadatos G et al. [Lead optimization using matched molecular pairs](https://pubmed.ncbi.nlm.nih.gov/20873842/). JCIM, 2010.
- Warner DJ et al. [WizePairZ: A Novel Algorithm to Identify, Encode, and Exploit Matched Molecular Pairs with Unspecified Cores](https://pubmed.ncbi.nlm.nih.gov/20690655/). JCIM, 2010.
- Kramer C et al. [Matched Molecular Pair Analysis: Significance and the Impact of Experimental Uncertainty](https://pubmed.ncbi.nlm.nih.gov/24738976/). J Med Chem, 2014.
- Lukac I et al. [Turbocharging Matched Molecular Pair Analysis](https://pubmed.ncbi.nlm.nih.gov/28967750/). JCIM, 2017.
- Dossetter AG et al. [Matcher](https://github.com/Merck/matcher) and its [open manuscript](https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/63586c15aca19850f7e53e55/original/matcher-an-open-source-application-for-translating-large-structure-property-datasets-into-insights-for-drug-design.pdf).
- Gupta-Ostermann D, Bajorath J. [The use of matched molecular series networks for cross-target SAR translation](https://pubmed.ncbi.nlm.nih.gov/30108724/). MedChemComm, 2018.
- Gupta-Ostermann D, Bajorath J. [SAR Matrix method](https://pmc.ncbi.nlm.nih.gov/articles/PMC4215758/). 2014.
- Kramer C, Fuchs JE, Liedl KR. [Strong nonadditivity as a key SAR feature](https://pubmed.ncbi.nlm.nih.gov/25760829/). JCIM, 2015.
- Kramer C. [Nonadditivity Analysis](https://pubmed.ncbi.nlm.nih.gov/31508950/). JCIM, 2019.
- CAS BioFinder. [Matched Molecular Pair Analysis visualization](https://cas-biofinder.zendesk.com/hc/en-us/articles/37303631485965-March-2025-Matched-Molecular-Pair-Analysis-MMPA). 2025.
- Chang G et al. [A multi-endpoint matched molecular pair analysis of 6-membered heterocycles](https://pubmed.ncbi.nlm.nih.gov/27840138/). Bioorg Med Chem, 2017.
- Bradley AR et al. [OOMMPPAA: a tool to aid directed synthesis by the combined analysis of activity and structural data](https://pubmed.ncbi.nlm.nih.gov/25244105/). JCIM, 2014.
- Awale M et al. [The Playbooks of Medicinal Chemistry Design Moves](https://pubs.acs.org/doi/10.1021/acs.jcim.0c01143). JCIM, 2021.
- Hu Y et al. [Matched molecular pair-based data sets for computer-aided medicinal chemistry](https://pubmed.ncbi.nlm.nih.gov/24627802/). F1000Research, 2014.
- Sushko I et al. [Prediction-driven matched molecular pairs to interpret and optimize models](https://pmc.ncbi.nlm.nih.gov/articles/PMC4272757/). J Cheminform, 2014.
- Nittinger J et al. [Matched pairs demonstrate robustness against inter-assay variability](https://pmc.ncbi.nlm.nih.gov/articles/PMC11748845/). J Cheminform, 2025.
