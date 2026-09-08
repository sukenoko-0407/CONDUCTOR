# CONDUCTOR 0.1.11 A008 MMP大幅更新 仕様概要書

Status: **Report再設計を実装中。旧A008_v10は人間評価で不合格のため完了扱いにしない。**

## 1. 文書の位置づけ

本書は、0.1.11で実施するA008 MMP大幅更新の仕様案を、これまでの協議内容に基づいて統合したものである。0.1.10で実装済みのMMP Reportをbaselineとし、解析、情報抽出、Target improvement、Interactive HTMLを一体として再設計する。

- 0.1.10: A003、Schema、Series、Report監査、Prompt等の追補。MMP追加改修は行わない。
- 0.1.11: A008 MMPだけを大幅更新する。
- 0.1.12: Runtime Supervisor、Endpoint選抜安定性、A005予測安定性、共通runner再編を扱う。

0.1.11の実装は、本書と[`CONDUCTOR_0.1.11_implementation_plan.md`](CONDUCTOR_0.1.11_implementation_plan.md)に従う。数値閾値を事前推測で固定せず、計画されたbenchmark checkpointで人間が確定する。

## 2. 目的

0.1.11では、A008をTarget周辺のMMP列挙機能から、次の二つを根拠付きで提供するMMP intelligence toolへ発展させる。

1. **Positive N2T**: Targetを常に表示上の生成物側に置いた`ΔN2T >= +0.10`のEvidenceを整理する。
2. **Negative N2T**: 同じTarget固定方向の`ΔN2T <= -0.10`のEvidenceを整理する。

MMPがTargetへ直接接続するか、別Coreで観測された間接Evidenceかは、説明／改善とは別の分類軸である。Direct MMPにもTarget改善があり、Transferred evidenceにもTarget説明がある。

製品目標は、PCワイド画面で利用するoffline Interactive HTMLである。Web server、Web API、account、外部Databaseは0.1.11では要求しない。

## 3. 非対象

- 3-cutの標準解析
- ring bondを自由に切断する一般的scaffold hopping
- 3D binding-site解析
- 合成可能性の保証または合成route設計
- Virtual CandidateのEndpoint値を確定値として予測すること
- MMP以外のA003–A007、A009本体、Series形成の仕様変更。ただしA009へのstatic Relationship Map埋め込みは0.1.11の接続変更に含む
- Runtime Supervisor等、0.1.12へ移管済みの項目

## 4. 用語と責務

| 用語 | 意味 |
|---|---|
| Observed pair | Run内の二つの実測化合物から得たcanonicalなMMP pair |
| Transformation | variable fragmentの`From → To`置換規則 |
| Exact Core | attachment pointを含み、pair内で厳密に保持されたconstant構造 |
| Environment | attachment point周辺のradius 0–2の局所構造 |
| Target-oriented pair | TargetまたはTarget対応構造を常に生成物側へ置き、反対側からTarget側へのsigned Δを保持したReport表現 |
| Connection scope | Targetを実測pairに含む`direct`か、別pairから対応付けた`transferred`か |
| N2T class | `ΔN2T`の符号による`Positive N2T / Negative N2T / Neutral`。Evidence自体の優劣ではない |
| Direct evidence | Target自身を一端に含むObserved pair |
| Transferred evidence | Targetを含まないObserved pairから、Targetへの適用可能性を評価したEvidence |
| Virtual Candidate | 観測TransformationをTargetへ適用して生成した未測定構造 |
| Analysis unit metadata | Target／NeighborのSeries・Cluster所属情報。MMP数を増やすEvidenceではない |

2-cutの`A—B—C → A—B'—C`では、創薬化学上Bをcore部分と呼ぶ場合があるが、MMP内部では交換されるB/B'が`variable`、保持されるA/Cが`constant`である。SchemaとReportではこの語義を混同しない。

## 5. 実行Mode

現行Type-I／II／IIIを二つのModeへ集約する。

| 表示名 | CLI／contract値 | 目的 |
|---|---|---|
| Mode I: Target analysis | `target` | Execution Requestで明示されたTargetを解析し、個別Interactive HTMLを生成する |
| Mode II: Database build | `database` | Run全体のcanonical MMP Databaseと集計Artifactを構築する |

