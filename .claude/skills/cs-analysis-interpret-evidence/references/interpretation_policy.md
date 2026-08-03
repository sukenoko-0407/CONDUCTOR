# CONDUCTOR v4 Interpretation Policy

Version: 1.0.0

## 1. 目的

Interpretation Agentは、固定された一つの説明へ収束するためではなく、Operator evidence、Group、Description、scopeの組合せを多面的に比較し、人間が注目すべき一致、相違、矛盾、例外、局所化、再現Cliffを発見するために働く。

Interpretationは読み取りと探索要求の生成に専念する終端stageである。Stateの変更、Operatorの直接実行、計算資源の予約、人間承認の代行は行わない。追加解析は探索要求としてOrchestratorへ返し、OrchestratorがCatalog、State、予算、重複署名、承認条件を検証して新しいbranchを作る。そのbranchも新しいInterpretation nodeで終える。

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

正本JSONには、evidence index、関係graph、注目結果、未解決矛盾、反証状態、探索履歴、未実行候補、次の探索要求を含める。MarkdownとHTMLは情報を削除せず、注目理由別に人間が走査できる形へ整理する。具体的な新規SMILESは生成しない。
