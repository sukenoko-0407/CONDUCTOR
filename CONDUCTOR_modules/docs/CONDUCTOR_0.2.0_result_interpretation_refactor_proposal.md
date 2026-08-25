# CONDUCTOR Result Card・比較・Interpretation再設計提案

## 1. 文書の位置づけ

本文書は、CONDUCTOR 0.1.7の逐次Result Screeningを基礎としつつ、次の目的へより直接的に最適化するための破壊的変更案である。

> Endpointをfavorableな方向へ改善するための知見、またはその候補となるGlobal–Local・Cluster間の「違和感」を見つける。

提案Versionは`0.2.0`とする。0.1.6成果物・Run・Result Cardの後方互換性は保証しない。Description、Clustering、Operatorの科学計算kernelは原則維持し、出力契約、比較単位、一次評価、Interpretation選択を作り直す。

本文書は0.2.0実装の設計基準である。

実装状態：0.2.0として実装済み。Runtimeが自動生成するBundleはGlobal、Global–Local、Sibling Clusterの3種類とする。`cross_evidence`はschema上の予約型として保持するが、候補評価を入力にして再び一次評価を作る循環を避けるため自動生成しない。異種Description・Operator間の支持／反証は、正式Synthesisまたは人間指定のread-only深掘りで扱う。

## 2. 現状の問題

### 2.1 Result Cardの意味的不均一

現行Result Cardはscope、Cluster、Description、sample count、metric、artifact linkなどのprovenanceを共通形式で持つ。一方、`key_metrics`は自由度の高いobjectであり、Operatorによって情報量、方向性、不確実性、Global比較の有無が異なる。

このため、形式的には同じCardであっても、同じ品質で一次評価できるとは限らない。

### 2.2 Local結果を単独評価できる

現行RuntimeはLocal Resultに対応するGlobal Resultを比較候補として探索するが、次は保証されない。

- metric・Operator parameterを含む完全な比較可能性
- LocalごとのGlobal comparatorの存在
- sibling Clusterの系統的な比較
- 重複Clusterと独立Clusterの区別

Global comparatorがなくてもLocal Resultの採点は可能であり、Global–Local比較が必須という科学的前提がRuntime契約になっていない。

### 2.3 一次評価の合計点が意味を混ぜる

現行は`signal`、`contrast`、`independence`、`interpretability`、`follow_up_value`を0～2点で評価し、合計0～10点を`interest_score`とする。複数項目は保存されるが、主要な選択順は合計点に依存する。

その結果、次のように性質の異なる候補が同じ点数になり得る。

- favorableな方向を直接示す設計候補
- 活性方向は不明だがGlobal–Localで反転した違和感
- 解釈しやすいが活性とは関係のない解析
- 機能しないDescriptionやClusteringの記述

### 2.4 人間向けReportが失敗解析へ視線を誘導する

機能しないDescription、Clustering、Operatorは実行履歴としては必要だが、それ自体をInsightとして人間に提示する価値は低い。現行はこれを排除する強い掲載ゲートがない。

## 3. 再設計の原則

1. Result Cardは解釈文ではなく、比較可能な標準要約とする。
2. Cluster-localの活性関連Resultは単独評価しない。
3. 一次評価の単位をResult CardからReview Bundleへ変更する。
4. 一次評価は絶対基準による複数軸とし、単純合計点を用いない。
5. 「活性改善候補」と「違和感」を別経路で拾い上げる。
6. 機能しない解析は保存するが、単独Insightとして掲載しない。
7. `higher_is_better`の解釈はRuntimeで`favorable`方向へ正規化し、LLMにhigh／lowの翻訳を委ねない。
8. 科学計算kernelは不要に作り直さない。
9. Runtimeは比較成立性と状態を決定論的に管理し、LLMは科学的価値判断に限定する。

## 4. Result Card v2

### 4.1 役割

Result Card v2はOperatorの完全結果ではない。一次評価、比較Bundle生成、正式Interpretation選択に必要な最小情報と、詳細成果へのpointerを持つ。

### 4.2 必須要素