### 5.1 Mode IのTarget

Mode Iは、Execution Requestで明示されたRun内compound IDのTarget一覧だけを解析する。`standard`／`explicit`等の追加submodeは設けず、Targetを誰が選んだかは`selection_source` metadataで表す。

- CONDUCTOR定型実行では、Orchestratorが各採用analysis unitのEndpoint Top 1とRun全体のEndpoint Top 1を選び、重複除去した一覧をMode Iへ明示的に渡す。
- On-demandでは、人間が指定したRun内compound IDをMode Iへ明示的に渡す。
- 一つのrequestで複数sourceが同じcompound IDを選んでも、MMP抽出と個別HTMLは一度だけ作り、Target registryには全`selection_source`を保持する。

Endpoint同値時は、入力順に依存せずcompound ID昇順で決定する。Favorable方向はRun contractを使用する。Run外compound IDは受け付けない。

TargetにDirect MMPが0件でも、Target registry、個別HTML、A009からの導線を作る。Target improvement候補がある場合はDirect MMPが0件でも別枠で示す。

### 5.2 Mode IIの役割

Mode IIは、Run全体の1-cut／2-cut pair、Transformation、Exact Core／Retained anchors、Environment、固定構造方向のEndpoint差を一度だけ構築する。Canonical DatabaseはTarget非依存かつ構築完了後immutableとする。Target registry、Target別Evidence、Virtual Candidate、Report用状態は保存しない。

Mode Iは最初にcompatibleなCanonical Databaseを探索する。存在すればread-onlyで再利用し、存在しなければMode IIと同じbuilderをMode I内部から一度だけ呼び出して構築してからqueryする。標準RuntimeでMode II NodeとMode I Nodeを二重作成しない。Mode IIはDatabaseだけを明示的に事前構築したい場合にも単独実行できる。

正式対応上限は1 Run 5,000化合物とする。通常想定は2,000化合物未満であり、5,000化合物は性能・容量試験の上限caseとして扱う。

Database compatibilityは二層signatureで判定する。

- `structure_signature`: compound ID、canonical isomeric SMILES、fragmentation engine／version、cut SMARTS、cut数、構造gate parameter、canonicalization規則。
- `effect_signature`: Endpoint列と値、Higher／Lower favorable、neutral tolerance、効果量計算version。

Report Template／CSS／JavaScriptの変更はDatabase再構築理由にしない。構造signatureが一致しeffect signatureだけが変わる場合は、保存済み構造pairから効果列を再計算できる構成にする。構築は一時Databaseへ行い、Schema・件数・整合性監査PASS後にatomic renameしてimmutable完成版とする。失敗した一時Databaseをcompatible cacheとして扱わない。

### 5.3 旧Typeとの互換

0.1.11では旧parameterを互換adapterで次へ変換し、deprecation warningと変換結果をmanifestへ記録する。

| 旧指定 | 変換先 |
|---|---|
| Type-I | Orchestratorがanalysis unit Top 1＋Global Top 1を明示Target化した`target` |
| Type-II | 人間指定Targetだけを明示した`target` |
| Type-III | `database` |

新engine内部には3 Type別の科学計算分岐を残さない。

## 6. Canonical dataと方向

### 6.1 Canonical pair

IDは三層に分ける。`compound_pair_id`はcanonicalな二つのcompound IDだけから作るcut非依存ID、`pair_id`は`compound_pair_id + cut_count`から作るcut別ID、`pair_transformation_id`は`pair_id + transformation_id + core_id`から作る変換行IDとする。同じcutのpairが複数analysis unit、複数radius、複数Coreに現れても独立pair数を増やさず、非包含な複数Coreの変換行は失わない。

Databaseでは方向中立なcanonical pairと、Endpointに依存せずcanonical fragment順で決めた固定構造方向を保存する。Target-oriented viewはTarget解析時に派生させ、Canonical Databaseのrow方向を変更しない。

- `compound_x_id`、`compound_y_id`
- 両側のSMILESとEndpoint
- fixed structural directionの`directed_transform_id`とsigned delta
- direction-neutralな`transformation_family_id`
- fixed structural directionで正負を保持する`normalized_signed_delta`
- `effect_semantics`

