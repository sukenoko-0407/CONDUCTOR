# CONDUCTOR v4 Interpretation Policy

Version: 1.1.0

## 1. 目的

Interpretation Agentは、固定された一つの説明へ収束するためではなく、Operator evidence、Group、Description、scopeの組合せを多面的に比較し、人間が注目すべき一致、相違、矛盾、例外、局所化、再現Cliffを発見するために働く。

Interpretationは読み取りと探索要求の生成に専念する終端stageである。Stateの変更、Operatorの直接実行、計算資源の予約、人間承認の代行は行わない。追加解析は探索要求としてOrchestratorへ返し、OrchestratorがCatalog、State、予算、重複署名、承認条件を検証して新しいbranchを作る。そのbranchも新しいInterpretation nodeで終える。

反復InterpretationはCapability `I001`を新しい実行Node `I001`、`I002`、...として行う。前回reportはread-only lineageとして比較し、上書きしない。同じ固定Evidenceを新しい人間の問いや比較観点で再解釈することは、Description・Grouping・Operatorの重複計算とは区別して許可する。

## 2. 探索原則

- Observation、comparison、interpretation、hypothesisを区別する。
- 一貫した単一仮説を作ることを目的にしない。両立しない説明や未解決の矛盾を並列に保持する。
- 発見候補が多いこと自体を失敗としない。人間が処理できない場合はOrchestratorへ追加の識別解析を要求する。
- 多重探索による偶然の発見を理由に探索を抑制しない。ただし、探索的発見であること、試行履歴、依存性、反証結果を隠さない。
- 同じcapability、入力scope、上流artifact、parameterの解析を繰り返さない。Stateのanalysis signatureと探索ledgerを確認する。
- randomまたは確率的選択ではseed、候補集合、選択理由、未選択候補を記録する。
- 高いscoreだけを追わない。弱い結果、negative result、失敗、skip、coverage gapも比較対象にする。

## 3. 二つの探索モード

### 自律探索

人間が設定したwall time、最大iteration、最大追加node数、並列上限、利用可能capabilityの範囲で候補scopeを確率的に選ぶ。全Cartesian productは作らず、未探索の関係タイプと期待情報利得を優先する。

### Orchestrator限定探索

Orchestratorが対象Group、Description family、Cliff近傍、Operator familyなどの境界を指定する。Interpretation Agentは境界外へ拡張せず、その内部で切り出しと比較を反復提案する。

どちらのモードでも高コスト処理と委譲予算外の処理は人間承認対象である。

## 4. 比較軸

少なくとも次を候補として検討する。

- global、within-group、between-groups、group-boundary
- Groupの交差、差分、包含、重複
- 同一Operator × 異なるDescription family
- 同一Description × 異なるOperator
- 同一Group × 異なる評価表現
- 同一または類似Cliff pairの表現間再現
- 全体傾向と局所例外
- 構造的に近いがpropertyが割れる領域
- 構造的に多様だがpropertyが揃うGroup
- assay条件、欠損、測定誤差で説明できる見かけの差
- 成功、失敗、skip、未実行軸

## 5. evidenceの依存性

異なるOperator名だけを根拠に独立と判断しない。共通するDescription、Metric、Group、compound集合、pair、endpoint、assay、前処理、上流nodeを記録する。

- 同一Descriptionのparameter variantは強く依存する。
- 同じfingerprint familyまたは同じ近傍edgeを使う結果は依存性が高い。
- 同じGroupを評価するprofileとenrichmentは補完的だが完全には独立でない。
- 2D物性、graph fingerprint、substructure、pharmacophore、3D shapeなど異原理の一致は相対的に注目度が高い。
- Group membershipが大きく重なる場合、別Grouping名でも独立支持として数えない。

関係は`corroborates`、`duplicates`、`refines`、`localizes`、`conditionalizes`、`contradicts`、`apparent_contradiction`、`exception`、`incomparable`のいずれか、または未確定として記録する。

## 6. Groupの優先順位

Group sizeは固定閾値だけで選別せず、全体に対する割合、構造凝集性、property range、pair数、他Groupとの重複を併記する。

- 原則としてsample数が多く、安定した比較が可能なGroupを優先する。
- 全体の30%以上を占めるGroupは局所性が弱まり始めるため注意を付ける。
- 全体の50%を超えるGroupはglobal解析に近い可能性を明示し、より局所的な分割または差分scopeも検討する。
- 小Groupでも構造類似性が高い、明確なMCSを持つ、同一変換seriesを構成する、または反復Cliffを含む場合は優先候補になり得る。
- 小Groupの非検出を「現象がない」と解釈しない。sample数、pair数、effective k、一化合物感度を確認する。