| 要素 | 内容 |
|---|---|
| identity | Result、Node、Operator、Round |
| analysis subject | scope、Cluster、Description、Clustering、sample count |
| result role | `activity_signal`、`landscape`、`model`、`context`、`quality`、`specialized` |
| interpretation profile | Operatorごとの評価契約ID |
| comparison family | 同一条件でGlobal・Local・siblingを結ぶID |
| favorable payload | favorable方向、effectの有無、方向の信頼性 |
| comparison metrics | 比較可能な名付き指標と単位・方向・適用範囲 |
| quality | sample、欠損、不確実性、重複、警告 |
| artifact links | JSON、CSV、HTML、detail |

`key_metrics`の無制限利用は廃止し、人間向けの自由な追加情報は`operator_details`へ分離する。一次評価はtypedな`comparison_metrics`だけを比較に使用する。

### 4.3 favorable正規化

Operatorが活性方向を扱う場合、Runtimeは次の統一表現を生成する。

- 正の`favorable_effect`：Endpointを望ましい方向へ動かす。
- 負の`favorable_effect`：Endpointを望ましくない方向へ動かす。
- null：活性方向を表さないOperator、または方向を決められない。

`higher_is_better=false`の場合も、科学Skillの生値は保持したまま、解釈用effectだけをRuntimeが反転する。

### 4.4 Operator Interpretation Profile

各Operatorの`capability.json`に、次を宣言する。Catalogはこれを集約する。

- Result role
- 一次評価で使える軸
- typed comparison metric
- metricの大小の意味
- 比較可能な条件
- Global comparatorの必要性
- sibling Cluster比較の必要性
- null resultの扱い
- 最低支持条件
- Insightを単独生成できるか、他Resultの補助に限定するか

このprofileはSkill自身が科学的な指標の意味を所有し、RuntimeがOperatorごとの長い分岐を抱えないための契約である。

## 5. Review Bundle

### 5.1 一次評価の新しい単位

InterpreterはResult Cardを無関係に並べたbatchではなく、Runtimeが決定論的に生成したReview Bundleを評価する。

| Bundle | 内容 |
|---|---|
| Global | Global Result単独。Globalで成立する設計候補の評価 |
| Global–Local | Local targetと完全一致するGlobal comparator |
| Sibling Cluster | 同一Clustering、Operator、Description、parameterのCluster間比較 |
| Cross-evidence | schema上の予約型。既存候補を異なるDescription・Operator・構造contextで支持または反証する明示的な深掘り用。通常Roundでは自動生成しない |

### 5.2 comparison family

`comparison_family_id`は少なくとも次から決定論的に生成する。

- Operator capability
- Endpoint column、unit、transform、`higher_is_better`
- analysis Description signature
- metric
- 比較結果に影響するOperator parameter
- reference populationの定義

Clustering NodeはGlobal–Local familyの一致条件に入れないが、sibling familyの一致条件に入れる。

### 5.3 Localの必須ゲート

活性関連のLocal Resultは、対応Globalが存在する場合だけ一次評価する。存在しない場合は`awaiting_comparator`とし、次のいずれかとする。

1. 現在の人間承認予算内でGlobal Nodeを優先計画する。
2. 予算がなければ未評価のまま次Roundへ候補を引き継ぐ。

Globalとの比較が科学的に成立しないOperatorは、Interpretation Profileで`global_comparator=not_applicable`と宣言する。その場合でも、Cluster単独から活性改善Insightを作らない。

### 5.4 sibling Cluster比較

同一familyに多数のClusterがある場合、各CardをすべてLLM contextへ入れない。Runtimeが比較可能metricだけのcompact tableを作り、次を添付する。

- Cluster size
- Global value
- Local value
- favorable方向への差
- Globalからの偏差または反転
- sibling内順位
- Cluster間分散
- Cluster overlap
- 最低支持条件の充足

Cluster間重複がある場合は独立再現として扱わず、Bundleに明示する。

## 6. 一次絶対評価

### 6.1 評価軸

各軸は`0`～`3`または`not_applicable`とする。他Bundleの点数分布は採点基準に使用しない。

| 軸 | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| favorable signal | favorable方向の情報なし | 間接的・弱い示唆 | 限定scopeで明確 | 方向・大きさ・一貫性が明確 |
| context deviation | 情報のある差なし | 軽度の差 | Global–Localまたはsiblingで明確な変化 | 反転・局所化・平滑化など解釈を変える差 |
| chemical actionability | 操作可能な要素なし | 広い物性・カテゴリ | 特定feature・core・regionに接続 | 方向の定まった構造変換・設計操作に接続 |
| independent support | 支持なしまたは矛盾のみ | 単一evidence | 異なる表現またはOperatorから支持 | 複数の独立evidenceが同じ候補を支持 |
| follow-up leverage | 有用な追加検証なし | 追加確認は可能 | 明確な反証・深掘り手順あり | 少数の追加解析・化合物で意思決定を大きく改善 |