Target別Artifactには、上記から派生したsigned `target_oriented_delta`、`connection_scope`、`interpretation_role`を保存する。互換・集計用の`pair_favorable_gain`は残してよいが、Target Reportの方向やΔ表示には使用しない。

row順から方向を推測してはならない。

### 6.2 Report上のTarget固定方向

Favorable判定用の符号はRun contractから決めるが、Reportでは正方向へ並べ替えない。化合物XからYへの正規化変化を次で計算する。

```text
Higher-is-favorable: normalized_delta(X → Y) = Endpoint(Y) - Endpoint(X)
Lower-is-favorable:  normalized_delta(X → Y) = Endpoint(X) - Endpoint(Y)
```

Direct MMPは常に`Neighbor → Target`と表示し、`target_oriented_delta = normalized Endpoint(Target) - normalized Endpoint(Neighbor)`とする。矢印の先は正負に関係なくTargetである。`|Δ| < 0.10`はneutralとし、Databaseのsigned deltaは反転・上書きしない。

Targetとの関係は次のように分類する。

| Connection scope | Target対応位置 | Interpretation role | 表示内容 |
|---|---|---|---|
| Direct | `ΔN2T >= +0.10` | Positive N2T | Neighbor → Target |
| Direct | `ΔN2T <= -0.10` | Negative N2T | Neighbor → Target |
| Transferred | `ΔN2T >= +0.10` | Positive N2T | counterpart → Target-like side |
| Transferred | `ΔN2T <= -0.10` | Negative N2T | counterpart → Target-like side |

したがって、一つのTarget Report内に説明Evidenceと改善Evidenceの両方が存在し得る。TargetがGlobal Top 1なら説明が多くなりやすいが、Hit-to-LeadのHitをTargetにした場合はDirect improvementも重要な主結果となる。

Transformation集計では、direction-neutralなfamilyとDatabase固定構造方向のsigned deltaを使用する。Consensusと同じ符号を`supporting`、逆符号を`conflicting`、`|Δ| < 0.10`を`neutral`とし、方向一致率は`supporting / (supporting + conflicting)`とする。これはEvidence再現性の集計規則であり、Target Reportを正方向化する規則ではない。

Target別のConsensus favorable directionは、同一`target_id + cut_count + transformation_family_id`内で次の単純な決定規則により決める。Target全体や異なるTransformation familyを横断した一つの多数決にはしない。

1. 当該Transformation familyにExact Target Coreの直接MMPがある場合は、そのTarget接続変換だけを方向決定母集団とし、類似Coreのpairをその方向へalignする。複数行があれば方向別Count後に同じSort規則を適用する。
2. Exact Target Coreがない場合は、互換性のある同一Environment class内で非neutral pairを方向別にCountする。
3. `count`降順、次にcanonicalな方向key昇順でSortし、一番上の方向を採用する。canonical方向keyはattachment label付きcanonical variable fragmentの`from_smiles → to_smiles`とする。同数時のmedian判定や`direction ambiguous`への追加分岐は設けない。
4. Radius-2一致、Radius-1一致、Environment不一致を混ぜてCountしない。Environment不一致は比較referenceとして分離する。

Target表示とTransformation集計では方向の目的が異なるため、値を分ける。

- `target_oriented_delta`: TargetまたはTarget対応構造を生成物側へ固定したsigned値。Target Report、Map、説明文で使う。
- `normalized_signed_delta`: Database固定構造方向のsigned値。Canonical Databaseで保持する。
- `consensus_aligned_delta`: 互換性のあるEnvironment群内のConsensus方向へ揃えたsigned値。Evidence集計とTransferred routingで使う。
- `pair_favorable_gain`: 旧表示との互換・補助集計用の絶対値。Target Reportの矢印とΔ表示には使わない。

