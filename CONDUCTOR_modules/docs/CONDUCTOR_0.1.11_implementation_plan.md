# CONDUCTOR 0.1.11 A008 MMP大幅更新 実装計画書

Status: **Report再設計を実装中。A008_v10は人間評価で不合格。再生成物の確認前は完了扱いにしない。**

## 1. 目的と前提

本書は、[`CONDUCTOR_0.1.11_specification_overview.md`](CONDUCTOR_0.1.11_specification_overview.md)を実装するための作業順、test、human checkpointを定める。

0.1.11はA008 MMP専用Versionである。0.1.10追補作業と、0.1.12へ移管したRuntime等の作業を混在させない。

設計上の必須判断は本書へ反映済みである。実装開始時は0.1.10追補のMMP非対象境界を維持し、本文で指定したbenchmark checkpointだけを人間へ提示する。

## 2. 実装原則

- MMP検出、Evidence判定、HTML表示を分離する。
- 化合物組を表す`compound_pair_id`と、cut別のMMP pairを表す`pair_id`を分け、Target／unit／radius／複数Coreによる重複計上を防ぐ。
- Direct／Transferredという接続性と、explanation／improvementという解釈役割を独立して扱う。
- Canonical Databaseは固定構造方向のsigned deltaを保持する。Target ReportはTargetを常に生成物側へ置いたsigned `target_oriented_delta`を派生させ、正値へ強制しない。
- 観測結果とVirtual Candidateを別data model、別Report Viewにする。
- 1-cutと2-cutの件数、統計、表示を混ぜない。
- Endpointによる見栄えのよいpair選抜をfragmentationへ持ち込まない。
- Interactive HTMLはofflineで動作し、JavaScriptへ化学計算を持たせない。
- Templateを唯一のHTML生成経路とし、自由生成Reportを禁止する。
- 各Phaseのcontract testを通すまで後段へ進まない。
- LLM VisionとScreenshot内容判定をtestへ使用しない。
- Canonical DatabaseはTarget非依存、構築完了後immutable、1 Run 5,000化合物までを正式対応範囲とする。

## 3. 主な変更対象

- `.claude/skills/cs-analysis-matched-molecular-pairs/SKILL.md`
- `.claude/skills/cs-analysis-matched-molecular-pairs/README.md`
- `.claude/skills/cs-analysis-matched-molecular-pairs/capability.json`
- `.claude/skills/cs-analysis-matched-molecular-pairs/references/mmp_contract.md`
- `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/run.py`
- `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/mmp_engine.py`
- `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/mmp_outputs.py`
- `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/conductor_request_adapter.py`
- `.claude/skills/cs-analysis-matched-molecular-pairs/templates/`
- `CONDUCTOR_modules/catalog/`
- `CONDUCTOR_modules/schemas/`
- `CONDUCTOR_modules/docs/CONDUCTOR_output_contract.md`
- A008、A009導線、package verification、contract test

実装前に実際のimport／call graphを確認し、科学Kernel、data model、renderer、adapterの責務境界に沿って変更範囲を確定する。

## 4. Phase 0: Baselineとfixture固定

### 作業

1. Git revision、working tree、Skill version、mmpdb／RDKit versionを記録する。
2. 現行Type-I／II／IIIのArtifact、column、件数、方向をfixture化する。
3. 0.1.10で承認済みの1／3／4／5 Core relationship mapをreferenceとして固定する。
4. 次の化学fixtureを準備する。
   - 1-cut terminal substitution
   - 明確なA-B-C → A-B'-C 2-cut
   - 1-cutへ還元できる2-cut
   - 極小constant fragmentを含むnoise
   - symmetry-equivalent mapping
   - ambiguous mapping
   - Environment radius 2／1／不一致
   - supporting／conflicting Endpoint方向
   - Direct MMP 0件のTarget
   - 同じTargetが複数analysis unitとGlobal Top 1を兼ねるcase
   - Target固定方向のsigned Δが正となるDirect／Transferred observation
   - Target固定方向のsigned Δが負となるDirect／Transferred observation
   - 同じ構造変換がcontextによりFavorable方向を反転するcase
5. ChEMBL JAK2 validation RunをE2E用に保持する。

### 完了条件

- 0.1.10 baselineを再生成できる。
- 各fixtureの期待するpair、cut count、mapping、表示件数を人間が確認できる。
- fixtureを科学結論用dataとReport layout用synthetic dataに区別している。

## 5. Phase 1: Version、2 Mode、入力契約

### 作業

1. A008 calculation／capability versionを0.1.11へ更新する。
2. contractへ`mode: target | database`を追加する。
3. `target`は明示Target ID一覧を必須とし、`standard`／`explicit`等のsubmodeを設けない。
4. Targetごとに`selection_sources[]`を持たせる。要素は少なくとも`source_type = analysis_unit_top1 | global_top1 | human_explicit`と、必要な場合の`source_id`を持つ。
5. CONDUCTOR定型経路ではOrchestratorがanalysis unit Top 1＋Global Top 1を選択・重複除去し、Mode Iへ明示Target一覧として渡す。On-demandでは人間指定IDだけを渡す。
6. `target`へCanonical Database path／探索規則、Evidence parameterを定義する。compatible DBがなければ同じbuilderをMode I内部から一度だけ呼ぶ。
7. `database`へfragmentation、radius、quality gate parameterを定義する。
8. 旧Type-I／II／IIIを2 Modeへ変換するadapterを実装し、旧指定と変換結果をmanifestへ記録する。
9. 新engineから旧Type分岐を除去する。

### Test

- Type-I → Orchestrator選択済みTarget一覧による`target`
- Type-II → 人間指定Target一覧による`target`
- Type-III → database
- 不明Mode、矛盾parameter、Run外Targetのreject
- 旧／新入力から同じcanonical requestを得ること
- 同じTargetの複数selection sourceが一Targetへ統合されること
- 明示Target一覧のないMode Iがfail-fastすること

### 完了条件

- 新しい科学処理が2 Modeだけを認識する。
- 旧入力の互換動作が決定的である。
- Targetの選び方は呼出側、Target解析はMode Iという責務分離が成立する。

## 6. Phase 2: Canonical MMP Database

### Data model

Canonical DatabaseにはTarget非依存Tableだけを正規化して保存する。

- `compounds`
- `pairs`
- `fragmentations`
- `transformation_families`
- `transformations`
- `pair_transformations`
- `exact_cores`
- `retained_anchors`
- `environments`
- `two_cut_quality`
- `exclusion_reasons`

