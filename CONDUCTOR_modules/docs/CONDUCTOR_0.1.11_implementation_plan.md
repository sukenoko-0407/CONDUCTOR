# CONDUCTOR 0.1.11 A008 MMP大幅更新 実装計画書

Status: **承認前計画。未実装。**

## 1. 目的と前提

本書は、[`CONDUCTOR_0.1.11_specification_overview.md`](CONDUCTOR_0.1.11_specification_overview.md)を実装するための作業順、test、human checkpointを定める。

0.1.11はA008 MMP専用Versionである。0.1.10追補作業と、0.1.12へ移管したRuntime等の作業を混在させない。

実装開始条件は次のとおりとする。

1. 仕様概要書と本計画を人間が承認する。
2. 本書末尾の最終確認事項に回答する。
3. 0.1.10追補のMMP非対象境界を維持する。

## 2. 実装原則

- MMP検出、Evidence判定、HTML表示を分離する。
- Canonical pairを一度だけ作り、Target／unit／radiusによる重複計上を防ぐ。
- Direct／Transferredという接続性と、explanation／improvementという解釈役割を独立して扱う。
- EndpointのFavorable方向をA → Bへ正規化し、内部値`favorable_gain`と表示上のFavorable Δを正値へ揃える。
- 観測結果とVirtual Candidateを別data model、別Report Viewにする。
- 1-cutと2-cutの件数、統計、表示を混ぜない。
- Endpointによる見栄えのよいpair選抜をfragmentationへ持ち込まない。
- Interactive HTMLはofflineで動作し、JavaScriptへ化学計算を持たせない。
- Templateを唯一のHTML生成経路とし、自由生成Reportを禁止する。
- 各Phaseのcontract testを通すまで後段へ進まない。
- LLM VisionとScreenshot内容判定をtestへ使用しない。

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
   - TargetがFavorable側BにあるDirect／Transferred explanation
   - Targetが非Favorable側AにあるDirect／Transferred improvement
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
3. `target`へ自動Target、明示Target、Database input、Evidence parameterを定義する。
4. `database`へfragmentation、radius、quality gate parameterを定義する。
5. 旧Type-I／II／IIIを2 Modeへ変換するadapterを実装する。
6. adapterは旧指定、変換後Mode、追加されたGlobal Top 1をmanifestへ記録する。
7. 新engineから旧Type分岐を除去する。

### Test

- Type-I → target auto selection
- Type-II → target explicit selection
- Type-III → database
- 不明Mode、矛盾parameter、Run外Targetのreject
- 旧／新入力から同じcanonical requestを得ること

### 完了条件

- 新しい科学処理が2 Modeだけを認識する。
- 旧入力の互換動作が決定的である。

## 6. Phase 2: Canonical MMP Database

### Data model

最低限、次を正規化して保存する。

- `compounds`
- `pairs`
- `fragmentations`
- `transformation_families`
- `transformations`
- `pair_transformations`
- `exact_cores`
- `environments`
- `target_registry`
- `target_selection_sources`
- `analysis_unit_memberships`
- `evidence_assessments`
- `virtual_candidates`
- `exclusion_reasons`

### 作業

1. Stable IDの入力項目とcanonicalization規則を文書化する。
2. pair IDをcompound順、unit、Target指定、radiusから独立させる。
3. Transformation IDへcut countとordered attachment topologyを含める。
4. Exact Core IDへattachment labelを含める。
5. radius 0–2を同じpair transformationに従属させる。
6. SQLite schema version、index、manifest、calculation signatureを追加する。
7. Mode IがcompatibleなMode II Databaseを再利用できるようにする。
8. input hash、Endpoint列、Favorable方向、fragmentation parameter、Skill version不一致時は再利用を拒否する。

### Test

- 同じpairのunit／radius重複が一つのpair IDになる。
- attachment label違いが誤って同じCore IDにならない。
- 同じDatabaseを再生成してStable IDと主要Table件数が一致する。
- incompatible Databaseをfail-fastする。