conflicting pairを個別に正方向へ反転して方向一致率を計算してはならない。Target別ArtifactとReport schemaは、どちらの値かをcolumn名で区別する。

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
- 同一Target–Neighborと同じcut countに複数Coreがある場合、Databaseは全行を保持し、Reportだけを最大Coreへ集約する。1-cutはattachment dummyを除いたCore本体、2-cutはdummyを除いた二つのRetained anchor componentの一対一対応で部分構造包含を判定する。包含される小Coreを除外し、相互に包含されないCoreは両方残す。同一Coreの重複行は決定論的に1件へ集約する。
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

2-cut候補には、危険または解釈不能な表現を除く`absolute safety floor`と、初期表示品質を決める`standard quality threshold`の二段階を適用する。

`absolute safety floor`では少なくとも次を要求する。

- variable fragmentは一つの連結成分でattachment pointが正確に二つ。
- 二つのconstant fragmentをcanonicalなattachment順で保持する。
- attachment mappingがuniqueまたはsymmetry-equivalent。
- 再構成後のvalence、芳香族性、stereochemistry、分子内接続が妥当。
- 1-cutへ還元できる冗長表現を標準2-cut Evidenceへ含めない。

`standard quality threshold`では、両constant fragmentの最小heavy atom数、combined constantの最小保持割合、variable fragmentの最大heavy atom数／分子割合を評価する。最終数値はbenchmark checkpointで固定する。

ring bond切断と3-cutは0.1.11標準から除外する。

### 7.3 2-cut構造品質class

`2C-A／B／X`はTarget非依存の構造品質だけを表し、Targetへの適用性、Environment適合、support件数を含めない。

| Class | 意味 | 標準表示 |
|---|---|---|
| `2C-A` | 標準size条件をすべて満たし、mappingがunique／symmetry-equivalent、1-cut非冗長、再構成可能 | 初期表示候補 |
| `2C-B` | attachmentと再構成、両Anchorの最低sizeは妥当だが、保持割合またはvariable sizeの標準条件に届かないreview対象 | 折り畳みreference |
| `2C-X` | いずれかのRetained anchorがheavy atom 4未満、mapping ambiguous／failed、attachment不正、ring cut、1-cut冗長、再構成不正 | 非表示。除外理由だけ監査可能 |

Target別Evidence品質は別列`target_evidence_quality = high | limited | not_applicable | ambiguous`で保存する。同じ2-cutがTarget Xでは`high`、Target Yでは`limited`、Target Zでは`not_applicable`となり得る。`2C-A／B／X`自体は変化させない。

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

Exact Coreでない候補にはAttachment-constrained MCSを使用する。

- attachment dummy／labelを保持する。
- Attachmentを含まないMCSを採用しない。
- 同率mappingを列挙する。
- `unique`、`symmetry_equivalent`、`ambiguous`、`failed`に分類する。
- ambiguous／failedはTransferred explanation／improvementの標準候補にしない。
- TargetにDirect MMPがなくてもTarget自身のeligible 1-cut／2-cut fragmentationを保存し、Target側variable fragment、constant／Retained anchors、full-molecule attachment atomの対応をqueryに使用する。
- Transferred evidenceでは、Targetの現在のvariable fragmentがObserved TransformationのA側、B側、どちらでもない、または両側のどれに対応するかを判定する。A/B対応からTarget固定方向のsigned Δを導出し、その符号で読み分ける。どちらでもなければ`not_applicable`、両側または複数siteへ非同値mappingする場合は`ambiguous`とする。

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

方向集計用の`environment_group_id`は、cut count、ordered attachment topology、採用した最大一致radius、同radiusのcanonical Environment signatureから作る。同じEvidence classでもEnvironment signatureが異なる行は別groupとする。Radius-2が一致する行はRadius-1集計へ重複投入せず、利用可能な最大一致radiusへ一度だけ所属させる。Environment mismatchは各signature別の比較referenceとし、Target向けConsensus directionを決めない。

### 8.4 Evidence Summary

各Evidence groupは`cut_count + transformation_family_id + environment_group_id`単位とし、同一`pair_id`を一度だけ数える。各groupについて少なくとも次を保存する。

