# CONDUCTOR 0.1.11 A008 MMP大幅更新 仕様概要書

Status: **承認前Draft。MMP専用Version。未実装。**

## 1. 文書の位置づけ

本書は、0.1.11で実施するA008 MMP大幅更新の仕様案を、これまでの協議内容に基づいて統合したものである。0.1.10で実装済みのMMP Reportをbaselineとし、解析、情報抽出、Target improvement、Interactive HTMLを一体として再設計する。

- 0.1.10: A003、Schema、Series、Report監査、Prompt等の追補。MMP追加改修は行わない。
- 0.1.11: A008 MMPだけを大幅更新する。
- 0.1.12: Runtime Supervisor、Endpoint選抜安定性、A005予測安定性、共通runner再編を扱う。

0.1.11の実装は、本書と[`CONDUCTOR_0.1.11_implementation_plan.md`](CONDUCTOR_0.1.11_implementation_plan.md)の承認後に開始する。

## 2. 目的

0.1.11では、A008をTarget周辺のMMP列挙機能から、次の二つを根拠付きで提供するMMP intelligence toolへ発展させる。

1. **Target explanation**: EndpointがFavorableになる向きを`A → B`としたとき、TargetまたはTargetに対応する構造がB側にあるEvidenceから、TargetのFavorable要因を説明する。
2. **Target improvement opportunity**: 同じ`A → B`においてTargetまたはTargetに対応する構造がA側にあるEvidenceから、実測済みの改善NeighborまたはVirtual Candidateを提示する。

MMPがTargetへ直接接続するか、別Coreで観測された間接Evidenceかは、説明／改善とは別の分類軸である。Direct MMPにもTarget改善があり、Transferred evidenceにもTarget説明がある。

製品目標は、PCワイド画面で利用するoffline Interactive HTMLである。Web server、Web API、account、外部Databaseは0.1.11では要求しない。

## 3. 非対象

- 3-cutの標準解析
- ring bondを自由に切断する一般的scaffold hopping
- 3D binding-site解析
- 合成可能性の保証または合成route設計
- Virtual CandidateのEndpoint値を確定値として予測すること
- MMP以外のA003–A007、A009、Series形成の仕様変更
- Runtime Supervisor等、0.1.12へ移管済みの項目

## 4. 用語と責務

| 用語 | 意味 |
|---|---|
| Observed pair | Run内の二つの実測化合物から得たcanonicalなMMP pair |
| Transformation | variable fragmentの`From → To`置換規則 |
| Exact Core | attachment pointを含み、pair内で厳密に保持されたconstant構造 |
| Environment | attachment point周辺のradius 0–2の局所構造 |
| Favorable-oriented pair | EndpointがFavorableになる向きを`A → B`とし、表示上の`Favorable Δ`を正値へ揃えたpair |
| Connection scope | Targetを実測pairに含む`direct`か、別pairから対応付けた`transferred`か |
| Interpretation role | Target対応構造がA側なら`improvement`、B側なら`explanation` |
| Direct evidence | Target自身を一端に含むObserved pair |
| Transferred evidence | Targetを含まないObserved pairから、Targetへの適用可能性を評価したEvidence |
| Virtual Candidate | 観測TransformationをTargetへ適用して生成した未測定構造 |
| Analysis unit metadata | Target／NeighborのSeries・Cluster所属情報。MMP数を増やすEvidenceではない |

2-cutの`A—B—C → A—B'—C`では、創薬化学上Bをcore部分と呼ぶ場合があるが、MMP内部では交換されるB/B'が`variable`、保持されるA/Cが`constant`である。SchemaとReportではこの語義を混同しない。

## 5. 実行Mode

現行Type-I／II／IIIを二つのModeへ集約する。

| 表示名 | CLI／contract値 | 目的 |
|---|---|---|
| Mode I: Target analysis | `target` | 自動選抜または人間指定Targetを解析し、個別Interactive HTMLを生成する |
| Mode II: Database build | `database` | Run全体のcanonical MMP Databaseと集計Artifactを構築する |