Mode IのTarget別Artifactへ、Canonical Databaseとは分離して次を保存する。

- `target_registry`
- `target_selection_sources`
- `analysis_unit_memberships`
- `target_fragmentations`
- `evidence_assessments`
- `virtual_candidates`

### 作業

1. Stable IDの入力項目とcanonicalization規則を文書化する。
2. Stable IDを次の三層へ分ける。
   - `compound_pair_id`: canonicalな二つのcompound IDだけから作り、1-cut／2-cut、unit、Target、radiusに依存しない。
   - `pair_id`: `compound_pair_id + cut_count`から作る。1-cutと2-cutを別pairとして管理するが、同じcut内の複数Core／radius／unitで増やさない。
   - `pair_transformation_id`: `pair_id + transformation_id + core_id`から作り、一つのpairに存在する複数の有効な最小変換を失わず保持する。
3. direction-neutralなTransformation family IDとfixed directed Transformation IDの双方へcut countとordered attachment topologyを含める。familyはA/B交換で同一、directed IDは固定構造方向を区別する。
4. Exact Core IDへattachment labelを含める。
5. radius 0–2を同じpair transformationに従属させる。
6. 1-cutと2-cutのID namespace、TableまたはView、Summaryを明確に分離し、mmpdbの最大2-cut出力に含まれる1-cutを`cut_count`で確実に振り分ける。
7. SQLite schema version、index、manifestと二層calculation signatureを追加する。
   - `structure_signature`: compound ID、canonical isomeric SMILES、fragmentation engine／version、cut SMARTS、cut数、構造gate、canonicalization規則。
   - `effect_signature`: Endpoint列と値、Favorable方向、neutral tolerance、効果量計算version。
8. Template／CSS／JavaScript versionをDatabase signatureから外し、Report-only変更で再構築しない。
9. structure signature一致・effect signature不一致では保存済み構造pairから効果列を再計算する。structure signature不一致では再利用しない。
10. builderは一時SQLiteへ書き、Schema・foreign key・件数監査PASS後にatomic renameしてimmutable完成版とする。失敗した一時fileは再利用しない。
11. Mode Iはcompatible Databaseをread-onlyで再利用し、存在しない場合だけ同じbuilderを内部呼出する。Mode IIとMode IのRuntime Nodeを二重作成しない。

Schema上は、Canonical Databaseの`normalized_signed_delta`、Consensus集計用のsigned `consensus_aligned_delta`、Target表示用のsigned `target_oriented_delta`を別fieldとする。絶対値`pair_favorable_gain`は互換・補助集計に限定する。Direction consistencyは`consensus_aligned_delta`だけから計算し、pairごとの正方向化後の値を使用しない。Consensus方向はTarget全体を横断して一つだけ決めるのではなく、少なくとも`target_id + cut_count + transformation_family_id + environment_group_id`ごとに決める。

### Test

- 同じ化合物組の1-cut／2-cutが同じ`compound_pair_id`、別`pair_id`になり、同じcut内のunit／radius／複数Coreで`pair_id`が増えない。
- 一つのpairに複数の非包含Coreがある場合、`pair_transformation_id`を分けて原本情報を保持できる。
- attachment label違いが誤って同じCore IDにならない。
- 同じDatabaseを再生成してStable IDと主要Table件数が一致する。
- incompatible Databaseをfail-fastする。
- Targetを変えてもCanonical DatabaseのhashとTable件数が変わらない。
- Target registry／Virtual CandidateがCanonical Databaseに混入しない。
- Report Templateだけを更新してもDatabaseを再構築しない。
- build途中の中断fileをcompatible Databaseと判定しない。

### 完了条件

- Target Reportを再計算せずDatabaseから再構成できる。
- 全集計値をcanonical pairへdrill-downできる。
- Canonical DatabaseがTarget非依存かつimmutableである。

## 7. Phase 3: Target registryと方向correctness

### 作業

1. Mode I requestの明示Targetを一つのTarget registryへ統合し、重複Targetへselection sourceを複数接続する。
2. analysis unit Top 1とGlobal Top 1の選択はOrchestrator adapter、人間指定はOn-demand requestの責務とし、Mode I engine内でTargetを暗黙追加しない。
3. Endpoint同値時のcompound ID順tie-breakを実装する。
4. Canonical Databaseではcanonical fragment順に固定した構造方向と`normalized_signed_delta`を保存し、Target別ArtifactでTargetを生成物側へ置いたsigned `target_oriented_delta`を派生する。
5. `|Δ| < 0.10`をneutral、Endpoint欠損をmissingとし、どちらも方向一致率の分母から外して別件数にする。
6. TargetがA／B／neither／bothのどこに対応するかを判定する。
7. Target別Consensus directionは、同一`target_id + cut_count + transformation_family_id`内で次のように決定する。異なるTransformation familyや1-cut／2-cutを一つの多数決へ混ぜない。
   - 当該Transformation familyにExact Target CoreのDirect pairがあれば、それだけを方向決定母集団とし、類似Coreのpairをその方向へalignする。
   - なければ互換性のある同一Environment class内で非neutral pairを方向別Countする。
   - Count降順、attachment label付きcanonical variable fragmentの`from_smiles → to_smiles`昇順でSortし、先頭を採用する。同数時のmedian判定やambiguous分岐を追加しない。
   - Radius-2、Radius-1、Environment mismatchを同じCountへ混ぜない。
8. `connection_scope`、`interpretation_role`、`observation_status`を独立列として保存する。
9. Directは常にNeighbor → Targetとして表示し、`target_oriented_delta`が正ならTargetを支える観測、負ならObserved improvementの手掛かりへ分類する。
10. Transferred evidenceはTarget対応側へ向けたsigned Δを作り、正ならTargetを支える参考観測、負ならProposed improvementの手掛かりとする。neitherはnot applicable、both／非同値複数siteはambiguousとする。
11. direction-neutral transformation familyとfixed directed transformationを併存させ、固定方向のsigned deltaでsupport／conflictを数える。
12. HTML、CSV、SQLite、Summaryで方向と分類が一致するcontract testを追加する。

### Test

- Favorableがhigh／lowの両方
- Targetがcanonical pairのA側／B側の両方
- Direct／Transferredそれぞれのexplanation／improvement四象限
- 同じTargetが複数unitとGlobalに属するcase
- Direct MMP 0件
- 欠損Endpointを含むpair
- neutral tolerance内外
- 同じTransformation familyでFavorable方向が反転するcontext
- Exact Target Coreあり／なしのConsensus direction
- 異なるTransformation family間でConsensus directionが共有されないこと
- 同数時にcanonical方向keyで決定され、median分岐がないこと
- Radius-2一致群とEnvironment mismatch群の多数決が混ざらないこと
- 各pairを正方向化した`pair_favorable_gain`から方向一致率を誤計算しないこと
- Consensus方向に反するpairの`consensus_aligned_delta`が負で保持されること

