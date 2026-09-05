# CONDUCTOR 0.1.11 A008 MMP大幅更新 引継ぎ・協議事項

Status: **MMP専用Version。仕様概要書・実装計画書作成済み、承認待ち・未実装。**

## 1. 位置付け

0.1.11はA008 MMPだけを大幅更新するVersionとする。0.1.10追補修正からMMP追加改修を外し、従来0.1.11で検討していたRuntime Supervisor、Endpoint選抜安定性、A005予測安定性、共通runner再編は0.1.12へ移管する。

- 0.1.10追補: MMP追加改修を行わない。
- 0.1.11: A008 MMP解析、情報抽出、Report／Interactive visualizationだけを扱う。
- 0.1.12: [`CONDUCTOR_0.1.12_handoff.md`](CONDUCTOR_0.1.12_handoff.md)の非MMP項目を検討する。

0.1.11の実装は、調査、事例dataによる試作、仕様概要書、実装計画書の承認後に開始する。

## 2. 参照文書

- 0.1.11仕様概要書: [`CONDUCTOR_0.1.11_specification_overview.md`](CONDUCTOR_0.1.11_specification_overview.md)
- 0.1.11実装計画書: [`CONDUCTOR_0.1.11_implementation_plan.md`](CONDUCTOR_0.1.11_implementation_plan.md)
- 現行仕様、課題、外部調査: [`research/mmp_transformation_evidence/report-source.md`](research/mmp_transformation_evidence/report-source.md)
- 旧Transformation evidence案: [`research/mmp_transformation_evidence/archive/2026-09-05_v1/report-source.md`](research/mmp_transformation_evidence/archive/2026-09-05_v1/report-source.md)
- 0.1.10実装済みMMP Report仕様: [`CONDUCTOR_0.1.10_specification_overview.md`](CONDUCTOR_0.1.10_specification_overview.md)

## 3. 0.1.11の目的

現行A008を、Target周辺MMPを列挙する機能から、次の二つを根拠付きで提供するMMP intelligence toolへ発展させる。

1. **Target explanation**: EndpointがFavorableになる向きをA → Bとしたとき、TargetまたはTarget対応構造がB側にあるEvidenceからFavorable要因を説明する。
2. **Target improvement opportunity**: 同じA → BにおいてTargetまたはTarget対応構造がA側にあるEvidenceから、実測済み改善NeighborまたはVirtual Candidateを探索する。

Direct／TransferredはEvidenceの接続性、explanation／improvementはTargetのA/B位置による解釈役割であり、独立した分類軸とする。

Analysis unitとの接続とMMP解析自体の高度化は、独立した設計軸として扱う。

## 4. 現時点で確定している方向

### 4.1 2 Mode化

現行Type-I／II／IIIを次へ集約する。

| Mode | 目的 |
|---|---|
| `target` | 人間指定Target、定型analysis unit Top 1、Global Top 1を同じTarget解析経路で処理する |
| `database` | Run全体のMMP Database、全pair、transform、core、context Summaryを構築する |

- 定型Targetには各採用analysis unitのTop 1とGlobal Top 1を含める。
- 人間が指定したRun内compound IDを主要なTarget指定方法とする。
- 同じTargetが複数selection sourceから選ばれても、MMP抽出と個別Reportは一度だけ作る。
- MMP探索母集団はTarget所属unit内ではなくRun全体とする。
- TargetでMMPが0件でも次順位へ自動補充しない。
- 旧Type parameterは互換adapterだけで扱い、新実装本体へ分岐を残さない。

### 4.2 Favorable方向と解釈役割を分離する

```text
EndpointがFavorableになる向き: A → B

TargetがA側: improvement
TargetがB側: explanation
```

この規則はDirect／Transferredの両方へ適用する。Direct MMPでTarget=AならTarget → 実測Neighbor BというObserved improvementであり、Target=Bなら実測Neighbor A → TargetというTarget explanationである。Transferred evidenceでも、Target対応構造がAならProposed improvement、BならTransferred explanationとなる。

内部値`favorable_gain`と表示上のFavorable Δは正値へ揃える。一方、同じ化学変換がcontextにより逆方向へ働く矛盾を検出するため、固定構造方向のsigned deltaとdirection-neutralなTransformation familyもDatabaseへ保持する。現行Type-IIのCSV SummaryとTarget HTMLで方向が一致しない問題も0.1.11で解消する。

### 4.3 Relationship map