### 5.1 Mode IのTarget

定型実行では次の和集合をTargetとする。

- 各採用analysis unitのEndpoint Top 1
- Run全体のEndpoint Top 1
- 人間が明示したRun内compound ID

同じcompound IDが複数sourceから選ばれても、MMP抽出と個別HTMLは一度だけ作る。Target registryには全selection sourceを保持する。

Endpoint同値時は、入力順に依存せずcompound ID昇順で決定する。Favorable方向はRun contractを使用する。Run外compound IDは受け付けない。

TargetにDirect MMPが0件でも、Target registry、個別HTML、A009からの導線を作る。Target improvement候補がある場合はDirect MMPが0件でも別枠で示す。

### 5.2 Mode IIの役割

Mode IIは、Run全体の1-cut／2-cut pair、Transformation、Exact Core、Environment、効果統計を一度だけ構築する。Mode Iはこのcanonical Databaseをqueryし、同じ全体fragmentationをTargetごとに繰り返さない。

Target improvementにRun全体Evidenceが必要なため、定型A008ではMode IIをMode Iの前提処理として実行または再利用する案を推奨する。この自動前提化は最終確認事項とする。

### 5.3 旧Typeとの互換

0.1.11では旧parameterを互換adapterで次へ変換し、deprecation warningと変換結果をmanifestへ記録する。

| 旧指定 | 変換先 |
|---|---|
| Type-I | `target`＋analysis unit Top 1＋Global Top 1 |
| Type-II | `target`＋人間指定Target |
| Type-III | `database` |

新engine内部には3 Type別の科学計算分岐を残さない。

## 6. Canonical dataと方向

### 6.1 Canonical pair

compound pairはunit所属、Target指定、radiusに依存しない一つの`pair_id`として保存する。同じpairが複数analysis unitや複数radiusに現れても、独立pair数を増やさない。

Databaseでは方向中立なcanonical pair、構造変換の固定方向、Endpointに基づくFavorable-oriented viewを分離する。

- `compound_x_id`、`compound_y_id`
- 両側のSMILESとEndpoint
- fixed structural directionの`directed_transform_id`とsigned delta
- direction-neutralな`transformation_family_id`
- `favorable_from_compound_id`（A）
- `favorable_to_compound_id`（B）
- 正値の`favorable_gain`
- `connection_scope`と`interpretation_role`を持つTarget別Evidence view
- `effect_semantics`

row順から方向を推測してはならない。

### 6.2 Report上の方向

Favorable方向の符号をRun contractから決め、化合物XからYへの正規化変化を次で計算する。

```text
Higher-is-favorable: normalized_delta(X → Y) = Endpoint(Y) - Endpoint(X)
Lower-is-favorable:  normalized_delta(X → Y) = Endpoint(X) - Endpoint(Y)
```

`normalized_delta > neutral tolerance`となる向きをA → Bとし、内部値`favorable_gain`とReport上の`Favorable Δ`は常に正値とする。逆向きならX/Yを入れ替える。閾値内は`neutral`とし、無理にA/Bへ振り分けない。

Targetとの関係は次のように分類する。

| Connection scope | Target対応位置 | Interpretation role | 表示内容 |
|---|---|---|---|
| Direct | A側 | Observed improvement | Target → 実測済みのよりFavorableなNeighbor B |
| Direct | B側 | Target explanation | 実測Neighbor A → Target |
| Transferred | A側 | Proposed improvement | Target → Virtual Candidate Bと根拠pair |
| Transferred | B側 | Transferred explanation | A → Target類似構造Bとなる別Core Evidence |

したがって、一つのTarget Report内に説明Evidenceと改善Evidenceの両方が存在し得る。TargetがGlobal Top 1なら説明が多くなりやすいが、Hit-to-LeadのHitをTargetにした場合はDirect improvementも重要な主結果となる。

Favorable方向へpairを並べ替えても、反対方向の効果を消してはならない。Transformation集計では、direction-neutralなfamilyと固定構造方向のsigned deltaを保持し、同じ置換がcontextによって逆転した場合をconflicting Evidenceとして検出する。