### 完了条件

- Target Reportを再計算せずDatabaseから再構成できる。
- 全集計値をcanonical pairへdrill-downできる。

## 7. Phase 3: Target registryと方向correctness

### 作業

1. analysis unit Top 1、Global Top 1、人間指定Targetを一つのTarget registryへ統合する。
2. 重複Targetへselection sourceを複数接続する。
3. Endpoint同値時のcompound ID順tie-breakを実装する。
4. canonical pairの方向中立値、固定構造方向のsigned delta、Favorable-oriented viewを分離する。
5. RunのFavorable方向から各pairをA → Bへ正規化し、`favorable_gain > 0`へ揃える。
6. TargetがA/Bのどちらにあるかを判定する。
7. `connection_scope`、`interpretation_role`、`observation_status`を独立列として保存する。
8. Direct A → BでTarget=AならObserved improvement、Target=BならTarget explanationへ分類する。
9. Transferred evidenceでもTarget対応構造がAならProposed improvement、BならTransferred explanationへ分類する。
10. direction-neutral transformation familyとdirected transformationを併存させ、contextによる効果反転をconflictとして保持する。
11. HTML、CSV、SQLite、Summaryで同じ方向と分類になるcontract testを追加する。

### Test

- Favorableがhigh／lowの両方
- Targetがcanonical pairのA側／B側の両方
- Direct／Transferredそれぞれのexplanation／improvement四象限
- 同じTargetが複数unitとGlobalに属するcase
- Direct MMP 0件
- 欠損Endpointを含むpair
- neutral tolerance内外
- 同じTransformation familyでFavorable方向が反転するcontext

### 完了条件

- row順を反転してもFavorable-oriented A/Bとgainが変わらない。
- Direct／Transferredを変更しても、TargetのA/B位置が同じなら解釈役割は変わらない。
- 成果物間でeffect semanticsが一致する。

## 8. Phase 4: 1-cut維持と2-cut追加

### 8.1 1-cut回帰保護

現行1-cutのeligible pair、Exact Core、radius 0–2、最小変換表示をgolden fixtureで保護する。2-cut追加によって1-cut件数とIDを不用意に変えない。

### 8.2 2-cut候補生成

1. non-ring bond二本の組合せを生成する。
2. 二つのconstant fragmentと一つのtwo-attachment variableを検証する。
3. attachment順序とsymmetry classをcanonical化する。
4. cut count、fragment size、retained fraction、mapping statusを保存する。
5. ring cutと3-cutを拒否する。

### 8.3 Hard gate benchmark

最終閾値をコードへ固定する前に、次の小規模gridをfixtureと実データで評価する。

| Parameter | 比較候補 |
|---|---|
| 各constant fragmentの最小heavy atom数 | 3、4 |
| combined constantの最小保持割合 | 0.50、0.60、0.70 |
| variable fragment最大heavy atom数 | 10、15、20 |
| variable fragment最大分子割合 | 0.30、0.40、0.50 |

すべての直積を無条件採用せず、代表条件を段階比較する。評価順は次とする。

1. 極小anchorと1-cut冗長表現の混入率が低い。
2. 明確なlinker／central ring交換を保持する。
3. ambiguous mappingが少ない。
4. pair数とDatabase容量が実用範囲にある。

### 8.4 Reducibility

同じcompound pairについて、2-cut variable交換が1-cutの小さい置換へ還元できるか判定する。還元可能な表現はDatabaseへprovenanceを残してよいが、`2C-A`へ分類せず標準表示しない。

### Test

- A-B-C → A-B'-Cの検出
- constant fragment順序を入れ替えた同値表現の統合
- 極小anchor除外
- reducible 2-cutの分類
- symmetry-equivalent／ambiguousの分離
- 再構成不能なfragmentの除外

### Human checkpoint A