0.1.10で試作・確認したTarget中心、Exact Core中間、Neighbor外周のmapを、Direct MMPの基礎Viewとして引き継ぐ。

- Targetは紺、Exact Coreは緑、Neighborはオレンジ。
- Neighbor cardにNeighbor側variable fragment、Endpoint、正値のFavorable Δを示す。TargetがBならNeighbor fragmentはBefore、TargetがAならAfterとなる。
- edgeは常にFavorable方向A → Bとし、Targetへ入る矢印をexplanation、Targetから出る矢印をObserved improvementとして区別する。
- 3／4／5 Coreの承認済みlayoutをreferenceとする。
- Report本文幅内の横長表示とし、表示上限超過時は省略数と詳細導線を示す。

## 5. MMP解析・情報抽出の協議軸

### 5.1 Exact Core以外のTransformation evidence

Targetから得られたExact Coreだけでなく、Run全体の別MMPから同じTransformationの情報を利用する。

現時点の候補分類は次である。

- `Exact-core evidence`
- `Radius-2 matched similar-core evidence`
- `Radius-1 matched related-core evidence`
- `Attachment-mapped but environment-mismatched reference`
- `Ambiguous / excluded`

Core全体の類似性、Attachment point対応、Environment一致を別々に評価する。

### 5.2 Attachment mapping

Environmentが異なる場合でも、大局的に同じ変換位置であることを判定できる仕組みを検討する。

第一候補はAttachment-constrained MCSである。

- attachment dummy／labelを保持する。
- Attachmentを含むMCSだけを許可する。
- custom atom comparator、seed、final match checkを使用する。
- 同率MCS mappingを列挙し、unique、symmetry-equivalent、ambiguous、failedへ分類する。
- MCS対応部分、Attachment、Radius 1/2、非対応部分を色分けする試作図を事例dataで評価する。

Core similarityは候補検索／順位付け、Attachment-constrained MCSは位置対応、Environmentは変換適用可能性と効果差の解釈に使用する。

### 5.3 Environment解析

- radius 0–2を入れ子のcontextとして扱う。
- 同じpairをradiusごとに重複Evidenceとして数えない。
- Environment一致は転用可能性の判定だけでなく、Environment差によるeffect反転を理解するためにも使用する。
- Environment不一致だがAttachment mappingが一意なcaseは、統合Evidenceではなく比較referenceとして扱う方向で検討する。

### 5.4 Analysis unitとの接続

Analysis unit情報はMMP検出の前提にせず、Canonical MMPへ重ねるmetadataとする方向で検討する。

- Target／Neighborの所属unit
- pairがunit内部、境界、unit外のどこにあるか
- 同じtransformが複数unitで支持されるか
- Cross-representation Core／Core／Fringeとの関係

複数unitへの所属行を独立MMP数として重複計上しない。

### 5.5 Target explanation／improvement routing

MMPがTargetへ直接接続するかではなく、Favorable-oriented A → Bのどちら側へTargetが位置するかで解釈する。

| 接続 | Target位置 | 役割 |
|---|---|---|
| Direct | A | 実測済みObserved improvement |
| Direct | B | Target explanation |
| Transferred | A | Proposed improvement／Virtual Candidate |
| Transferred | B | Transferred explanation |

Transferred evidenceでTargetがA側に対応する場合は、Targetへ適用可能な変換を探索する。

概念flowは次とする。

```text
Run全体のobserved transformation
  → TargetがBefore fragmentを持つか
  → Target上のAttachment位置をmappingできるか
  → EnvironmentとCore類似性は十分か
  → After fragmentへ変換したVirtual Candidate
  → 根拠pair、効果分布、矛盾を提示
```

Virtual Candidateは未測定の仮説であり、観測MMPと明確に区別する。

## 6. 1-cut／2-cutの協議

### 6.1 Motivation

1-cutは末端置換の解釈性が高い。一方、2-cutでは概念的に次を扱える。

```text
A—B—C  →  A—B'—C
```

2本のbondを切ると、AとCが二つのconstant fragment、中央のB/B'が二点接続variable fragmentになる。これによりlinker replacement、central heterocycle replacement、ring／scaffold replacementの一部を抽出できる可能性がある。

ここで、創薬化学上はBを「core部分」と呼ぶ場合があるが、MMPのfragment表現では交換されるB/B'が`variable`、保持されるAとCが`constant`である。この語義をReportとSchemaで混同しない。