### 6.3 表示と集計の独立軸

各Target Evidenceは少なくとも次の三軸を別々に持つ。

- `connection_scope`: direct／transferred
- `interpretation_role`: explanation／improvement／neutral
- `observation_status`: observed／virtual

説明／改善はViewを分けるが、Direct／Transferredはfilterとprovenanceとして両View内に表示できる。ObservedとVirtualは同じ件数に合算しない。

### 6.4 重複の扱い

- 同じTargetの複数selection sourceはTarget provenanceであり、Target数を増やさない。
- 同じpairの複数unit接続はmembership provenanceであり、pair数を増やさない。
- radius 0／1／2は入れ子のEnvironmentであり、三つの独立Evidenceとして数えない。
- 同一Target–Neighborに複数Exact Coreがある場合、Databaseは保持し、Reportは包含される小さいCoreを除いた最小変換を優先する。
- 1-cutへ還元できる2-cutは`reducible_to_1cut`を付け、標準表示では1-cutを優先する。

## 7. Fragmentation scope

### 7.1 1-cut

1-cutをPrimaryな`terminal substitution`として維持する。現行のnon-ring bond切断、radius 0–2、Target／Neighbor orientationをbaselineとする。

### 7.2 2-cut

2-cutを独立した`linker/core replacement` classとして追加する。

```text
A—B—C → A—B'—C
```

対象例はlinker長、linker原子、中央heterocycle、二点接続ringの交換である。1-cutと件数、統計、UIを分ける。

標準Evidence候補には次のHard structural gateを適用する。

- variable fragmentは一つの連結成分でattachment pointが正確に二つ。
- 二つのconstant fragmentをcanonicalなattachment順で保持する。
- 両constant fragmentがそれぞれ最小heavy atom数を満たす。
- combined constantがpair両側で最小保持割合を満たす。
- variable fragmentが最大heavy atom数または最大分子割合を超えない。
- attachment mappingがuniqueまたはsymmetry-equivalent。
- 再構成後のvalence、芳香族性、stereochemistry、分子内接続が妥当。
- 1-cutへ還元できる冗長表現を標準2-cut Evidenceへ含めない。

ring bond切断と3-cutは0.1.11標準から除外する。

### 7.3 2-cut品質class

| Class | 意味 | 標準表示 |
|---|---|---|
| `2C-A` | 両anchorが十分、mappingが一意、1-cut非冗長、Target context適合、支持あり | 初期表示 |
| `2C-B` | 構造的には妥当だが、支持数またはEnvironment適合が弱い | 折り畳み |
| `2C-X` | mapping曖昧、極小anchor、1-cut冗長、再構成不正等 | 非表示。除外理由だけ監査可能 |

Endpoint差が大きいことをfragmentationの採否条件には使用しない。構造適格性とEndpoint Evidence評価を分離する。

## 8. Transformation evidence

### 8.1 Evidence分類

Direct／Transferredのどちらについても、Targetとの構造対応を次の順に分類する。

1. `Exact-core evidence`
2. `Radius-2 matched similar-core evidence`
3. `Radius-1 matched related-core evidence`
4. `Attachment-mapped but environment-mismatched reference`
5. `Ambiguous / excluded`

Core全体の類似性、Attachment point対応、Environment一致を別項目として評価する。

### 8.2 Attachment mapping

Exact Coreでない候補にはAttachment-constrained MCSを使用する方向とする。

- attachment dummy／labelを保持する。
- Attachmentを含まないMCSを採用しない。
- 同率mappingを列挙する。
- `unique`、`symmetry_equivalent`、`ambiguous`、`failed`に分類する。
- ambiguous／failedはTransferred explanation／improvementの標準候補にしない。

可視化では次を使用する。

- MCS対応部分: 同じ色
- Attachment point: 赤
- Radius 1／2 Environment: 段階的な色
- 対応しないCore部分: 灰色

### 8.3 Environment