閾値Matrixを件数、代表構造、noise理由とともにSession内で提示する。HTML Reportへは掲載しない。人間が標準Hard gateを承認してからPhase 5へ進む。

## 9. Phase 5: Similar Core、Attachment mapping、Environment

### 作業

1. Exact Core一致Evidenceを基準classとする。
2. similar Core候補を高速metricでpre-filterする。
3. Attachment-constrained MCSで変換位置を確定する。
4. 全同率mappingを列挙する。
5. `unique`、`symmetry_equivalent`、`ambiguous`、`failed`へ分類する。
6. radius 2、radius 1、environment mismatchを別Evidence classへ割り当てる。
7. MCS、Attachment、radius、非対応部分のhighlight用atom mappingをArtifactへ保存する。

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

### Human checkpoint B

候補検索漏れと誤mappingを代表構造で提示し、metric、閾値、mapping合否を承認する。

## 10. Phase 6: Evidence集計とTarget explanation／improvement

### 10.1 Evidence集計

次をcanonical pair単位で集計する。

- unique pair数
- unique compound数
- unique Exact Core／constant-context数
- 固定構造方向のsigned deltaと、Target別の正値Favorable gainについてのmedian／IQR／range
- Favorable方向一致率
- supporting／conflicting pair
- Environment class
- mapping confidence

同一compoundの多数pairを統計的独立とはみなさない。radius、unit membership、fragmentation候補数でsupportを水増ししない。

### 10.2 初期表示候補のbenchmark

Transferred evidenceをTarget explanation／improvementの初期表示へ載せる条件を、次の候補で比較する。

| Parameter | 比較候補 |
|---|---|
| unique pair数 | 2、3、5 |
| unique constant-context数 | 1、2、3 |
| Favorable方向一致率 | 0.67、0.75、0.80 |
| Environment | Exact、Radius-2、Radius-1まで |

推奨初期値は、unique pair 3以上、unique context 2以上、方向一致率0.80以上、mappingがunique／symmetry-equivalentである。基準未達Evidenceは削除せず、低信頼referenceとして折り畳む。

測定誤差情報が入力にない場合、統計的significanceを擬似的に作らない。入力にreplicate／assay情報がある場合だけ、別のuncertainty項目として利用する。

### 10.3 Target別routing

1. Direct MMPでTargetがB側ならTarget explanationへ送る。
2. Direct MMPでTargetがA側ならObserved improvementへ送る。
3. Transferred evidenceでTarget類似構造がB側ならTransferred explanationへ送る。
4. Transferred evidenceでTarget類似構造がA側ならProposed improvementへ送る。
5. neutral、両側mapping、ambiguous mappingはEvidence viewへ残し、主結果へ混ぜない。

同じTargetは四つのrouteを同時に持ち得る。TargetがGlobal Top 1かどうかでrouting ruleを変更しない。

### 10.4 Virtual Candidate

1. Target上のBefore fragmentとattachmentをmappingする。
2. After fragmentへ置換する。
3. RDKit sanitize、valence、stereo、重複を検証する。
4. supporting／conflicting Evidenceを接続する。
5. Candidate rankの各根拠を別列で保存する。

Rankingは不透明な一つのscoreだけに依存せず、少なくともmapping、Environment、support、direction consistency、median deltaを表示可能にする。

### Human checkpoint C

説明／改善Evidenceの初期表示条件、最大候補数、Virtual Candidate生成範囲を人間が承認する。

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
- Map／Explanation／Improvement／Evidence tab
- main workspace
- 右Detail Drawer
- compact footer／詳細CSV link

desktopでは`100dvh`内へ収め、page全体の縦scrollを発生させない。DrawerとTableだけを内部scrollとする。

### 12.2 Relationship Map

