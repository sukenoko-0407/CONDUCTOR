# CONDUCTOR 0.1.11 A008 MMP大幅更新 引継ぎ事項

Status: **A008 Report再設計を実装中。旧A008_v10は人間評価で不合格。**

## 1. Version境界

- 0.1.10: MMP追加改修を行わず、既存Reportをbaselineとして維持する。
- 0.1.11: A008 MMP解析、情報抽出、Target improvement、Interactive visualizationを大幅更新する。
- 0.1.12: Runtime Supervisor、Endpoint選抜安定性、A005予測安定性、共通runner再編を扱う。

実装契約は次の二文書を正とする。

- [`CONDUCTOR_0.1.11_specification_overview.md`](CONDUCTOR_0.1.11_specification_overview.md)
- [`CONDUCTOR_0.1.11_implementation_plan.md`](CONDUCTOR_0.1.11_implementation_plan.md)

現行仕様・課題・外部調査は[`research/mmp_transformation_evidence/report-source.md`](research/mmp_transformation_evidence/report-source.md)、初期案は[`research/mmp_transformation_evidence/archive/2026-09-05_v1/report-source.md`](research/mmp_transformation_evidence/archive/2026-09-05_v1/report-source.md)へ保存している。初期案と確定仕様が異なる場合は、上記二つの実装契約を優先する。

## 2. 0.1.11の到達目標

A008をTarget周辺MMPの列挙から、次を根拠付きで提供するMMP intelligence toolへ発展させる。

1. **Positive N2T**: Targetを常に生成物側へ置いた`ΔN2T >= +0.10`のEvidenceを整理する。
2. **Negative N2T**: 同じTarget固定方向の`ΔN2T <= -0.10`のEvidenceを整理する。

Direct／TransferredはTargetとの接続性、Positive／Negative N2TはTargetを生成物側へ固定したsigned `ΔN2T`による分類であり、独立した軸とする。A/BはTransferred mappingとConsensus集計の内部表現に限定する。TargetがGlobal Top 1かHit-to-LeadのHitかによってrouting規則を変えない。

## 3. 実行Mode

| Mode | Contract | 目的 |
|---|---|---|
| Mode I | `target` | 明示Target一覧を解析し、Target別ArtifactとInteractive HTMLを生成する |
| Mode II | `database` | Target非依存のRun全体Canonical MMP Databaseを単独構築する |

- Mode Iに`standard`／`explicit`等のsubmodeを設けない。
- CONDUCTOR定型実行では、Orchestratorがanalysis unit Top 1＋Global Top 1を選び、重複除去してMode Iへ明示する。
- On-demandでは、人間が指定したRun内compound IDをMode Iへ明示する。
- 同じTargetに複数sourceがあっても、解析とHTMLは一度だけ作り、全`selection_source`を保存する。
- Mode Iはcompatible Databaseをread-onlyで再利用し、なければMode IIと同じbuilderを内部で一度だけ呼ぶ。標準RuntimeでMode IIとMode Iを二重Node化しない。
- Mode IIはDatabaseだけを事前構築したい場合に単独実行できる。
- 旧Type-I／II／IIIは互換adapterだけでMode I／IIへ変換し、新engineに旧分岐を残さない。
- 正式対応上限は1 Run 5,000化合物とする。

## 4. Canonical Databaseと方向

Canonical DatabaseはTarget非依存かつ構築後immutableとする。Target registry、Target別Evidence、analysis unit membership、Virtual Candidate、Report状態は別Artifactへ保存する。

Databaseではcanonical fragment順に固定した構造方向と`normalized_signed_delta`を保持する。Target別ReportではTargetを表示上の生成物側に固定したsigned `target_oriented_delta`を別途導出し、正方向への反転もDatabase rowの上書きも行わない。

```text
Higher-is-favorable: Δ(X → Y) = Endpoint(Y) - Endpoint(X)
Lower-is-favorable:  Δ(X → Y) = Endpoint(X) - Endpoint(Y)
```

- `|Δ| < 0.10`: neutral
- `|Δ| >= 0.10`: Target ReportではTargetを生成物側へ置いたsigned `target_oriented_delta`を派生する。正値へ揃えない
- missingとneutralは方向一致率の分母へ含めず、別件数で示す。
- 方向一致率は`supporting / (supporting + conflicting)`とする。

Target別Consensus directionは同一Target・cut count・Transformation family内で決める。異なるTransformation familyを横断した多数決は行わない。

1. 当該Transformation familyにExact Target CoreのDirect pairがあれば、その集合だけを基準にし、類似Coreのpairをその方向へalignする。
2. なければ互換性のある同一Environment class内の非neutral pairを方向別にCountする。
3. Count降順、attachment label付きcanonical variable fragmentの`from_smiles → to_smiles`昇順でSortし、一番上へ合わせる。
4. 同数時のmedian判定や`direction ambiguous`分岐は設けない。
5. Radius-2、Radius-1、Environment mismatchを混ぜない。不一致群は比較referenceとして残す。