radius 0–2を親子関係のある局所contextとして保存する。大きいradiusほどspecificなEvidenceであるが、常に優れているとは限らない。

- Radius-2一致: 強い局所対応
- Radius-1一致: 関連する局所対応
- Environment不一致＋一意Attachment mapping: 効果差を考察するreference
- mapping不能: 除外

Environment不一致Evidenceを平均へ混ぜず、supporting／conflicting referenceとして分離する。

### 8.4 Evidence Summary

Transformationごとに少なくとも次を保存する。

- unique compound-pair数
- unique compound数
- unique Exact Core／constant-context数
- 固定構造方向のsigned deltaと、Target別の正値Favorable gainのmedian、IQR、min、max
- Favorable方向一致率
- supporting pairとconflicting pair
- 利用可能な最大Environment radius
- mapping statusとmapping confidence
- cut countと2-cut品質class

`independent_compound_count`という名称は使わない。unique数は統計的独立性を保証しないためである。

## 9. Target explanation／improvement routing

### 9.1 Direct MMP

Targetへ直接接続するMMPを、TargetがFavorable-oriented pairのどちら側にあるかで分ける。

- TargetがB側: Neighbor A → Target Bであり、Target explanationへ表示する。
- TargetがA側: Target A → Neighbor Bであり、実測済みObserved improvementへ表示する。
- neutral: Endpoint差のない構造変換としてEvidence viewへ残すが、説明／改善の主結果へ含めない。

Direct MMPを一律にTarget explanationとみなさない。

### 9.2 Transferred evidence

Targetを含まないObserved Transformationについて、Targetまたは類似CoreがA/Bのどちらへ対応するかをAttachment mappingで判定する。

- TargetがB側へ対応: 別CoreでA → BがFavorableだったことをTransferred explanationとして示す。
- TargetがA側へ対応: TargetへB側変換を適用するProposed improvementとして評価する。
- Targetが両側へmapping可能、または対応が一意でない: ambiguousとして標準表示しない。

### 9.3 Proposed improvementとVirtual Candidate

TargetがA側へ対応するRun全体のObserved Transformationから、Targetへ適用可能な改善候補を探索する。

```text
Observed Transformation
  → EndpointのFavorable方向をA → Bへ正規化
  → TargetがBefore fragmentを持つか
  → TargetがA側へ一意に対応するか
  → Attachment位置を一意にmappingできるか
  → Environment／Core条件を満たすか
  → After fragmentへ置換
  → RDKitで構造を再構成・検証
  → Supporting／conflicting Evidenceとともに表示
```

Virtual Candidateは次を満たす場合だけ生成物として保存する。

- sanitize可能
- valence妥当
- attachment数と順序が一致
- 元Targetと同一構造でない
- Run内既存化合物との一致判定済み
- stereochemistryの保持／未定義化を明示

Virtual Candidateに対し、観測Endpoint、確定的改善、合成可能性を主張しない。予測値を表示する場合もObserved delta分布からの参考推定として明示する。

## 10. Analysis unitとの接続

Analysis unit情報はcanonical MMPへ重ねるmetadataとする。

- Target／Neighborが所属する採用Series／Cluster
- Series内のCross-representation Core／Core／Fringe
- 同じTransformationが複数unitに現れるか

複数unit所属を独立Evidenceとして数えない。Cross-representation CoreをTarget選択、A007構造、MMP件数の重みへ使用しない。

Interactive Map上のunit表示は任意機能とし、初期状態では非表示とする。必要な場合だけbadge／filterで確認できる設計を候補とする。

## 11. PCワイド画面向けInteractive HTML

### 11.1 基本方針

Target個別HTMLを、縦長Reportではなく一画面内で表示内容を切り替えるoffline workspaceとする。

- 対象画面: desktop幅1,280 px以上を主対象
- workspace: `100dvh`相当。headerを除く領域をMap／Table／Drawerで使用
- desktopではpage全体を縦scrollさせず、DrawerとTableだけを内部scroll
- 外部CDN、Web API、serverを要求しない
- 化学計算、mapping、Evidence判定はPython側で完了する
- JavaScriptはfilter、sort、選択、表示切替だけを担当する