Group IDはrun共通`group_registry.csv`を正本とし、必要な候補だけ横持ち`Cpd_Group_matrix_*.csv`からmembershipを読む。`discarded` Groupは新しい自動探索候補から外すが、過去evidenceの説明と人間監査には残す。Interpretationが新しいrandom、intersection、difference、boundary scopeを提案した場合、そのGroup IDとmembershipの登録はOrchestratorへ委ねる。

## 7. 反証探索

注目ポイントを発見した場合は、必ず少なくとも一つの反証探索を探索要求へ含める。反証候補がまだ実行できない場合は、その理由を未解決事項として残す。

反証には次を利用する。

- 異なるDescription familyでの再評価
- Group外またはmatched random subsetでの比較
- Groupの交差ではなく差分部分での比較
- assay条件別解析
- bootstrap、leave-one-out、sample-size matched control
- 別Operatorで同じ現象が再現するか
- 逆方向の例外、Cliff、境界edgeの探索

反証された仮説とnegative resultを削除しない。探索履歴と最終reportに残す。

## 8. SALIとCliff

SALIは同じendpoint scale、Description、Metric、前処理基準の範囲で比較する。連続Descriptionのscope比較ではglobal referenceでfitした前処理を既定とし、local再fitは別の問いとして明示する。

globalとlocalの差を評価するときは、raw SALIだけでなく次を比較する。

- median、upper tail、近傍property整合性
- within-group、between-groups、group-boundary edge
- property range、sample数、pair数、effective k
- 同じCliff pairまたは構造変換の再現性
- A007、Grouping、別Description familyとの対応

全体でroughだが各Group内でsmoothな場合、Group間境界へのroughness局在、複数local landscapeの混合、property range縮小、近傍構成変化を代替説明として並列に保持する。

## 9. 探索要求とOrchestrator

探索要求には次を含める。

- request IDとiteration
- discoveryまたは未解決事項との対応
- `characterize`、`falsify`、`control`、`replicate`の目的
- capability ID、既存上流nodeまたはplan内で先に定義したrequest ID、scope、parameter
- 期待する情報と識別したい代替説明
- seedとanalysis signature
- 予想costと承認要否は未確定としてよい

既存Grouping artifactにないrandom、matched random、交差、差分、boundary scopeを要求するときは、`scope_id`、選択法、target/comparisonのcompound ID集合、元Group、選択理由をPlanへ明記する。OrchestratorはIDをrun inputと照合し、content-addressed membership CSVへ固定してからOperator nodeへ渡す。同じcompound集合、capability、上流node、科学的parameterの組合せは、request IDを変えても再登録しない。

Interpretation Agentはapprovalを決定しない。OrchestratorがCatalogとdataset規模から決定する。

## 10. 停止と出力

探索は次を考慮して停止する。

- 委譲予算への到達
- 新しい関係タイプまたは識別可能な問いが増えない
- 注目候補が独立解析で再現または反証された
- 残る候補が高コストで人間判断を必要とする

### 人間向けInterpretation report

`interpretation.md`と`interpretation.html`は作業記録ではなく、本stageの主成果物である。人間が元artifactを開かなくても、少なくとも「何を解析したか」「何を観察したか」「それをどう解釈するか」「なぜ注目するか」「何が制約か」を理解できる記述にする。

- 本文は解析の目的、解釈サマリー、重要な解釈、矛盾・反証・negative result、仮説候補、次解析の順とし、Evidence index、関係候補、探索ledgerは付録へ置く。
- `F`はFinding、`H`はHypothesis、`R`はEvidence Relationの追跡IDとする。IDより人間が理解できる主張を見出しの中心に置く。
- ObservationとInterpretationを別フィールドに記録する。`analyzed N rows`やartifact pathだけをInterpretationとして掲載しない。
- 仮説は検証可能な主張が形成できる場合だけ作る。Evidence一件につき機械的にHを一件作らない。意味のある仮説がなければ空配列を許容する。
- 解析条件としてOperator、Description、Grouping、scope、Metric、sample数を明示し、主要数値は人間が比較できる桁数へ丸める。
- 矛盾は`not_assessed`、`none_found`、`found`を区別する。未評価を「矛盾なし」と表現しない。
- confidenceはsample数だけで決めず、effect size、uncertainty、Evidence依存性、例外、反証、再現性を根拠として説明する。
- HTMLは外部assetへ依存せず、低彩度の配色とテキストlabelを併用して、支持、探索的仮説、反証、制約、negative resultを視覚的に区別する。

runnerが最初に作るJSON、Markdown、HTMLは`report_status=draft`の機械下書きである。専用Interpretation AgentはartifactとEvidenceを比較して本文を編集し、`agent_review.completed=true`、`report_status=agent_interpreted`へ更新する。final rendererの品質gateを通過したものだけを正式な人間向け成果物とする。

正本JSONには、report summary、evidence index、関係graph、注目結果、矛盾評価、反証状態、探索履歴、未実行候補、次の探索要求を含める。具体的な新規SMILESは生成しない。
