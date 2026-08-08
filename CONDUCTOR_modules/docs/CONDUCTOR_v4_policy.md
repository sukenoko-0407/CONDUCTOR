# CONDUCTOR 4.3.1 Orchestration Policy

## 1. 役割

Orchestratorは、Catalogで人間が許可したSkillだけを使い、Run内のRound、coverage、DAG、Question、salienceを管理する。科学計算をSkill外へ複製せず、機械的coverageと探索的判断を分離する。

## 2. 絶対条件

- 1 Runは一つのendpointと`higher_is_better`を扱う。
- input、endpoint、方向を黙示的に変更しない。
- 分子標準化、単位変換、pActivity化を暗黙に行わない。
- 重複compound IDでは停止する。invalid SMILESは保持して警告する。
- Catalog外Capabilityを使わない。
- CONDUCTOR Nodeは必ず予約後に`--conductor`、project、run ID、Node ID、設定、output directoryを渡して実行する。
- 同じanalysis signatureを理由なく再実行しない。
- 高コスト基本計算はRunごとに一括承認し、承認scopeを記録する。
- 新しい高コスト深掘りは目的、対象、資源、期待情報を示して別途確認する。
- 人間指定parallel limitを超えない。
- 同じStateを複数Orchestratorが同時に更新しない。
- bootstrapで単一Writer leaseを取得し、すべてのState変更にsession tokenを用いる。別Writerがleaseを保持する場合はread-onlyで終了する。
- Node失敗の再試行は同じNode IDの新execution attemptとし、復旧目的の代替Nodeを作らない。
- 成功Operator EvidenceがあるRoundは、同Roundの成功InterpretationとJSON／Markdown／HTMLなしにcheckpoint／completedへしない。
- 相関、局所傾向、SALIを因果や機序として断定しない。

## 3. Round lifecycle

人間が新規または継続Round番号とState pathを指定する。番号がStateの`next_round`と一致すれば開始し、同番号がactiveなら再開する。完了済み番号、欠番、別active Roundがある場合は書き込まず報告する。

Roundは既定resource envelopeをsnapshotする。人間の追加指示がなければ、未完了mandatory coverage、前Roundの`next_round_brief`、active Question、coverage gapに基づいて進める。承認応答は新Roundに数えない。

Wall Timeは最大予算としてdeadlineを持つ。使い切り自体を目的にしないが、eligible workが残る間の説明不能な早期終了は許容しない。終盤はInterpretationとFull Auditのためのreserveへ切り替え、停止理由を定義済みcodeで記録する。

## 4. Phase gate

1. `basic_compute`を初期探索より優先する。
2. 基本計算の失敗は再試行・代替を確認し、解決不能なら人間の`waived`なしに黙って探索へ進まない。
3. `initial_global`と`initial_local`がterminalになるまで、自動`additional_exploration`と`deep_dive`を開始しない。人間の明示的overrideは理由付きで許容する。
4. `not_applicable`は成功の代用ではなく、科学的・技術的理由を持つcoverage状態とする。

## 5. 基本計算

Catalog profileに含まれる全Descriptionを計画する。高コストを無言で除外しない。runtime preflightでbinary、model weight、GPU、3D／quantum依存を確認し、`succeeded/failed/unavailable/waived`を区別する。

Groupingはdirect structureとDescription-vectorを混同しない。vector metricは入力表現から決定し、binary fingerprintはTanimotoを必須とする。MCSの制限pairはseed付き一様ランダム非復元抽出とする。

## 6. 初期探索

### 6.1 Global wave

全体scopeで全applicable Operator roleを実行する。Description依存Operatorは共通master panelを互換性でfilterする。Grouping-wide Operatorは全Grouping artifactをscreenし、Group size、Endpoint分散、enrichment、構造凝集性、overlap semanticsをcompact summaryへ出す。

### 6.2 Local wave

各Grouping Nodeから、十分なNで局所性を保つGroup、中程度Group、構造凝集性の高いGroup、Endpoint dispersion極値、既選択と低重複のGroupを選ぶ。Endpoint依存選択はdiscovery biasとして記録する。

代表Groupには全applicable local Operator roleを計画する。A009のような単一Group非対応Operatorを無理に実行しない。Grouping-wide出力の既存行で同じcoverageを満たせる場合は重複Nodeを作らない。

排他的partitionのGroup間比較は、同じendpoint、同じDescription、同じmetricで行う。重複Groupを母集団partitionとして扱わない。

## 7. 追加探索

未実行かつ有効なanalysis cellをfamily、Operator、scopeで層化し、実施数の少ない層を優先してseed付きランダム非復元抽出する。candidate pool hash、seed、採択順、除外理由を記録する。Agentの仮説でrandom探索を歪めない。

## 8. 深掘り

深掘りNodeは原則Questionへ所属し、単独Nodeではなく比較bundleとして計画する。Questionの人間decisionが`skip`なら自動実行しない。`defer`は保留し、`allow`または未reviewでresource envelope内なら候補にできる。

注目結果には反証、control、異Description、global／local、sibling Groupの少なくとも一つを検討する。すべてを無理に実行するのではなく、代替説明を識別できる比較を優先する。

## 9. Evidenceの読込

全Evidenceの存在、digest、provenance、coverageは保持する。毎Round全文を再読込しない。標準読込順は次とする。

1. `orchestrator_brief.json`
2. 必要な場合だけboundedな`state_summary.json`
3. focused queryで対象Node、Evidence、Question、batch
4. untriaged、priority、human-pinned、active Question関連digest
5. 必要な完全Evidence、CSV、Operator HTML

全EvidenceペアのCartesian comparisonは禁止する。

## 10. Salience

Operator artifactはimmutableとし、importanceは可変indexで管理する。`routine`は削除、忘却、coverage除外を意味しない。新しいRelation、Question、人間指示、反証候補により再昇格できる。human pinは人間が解除するまで自動降格しない。

## 11. 失敗・再開・変更検出

- 上流artifactが変われば下流を`stale`にする。
- 同じ失敗を無制限に再試行しない。
- active Round、running attempt、lease、pending approvalをbootstrap Quick Auditで検査する。
- package、Catalog、profile、Policy hashが変わった場合は差分を提示し、承認なく混在させない。
- Derived index不整合時はimmutable artifactとStateから再構築する。
- 4.3.0 Stateは通常Runtimeで更新しない。一回限りのMigration Skillだけが、source非変更、別target、dry-run、人間承認、検証を条件に科学artifactをimportできる。

## 12. Round終了

Round終了時に、Node差分、coverage差分、新規・更新Finding／Hypothesis／Question、salience変更、矛盾、pending approval、次Round候補を保存する。成功Operator Evidenceがある場合は新しいInterpretation Nodeで必ず閉じ、Full Auditを通す。単なる計算checkpointでこのgateを回避しない。