### 完了条件

- 入力row順を反転してもcanonical固定方向、fixed signed delta、Consensus方向、補助gainが変わらない。
- Direct／Transferredを変更しても、TargetのA/B位置が同じなら解釈役割は変わらない。
- 成果物間でeffect semanticsが一致する。
- Databaseのsigned deltaをReport都合で反転・上書きしない。

## 8. Phase 4: 1-cut維持と2-cut追加

### 8.1 1-cut回帰保護

現行1-cutのeligible pair、Exact Core、radius 0–2、最小変換表示をgolden fixtureで保護する。Reportの最大Core判定ではattachment dummyを除去して包含を比較し、切断境界が外側へ移動する実例を回帰fixtureに含める。2-cutは二つのRetained anchorを別componentのまま一対一対応させる。2-cut追加によって1-cut件数とIDを不用意に変えない。

### 8.2 2-cut候補生成

1. non-ring bond二本の組合せを生成する。
2. 二つのconstant fragmentと一つのtwo-attachment variableを検証する。
3. attachment順序とsymmetry classをcanonical化する。
4. cut count、fragment size、retained fraction、mapping statusを保存する。
5. mmpdbの最大2-cut出力を`cut_count`で分離し、1-cut rowを2-cut集計へ混ぜない。
6. ring cutと3-cutを拒否する。

### 8.3 Hard gate benchmark

最終閾値をコードへ固定する前に、次の小規模gridをfixtureと実データで評価する。

| Parameter | 比較候補 |
|---|---|
| 各constant fragmentの最小heavy atom数 | 3、4 |
| combined constantの最小保持割合 | 0.50、0.60、0.70 |
| variable fragment最大heavy atom数 | 10、15、20 |
| variable fragment最大分子割合 | 0.30、0.40、0.50 |
| cut SMARTS | `default`、`cut_AlkylChains`、`exocyclic` |

すべての直積を無条件採用せず、代表条件を段階比較する。評価順は次とする。

1. 極小anchorと1-cut冗長表現の混入率が低い。
2. 明確なlinker／central ring交換を保持する。
3. ambiguous mappingが少ない。
4. pair数とDatabase容量が実用範囲にある。

構造条件は二段階に分ける。

- `absolute safety floor`: attachment数、連結性、mapping unique／symmetry-equivalent、再構成、ring cut、1-cut reducibility、および両Retained anchor各heavy atom 4以上。違反は`2C-X`。
- `standard quality threshold`: retained fraction、variable size。通過は`2C-A`、安全下限は満たすが標準値未達は`2C-B`。

`2C-A／B／X`へsupport数、Endpoint方向、Target mapping、Environment適合を入れない。これらはTarget別`target_evidence_quality = high | limited | not_applicable | ambiguous`で別評価する。

### 8.4 Reducibility

同じcompound pairについて、2-cut variable交換が1-cutの小さい置換へ還元できるか判定する。還元可能な表現はDatabaseへprovenanceを残してよいが、`2C-A`へ分類せず標準表示しない。

### Test

- A-B-C → A-B'-Cの検出
- constant fragment順序を入れ替えた同値表現の統合
- 極小anchor除外
- reducible 2-cutの分類
- symmetry-equivalent／ambiguousの分離
- 再構成不能なfragmentの除外
- `2C-A／B／X`がTargetを変えても変化しないこと
- 同じ2-cutにTarget別`target_evidence_quality`を独立付与できること
- cut SMARTSごとのcoverage、noise、pair数を比較できること

### Human checkpoint A

閾値・cut SMARTS Matrixを件数、代表構造、既知有用変換coverage、noise理由とともにSession内で提示する。HTML Reportへは掲載しない。人間がabsolute safety floorとstandard quality thresholdを承認してからPhase 5へ進む。

## 9. Phase 5: Similar Core、Attachment mapping、Environment

### 作業

1. Exact Core一致Evidenceを基準classとする。
2. similar Core候補を高速metricでpre-filterする。
3. Attachment-constrained MCSで変換位置を確定する。
4. 全同率mappingを列挙する。
5. `unique`、`symmetry_equivalent`、`ambiguous`、`failed`へ分類する。
6. radius 2、radius 1、environment mismatchを別Evidence classへ割り当てる。
7. MCS、Attachment、radius、非対応部分のhighlight用atom mappingをArtifactへ保存する。
8. Direct MMPが0件でもTarget自身のeligible 1-cut／2-cut fragmentationを作り、variable fragment、Exact Core／Retained anchors、full-molecule attachment atomをTarget別Artifactへ保存する。
9. Transferred pairのvariable fragmentとTargetの現在のvariable fragmentを比較し、A／B／neither／bothを判定する。
10. Radius-2、Radius-1、Environment mismatchは別集計groupとし、方向Countや一致率を混ぜない。
11. `environment_group_id`をcut count、ordered attachment topology、最大一致radius、canonical Environment signatureから作る。各rowは最大一致radiusの一groupだけへ所属させ、Environment mismatch groupはConsensus directionに使わない。

### 候補metric benchmark

初期比較案は次とする。

- pre-filter: attachmentを保持したCore Morgan fingerprint Tanimoto 0.60／0.70／0.80
- final mapping: MCS coverageを両Coreそれぞれ0.60／0.70／0.80
- mapping status: uniqueまたはsymmetry-equivalentだけを標準候補とする

Core全体similarityだけで変換位置を確定しない。Environment一致だけで、構造的に不対応なCoreを採用しない。

### Test

- Exact Core
- Radius-2 matched similar Core
- Radius-1 matched related Core
- Attachment mapped／Environment mismatch
- ambiguous／excluded
- Core類似性は高いがAttachment位置が対応しないnegative case
- Target variable fragmentがA／B／neither／bothとなるcase
- Direct MMP 0件でもTarget fragmentationからTransferred evidenceをqueryできるcase
- 同じradius classでもEnvironment signatureが異なるpairが別groupになるcase

### Human checkpoint B

候補検索漏れと誤mappingを代表構造で提示し、metric、閾値、mapping合否を承認する。

## 10. Phase 6: Evidence集計とTarget explanation／improvement

### 10.1 Evidence集計