- unique compound-pair数
- unique compound数
- unique Exact Core／Retained-anchor context数
- 固定構造方向のsigned deltaのmedian、IQR、min、max
- Target別表示用のsigned `target_oriented_delta`（`pair_favorable_gain`は互換・補助集計のみ）
- Favorable方向一致率
- supporting pairとconflicting pair
- neutral pair数とmissing Endpoint pair数
- 化合物を共有しないpairの最大集合数`disjoint_pair_count`（hub集中の参考指標であり合否条件にはしない）
- 利用可能な最大Environment radius
- mapping statusとmapping confidence
- cut countと2-cut品質class

`independent_compound_count`という名称は使わない。unique数は統計的独立性を保証しないためである。

`unique context`は、1-cutではattachment labelを含むExact Core、2-cutではordered attachment topologyを含むRetained anchorsの一意数とする。同じcontextのradius違い、analysis unit所属違い、Target違いは増分しない。Endpoint missing／neutral pairはcontextの存在件数には含められるが、方向一致率の分母には含めない。`disjoint_pair_count`はcompoundを頂点、pairを辺とするgraphの最大cardinality matchingの辺数とする。

## 9. Target explanation／improvement routing

### 9.1 Direct MMP

Targetへ直接接続するMMPは、正負にかかわらず常に`Neighbor → Target`として表示する。`target_oriented_delta = normalized Endpoint(Target) - normalized Endpoint(Neighbor)`を使い、正値へ反転しない。

- `target_oriented_delta >= +0.10`: TargetのEndpointを支える観測として表示する。
- `target_oriented_delta <= -0.10`: Neighbor側のFragmentをTarget改善へ検討する手掛かりとして表示する。
- `|target_oriented_delta| < 0.10`またはEndpoint欠損: neutral／missing Evidenceとして残し、上記二つの主結果へ含めない。

正負はEvidence品質の上下を意味せず、同じ実測MMPに対するTarget基準の読み方だけを変える。

### 9.2 Transferred evidence

Targetを含まないObserved Transformationについて、Targetのeligible fragmentationとObserved pairをAttachment mappingで対応付け、Targetの現在のvariable fragmentがConsensus directionのA/Bのどちらへ対応するかを判定する。A/BはDatabase集計と対応判定のための内部表現であり、Target Reportの矢印方向ではない。

- TargetがB側へ対応: Target類似側を表示上の生成物として`target_oriented_delta`を導出する。正ならTargetを支える参考観測、負なら改善の手掛かりと読む。
- TargetがA側へ対応: 同様にTarget類似側を表示上の生成物としてsigned Δを導出し、その正負で読み分ける。
- Targetが両側へmapping可能、または対応が一意でない: ambiguousとして標準表示しない。
- TargetがA/Bどちらのvariable fragmentも持たない: not applicableな比較referenceとし、説明／改善へ送らない。

`target_evidence_quality`は次で決める。

- `high`: Direct exact observation、またはmappingがunique／symmetry-equivalent、EnvironmentがExact／Radius-2、かつTransferred初期表示のsupport条件を満たす。
- `limited`: mappingはunique／symmetry-equivalentだが、support不足、Radius-1一致、またはEnvironment mismatchである。Environment mismatchは比較referenceとして分離する。
- `not_applicable`: Targetの現在fragmentがA/Bどちらにも対応しない。
- `ambiguous`: A/B両側または複数非同値siteへ対応する、もしくはmapping自体がambiguous／failedである。

### 9.3 Proposed improvementとVirtual Candidate

Run全体のObserved Transformationのうち、Targetの現在FragmentからEndpoint改善側Fragmentへの置換を一意に対応付けられるものから、Targetへ適用可能な改善候補を探索する。