1. 3／4／5 Coreの承認済みradial layoutをcomponent化する。
2. Target紺、Core緑、Neighborオレンジを固定する。
3. Initial Mapを最大5 Core × 各3 Neighborへ制限する案を実装する。
4. Neighborへ小さいNeighbor側variable fragment、ID、Endpoint、改行した正値のFavorable Δを示す。TargetのA/B位置からBefore／After labelを決める。
5. 省略件数を`+N`で表示する。
6. viewport変更時にMapを再fitし、Nodeが切れないようにする。
7. Direct pairのedgeを常にFavorable方向A → Bの矢印で描く。
8. Targetへ入るedgeをexplanation、Targetから出るedgeをObserved improvementとしてbadge表示する。

### 12.3 Interaction

Neighbor click:

- Target–Core–Neighbor pathを強調
- 他Nodeをdim
- Drawerにalign済みTarget／Neighbor、Before／After、Endpoint、正値のFavorable Δを表示
- Direct／Transferred、explanation／improvement、observed／virtualを独立badgeで表示

Core click:

- Core構造、Attachment、件数、Favorable Δ Summaryを表示
- 関連MMP compact tableを表示
- 上位5件を初期表示
- row clickでNeighbor detailへ切替

共通:

- 一度に一つのDrawerだけを開く
- Escape、close、Map空白clickで閉じる
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
- Neighbor／Core clickで正しいDrawerへ切り替わる。
- focus、Escape、closeが動作する。
- sort／filter後の表示件数がdata件数と一致する。
- 詳細CSV linkが存在する。

Screenshot画像の意味判定は行わず、DOM、bounding box、text、attribute、eventによって検証する。

### Human checkpoint D

実データとsyntheticな1／3／4／5／8 Core例を人間が操作し、情報密度、Drawer幅、構造サイズ、初期表示数を承認する。

## 13. Phase 9: 全体ReportとA009導線

### 作業

1. Mode I全体Reportを重複のないTarget indexへ変更する。
2. Target cardへselection source一覧、Direct explanation、Observed improvement、Transferred explanation、Proposed improvement、1-cut／2-cutの件数を示す。
3. Mode II Database Summaryを別HTMLとして生成する。
4. A009は`mmp_report_index.json`だけを読み、個別Interactive HTMLへlinkする。
5. Direct MMP 0件Targetにもlinkを作る。
6. 旧pathを参照するconsumerに互換linkまたは明確なmigration errorを提供する。

### Test

- 同一Targetの複数sourceが一つのcard／HTMLになる。
- A009から全Targetへのlinkが解決する。
- Report件数がTarget registry、canonical pair、Evidence tableと一致する。

## 14. Phase 10: Runtime、Catalog、文書同期

### 作業

1. RuntimeのA008 Execution Requestを2 Modeへ更新する。
2. Mode II → Mode Iの依存関係をprofileへ反映する。
3. capability、catalog、included skills、package verifierを同期する。
4. `CONDUCTOR_output_contract.md`、Skill README、SKILL.md、quick reference、Promptを更新する。
5. 旧Type名称が新規Reportや新規Promptへ残っていないことを検査する。
6. Versionとcalculation signatureを全Artifactで一致させる。

### 完了条件

- Runtime、Skill、Schema、Catalog、docsが同じ2 Mode契約を示す。
- 配布Skillがself-containedである。

## 15. Phase 11: E2E、性能、Report監査

### 科学contract test

- 1-cut回帰
- 2-cut Hard gate
- reducibility
- Attachment mapping
- Environment class
- direction consistency
- Target deduplication
- Favorable-oriented A/B routing
- Direct／Transferred × Explanation／Improvement分類
- Evidence support／conflict
- Virtual Candidate validation

### Report contract test

- Template ID／Version／hash
- 必須ViewとDrawer
- DOM click behavior
- 表示件数とcanonical data件数
- link切れ
- CSV／SQLiteへのdrill-down
- unit metadataの重複非計上
- 1-cut／2-cut、Observed／Virtualの表示分離
- Direct／TransferredとExplanation／Improvementの四象限分類
- Map edge方向と正値Favorable Δ