次を`cut_count + transformation_family_id + environment_group_id`ごとに、同一`pair_id`を一度だけ数えて集計する。1-cutと2-cutを横断した参考照合にだけ`compound_pair_id`を使い、方向supportへ合算しない。

- unique pair数
- unique compound数
- unique Exact Core／Retained-anchor context数
- 固定構造方向のsigned deltaのmedian／IQR／range
- 互換・補助集計用の絶対値`pair_favorable_gain`と、Target別表示用のsigned `target_oriented_delta`
- Favorable方向一致率
- supporting／conflicting pair
- neutral pair数／missing Endpoint pair数
- 化合物を共有しないpairの最大集合数`disjoint_pair_count`
- Environment class
- mapping confidence

`unique context`は、1-cutではattachment labelを含むExact Core、2-cutではordered attachment topologyを含むRetained anchorsの一意数とする。同じcontextのradius、analysis unit、Target違いは増分しない。missing／neutral pairはcontext存在件数には含められるが、方向一致率`supporting / (supporting + conflicting)`の分母には含めない。

同一compoundの多数pairを統計的独立とはみなさない。radius、unit membership、fragmentation候補数、同一pairの複数Coreでsupportを水増ししない。`disjoint_pair_count`はcompoundを頂点、pairを辺とするgraphの最大cardinality matchingの辺数として決定論的に算出し、hub biasの参考指標として表示するが、0.1.11の合否条件にはしない。

### 10.2 Transferred evidenceの初期表示条件

初期表示は次をすべて満たすEvidenceに固定する。

- unique compound pair 3以上
- unique Exact Core／Retained-anchor context 2以上
- 方向一致率0.80以上
- mappingがuniqueまたはsymmetry-equivalent
- `target_evidence_quality = high`

基準未達は`limited`として折り畳む。ambiguousは標準表示しない。Environment mismatchは比較referenceとして独立表示し、一致群の方向Countへ混ぜない。Direct observed pairはsupport件数に関係なくDirect Viewから到達可能にする。

測定誤差情報が入力にない場合、統計的significanceを擬似的に作らない。入力にreplicate／assay情報がある場合だけ、別のuncertainty項目として利用する。

### 10.3 Target別routing

1. Direct MMPは常にNeighbor → Targetとして表示し、signed `target_oriented_delta`が`+0.10`以上ならTargetを支える観測へ送る。
2. Direct MMPのsigned `target_oriented_delta`が`-0.10`以下なら改善の手掛かりへ送る。
3. Transferred evidenceはTarget対応側を表示上の生成物としてsigned `target_oriented_delta`を導出し、同じ符号規則で二つの読み方へ振り分ける。
4. A/BはConsensus集計とTarget Fragment対応の内部表現に限定し、Reportの矢印は正負にかかわらずTargetへ向ける。
5. neitherはnot applicable reference、neutral／両側mapping／ambiguous mappingはEvidence viewへ残し、主結果へ混ぜない。

同じTargetは四つのrouteを同時に持ち得る。TargetがGlobal Top 1かどうかでrouting ruleを変更しない。

`target_evidence_quality`は次の決定表で付与する。

- `high`: Direct exact observation、またはunique／symmetry-equivalent mapping＋Exact／Radius-2 Environment＋10.2のsupport条件を満たす。
- `limited`: mappingは妥当だが、support不足、Radius-1一致、またはEnvironment mismatch。mismatchは別reference Viewへ送る。
- `not_applicable`: Target fragmentがA/Bどちらにも対応しない。
- `ambiguous`: A/B両側、非同値複数site、またはambiguous／failed mapping。

### 10.4 Virtual Candidate

1. Target上のBefore fragmentとattachmentをmappingする。
2. After fragmentへ置換する。
3. RDKit sanitize、valence、stereo、重複を検証する。
4. supporting／conflicting Evidenceを接続する。
5. Candidate rankの各根拠を別列で保存する。
6. 生成構造がRun内既存化合物と一致した場合はVirtualのまま残さず、既存compound IDとEndpointへ接続したObserved compoundへ再分類する。
7. Target内の非同値な複数siteはsite別に生成し、canonical isomeric SMILESで重複排除する。
8. 既存のstereochemistryは保持する。変換によって新しい未指定stereocenterが生じる場合は任意の立体を割り当てず、`stereo_status = unresolved_new_center`として明示し、標準の上位候補からは除外して折り畳みreferenceへ送る。

Rankingは不透明な一つのscoreだけに依存しない。初期順は、`target_evidence_quality`、Environment class（Exact、Radius-2、Radius-1、mismatch）、mapping status、方向一致率、unique pair数、median `consensus_aligned_delta`の順に降順優先し、最後をcanonical Transformation／Candidate ID昇順として決定論的にする。各根拠値を表示可能にする。

### Human checkpoint C

代表caseでrouting、Observed再分類、Virtual Candidate validation、初期表示／折り畳みの情報密度を人間が確認する。科学的初期表示条件は10.2から変更せず、画面へ埋め込む最大候補数だけを性能実測に基づいて固定する。

## 11. Phase 7: Analysis unit metadata

### 作業

1. Target／Neighborと採用analysis unitの多対多membershipを保存する。
2. Cross-representation Core／Core／Fringeをmetadataとして保存する。
3. canonical pair件数とunit接続行数を別集計にする。
4. UIではunit情報を初期非表示とし、optional badge／filterとして実装可能なdataを供給する。
5. unit情報をTarget選択優先度、MMP support数、A007構造選択へ流用しない。

### Test

- 同一Target／Neighborの複数unit所属
- membership追加でpair数とEvidence supportが変わらないこと
- unit metadataなしでもA008が成立すること

## 12. Phase 8: PCワイドInteractive HTML

### 12.1 Template構造

Target個別HTMLを次のapplication shellへ変更する。

- compact Target header
- Relationship Map／Transformation／N2T Direction／Target Connection／N-Cuts／Data Tableの主navigationと、右端のEvidence Guide補助tab。TransformationはAll／Direct／Transferred、N2T Directionは`ΔN2T >= 0`／`ΔN2T < 0`、Target ConnectionはDirect MMPあり／Transferredのみ、N-Cutsは1 Cut／2 Cutsのsubtabで切り替える
- main workspace
- 右側の広幅Detail panel（desktop幅の約55–60%、650–920 px）
- compact footer／詳細CSV link

desktopでは`100dvh`内へ収め、page全体の縦scrollを発生させない。Detail panelと各Viewだけを内部scrollとする。