狭い画面では機能を削らず縦積みへfallbackするが、0.1.11の最適化対象はPCワイド画面とする。

### 11.2 画面構成

```text
┌ Target header / Endpoint / selection source / legend ┐
├ Map | Explanation | Improvement | Evidence tabs ────┤
│                                                       │
│ Main workspace                         Detail drawer  │
│ Map / compact table / evidence view    380–460 px     │
│                                                       │
└ Status / shown count / detailed CSV link ─────────────┘
```

Drawerを閉じた状態ではMain workspaceを全幅で使う。Drawerを開いてもviewport内に収め、巨大なModalやpage下部への追加表示は行わない。

### 11.3 初期Relationship Map

- Targetを中央、Exact Coreを中間、Neighborを外周に配置する。
- Targetは紺、Exact Coreは緑、Neighborはオレンジ。
- Target cardを最大、Core cardを小さく、Neighbor cardをさらにcompactにする。
- Neighbor cardには小さいNeighbor側variable fragment、compound ID、Endpoint、改行した正値のFavorable Δだけを示す。Target=BのexplanationではNeighbor fragmentがA／Before、Target=AのimprovementではNeighbor fragmentがB／Afterとなる。
- 初期表示は最大5 Core、各Coreの`favorable_gain`上位3 Neighborを基本案とする。
- 省略分は`+N`で示し、Core clickで全関連MMP一覧を開く。
- Mapは利用可能な幅と高さへfitし、3／4／5 Coreで確認済みのradial layoutを基準とする。
- Direct pairの矢印は常にFavorable方向A → Bとする。Targetへ入る矢印はexplanation、Targetから出る矢印はObserved improvementを表す。
- Direct explanation／improvementはbadgeとarrow directionで区別し、Neighbor色だけで意味を表さない。

### 11.4 Neighbor click

NeighborをclickするとTarget–Core–Neighbor経路を強調し、他Nodeを薄くする。右Drawerには次をcompactに示す。

- Target／Neighborのalign済み全体構造
- Before → After fragment
- Target／Neighbor IDとEndpoint
- 正値のFavorable Δ
- Direct／Transferred、explanation／improvement、observed／virtualの各分類
- 1-cut／2-cut
- Exact Core、Environment radius、Evidence class
- Supporting／conflicting Evidenceへの導線

Drawer内の構造は比較可能な大きさに限定し、画面を覆うModalを使用しない。

### 11.5 Core click

Coreをclickすると右DrawerをCore viewへ切り替える。

- Core構造とAttachment point
- MMP数、Neighbor数
- median Favorable Δと範囲
- 関連MMPのcompact table
- `favorable_gain`上位5件を初期表示
- Table行clickでNeighbor detailへ切替

### 11.6 View切替

- `Map`: Targetへ直接接続する実測MMPの俯瞰。Favorable方向の入出力で説明／改善を区別
- `Explanation`: TargetがB側に対応するDirect／Transferred evidence
- `Improvement`: TargetがA側に対応する実測NeighborとVirtual Candidate
- `Evidence`: 全Observed pair、Exact／similar Core、Environment、support／conflictのdrill-down

選択中Target、Core、Neighbor、filter状態はView切替後も保持する。Escape、close button、Map空白clickでDrawerを閉じる。

### 11.7 Tableと導線

- Tableはsort、text filter、cut class filter、Evidence class filterに対応する。
- 詳細CSVリンクは各Viewの最下部または固定footerに置く。
- HTMLへ埋め込むのは表示対象Evidenceと表示用metadataに限定する。
- 未縮約全列、全pair、除外行はCSV／SQLiteに保持する。

## 12. 全体Report

Mode Iの全体ReportはTarget indexとして使用する。

- Target IDと構造
- Endpoint
- selection source一覧
- Direct explanation／Observed improvement件数
- Transferred explanation／Proposed improvement件数
- 1-cut／2-cut内訳
- 個別Interactive HTMLへのlink