Direct Mapでは常にNeighbor → Targetを表示し、signed `target_oriented_delta`を使う。Transformation Evidenceの再現性集計では全pairをConsensusへ揃えたsigned `consensus_aligned_delta`を使い、正をsupporting、負をconflictingとする。`pair_favorable_gain`は互換・補助集計用でありMap表示には使わない。

Database compatibilityは`structure_signature`と`effect_signature`へ分ける。Report Template変更だけでDatabaseを再構築せず、構造signatureが一致する場合は保存済みpairから効果列を再計算できる構成にする。

## 5. 1-cut／2-cut

1-cutをPrimaryなterminal substitutionとして維持し、2-cutを独立したlinker／core replacementとして追加する。`compound_pair_id`はcut非依存、`pair_id`はcut別、`pair_transformation_id`はCore／Transformation別とし、解析、Table／View、集計、Reportを分ける。mmpdbの最大2-cut出力に含まれる1-cutは`cut_count`で確実に分離する。

```text
A—B—C → A—B'—C
```

2-cutは二段階で品質管理する。

- `absolute safety floor`: attachment、連結性、mapping unique／symmetry-equivalent、再構成、ring cut、1-cut reducibility、および両Retained anchor各heavy atom 4以上。
- `standard quality threshold`: retained fraction、variable size。

| 構造品質 | 意味 |
|---|---|
| `2C-A` | standard quality thresholdを満たすTarget非依存の構造候補 |
| `2C-B` | safety floorは満たすが標準size等に届かないreview reference |
| `2C-X` | ambiguous／failed mapping、attachment不正、ring cut、1-cut冗長、再構成不正、安全下限未満 |

`2C-A／B／X`へTarget適用性、Environment、support、Endpoint方向を混ぜない。Target別評価は`target_evidence_quality = high | limited | not_applicable | ambiguous`へ保存する。2-cutの保持構造はReportで`Exact Core`ではなく`Retained anchors`と表示する。

## 6. Transferred evidence

Target自身のeligible fragmentationを作り、Targetの現在のvariable fragmentがObserved TransformationのA側、B側、neither、bothのどれに対応するかをAttachment-constrained MCSで判定する。

| 対応 | 解釈 |
|---|---|
| Direct・`ΔN2T >= +0.10` | Positive N2T |
| Direct・`ΔN2T <= -0.10` | Negative N2T |
| Transferred・`ΔN2T >= +0.10` | Positive N2T |
| Transferred・`ΔN2T <= -0.10` | Negative N2T |
| neither | not applicable reference |
| both／非同値複数mapping | ambiguous。標準表示しない |

Evidence classは次の順とする。

1. Exact-core evidence
2. Radius-2 matched similar-core evidence
3. Radius-1 matched related-core evidence
4. Attachment-mapped but environment-mismatched reference
5. Ambiguous／excluded

Environment方向集計はcut count、ordered attachment topology、最大一致radius、canonical Environment signatureが同じgroup内だけで行う。同じradius classでもsignatureが違えば混ぜず、Environment mismatchはTarget向けConsensus directionに使用しない。

初期表示はunique compound pair 3以上、unique Exact Core／Retained-anchor context 2以上、方向一致率0.80以上、mapping unique／symmetry-equivalent、Target Evidence quality highを満たすものに固定する。基準未達はlimitedとして折り畳み、Direct observed pairは件数に関係なく到達可能にする。

`unique context`は、1-cutではattachment label込みExact Core、2-cutではordered attachment topology込みRetained anchorsの一意数とする。radius、unit、Target違いで水増ししない。hub bias確認用の`disjoint_pair_count`はcompound-pair graphの最大cardinality matchingで算出して示すが、合否には使用しない。

## 7. Virtual Candidate

TargetがA側へ一意に対応するTransferred transformationだけを候補化し、RDKitでsanitize、valence、attachment順、stereochemistry、重複を検証する。

- Run内既存化合物と一致した場合はVirtualのまま残さずObserved compoundへ再分類する。
- 非同値な複数適用siteはsite別に生成し、canonical isomeric SMILESで重複除去する。
- Endpoint確定値、合成可能性、候補自動採用を主張しない。
- 根拠pair、Environment、support／conflict、signed delta分布を追跡可能にする。

## 8. ReportとA009

Target個別ReportはPCワイド画面の一画面内で操作するoffline Interactive HTMLとする。