### 12.2 Relationship Map

1. 3／4／5 Coreの承認済みradial layoutをcomponent化し、斜め位置のCoreではNeighborを主に左右外側へ展開して縦幅を抑える。
2. Target紺、Core緑、Neighborオレンジを固定する。
3. Initial Mapを最大5 Coreとする。各CoreのNeighborが5件以下なら全件、6件以上なら`N Neighbor`件数Nodeを表示し、全件をCore detailへ保持する。Core順位はDirect pair数降順、最大`|target_oriented_delta|`降順、canonical Core ID昇順とする。
4. MapのNeighbor cardからFragment画像を外し、ID、Endpoint、`ΔN2T`だけを示す。非重複を最優先し、その範囲で横幅を広げる。
5. Core cardにDirect Neighbor件数と類似Core Evidence件数を示す。
6. viewport変更時にMapを再fitし、Nodeが切れないようにする。
7. Direct pairのedgeを正負にかかわらず常にNeighbor → Targetの矢印で描く。
8. Map内の全connectorは破線で統一し、外周Neighbor列と他のcardが交差・重複しない配置を使う。
9. `ΔN2T >= +0.10`なら紺、`ΔN2T <= -0.10`ならオレンジ、neutral／missingは灰色で表す。正負はEvidenceの優劣ではない。
10. 矢印はTarget–Neighbor間のcompound変換を表し、Core Nodeを反応中間体として扱わない。
11. 1-cutと2-cutを同じMap layerへ混在させず、2-cutの中間Nodeは`Exact Core`ではなく`Retained anchors`と表示する。
12. 各Target MapからA009埋め込み用の自己完結static SVGも生成する。

### 12.3 Interaction

Neighbor click:

- 広幅Detail panelにTargetとNeighborを固定二列で表示
- 左Neighbor、右Target、中央に常にTargetへ向く矢印と`ΔN2T`を表示
- 両化合物のEndpoint、中央の共通Core、Neighbor／Target Fragmentを縦順に表示
- 全体構造は共通Core基準で2D Alignし、失敗時も全体構造を残して`Align ×`を明示

Core click:

- 最上段は左に緑枠のCore、右に紺枠のTargetを横並び表示する
- Core構造、Attachment、Direct Neighbor全件、Similar Core Evidence件数を表示
- Similar Coreをsecondary Mapとして表示し、別Coreで観測されたMMPへ遷移可能にする
- Core → Similar Core → 個別MMPの状態履歴と戻るbuttonを実装する

共通:

- 一度に一つのDetail panelだけを開く
- Escape、close、Map空白clickで閉じる
- 主ViewではEvidence行をTransformation family単位に集約し、正／負件数、median `ΔN2T`、Direct／Transferred内訳と代表Fragmentを示す
- Positive／Negative cardから「この読み方」等の解釈誘導文を除く
- 生のTableは`Data Table`へ降格し、確認用のsecondary Viewとする
- 右端の`Evidence Guide`へN2T、Direct／Transferred、Evidence quality、`2C-A／B／X`、1/2-cut、Core mapping、Align成否の固定説明を置く
- tabを変えても選択とfilterを保持する
- browser backを壊す不要なpage navigationを行わない

### 12.4 Offline実装

- Vanilla JavaScriptまたはrepositoryへ固定した小規模libraryだけを使用する。
- 外部CDN、remote font、Web APIを使用しない。
- 化学構造SVGと表示用JSONはPython側で生成する。
- HTMLへ埋め込むのは標準表示とdrill-downに必要なdataだけとする。
- 全列と非表示pairはCSV／SQLiteへ残す。

### 12.5 DOM test

- 1,280 × 720、1,440 × 900、1,920 × 1,080でworkspaceがviewportを超えない。
- Map Nodeがcontainer外へ出ない。
- Neighbor／Core clickで正しいDetail panelへ切り替わる。
- Core → 類似Core → MMP → 戻るで元のCore状態へ戻る。
- CoreごとのDirect件数と、個別Neighbor Node＋集約Nodeの表現件数が一致する。
- focus、Escape、closeが動作する。
- sort／filter後の表示件数がdata件数と一致する。
- 詳細CSV linkが存在する。

Screenshot画像の意味判定は行わず、DOM、bounding box、text、attribute、eventによって検証する。
browser test runnerはrepositoryでVersion固定したPlaywrightとし、install手順とbrowser binary versionをlockfile／開発文書へ記録する。

### Human checkpoint D

実データとsyntheticな1／3／4／5／8 Core例、多Neighbor例を人間が操作し、情報密度、Detail panel幅、構造サイズ、集約閾値を承認する。

## 13. Phase 9: 全体ReportとA009導線

### 作業

1. Mode I全体Reportを重複のないTarget indexへ変更する。
2. Target cardへselection source一覧、Direct／Transferred別の「Targetを支える観測」「改善の手掛かり」、1-cut／2-cutの件数を示す。
3. Mode II Database Summaryを別HTMLとして生成する。
4. `mmp_report_index.json`へTarget ID、selection source、Interactive HTML path、static SVG path、主要件数をVersion付きで保存する。
5. A009はindexだけを読み、Interactive HTML／JavaScript／Evidence tableを複製せずstatic Relationship Mapだけを掲載する。
6. A009個別analysis unit Reportには当該unit Top 1、A009全体SummaryにはGlobal Top 1のstatic Mapを掲載する。同一TargetならA008側SVGを再利用する。On-demand TargetをA009へ自動追記しない。
7. Direct MMP 0件Targetにも空状態を示すstatic Mapと個別Interactive HTMLを作る。
8. 旧pathを参照するconsumerに互換linkまたは明確なmigration errorを提供する。

### Test

- 同一Targetの複数sourceが一つのcard／HTMLになる。
- A009のstatic SVG参照が解決し、A009内にInteractive scriptや巨大Evidence dataが混入しない。
- Report件数がTarget registry、canonical pair、Evidence tableと一致する。

## 14. Phase 10: Runtime、Catalog、文書同期

### 作業

1. RuntimeのA008 Execution Requestを2 Modeへ更新する。
2. 定型RuntimeはMode I Nodeだけを要求し、Mode Iがcompatible Databaseを再利用または同じbuilderで内部構築する。Mode II → Mode Iの二重Node依存をprofileへ追加しない。
3. 明示的なDatabase事前構築requestだけをMode II単独Nodeとして扱う。
4. capability、catalog、included skills、package verifierを同期する。
5. `CONDUCTOR_output_contract.md`、Skill README、SKILL.md、quick reference、Promptを更新する。
6. 旧Type名称が互換説明以外の新規Reportや新規Promptへ残っていないことを検査する。
7. Versionと二層calculation signatureを全Artifactで一致させる。

