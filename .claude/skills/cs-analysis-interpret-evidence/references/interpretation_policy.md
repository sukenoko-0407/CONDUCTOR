# CONDUCTOR 4.3.1 Interpretation Policy

## 1. 目的

Interpretationは作業記録ではなく、Operator Evidenceを全体／局所、Description、Grouping、Operator、Roundの違いから比較し、人間が検討すべき観察、矛盾、例外、仮説候補、未解決Questionを提示する科学的レポートである。

一つの整った物語を強制しない。局所化による変化と、説明できない差異を価値ある結果として保持する。

## 2. 役割境界

Interpreterは計算Nodeを実行せず、State、artifact、salienceを直接変更しない。Finding、Hypothesis、Question、Relation、salience update、追加解析要求を提案する。OrchestratorとState ManagerがID予約、検証、State登録、Node作成を行う。

Interpretation NodeはRun内の一時点におけるread-only reviewであり、過去reportを上書きしない。Interpreter停止時は同じNI Nodeを再試行し、復旧のために別NIを発行しない。Orchestratorだけが完成eventをStateへ登録する。

## 3. 入力の段階読込

1. `orchestrator_brief.json` のInterpretation要求と、予約済みNIのfocusを確認する。
2. 全Evidenceのcompact digestとcoverageを確認する。
3. 新規、untriaged、priority、human-pinned、active Question関連Evidenceを詳細確認する。
4. indexed joinで成立したglobal/local、cross-Description、sibling Group、cross-Operator、counterexample候補を確認する。
5. 必要な数値CSV、supporting compound／pair、Operator HTMLへdrill-downする。

過去Interpretation全文を無条件に連結せず、最新ledger、Round summary、`next_round_brief`を入口にする。routine Evidenceもdigest検索対象に残す。

## 4. 必須比較軸

- 同一Operator・同一評価Descriptionのglobal対local
- 同一Group・同一Operatorの異Description family
- 同一Group・異Operator
- sibling Groupとglobal comparator
- Group内、Group外、between、boundary、overlap／difference scope
- Grouping生成表現と評価表現の依存性
- 同じ傾向を支持する独立Evidenceと、当然似る従属Evidence
- positive result、negative result、矛盾、例外、反証

異metric、異endpoint scale、異なる統計量のraw値を直接統合しない。比較不能は`incomparable`として記録する。

## 5. Entity

### Finding

Evidenceから読み取れる具体的観察である。Operatorを実行した事実や解析件数だけをFindingにしない。Observation、Interpretation、notable reason、limitationsを分離する。

### Hypothesis

検証可能な説明候補である。Findingごとに生成せず、十分な観察と反証可能性がある場合だけ作る。支持Evidence、反対Evidence、代替説明、適用scope、例外を明記する。

### Relation

EvidenceやFinding間の`corroborates`、`localizes`、`conditionalizes`、`contradicts`、`refines`、`exception`、`incomparable`などの関係である。全ペアへ機械生成せず、比較keyまたはQuestionにより意味のある組だけを作る。

### Question

追加解析で識別したい問いである。すべてを深掘りしない。Agentの`deep_dive_potential`、priority、人間の`human_decision`、statusを持つ。人間の`skip`はhard gateとする。

## 6. Run-global IDとrevision

Finding、Hypothesis、Question、RelationのIDはRun内通番であり、Roundごとにリセットしない。同じentityの評価変更は同じIDのrevisionとして扱い、主張や対象が別物なら新IDを作る。詳細は[識別子リファレンス](CONDUCTOR_identifier_reference.md)に従う。

## 7. Groupの扱い

sample数だけで順位を決めない。全体の30～50%を超えるGroupは局所性低下を注意し、小Groupでも構造凝集性、明確なMCS、反復Cliff、人間解釈への接続性が高ければ候補にできる。

排他的partitionと重複Groupを区別する。重複GroupのGroup間分散を母集団分割として解釈しない。Endpointを使った代表Group選択は探索的選択であり、独立検証ではないことを記載する。

## 8. SALIとLandscape

SALIは空間の平滑性・起伏を評価する。median、upper tail、有効pair数、top pairを併記する。globalで高くlocalで低い場合は、Groupingにより滑らかな局所Landscapeへ分解された可能性を検討する。異metricのraw SALI値は直接比較しない。

Cliffには構造差、pharmacophore差、assay条件、別Description、sibling Group、反証例を照合する。高SALIだけで機序を断定しない。

## 9. Salience update

`attention_class`は`untriaged/routine/candidate/priority`、科学的roleは`signal/no_signal/support/contradiction/falsification/control/exception/inconclusive`を使用する。分類は可変であり、変更理由、Round、Interpretation、Questionをeventへ記録する。

明確なsignalがなくてもglobal comparator、反証、controlなら高い価値を持ち得る。新しいEvidenceとの関係からroutine Evidenceを再昇格できる。

## 10. 追加解析要求

深掘り要求には、Question、目的、対象scope、Capability、依存Node、比較bundle内のrole、期待する識別情報、代替説明、cost classを含める。孤立Nodeではなく、何と何を比較するかを明示する。

追加探索のbalanced random NodeはInterpreterが科学的に選ばず、Orchestratorのcoverage plannerへ委ねる。

## 11. Human report

`interpretation.md`と`interpretation.html`は少なくとも次を含む。

- 対象RunとRound、解析目的、coverage
- 新規または更新されたFinding
- Hypothesisと支持／反対Evidence
- global/local、cross-Description、Group間の主要contrast
- 矛盾、例外、negative result
- Question一覧、deep-dive potential、人間decision
- 重要度変更
- 不足している比較と次Round候補
- Operator HTMLへの導線

各entityにID、初出Round、最終更新Round、revision、statusを表示する。IDだけを並べず、人間が解析内容と意味を理解できる文章を記載する。

成功Operator EvidenceがあるRoundのcheckpoint／completedには、`agent_interpreted` のJSON、Markdown、HTMLがすべて必要である。resource上限に近づいた場合も、科学Node追加よりこのreport完成を優先する。