同じTargetをunitごとに重複card化せず、一つのTarget cardにsource unit一覧を示す。

Mode IIのDatabase Summaryは、全pair数、1-cut／2-cut内訳、Transformation数、quality class、除外理由、Environment coverage、主要CSV／SQLiteへの導線を示す。個別Target Reportとは分離する。

## 13. Artifact契約案

```text
operators/A008/
├── mmp_database.sqlite
├── mmp_database_manifest.json
├── mmp_pair_detail.csv
├── transformation_summary.csv
├── context_summary.csv
├── two_cut_quality_summary.csv
├── target_registry.csv
├── mmp_report_index.json
├── mmp_report.html
├── mmp_database_report.html
├── targets/
│   ├── mmp_target_<compound_id>_<hash>.html
│   ├── target_evidence_<compound_id>.csv
│   └── virtual_candidates_<compound_id>.csv
└── assets/
    └── generated structure SVG files when needed
```

具体的filenameは既存A009導線との互換性を確認して固定する。HTML単体の可搬性よりも、Run Artifact全体の自己完結性とlink監査可能性を優先する。

## 14. Templateと監査

- HTMLはVersion付きcanonical Templateだけから生成する。
- Template ID、Version、hashをmanifestへ記録する。
- JavaScriptとCSSはrepository管理し、外部CDNへ依存しない。
- HTML文字列、ID、SMILES、SMARTSをescapeし、`eval`を使わない。
- Report監査はDOM、link、件数、filter対象、click後の表示内容を機械確認する。
- LLM Vision、Screenshot解釈、画像内容のAI判定は禁止する。
- 化学構造の正しさは元SMILES、描画成功、mapping atom index、生成物validationで検証する。

## 15. 互換性

- 0.1.10以前の完了Run Artifactを書き換えない。
- 0.1.11の新規Runだけへ新Database schemaとInteractive HTMLを適用する。
- 0.1.10のMMP HTML rendererはlegacy fixtureとして保持する。
- 旧3 Type入力は0.1.11で互換adapterを通すが、新Artifactは2 Mode用語だけを使用する。
- A009は巨大なpair dataを読まず、`mmp_report_index.json`だけからTarget導線を生成する。

## 16. 確定済み事項

- 0.1.11はMMP専用Versionである。
- 2 Modeへ集約する。
- Mode Iに各analysis unit Top 1、Global Top 1、人間指定Targetを含められる。
- Target探索母集団はRun全体である。
- 同じTargetは一度だけ解析・Report化する。
- Relationship Mapは個別HTML最上部の初期Viewである。
- Targetは紺、Coreは緑、Neighborはオレンジとする。
- Map clickからNeighbor detail／Core MMP一覧へ移動する。
- PCワイド画面内で表示を切り替え、詳細はcompact Drawerに出す。
- 1-cutをPrimary、2-cutを独立classとする。
- Analysis unit所属は保存するが、Mapでの明示はoptionalである。
- Target explanationとTarget improvementを分離する。
- Direct／Transferredと説明／改善を独立した分類軸にする。
- MMPの表示方向はFavorable Δが正となるA → Bへ揃える。
- 0.1.11ではWeb GUI／APIを導入しない。

## 17. 実装前の最終確認事項

次は設計方針が未確定、または数値を事例評価で固定する必要がある。

1. Mode IIを定型A008で常に先行実行するか。
2. 2-cut Hard gateの数値。
3. Transferred evidenceを説明／改善へ初期表示する最低support。
4. similar Coreの候補検索metricと閾値。
5. Virtual Candidateを0.1.11で構造生成まで行うか、Transformation候補提示までに留めるか。
6. 初期Map上限を5 Core × 3 Neighborで固定するか。
7. Target HTMLの容量、初期描画時間、最大埋め込みEvidence件数の合格値。
8. Endpoint差をneutralとみなすtolerance。測定誤差情報がなければ0を推奨する。

推奨案と比較方法は実装計画書に示す。数値閾値は、代表的なpositive／negative caseを用いた事前benchmark後に人間が承認する。