### 完了条件

- Runtime、Skill、Schema、Catalog、docsが同じ2 Mode契約を示す。
- 配布Skillがself-containedである。
- 定型実行で同じCanonical Database buildを二重起動しない。

## 15. Phase 11: E2E、性能、Report監査

### 科学contract test

- 1-cut回帰
- 2-cut Hard gate
- reducibility
- Attachment mapping
- Environment class
- direction consistency
- Exact Core優先／Count→SortによるConsensus direction
- neutral 0.10、missing、Environment class別集計
- Target deduplication
- Target固定方向のsigned Δ routing
- Direct／Transferredと「Targetを支える観測／改善の手掛かり」の独立分類
- Evidence support／conflict
- unique context／disjoint pair count
- 2C構造品質とTarget Evidence品質の分離
- Virtual Candidate validation

### Report contract test

- Template ID／Version／hash
- 必須Viewとwide detail panel
- DOM click behavior
- 表示件数とcanonical data件数
- link切れ
- CSV／SQLiteへのdrill-down
- unit metadataの重複非計上
- 1-cut／2-cut、Observed／Virtualの表示分離
- Direct／Transferredと「Targetを支える観測／改善の手掛かり」の四象限分類
- Map edgeが常にTargetへ向き、signed Target基準Δを正値へ反転しないこと
- A009 static Mapだけの埋め込み

### E2E

1. 小規模化学fixture
2. ChEMBL JAK2 validation data
3. Direct MMP 0件Target
4. 多数Core／多数Neighborを持つstress fixture
5. 最大5,000化合物相当のDatabase build性能確認。synthetic dataを使う場合は科学評価と分離する。

5,000化合物caseでは成功／失敗だけでなく、wall time、peak RSS、SQLite容量、pair／fragmentation件数を記録する。正式上限を超える入力は警告継続ではなく入力契約でrejectする。

### 性能目標案

- Target個別HTML: 原則10 MiB以下
- 初期表示用Node: 5 Core × 3 Neighborを基本上限
- reference PCで初期DOM ready: 2秒以内を目標
- clickからdetail panel更新: 100 ms以内を目標
- 1,280 × 720以上でpage-level縦scrollなし

性能値は実測後に最終承認する。上限超過時はEvidenceを削除せず、HTML埋め込み対象を減らしてCSV／SQLiteへ誘導する。

## 16. 実装順序

1. Baseline／fixture
2. Version／2 Mode contract
3. Canonical Database
4. Target registry／direction
5. 1-cut回帰＋2-cut
6. Similar Core／Attachment mapping／Environment
7. Evidence Summary／Target explanation／improvement
8. Analysis unit metadata
9. Interactive HTML
10. 全体Report／A009導線
11. Runtime／Catalog／docs
12. E2E／performance／監査

Phase 4、5、6、8のhuman checkpointを飛ばさない。科学閾値とUXを同じcheckpointで承認しない。

## 17. 主なリスクと対策

| Risk | 対策 |
|---|---|
| 2-cutでpair数とnoiseが急増 | Hard gate、1-cut reducibility、quality class、初期表示制限 |
| Similar Coreで変換位置を誤対応 | Attachment-constrained MCS、同率mapping列挙、ambiguous除外 |
| 同じEvidenceの水増し | Canonical pair、radius／unitをmetadata化、unique pair単位集計 |
| 改善候補を実測結果と誤解 | ObservedとVirtualを別View、別Schema、明示label |
| Interactive HTMLが巨大化 | Target別HTML、表示用data限定、CSV／SQLite drill-down |
| UI改良でTemplate再現性低下 | Version付きTemplate、DOM contract test、外部CDN禁止 |
| 旧Run／旧Typeが破損 | 旧Artifact read-only、互換adapter、legacy fixture |
| 方向が成果物間で逆転 | Database signed deltaをimmutableに保持し、Target別A/Bは派生、四象限fixture、cross-artifact test |
| Target情報でCanonical DBが汚染 | Target Tableを別Artifact化し、Target変更前後のDB hash test |
| Environment不一致が多数決を歪める | Radius／Environment class別集計をSchemaで分離し、混合集計negative test |
| 2C品質classへTarget評価が混入 | 構造品質`2C-A/B/X`と`target_evidence_quality`を別Table／columnでcontract化 |

## 18. Definition of Done

- A008が2 Mode契約で実行できる。
- Mode Iが明示Target一覧だけを処理し、暗黙のTarget追加を行わない。
- Run全体のTarget非依存Databaseを一度構築し、複数Targetがread-onlyで再利用できる。
- analysis unit Top 1、Global Top 1、人間指定Targetを重複なく扱える。
- 1-cut baselineを維持し、承認されたHard gateで2-cutを抽出できる。
- Exact／Radius-2／Radius-1／Environment mismatch／ambiguousを区別できる。
- Attachment mappingの位置とconfidenceを監査できる。
- Databaseは固定構造方向のsigned deltaを保持し、ReportはTargetを生成物側へ固定したsigned `target_oriented_delta`を使う。
- Exact Target CoreなしではEnvironment class別Count→SortだけでConsensus directionを決め、同数時のmedian／ambiguous分岐を持たない。
- Direct／TransferredとTarget explanation／improvementが独立分類される。
- Direct MMPを常にNeighbor → Targetで表示し、`ΔN2T`をPositive／Negativeとして表示できる。
- Transferred evidenceもTarget対応側を生成物として表示し、signed `ΔN2T`により分類できる。
- Virtual Candidateが観測化合物と明確に区別され、構造validationされる。
- Analysis unit membershipがpair supportを水増ししない。
- neutral／missingが方向一致率を水増しせず、`disjoint_pair_count`でhub集中を確認できる。
- 1-cut／2-cutと、2-cut構造品質／Target Evidence品質が別契約で管理される。
- PCワイド画面の一画面内でMap、Neighbor detail、Core MMP一覧、Evidence、Improvementを切り替えられる。
- 1／3／4／5／多数CoreでMap layoutとdetail panelが動作する。
- HTML、CSV、SQLiteの主要件数と方向が一致する。
- A009個別にはunit Top 1、A009全体にはGlobal Top 1のstatic Mapだけが掲載される。
- link／件数／DOM interaction監査がPASSする。
- PlaywrightによるDOM／bounding-box／event testが固定browser環境でPASSする。
- LLM Visionを使用していない。
- 5,000化合物の上限試験結果が記録され、5,000超を入力契約でrejectする。
- package verification、全contract test、代表E2EがPASSする。
- 人間が科学閾値とInteractive UXを別々に承認している。