```text
Observed Transformation
  → Environment group内のConsensus方向とsupport/conflictを確認
  → Targetが改善前Fragmentを持つか
  → Targetの現在Fragmentへ一意に対応するか
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

生成構造がRun内既存化合物と一致した場合はVirtual Candidateとして保存せず、既存compound IDとEndpointを接続してObserved compoundへ再分類する。Target内に非同値な複数適用siteがある場合はsite別候補を生成し、canonical isomeric SMILESで重複除去する。

既存のstereochemistryは保持する。変換によって新しい未指定stereocenterが生じる場合は任意の立体を割り当てず、`stereo_status = unresolved_new_center`として記録し、標準の上位候補ではなく折り畳みreferenceへ送る。

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
- workspace: `100dvh`相当。headerを除く領域をMap／情報抽出View／広幅Detail panelで使用
- desktopではpage全体を縦scrollさせず、Detail panelと各Viewだけを内部scroll
- 外部CDN、Web API、serverを要求しない
- 化学計算、mapping、Evidence判定はPython側で完了する
- JavaScriptはfilter、sort、選択、表示切替だけを担当する

狭い画面では機能を削らず縦積みへfallbackするが、0.1.11の最適化対象はPCワイド画面とする。

### 11.2 画面構成

```text
┌ Target header / Endpoint / selection source / legend ┐
├ Relationship Map | Transformation | N2T Direction | Target Connection | N-Cuts | Data Table ┤
├ Utility: Evidence Guide                                          ┤
│                                                       │
│ Main workspace                         Detail panel   │
│ Map / interpretation cards             650–920 px     │
│                                                       │
└ Status / shown count / detailed CSV link ─────────────┘
```

Detail panelを閉じた状態ではMain workspaceを全幅で使う。開いた場合はPC幅の約55–60%を使い、viewport内に収める。巨大なModalやpage下部への追加表示は行わない。

### 11.3 初期Relationship Map

- Targetを中央、Exact Coreを中間、Neighborを外周に配置する。
- Targetは紺、Exact Coreは緑、Neighborはオレンジ。
- Target cardを最大、Core cardを小さく、Neighbor cardをtext-onlyでcompactにする。小さいMap cardへFragment構造を入れない。
- Neighbor cardにはcompound ID、Endpoint、`ΔN2T`を示す。カード間の非重複を最優先し、その範囲で横幅を確保する。
- 各CoreのNeighborが5件以下なら全件を個別Nodeとして示す。6件以上は`N Neighbor`の件数Nodeへ集約するが、Core detailでは全件を省略せず表示する。
- 初期表示は最大5 Coreとし、Core順位は表示対象Direct pair数降順、最大`|target_oriented_delta|`降順、canonical Core ID昇順で決定する。
- Mapは利用可能な幅と高さへfitし、3／4／5 Coreで確認済みのradial layoutを基準とする。斜め位置のCoreからNeighborを外側の左右方向へ展開し、縦方向の拡大を抑える。
- Direct pairの矢印は正負にかかわらず常にNeighborからTargetへ向ける。Coreは保持構造を表す注釈Nodeであり反応中間体ではない。
- Target、Core、Neighborを結ぶMap内connectorはすべて破線で統一する。
- `ΔN2T >= +0.10`なら紺、`ΔN2T <= -0.10`ならオレンジ、neutral／missingは灰色で示す。これはEvidenceの優劣を表さない。
- Map内の凡例領域をNode領域から分離し、cardと説明文の重なりを構造的に禁止する。
- 1-cutと2-cutは同じ集計またはMap layerへ混在させず、cut class filter／Viewで切り替える。2-cutでは中間Nodeを`Retained anchors`と表示する。

### 11.4 Neighbor click

Neighborをclickすると広幅Detail panelへ次を示す。

- Target／Neighborのalign済み全体構造
- 中央に共通Core、その下にNeighbor Fragment → Target Fragment
- Target／Neighbor IDとEndpoint
- Neighbor → Targetの固定矢印と`ΔN2T`
- 2D Alignの成否を`Align ✓ / Align ×`で示す
- 1-cut／2-cut
- Exact Core、Environment radius、Evidence class
- Supporting／conflicting Evidenceへの導線

全体構造は共通Core基準で2D Alignする。Alignできない場合も両化合物全体を表示し、矢印下へ`Align ×`を明示して向きの対応を保証しない。

### 11.5 Core click

CoreをclickするとDetail panelをMMP portalへ切り替える。

- 左に緑枠のCore構造、右に紺枠のTarget構造
- MMP数、Neighbor数
- Direct MMPの全Neighbor一覧
- Target側Coreへ対応する類似Core一覧とTransferred Evidence件数
- 類似Coreを中心としたsecondary Map
- Neighbor clickでDirect detail、類似Core clickで観測MMP一覧へ切替
- Core → 類似Core → 個別MMPの遷移履歴を保持し、「戻る」で一段前へ戻す

### 11.6 View切替

- `Relationship Map`: Targetへ直接接続する実測MMPの探索portal
- `Transformation`: 同じFragment TransformationをTarget-side Core横断で単一cardへ集約する。All／Direct／Transferredを切り替え、詳細panelで固定構造方向A→B、Direct／Transferred件数、関連Core数、全観測への導線を示す
- `N2T Direction`: `ΔN2T >= 0`と`ΔN2T < 0`をsubtabで切り替え、Target基準の読み取り方向を示す。DirectとTransferredの双方を含み得るため各cardに内訳を示す。`|ΔN2T| < 0.10`は符号側へ置くが方向Evidenceの基準通過とは扱わない
- `Target Connection`: Targetを実際に含むDirect MMPあり／Transferredのみをsubtabで切り替える。cardは`Exact Core`と総称せず、1-cut／2-cutsとDirect／Transferred件数を示す
- `N-Cuts`: 1 Cutと2 Cutsをsubtabで切り替える
- `Data Table`: 全行を確認するsecondary Table。情報抽出の主画面とはしない
- `Evidence Guide`: 右端の補助tab。解析内容、N2T、Evidence品質、`2C-A／B／X`、1/2-cut、mapping、2D Alignの固定説明

選択中Target、Core、Neighbor、filter状態はView切替後も保持する。Escapeまたはclose buttonでDetail panelを閉じる。

### 11.7 Tableと導線

- 主Viewは生のEvidence行ではなく、Transformation familyごとの正／負件数、median `ΔN2T`、Direct／Transferred内訳、代表構造を示す。
- cut class、Evidence品質、text filterはTransformation、N2T Direction、Target Connection、N-Cuts、Data Tableへ共通適用する。
- 詳細CSVリンクは各Viewの最下部または固定footerに置く。
- HTMLへ埋め込むのは表示対象Evidenceと表示用metadataに限定する。
- Transferred全体構造は`targets/assets/*.svg`へ相対pathで外部化し、実体は復号済みSVG XMLとする。HTMLと`assets/`を同じ階層関係で移送すれば別machineでも表示できる。
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

A009へは静的Relationship Mapだけを接続する。全体Summaryでは主要解析結果、PCA／UMAP、個別report一覧の後にGlobal Top1 Mapを置く。個別analysis unit reportではA007 Structural signatureの後に当該unit Top1 Mapを置き、headerや冒頭へ配置しない。

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
├── mmp_report_index.json
├── mmp_report.html
├── mmp_database_report.html
├── targets/
│   ├── mmp_target_<compound_id>_<hash>.html
│   ├── mmp_static_map_<compound_id>_<hash>.svg
│   ├── target_registry_<compound_id>.csv
│   ├── target_evidence_<compound_id>.csv
│   └── virtual_candidates_<compound_id>.csv
└── assets/
    └── generated structure SVG files when needed
```

Canonical DatabaseとそのmanifestはTarget非依存とし、`targets/`以下はMode Iが生成するTarget別Artifactとする。Mode IはCanonical Databaseをread-onlyで使用する。

`mmp_report_index.json`はTarget ID、selection source一覧、Interactive HTML path、自己完結したstatic SVG path、主要件数を持つVersion付き契約とする。A009はこのindexだけを読み、static SVGだけをA009 Reportへ掲載する。Interactive HTML、JavaScript、Target Evidence tableはA009へ複製しない。

A009個別analysis unit Reportには、そのunitのTop 1 Targetのstatic Mapを掲載する。A009全体SummaryにはGlobal Top 1のstatic Mapを掲載する。同じcompound IDが両方を兼ねる場合もA008側のSVGは一つだけ生成して再利用する。On-demand TargetはA009へ自動追記しない。

## 14. Templateと監査

- HTMLはVersion付きcanonical Templateだけから生成する。
- Template ID、Version、hashをmanifestへ記録する。
- JavaScriptとCSSはrepository管理し、外部CDNへ依存しない。
- HTML文字列、ID、SMILES、SMARTSをescapeし、`eval`を使わない。
- Report監査はDOM、link、件数、filter対象、click後の表示内容を機械確認する。
- Interactive HTMLのDOM／bounding-box／event試験にはrepositoryでVersion固定したPlaywrightを使用する。
- LLM Vision、Screenshot解釈、画像内容のAI判定は禁止する。
- 化学構造の正しさは元SMILES、描画成功、mapping atom index、生成物validationで検証する。

## 15. 互換性

- 0.1.10以前の完了Run Artifactを書き換えない。
- 0.1.11の新規Runだけへ新Database schemaとInteractive HTMLを適用する。
- 0.1.10のMMP HTML rendererはlegacy fixtureとして保持する。
- 旧3 Type入力は0.1.11で互換adapterを通すが、新Artifactは2 Mode用語だけを使用する。
- A009は巨大なpair dataを読まず、`mmp_report_index.json`が示すTarget別static Relationship Mapだけを掲載する。

## 16. 確定済み事項

- 0.1.11はMMP専用Versionである。
- 2 Modeへ集約する。
- Mode Iに各analysis unit Top 1、Global Top 1、人間指定Targetを含められる。
- Mode Iに追加submodeを設けず、CONDUCTORまたは人間が作った明示Target一覧を処理する。
- Mode Iはcompatible Databaseを再利用し、存在しない場合だけ内部でCanonical Databaseを構築する。
- Canonical DatabaseはTarget非依存かつimmutableである。
- Canonical Databaseの正式対応上限は1 Run 5,000化合物である。
- Target探索母集団はRun全体である。
- 同じTargetは一度だけ解析・Report化する。
- Relationship Mapは個別HTML最上部の初期Viewである。
- Targetは紺、Coreは緑、Neighborはオレンジとする。
- Map clickからNeighbor detail／Core MMP一覧へ移動する。
- PCワイド画面内で表示を切り替え、詳細はwide detail panelにコンパクトに配置する。
- 1-cutをPrimary、2-cutを独立classとする。
- Analysis unit所属は保存するが、Mapでの明示はoptionalである。
- Positive N2TとNegative N2Tを分離する。
- Direct／TransferredとN2T classを独立した分類軸にする。
- Target Reportの表示方向は常にNeighbor／類似構造 → Targetとし、signed `ΔN2T`を正値へ揃えない。
- Databaseは固定構造方向のsigned deltaを保持し、Target別の表示方向や解釈で上書きしない。
- `|Δ| < 0.10`をneutralとする。
- Exact Target Coreがない場合のConsensus directionは、Environment classを混ぜず、方向別Count降順とcanonical方向key昇順で一意に決める。
- Consensus directionはTarget・cut count・Transformation family・Environment group単位で決め、異なるTransformationを同じ方向Countへ混ぜない。
- `2C-A／B／X`はTarget非依存の構造品質、`target_evidence_quality`はTarget別評価として分離する。
- 1-cutと2-cutはID、集計、Database View、Reportを分離する。
- A009にはTarget別のstatic Relationship Mapだけを掲載する。
- 0.1.11ではWeb GUI／APIを導入しない。

## 17. 実装中checkpointで固定する数値

設計方針は確定した。次の数値だけは、代表的なpositive／negative caseを用いた規定benchmark後に人間が固定する。

1. 2-cutの両Retained anchorは各heavy atom 4以上をabsolute minimumとする。retained fractionとvariable sizeは`2C-A／B`を分ける。
2. similar Core候補検索のMorgan TanimotoとAttachment-constrained MCS coverage。
3. cut SMARTSの標準設定。`default`、`cut_AlkylChains`、`exocyclic`をcoverageとnoiseで比較する。
4. Target HTMLの最大埋め込みEvidence件数。容量10 MiB以下、初期DOM ready 2秒以内、detail panel更新100 ms以内を合格目標とする。

Transferred evidenceの初期表示条件は、unique pair 3以上、unique Exact Core／Retained-anchor context 2以上、方向一致率0.80以上、mappingがunique／symmetry-equivalent、`target_evidence_quality=high`とする。基準未達は`limited`として折り畳み、ambiguousは標準表示しない。Direct observed pairはsupport数に関係なくDirect Viewから到達可能にする。
