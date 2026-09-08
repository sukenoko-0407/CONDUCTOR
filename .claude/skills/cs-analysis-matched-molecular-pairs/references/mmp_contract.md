# A008 MMP contract — 0.1.11

## Request

`parameters.mode` is `target` or `database`. `target` requires `parameters.targets[]`; each Target contains a Run `compound_id` and one or more `selection_sources` (`analysis_unit_top1`, `global_top1`, or `human_explicit`). `database` has no Target fields.

The formal input limit is 5,000 compounds. Maximum cuts is fixed to two; mmpdb also emits 1-cut rows and CONDUCTOR separates them by `cut_count`. Environment radius is 0–2.

## Canonical database direction

Database direction is fixed by canonical variable-fragment/compound ordering. `endpoint_delta = endpoint_to - endpoint_from` retains the raw numerical difference. `normalized_signed_delta` and its compatibility alias `fixed_direction_effect` apply the Run's higher/lower-is-better sign but are not made positive per pair.

`|fixed_direction_effect| < 0.10` is neutral. Equality at 0.10 is non-neutral. Missing and neutral rows remain stored but are excluded from `supporting / (supporting + conflicting)`.

Target reports derive signed `target_oriented_delta` with Target or the Target-matched side as the displayed product. It is never forced positive. `pair_favorable_gain` remains a compatibility/aggregate absolute value and must not drive report arrows. Aggregate consistency uses `consensus_aligned_delta`, not independently flipped pair gains. If an Exact Target Core group exists, its direction count anchors consensus. Otherwise, Count descending and canonical fixed-direction key ascending choose the first direction inside each compatible Environment group. Radius-2, Radius-1, and mismatch groups never vote together.

## Identity and counting

- `pair_id`: cut-scoped canonical compound pair, independent of Target, unit, and radius.
- `compound_pair_id`: cut-neutral compound pair identity used to prevent 1/2-cut double counting.
- `transformation_family_id`: direction-neutral variable-fragment pair plus cut count and ordered attachment topology.
- `transformation_id`: fixed directed transformation.
- `core_id`: attachment-labelled Exact Core for 1-cut or Retained anchors for 2-cut.
- `unique_context`: Exact Core for 1-cut; ordered Retained anchors for 2-cut. Radius, unit, and Target do not increase it.
- `disjoint_pair_count`: compound-pair graphのmaximum-cardinality matchingで求める、化合物を共有しないpair support診断値。合否には使用しない。

Canonical CSV／SQLiteは同一compound pairに対する全Coreを保持する。Target ReportだけはTarget–Neighborと`cut_count`ごとに最大Coreへ集約する。1-cutはattachment dummyを除いたCore本体の部分構造包含、2-cutはdummyを除いた二つのRetained anchor component間の一対一対応で包含を判定する。厳密に包含される小Coreは除き、相互に包含されないCoreは両方残す。同一Coreの重複行は`evidence_id`順の1件へ決定論的に集約する。

## 2-cut

`2C-A/B/X` measures structure quality only. Both retained anchors must independently contain at least 4 heavy atoms; a row below this absolute minimum is `2C-X`, remains auditable in the canonical Database, and is excluded from the main Evidence report. A passes the remaining safety and standard size checks; B passes safety but misses retained-fraction or variable-size checks; X is invalid, unsafe, ambiguous, below the anchor minimum, or reducible to 1-cut. Target-specific quality is separately `high`, `limited`, `not_applicable`, or `ambiguous`. The report calls the fixed portion `Retained anchors`, not Exact Core.

The numeric A/B boundary and standard cut SMARTS are provisional until Human checkpoint A.

## Target evidence

`connection_scope` is `direct` or `transferred`. `interpretation_role` is one of Target explanation, Observed improvement, Transferred explanation, Proposed improvement, neutral, not applicable, or ambiguous.

For Direct evidence, the report direction is always Neighbor → Target. Positive Target-oriented delta supports the Target Endpoint; negative delta is an observed improvement clue. For Transferred evidence, Target's current variable fragment must map to fixed A/B; orient the observed effect toward that Target-matched side without changing the canonical row. Positive and negative values change the interpretation only. Neither is not applicable, and both/non-equivalent multiple mappings are ambiguous.

Evidence classes are Exact Core, Radius-2 similar Core, Radius-1 related Core, Environment-mismatched mapped reference, and ambiguous/excluded. Mismatch rows are reference-only.

## Artifacts

Mode `database` emits SQLite, manifest, pair/fragmentation CSVs, Transformation/Context/2-cut-quality/Environment summary CSVs, and database HTML. Mode `target` additionally emits registry/source tables, one evidence/virtual-candidate CSV per Target, one Interactive HTML and one static SVG map per Target, an overview, and `mmp_report_index.json`.

Interactive HTMLへ埋め込むEvidenceは暫定最大500件とし、全件はTarget Evidence CSV／canonical SQLiteに保持する。Target reportの主navigationはRelationship Map／Transformation／N2T Direction／Target Connection／N-Cuts／Data Tableとする。Transformationは同じ`transformation_family_id`をTarget-side Core横断で集約し、All／Direct／Transferredを切り替え、詳細panelから全観測へ到達可能にする。N2T Directionは`ΔN2T >= 0`／`ΔN2T < 0`、Target ConnectionはDirect MMPあり／Transferredのみ、N-Cutsは1 Cut／2 Cutsのsubtabを持つ。Target ConnectionのcardはExact Coreと総称せず、cut数とTargetを含むDirect MMPの有無を明示する。上部のcut、Evidence品質、text filterはRelationship Map以外の全data viewにも共通適用する。右端にEvidence Guideを補助tabとして置き、`2C-A／B／X`を含む固定仕様を説明する。表示deltaは`ΔN2T`へ統一する。Mapの全connectorは破線とし、Similar Core detailではTarget-side CoreとEvidence Coreの両構造を必ず表示する。2D Align失敗時も化合物全体を表示し、`Align ×`を明示する。Transferred全体構造はHTMLからの相対pathで`targets/assets/*.svg`へ外部化し、Data URI文字列ではなく復号済みSVG XMLを保存する。監査は全外部SVGのXML parseと、directional／non-directional Transferred detailの各画像ごとのbrowser decodeを要求する。正式埋め込み件数はHuman checkpoint Dで承認する。

A009 uses only the index's static SVG path. On-demand Targets are not automatically appended to A009. Report validation uses template hashes, DOM/link/count tests, and a fixed browser environment. LLM Vision is prohibited.