汎用文言だけでは絶対評価は安定しない。各Operator Interpretation Profileは、そのOperatorが利用する軸に対し、指標固有のanchorと判定例を定義する。

### 6.2 信頼性の分離

注目度と信頼性は合算しない。次を別objectで保持する。

- `sample_support`: `insufficient | limited | moderate | strong`
- `comparator_validity`: `none | partial | matched`
- `effect_stability`: `unknown | unstable | mixed | stable`
- `independence`: `unknown | overlapping | partially_independent | independent`
- `quality_flags`
- 判定に使ったResult reference

数値的に決められる部分はRuntimeが設定し、LLMは未定義の統計閾値を作らない。

### 6.3 Candidate class

合計点の代わりに、次のclassを付与する。

| class | 意味 | 人間向けReport |
|---|---|---|
| `design_lead` | favorable方向と操作可能な化学要素が接続 | 原則掲載 |
| `contextual_anomaly` | 活性改善につながる可能性のあるGlobal–Local・Cluster間の違和感 | 原則掲載 |
| `supporting_evidence` | 他の候補を支持または反証 | 親候補の下でのみ掲載 |
| `background` | 実行済みだが現時点で人間へ提示する価値が低い | 掲載しない |
| `not_scorable` | Bundleまたは成果物が評価に不十分 | 掲載しない |
| `awaiting_comparator` | 必須Globalまたはsiblingが未実施 | 掲載しない。追加計画候補 |

Candidate classは明示的な決定表で付与する。LLMに自由なclass名や総合印象の生成を許可しない。

## 7. Insightと人間向けInterpretation

### 7.1 掲載ゲート

単独Insightの候補は原則として`design_lead`または`contextual_anomaly`に限定する。

次は単独Insightにしない。

- Descriptionに相関がなかった。
- Clusteringで活性差を検出できなかった。
- Projectionが活性を分離しなかった。
- 対象Operatorが不安定であった。
- 単なる作業完了、coverage、失敗数。

これらはRun-wide評価索引に保存し、有望候補の反証やcoverage制約として必要な場合だけ参照する。

### 7.2 Report構成

`interpretation.md`と`interpretation.html`は次の順序とする。

1. 主要なfavorable design lead
2. 活性改善につながる可能性のあるcontextual anomaly
3. 上記を支持・制限・反証するevidence
4. 人間が判断できる追加検証案
5. ごく短いcoverageと未評価範囲

掲載できる候補がない場合は、無用な解析を列挙せず、「今回の範囲では防御可能なdesign leadまたはcontextual anomalyは得られなかった」と簡潔に報告する。

### 7.3 選択上限

正式Interpretationの認知上限は維持する。上限を超える場合は単純合計点で並べず、次の決定論的な優先順を使用する。

1. `design_lead`
2. `contextual_anomaly`
3. 信頼性
4. chemical actionability
5. Operator・Description・Clusteringの多様性
6. 同一候補の重複結果を集約

## 8. Operatorの役割整理

新Operator追加よりも、まず現行OperatorのInterpretation Profileを明確にする。初期の位置づけは次を基準とする。

| Operator | 主な位置づけ | 単独design lead |
|---|---|---|
| A001 Activity distribution | Global・Clusterの活性baseline | 原則不可。他候補の比較根拠 |
| A002 Descriptor-activity correlation | 特徴量と活性の方向候補 | 条件付き可 |
| A003/A004 Projection | 局在、分離、局所的違和感 | 原則不可 |
| A005 Multi-Description model | 複数表現で埋もれた活性signal | 条件付き可 |
| A006 Pairwise similarity | 構造context、比較成立性 | 不可 |
| A007 kNN consistency | 局所活性の整合・違和感 | 条件付き可 |
| A008 SALI | landscapeの平滑性・局所変化 | 単独では限定的 |
| A009 Activity cliff | 活性を大きく変える局所候補 | 条件付き可 |
| A010 Cluster profile | Global–Localの活性分布変化 | 条件付き可 |
| A011 Cluster enrichment | favorable活性のCluster局在 | 条件付き可 |
| A012 Cluster overlap | Cluster比較の独立性 | 不可 |
| A013 Structural diversity | Clusterの化学的解釈性 | 不可 |
| A014 MMP | Transform・Core・Cluster contextの設計候補 | 専用read-only Interpretationで評価 |