- 初期Relationship Map: Target中央、1-cut Exact Core／2-cut Retained anchors中間、Neighbor外周。
- 色: Target紺、Core／anchors緑、Neighborオレンジ。
- 初期表示: 最大5 Core。Neighbor 5件以下は全件、6件以上は件数Nodeに集約し、Core detailで全件表示。
- Neighbor click: 全体構造、共通Core、Fragment、両Endpoint、`ΔN2T`、`Align ✓ / ×`を広幅Detail panelへ表示。
- Core click: 最上段に緑枠Coreと紺枠Targetを横並びにし、Direct Neighbor全件とSimilar Core secondary MapをDetail panelへ表示。
- 1-cut／2-cutを別Viewで切り替える。
- 矢印はCore経由の反応を表すのではなく、正負にかかわらずNeighbor → Targetを表す。
- Core → 類似Core → 個別MMPを辿り、戻るbuttonで一段前へ戻れる。
- 外部CDN、Web API、serverは不要。JavaScriptは表示操作だけを担当する。
- 主navigationはRelationship Map／N2T Direction／Core Type／N-Cuts／Data Tableとする。N2T Directionは`ΔN2T >= 0`／`ΔN2T < 0`、Core TypeはExact Core／Similar Core、N-Cutsは1 Cut／2 Cutsのsubtabを持つ。Evidence Guideは右端の補助tabとして維持し、`2C-A／B／X`を説明する。

A009へはInteractive機能を複製しない。

- A009個別analysis unit Report: 当該unit Top 1のstatic Relationship Map。
- A009全体Summary: Global Top 1のstatic Relationship Map。
- On-demand Target: A009へ自動追記しない。
- A009はVersion付き`mmp_report_index.json`からstatic SVGだけを取得する。

Interactive HTMLの監査はVersion固定したPlaywrightでDOM、bounding box、text、attribute、event、link、件数を検証する。LLM VisionとScreenshot意味判定は禁止する。

## 9. 実装中checkpoint

実装を開始できない設計上の未確定事項はない。次だけを実装中benchmarkで比較し、人間が固定する。

1. 2-cutのabsolute safety floorとstandard quality thresholdの数値。
2. 標準cut SMARTS: `default`、`cut_AlkylChains`、`exocyclic`の比較。
3. similar CoreのMorgan Tanimoto pre-filterとAttachment-constrained MCS coverage。
4. HTML 10 MiB以下、初期DOM ready 2秒以内、detail panel更新100 ms以内を守る最大埋め込みEvidence件数。

checkpointでは件数だけでなく、positive／negative代表構造、既知有用変換coverage、noise、誤mapping、容量・速度をSession内で提示する。これらは解析途中の判断材料であり、A008／A009 Reportへ掲載しない。

各checkpointの採用値と理由は仕様概要書と実装計画書へ追記する。Human checkpoint A～DとサンプルReportの人間確認が完了するまでは、実装完了と宣言しない。

## 10. 0.1.11で扱わない項目

- Bounded Runtime Supervisor
- Endpoint選抜安定性
- A005予測安定性
- 共通runner再編
- MMPと無関係なDescription／Clustering変更
- 3-cut、一般的ring-cut scaffold hopping、3D binding-site解析
- Web GUI／API、合成route設計、Endpoint確定予測

これらは0.1.12以降の別議論とする。

## 11. 実装・検証状況（2026-09-06）

- Mode I／II、Target非依存SQLite、1-cut／2-cut分離、fixed signed delta、Direct／Transferred Evidence、Virtual Candidate、A009 static Map接続は実装済み。
- `compound_pair_id`、cut別`pair_id`、Core／Transformation別`pair_transformation_id`を分離した。
- `disjoint_pair_count`はgreedy近似ではなくcompound-pair graphのmaximum-cardinality matchingで算出する。
- Target HTMLは最大500 Evidence埋め込みを暫定標準とし、詳細全件はCSV／SQLiteに保持する。
- ChEMBL JAK2 231化合物のMode II → Mode I Database再利用 → A009接続を実行した。
- contract／regression test 86件、package verification、A008件数・link・Template監査、A009 Template・link・件数監査はPASSした。
- 旧`A008_v10` Interactive HTMLは人間評価で不合格。Similar Core画像、全connector破線、Map配置、階層subtab、2C Guide、attachment dummyを除いた最大Core集約、Transferred外部SVGの正しいXML保存、Transformation横断View、Target Connection分類、全data view共通filterを反映した`A008_v24`とA009接続版`A009_v13`を生成し、人間による再評価待ちである。

確認用Artifactは`results/CONDUCTOR/report_validation/RV_CHEMBLE_JAK2_0111/operators/A008_v24/`と`A009_v13/`に生成した。Canonical Databaseは`A008_database_v7/`である。これらはvalidation outputでありGit管理対象外である。

Human checkpoint A～DとReportの人間確認が未完了なので、Releaseとしての実装完了宣言はまだ行わない。