### E2E

1. 小規模化学fixture
2. ChEMBL JAK2 validation data
3. Direct MMP 0件Target
4. 多数Core／多数Neighborを持つstress fixture
5. 最大5,000化合物相当のDatabase build性能確認。synthetic dataを使う場合は科学評価と分離する。

### 性能目標案

- Target個別HTML: 原則10 MiB以下
- 初期表示用Node: 5 Core × 3 Neighborを基本上限
- reference PCで初期DOM ready: 2秒以内を目標
- clickからDrawer更新: 100 ms以内を目標
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
| 方向が成果物間で逆転 | Favorable-oriented A/B、固定構造方向も併存、四象限fixture、cross-artifact test |

## 18. Definition of Done

- A008が2 Mode契約で実行できる。
- Run全体Databaseを一度構築し、複数Targetが再利用できる。
- analysis unit Top 1、Global Top 1、人間指定Targetを重複なく扱える。
- 1-cut baselineを維持し、承認されたHard gateで2-cutを抽出できる。
- Exact／Radius-2／Radius-1／Environment mismatch／ambiguousを区別できる。
- Attachment mappingの位置とconfidenceを監査できる。
- 全pairの表示方向がFavorable Δ正値のA → Bへ揃う。
- Direct／TransferredとTarget explanation／improvementが独立分類される。
- TargetがA側のDirect MMPをObserved improvementとして表示できる。
- TargetがB側のTransferred evidenceをTarget explanationとして表示できる。
- Virtual Candidateが観測化合物と明確に区別され、構造validationされる。
- Analysis unit membershipがpair supportを水増ししない。
- PCワイド画面の一画面内でMap、Neighbor detail、Core MMP一覧、Evidence、Improvementを切り替えられる。
- 1／3／4／5／多数CoreでMap layoutとDrawerが動作する。
- HTML、CSV、SQLiteの主要件数と方向が一致する。
- link／件数／DOM interaction監査がPASSする。
- LLM Visionを使用していない。
- package verification、全contract test、代表E2EがPASSする。
- 人間が科学閾値とInteractive UXを別々に承認している。

## 19. 実装前に必要な回答

### Q1. Mode IIの位置づけ

推奨: 定型A008ではMode IIを必須の先行処理とし、Mode Iはcompatible Databaseを必ず再利用する。これによりTarget improvementと全体Evidenceが常に同じ母集団になる。

### Q2. 2-cutの数値閾値

推奨: Phase 4のgridを先に計算し、Session内で代表構造と件数を確認してから固定する。現時点で単一値を決めない。

### Q3. Transferred evidenceの初期表示

推奨初期案: explanation／improvement共通で、unique pair 3以上、unique context 2以上、方向一致率0.80以上、unique／symmetry-equivalent mapping。基準未達は折り畳み、ambiguousは非表示とする。

### Q4. Similar Coreのmetric

推奨: Morgan Tanimotoを候補検索だけに使い、最終合否はAttachment-constrained MCS coverageとEnvironmentで決める。Tanimoto単独採用は禁止する。

### Q5. Virtual Candidate

推奨: 0.1.11で構造生成とRDKit validationまで実施する。Endpoint予測model、合成可能性予測、候補自動採用は行わない。

### Q6. Interactive Map上限

推奨: 初期表示を5 Core × 各3 Neighborとし、Core clickのDrawerから全関連MMPへ到達可能にする。

### Q7. Offline Artifact形態

推奨: HTML単体ではなくA008 Artifact directory全体を自己完結単位とする。HTMLには操作に必要な要約dataを埋め込み、構造asset、詳細CSV、SQLiteは相対linkで保持する。

### Q8. Neutral tolerance

推奨: assay由来の測定誤差情報がないRunでは0とし、Endpointが完全同値の場合だけneutralとする。信頼できる誤差幅が入力される場合に限り、その範囲内をneutralとして別parameterに記録する。