A012やA013のようなcontext Operatorは重要だが、単独で活性改善Insightを作らない。他の候補の信頼性・解釈性を高めるために使用する。

## 9. Runtime・Orchestrator・Interpreterの新フロー

```text
Operator artifact
  → typed interpretation payload validation
  → Result Card v2 commit
  → comparison familyへ登録
  → Review Bundle成立判定
      ├─ comparator不足 → awaiting_comparator
      └─ 成立 → bounded primary assessment
  → append-only assessment index
  → design lead / anomaly / supporting / backgroundに分類
  → 選択されたBundleだけで正式Interpretation
```

### Runtime

- Result Card v2とInterpretation Profileをschema validationする。
- comparison familyとBundleを決定論的に生成する。
- comparator不足を明示状態として管理する。
- favorable方向、sample、Cluster overlap、比較成立性を確定する。
- 一次評価の入力と出力を少数・固定schemaにする。
- Candidate classとReport掲載ゲートを確定する。

### Main Orchestrator

- 人間予算内の解析範囲を選ぶ。
- Globalが不足したままLocalへ過度に進まない。
- `awaiting_comparator`の中から価値のあるGlobal補完を選ぶ。
- 一次評価の点数や長文をMain contextへ展開しない。
- 人間の明示指示なしに新Roundを開始しない。

### Interpreter

- 一回に一つのbounded Review Bundleまたは少数Bundleだけを評価する。
- Operator profileの絶対anchorに従う。
- 単純合計点を出さない。
- favorable方向はRuntime値を使い、再解釈しない。
- 機能しない解析を単独Insightにしない。
- `design_lead`と`contextual_anomaly`に集中する。

## 10. LeaseとRuntime Worker

LLM Executor Subagentを通常フローから外しても、Leaseは次のために維持する。

- 複数Claude Code sessionによる同一Runの二重操作防止
- Stateを変更できるMain Orchestrator所有者の一意化
- stale commandの拒否
- PacketをControl revisionとOrchestrator sessionへ結び付ける
- session消失後の安全な引継ぎ

LeaseはCPU並列数や科学process所有権の機構ではない。Packet claim後の科学processは現行同様にRuntime Workerが所有し、Lease期限から独立して完了させる。

0.2.0でLease自体を廃止しない。まず用語を`Orchestration session lease`へ明確化し、通常時はlauncherとRuntimeが管理する。tokenを無理に隠蔽することで所有者識別を弱めない。

## 11. 後方互換性と移行方針

### 11.1 保証しないもの

- 0.1.6／0.1.7 Result Cardの受理
- 進行中の旧Roundの再開
- 旧Assessment Indexの自動変換
- 旧Interpretationの新schemaへの変換
- 旧Run Rootをそのまま0.2.0で継続すること

### 11.2 維持するもの

- Description、Clustering、Operatorの科学計算の基本アルゴリズム
- 一般利用CLIと`--conductor`の基本的役割
- Runtime Workerによるprocess所有権
- Run Root外への書き込み禁止
- DAG、Node ID、Cluster ID、Roundの原則
- MMP Global Databaseとread-only専用Interpretationの分離

### 11.3 推奨

0.2.0は新規Runとして開始する。移行patchは作らず、特に高コストなDescriptionの再利用も自動化しない。中途半端な互換層を避け、新Result Cardと比較契約の完全性を優先する。

## 12. 実装対象

### 12.1 schema

- Result Card v2
- Operator interpretation payload
- Operator Interpretation Profile
- comparison family
- Review Bundle
- primary assessment v2
- assessment index v2
- screening summary v2
- Interpretation context・Insight schema

### 12.2 Runtime

- 0.1.6互換branchの削除
- Result Card v2生成・検証
- favorable正規化
- comparison family管理
- Global–Local・sibling Bundle生成
- comparator不足の管理
- 複数軸Assessment commit
- Candidate classと掲載ゲート
- Auditによる比較完全性検査

### 12.3 Operator Skill