2-cutが特に有効なのは、同じ二つのanchorを保ったlinker長、linker原子、中央heterocycle等の交換である。一方、同じA/Cへ分離できないfused ring再編、標準fragmentationでring bond切断を要する変更、三点以上の接続を保つ変更は、2-cutだけでは安定して表現できない。これらを無理に2-cutへ含めず、Attachment-constrained MCS等の別Evidence classへ回す。

### 6.2 想定noise

- 小さすぎるAまたはCによる意味の薄いmatch
- 1-cutでも表現できる変換の冗長な2-cut表現
- variable fragmentが大きすぎ、局所変換と呼びにくいpair
- attachment label順序、対称性、mappingの曖昧さ
- contextの異なるpairの混在
- 2-cut pair数増加によるReport過密化
- ring bond切断や化学的に不自然なfragmentation

### 6.3 現時点の原則候補

- 1-cutをPrimary、2-cutを独立した`linker/scaffold transformation` classとし、件数と統計を混ぜない。
- Canonical Databaseには品質条件を満たす2-cutを保存できるが、標準Target Reportへ全件を自動展開しない。
- 1-cutへ還元できる2-cut表現は1-cutを優先する。
- 両constant fragment、combined constant、variable fragment、attachment topologyへ明示的なsize／構造条件を置く。
- attachment mappingがambiguousな2-cutは標準Evidenceから除外する。
- 2-cutの具体的閾値、ring規則、support条件、表示上限は事例評価後に決める。

これは確定仕様ではなく、次の協議事項である。

### 6.4 情報品質を担保する処理案

2-cutは「検出」「Evidence採用」「標準表示」を別々に制御する。Endpoint差が大きいpairだけを検出時に残すと選抜biasが入るため、構造適格性と効果Evidenceを分離する。

#### Stage 1: 構造候補の生成

- 1-cutと2-cutを別classとして生成し、`cut_count`を必須provenanceにする。
- 二つのattachment label、向き、constant fragmentの順序をcanonical化する。
- 対称性により複数mappingが生じる場合は、同値mappingか真の曖昧性かを記録する。

#### Stage 2: Hard structural gate

標準Evidence候補には少なくとも次を要求する方向で検討する。

- variable fragmentは連結成分一つで、attachment pointが正確に二つである。
- 両constant fragmentがそれぞれ十分なheavy atomを持つ。mmpdbの実装知見では、各constant fragmentの最小heavy atom数を3または4にすると、極小fragmentをanchorとする不要なmultiple-cutを大きく抑えられる。
- 二つのconstant fragmentを合計した保持構造が、pair両側で十分な割合を占める。
- B/B'が大きすぎる場合は、局所Transformationではなく広いscaffold changeとして別classへ送る。
- attachment対応が一意またはsymmetry-equivalentである。ambiguous mappingは標準Evidenceに使わない。
- valence、芳香族性、stereochemistry、分子内接続を再構成後に検証する。
- 1-cutへ還元できる表現には`reducible_to_1cut`を付け、標準表示では1-cutを優先する。

`min_heavies_per_constant_fragment`、`minimum_retained_fraction`、`maximum_variable_heavies`等の数値は設定値として保存する。ただし最終値は、実データのpositive／negative caseでprecisionとcoverageを比較してから決める。

#### Stage 3: Canonical化と重複排除

同じcompound pairから複数のcut表現が得られるため、次の順に代表Evidenceを決める。

1. 化学的に同じ変換なら1-cutを優先する。
2. 2-cut同士では、両anchorが大きく、保持構造割合が高く、mappingが一意な表現を優先する。
3. 非包含で別の二点変換を表す場合は両方を保持するが、独立pair数はcompound pair単位で重複計上しない。

#### Stage 4: Evidence評価

構造gate通過後に、次を別列で評価する。

- unique compound-pair数
- unique constant-context数
- Endpoint deltaの中央値、分布、方向一致率
- Radius 0/1/2のEnvironment一致
- Targetへのattachment mapping confidence
- 支持Evidenceとconflicting Evidence

単一の不透明な総合scoreだけで合否を決めず、まず各根拠を表示可能な列として保持する。Radius違いや複数analysis unit所属を独立Evidenceとして水増ししない。

#### Stage 5: 標準Reportへの掲載