## 19. 確定事項と実装中checkpoint

### 19.1 仕様として確定済み

- Mode Iは明示Target一覧を処理し、追加submodeを設けない。
- CONDUCTOR定型実行はanalysis unit Top 1＋Global Top 1、On-demandは人間指定Targetを呼出側で明示する。
- Mode Iはcompatible Databaseを再利用し、なければ同じbuilderを内部呼出する。Mode IIはDatabase単独構築用である。
- Canonical DatabaseはTarget非依存、immutable、fixed signed delta保持とする。
- neutral toleranceは`|Δ| < 0.10`とする。
- Exact Target Coreなしの方向はEnvironment class別にCount→Sortし、先頭へ合わせる。同数時のmedian／ambiguous処理は行わない。
- Consensus方向はTarget・cut count・Transformation family・Environment group単位で決め、異なるTransformationを同じ多数決へ混ぜない。
- Radius-2、Radius-1、Environment mismatchを同じ方向集計へ混ぜない。
- 1-cutと2-cutを解析、ID、集計、Viewで分離する。
- `compound_pair_id`はcut非依存、`pair_id`はcut別、`pair_transformation_id`はCore／Transformation別とする。
- `2C-A／B／X`は構造品質、`target_evidence_quality`はTarget別評価とする。
- Transferred evidenceの初期表示はunique pair 3、unique context 2、方向一致率0.80、mapping unique／symmetry-equivalent、quality highを必須とする。
- Virtual Candidateは構造生成とRDKit validationまで行う。Run内既存化合物と一致すればObservedへ再分類する。
- Initial Mapは最大5 Core。Neighbor 5件以下は全件、6件以上は件数Nodeで計上し、Core detailに全件を保持する。A009にはstatic Mapだけを後方セクションへ掲載する。
- Offline Artifact directoryを自己完結単位とし、詳細CSV／SQLiteを相対linkする。

### 19.2 実装中に人間が固定するparameter

次は仕様の未決ではなく、規定benchmarkを見て数値または選択肢を固定するcheckpointである。

1. 2-cutのabsolute safety floorとstandard quality thresholdの数値。
2. `default`、`cut_AlkylChains`、`exocyclic`から選ぶ標準cut SMARTS。
3. similar Core pre-filterのMorgan Tanimotoと、最終Attachment-constrained MCS coverage。
4. 10 MiB／2秒／100 msの性能目標を守るためHTMLへ埋め込むEvidence最大件数。

### 19.3 現時点の未確定事項

実装を開始できない設計上の未確定事項はない。19.2の4項目は意図的に残したHuman checkpointであり、暫定値を正式値とみなさない。各checkpointではSession内の比較表と代表構造を提示し、人間の承認後に設定値、選択理由、fixture結果を本書へ追記する。Human checkpoint A～Dをすべて通過し、サンプルReportを人間が確認するまでは0.1.11を実装完了と扱わない。

## 20. 実装結果とHuman checkpoint用benchmark（2026-09-06）

### 20.1 機械検証

- ChEMBL JAK2 231化合物でMode IIを構築し、同じSQLiteをMode Iがread-only再利用した。
- `default`のcanonical Databaseは11,472 pair-transformation行（1-cut 4,258、2-cut 7,214）、2,799 compound pair、9,435 fragmentationである。
- 2-cutは2C-A 167、2C-B 3,944、2C-X 3,103で、reconstruction failureは0件だった。
- Target 2件のInteractive HTMLとA009 static Map接続を生成した。
- unittest 80件、package verification、A008／A009 Template・link・件数監査はPASSした。
- Playwrightの4 viewportでoverflow 0、Map card衝突 0、DOM ready 312～315 ms、Neighbor detail 68～74 msだった。

### 20.2 Checkpoint A: 2-cut standard quality threshold

Hard gate通過4,111行に対する比較である。値は正式承認前の参考値とする。

| 条件 | 2C-A相当行 | Compound pair | Hard gate通過行に対する割合 |
|---|---:|---:|---:|
| lenient: anchor 2、retained 0.50、variable 20、variable fraction 0.50 | 1,641 | 1,500 | 39.9% |
| 暫定標準: anchor 3、retained 0.60、variable 15、variable fraction 0.40 | 167 | 122 | 4.1% |
| anchor 4 | 149 | 111 | 3.6% |
| retained 0.70 | 113 | 93 | 2.7% |
| variable 10 | 116 | 93 | 2.8% |
| variable fraction 0.30 | 105 | 87 | 2.6% |

### 20.3 Checkpoint B: cut SMARTS

| cut SMARTS | 全行 | 1-cut | 2-cut | 2C-A | 2C-B | 2C-X | Compound pair |
|---|---:|---:|---:|---:|---:|---:|---:|
| `default` | 11,472 | 4,258 | 7,214 | 167 | 3,944 | 3,103 | 2,799 |
| `cut_AlkylChains` | 11,624 | 4,289 | 7,335 | 188 | 3,979 | 3,168 | 2,799 |
| `exocyclic` | 6,382 | 4,076 | 2,306 | 29 | 1,476 | 801 | 2,679 |

### 20.4 Checkpoint C: Similar Core閾値

Transferred Evidence行の比較である。`high`はsupport／context／方向一致を含む全条件通過行である。

| Tanimoto／MCS | Target | Transferred | high | limited | Proposed | Explanation |
|---|---|---:|---:|---:|---:|---:|
| 0.60／0.60 | CHEMBL3699528 | 4,289 | 4 | 90 | 58 | 36 |
| 0.60／0.60 | CHEMBL3699558 | 3,018 | 0 | 14 | 4 | 10 |
| 0.70／0.70 | CHEMBL3699528 | 3,436 | 0 | 32 | 10 | 22 |
| 0.70／0.70 | CHEMBL3699558 | 2,692 | 0 | 0 | 0 | 0 |
| 0.80／0.80 | CHEMBL3699528 | 1,152 | 0 | 0 | 0 | 0 |
| 0.80／0.80 | CHEMBL3699558 | 1,716 | 0 | 0 | 0 | 0 |

### 20.5 Checkpoint D: HTML埋め込み上限

1,000件版はTarget HTMLが約10.14～10.34 MiBで目標を超えた。500件版は約7.15～7.48 MiB、DOM ready 312～315 ms、detail panel更新68～74 msで全高品質Evidenceを保持したため、500件を暫定標準へ変更した。正式値は人間承認後に固定する。