- 科学kernelは原則変更しない。
- 各Skillがtyped interpretation payloadを出力する。
- capability metadataにInterpretation Profileを追加する。
- favorable方向の原始情報、比較指標、不確実性を明示する。
- 一般利用出力は不要に変更しない。

### 12.4 Interpreter・Orchestrator

- InterpreterをResult Card modeからReview Bundle modeへ変更する。
- 絶対anchorとCandidate class契約を短く明記する。
- Orchestratorは欠落comparatorの補完と未評価Bundleの優先度だけを判断する。
- Main contextへ個別採点本文を戻さない。

## 13. 実装順序

1. 0.2.0のschemaとID契約を固定する。
2. Operator Interpretation Profileの共通契約を作る。
3. A001～A014ごとにResult role、comparison metric、comparator要件、絶対anchorを定義する。
4. Operator出力にtyped interpretation payloadを追加する。
5. RuntimeのResult Card v2生成とAuditを実装する。
6. comparison familyとReview Bundleを実装する。
7. 一次評価とAssessment Index v2を実装する。
8. Candidate class・掲載ゲート・正式Interpretationを実装する。
9. OrchestratorのGlobal優先とcomparator補完を簡潔な手順に更新する。
10. 0.1.6互換branchと古いschema受理を削除する。
11. 新規RunでDescription→Clustering→Global→Local→Screening→InterpretationをE2E検証する。

## 14. 受入条件

### Result Card

- A001～A014の全Result Card v2が共通schemaとOperator Profileを満たす。
- `comparison_metrics`の各数値に意味、方向、比較可能条件がある。
- favorable方向が`higher_is_better=true/false`の両方で正しい。
- Cardから存在しないartifactへ参照できない。

### Global–Local・Cluster間比較

- 活性関連Local Bundleに完全一致するGlobal comparatorが必須である。
- comparator不足は採点されず`awaiting_comparator`になる。
- sibling Cluster比較は同一Clusteringとcomparison family内に限定される。
- 重複Clusterが独立支持として数えられない。
- metric・parameterが異なるResultをGlobal–Localとして比較できない。

### 一次評価

- 評価は他Bundleの点数分布を参照しない。
- 全軸にOperator固有の絶対anchorがある。
- 注目度と信頼性が別々に保存される。
- 単純合計点が存在しない。
- 同じBundleを同じrubricで再評価すると大きく矛盾しない。

### Interpretation

- 機能しないDescription・Clusteringを単独Insightとして掲載しない。
- `design_lead`と`contextual_anomaly`が主要部に掲載される。
- counterevidenceは親候補に結び付く。
- Cluster ResultをGlobalと表示しない。
- Insightがない場合、無用な解析の長い列挙を行わない。
- Markdown・HTMLからResult、Operator report、Conciergeへ追跡できる。

### 状態管理

- 別Main sessionの二重起動がLeaseにより拒否される。
- Packet claim後のRuntime WorkerはMainの消失やLease期限で二重起動されない。
- Mainは評価本文や全Result Cardを読まず、compact stateだけで継続できる。

## 15. リスクと対応

| リスク | 対応 |
|---|---|
| Operatorごとのprofile作成量が大きい | 科学kernelを変えず、出力意味の定義に限定する |
| comparator必須化でLocal評価が遅れる | Global優先と`awaiting_comparator`の次Round引継ぎを使う |
| 複数軸で順位づけが複雑になる | Candidate classと固定決定表を用いる |
| LLMの採点揺れ | Operator固有anchor、少数Bundle、schema、再評価testを用いる |
| 違和感が偶然である | 信頼性を分離し、必ず反証・追加検証候補を付ける |
| 古いRunを継続できない | 0.2.0は新規Runに限定し、中途半端な移行層を作らない |
| Result Cardが大きくなる | typed metricを最小化し、詳細値はOperator artifactへ残す |

## 16. 推奨結論

0.1.7の逐次Screeningは認知負荷を抑える基盤として維持する。ただし、一次評価の対象を単独Result CardからReview Bundleへ変え、次の三点を0.2.0の中心とする。

1. Global–Local・Cluster間の比較をRuntimeの必須契約にする。
2. 単純合計点を廃止し、活性改善と違和感を別軸で絶対評価する。
3. 人間向けInterpretationを`design_lead`と`contextual_anomaly`に集中させる。

これはOperator数を増やす変更ではなく、既存の広い解析結果から、人間が検討すべき知見へ正しく視線を導くための再設計である。