- `1-cut: terminal substitution`と`2-cut: linker/core replacement`を別tab／sectionに分ける。
- 初期表示は、構造gateを通過し、Targetへ適用位置を一意に対応でき、Evidence品質が高い候補に限定する。
- 支持数不足だが直接観測された2-cutは、低信頼として折り畳む。曖昧mapping、極小anchor、1-cut冗長表現は標準画面へ出さず、詳細dataまたは除外理由Summaryから確認できるようにする。
- TargetがFavorable側Bなら、Direct／Transferredを問わずexplanationへ送る。
- Targetが非Favorable側Aなら、Direct pairは実測済みimprovement、Transferred evidenceはVirtual Candidate候補へ送る。
- predictionとobservation、DirectとTransferredは独立labelで示す。

### 6.5 暫定品質class

| Class | 意味 | 初期表示 |
|---|---|---|
| `2C-A` | 両anchorが十分、mappingが一意、1-cut非冗長、Target context適合、複数Evidenceあり | 表示 |
| `2C-B` | 構造的には妥当だが、支持数またはEnvironment適合が弱い | 折り畳み |
| `2C-X` | mapping曖昧、極小anchor、1-cut冗長、再構成不正等 | 非表示／除外理由のみ |

このclassはReportの情報量制御用であり、Databaseから都合の悪いEndpoint結果を消すものではない。

### 6.6 検証方針

件数が増えたことを成功条件にしない。次のfixtureを用意し、標準表示された`2C-A`のprecisionを最優先で確認する。

- A-B-C → A-B'-Cの明確なlinker交換
- 1-cutへ還元できる冗長な2-cut
- AまたはCが1～2 heavy atomしかないnoise
- 対称構造でattachment順序が同値なcaseと曖昧なcase
- ring切断を要求するcase
- 同じ2-cut transformが複数contextで同方向／逆方向を示すcase
- Targetへ適用するとvalenceまたはstereochemistryが破綻するcase

評価指標は、`2C-A`表示精度、既知有用変換のcoverage、1-cut重複率、ambiguous mapping混入率、1 Target当たりの初期表示件数とする。

### 6.7 技術的根拠

[mmpdb公式文書](https://github.com/rdkit/mmpdb)は、1、2、3本のnon-ring bond切断を扱い、cut数と同じ数のconstant fragmentと、一つのvariable fragmentを生成する。2-cut自体は確立したfragmentation表現であり、CONDUCTOR固有の新概念ではない。

一方、[mmpdb changelog](https://github.com/rdkit/mmpdb/blob/master/CHANGELOG.md)も、multiple-cutでは一原子程度の極小constant fragmentや1-cutへ還元できる冗長変換が増えることを明記している。`min-heavies-per-const-frag`と`smallest-transformation-only`が導入されているため、CONDUCTORでも同種のnoise制御を最低条件とし、その上にTarget適用性とReport表示制御を加える。

## 7. Interactive Reportの目標

Target個別ReportはPCワイド画面の`100dvh`相当へ収め、基本情報から複数の深さへ進めるoffline workspaceとする。初期Relationship Map、Neighbor clickによるcompact detail、Core clickによる関連MMP一覧、View切替を一画面内で提供する。

```text
Target overview / Direct relationship map
├─ Explanation: Target is favorable-side B
│  ├─ Direct A → Target B
│  ├─ Transferred A → Target-like B
│  └─ Exact Core / Environment detail
├─ Improvement: Target is less-favorable-side A
│  ├─ Direct Target A → observed Neighbor B
│  ├─ Transferred Target A → Virtual Candidate B
│  └─ Supporting / conflicting pairs
└─ Explore evidence
   ├─ Core alignment
   ├─ Radius 0/1/2
   ├─ Analysis unit scope
   └─ Canonical pair detail
```

表示はprogressive disclosureとし、初期画面へ全MMP Tableを展開しない。HTML内のfilter、sort、toggle、hover、detail drawer等を候補とするが、具体的GUIは事例dataで試作してから承認する。

## 8. 0.1.11で扱わない項目

- Bounded Runtime Supervisor
- Endpoint選抜安定性
- A005予測安定性
- 共通runner再編
- MMPと無関係なDescription／Clustering仕様変更

これらは0.1.12へ引き継ぐ。

## 9. 次の協議事項

1. 2-cutを標準Databaseへ含める条件
2. 2-cutを標準Target Reportへ表示する条件
3. 両constant fragmentとvariable fragmentのsize閾値
4. Attachment mappingのbenchmarkと合否条件
5. Core similarity metricと閾値
6. Radius別Evidenceの扱いとeffect反転表示
7. Target improvement候補のranking項目
8. Virtual Candidate生成時の化学構造validation
9. Analysis unit情報を初期表示する範囲
10. Interactive HTMLの最小機能と最大表示件数