### 20.6 A008_v10人間評価と再実装

`A008_v10`／`A009_v4`は人間評価で不合格となった。主因はMap cardと凡例の重なり、Fragment画像の過密表示、Transferred evidenceの説明・構造導線不足、狭いdetail panel、非整列構造、Coreから類似Coreへの導線欠落、生Table中心で情報抽出になっていない点である。

### 20.7 A008_v17再実装結果

Phase 8のTarget固定方向、portal Map、広幅Detail panel、類似Core secondary Map、戻る導線、Transformation単位の情報抽出View、A009後方配置を実装し、`A008_v17`／`A009_v8`を生成した。

- Target Reportの矢印は常にTargetへ向け、signed `target_oriented_delta`を正値へ反転しない。
- positive／negative insightは別cardとし、各cardから同符号の代表MMPだけを開く。
- Mapの全Direct Neighborは、5件以下なら個別Node、6件以上なら件数Nodeとしてaccountし、Core detailから全件へ到達できる。
- 4 viewportのPlaywright監査でpage overflow 0、Map card衝突 0、Legend重なり 0、Core → Similar Core → MMP → 戻る導線、1/2-cut切替、signed insight導線を確認した。
- Transferred evidenceは元Pairの両SMILES／EndpointをTarget artifactへ持ち越し、Target-like analogを右、counterpartを左に固定して2D Alignする。対応不能／曖昧なReferenceは方向を捏造せず`↔`で示す。aligned structureは自己完結`targets/assets/`へ外出しする。
- CHEMBL3699528／CHEMBL3699558のTarget HTMLは9,506,403 bytes／8,984,541 bytesで、10 MiB上限内だった。DOM readyは292.0／323.4 ms、detail panel更新はいずれも12.3 msだった。
- A008のTemplate・link・件数・payload・static Map監査、A009のTemplate・link・件数監査、0.1.11 unittest 24件、0.1.10 regression 52件、package verificationはPASSした。

人間によるReport品質確認を通過するまでは0.1.11を完了扱いとしない。

### 20.8 追加UI・2-cut品質修正（2026-09-07）

- 表示語を`ΔN2T`、`Positive N2T`、`Negative N2T`へ統一し、説明／改善を断定する表現を廃止する。
- Target Reportを5つの主navigationと階層subtabへ整理し、右端に固定の`Evidence Guide`補助tabを置く。
- Map Neighbor cardを拡幅し、外周寄りの水平展開で縦幅を抑え、bounding-box監査で非重複を保証する。
- Core detail最上段へ緑枠Coreと紺枠Targetを横並び表示する。
- 2D Align失敗時も化合物全体を表示し、`Align ×`を明示する。
- 2-cutは両Retained anchorが各heavy atom 4以上をabsolute minimumとする。未達行は`2C-X`としてDatabaseへ理由付きで保持し、主Evidence表示から除外する。
- JAK2 231化合物で`A008_database_v7`、`A008_v20`、`A009_v11`を再生成した。
- 2-cut品質は旧`2C-A 167 / 2C-B 3,944 / 2C-X 3,103`から`149 / 34 / 7,031`へ変化した。小Anchorによる2C-Xは6,787行で、Canonical Databaseへ理由付きで保持される。
- Target HTMLは8,765,743 bytes／7,726,595 bytes、DOM ready 472.4／441.7 ms、detail更新21.3／19.3 msで目標内だった。
- 4 viewportのPlaywright監査でpage overflow、Map card衝突、card内text overflow、Legend重なり、実線connector、Transferred Core画像欠落はいずれも0。階層subtab、Core＋Target、Similar Core navigation、全体構造、Evidence GuideもPASSした。
- 0.1.11 test 26件、0.1.10 regression 60件、package verification、A008／A009内部監査はPASSした。

### 20.9 最大Core集約バグ修正（2026-09-07）

- attachment dummyを含む比較では、切断境界が外側へ移動した大Coreに小Coreが一致しない不備を修正した。
- 1-cutはdummy除去後のCore本体、2-cutは二つのdummy除去済みRetained anchor componentの一対一対応でstrict containmentを判定する。
- 相互に包含されないCoreは維持し、同一Coreの重複行は`evidence_id`順で1件へ集約する。Canonical CSV／SQLiteは削減しない。
- JAK2実例では主表示対象Direct行が`CHEMBL3699528: 70→27`、`CHEMBL3699558: 61→35`へ整理された。既知の`CHEMBL3639983`との1-cut pairは両Targetとも23-heavy-atom最大Core 1件だけを保持した。
- 確認用Artifactは`A008_v21`とA009接続版`A009_v12`である。
- 0.1.11 test 29件、0.1.10を含む全回帰89件、4 viewport browser監査、A008／A009内部監査、package verificationはPASSした。

### 20.10 Transferred外部SVG表示バグ修正（2026-09-07）

- RDKit描画結果のBase64 Data URIを文字列のまま`.svg`へ保存していた不備を修正し、Base64復号後のSVG XMLを`targets/assets/`へ保存する。
- A008内部監査は全外部SVGをXML parseし、Browser監査はMapped Core、Observed compound、Fragmentの各画像を個別に`naturalWidth > 0`で確認する。
- Directionalだけでなく、`both／neither`のnon-directional Transferred detailもBrowser監査対象とする。
- JAK2出力の外部SVG 1,320件はすべてXMLとして検証済み。確認用Artifactは`A008_v22`とA009接続版`A009_v13`である。

### 20.11 Transformation横断Viewと共通Filter（2026-09-08）

- 同じFragment Transformationを`transformation_family_id`とcut数でまとめ、Target-side Core、Direct／Transferredを横断して一つのViewから閲覧できる`Transformation` tabを追加した。
- All／Direct／Transferredのsubtabと、固定構造方向A→B、観測数、Core数、Direct／Transferred内訳、全個別Evidenceへの導線を設けた。
- `Core Type`を`Target Connection`へ変更し、Direct MMPあり／Transferredのみで分類する。cardでは誤解を招く`Exact Core`総称を使わず、1-cut／2-cutsと接続内訳を表示する。
- cut数、Evidence品質、text filterをTransformation、N2T Direction、Target Connection、N-Cuts、Data Tableへ共通適用する。
- 確認用Artifactは`A008_v24`である。Target 2件の4 viewport Browser監査、Transformation drill-down、Direct／Transferred切替、既存画像・Map監査はPASSした。
