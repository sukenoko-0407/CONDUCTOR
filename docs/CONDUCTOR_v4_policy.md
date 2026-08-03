# CONDUCTOR v4 Orchestration Policy

## 1. 役割

Orchestration Agentは、Catalogに収載されたSkillだけを使い、run StateのDAGを更新しながら、広く浅い解析から情報価値の高い局所解析へ進む。固定的な総当たり手順ではなく、得られたevidenceと利用可能資源に応じて計画を更新する。

## 2. 絶対条件

- 人間が指定したendpointを1 runにつき一つだけ扱う。
- run開始前に`higher_is_better`を確認する。
- 活性値の単位変換やpActivity化を暗黙に行わない。
- 分子標準化を行わない。入力構造を人間が準備したものとして扱う。
- 重複IDがあれば停止する。invalid SMILESは保持して警告する。
- Catalog allowlist外のSkillをCONDUCTOR実行に使用しない。
- State DAG nodeとしてSkillを実行するときは`--conductor`、Stateのproject、run ID、予約済みnode IDを必ず一組で渡す。execution eventが期待contextと一致しなければ完了扱いにしない。
- capability内のvariantまたはparameter setを変える場合は別nodeを作り、Stateの`parameters`へ記録する。execution eventの`configuration`が計画値と一致しなければ完了扱いにしない。
- 個別計算の依頼をrepository名や互換artifactだけからCONDUCTOR実行と推測しない。CONDUCTORの明示がなければ個別Skillの通常モードとする。
- CONDUCTOR実行が明示されているがrun contextが未作成なら、個別Skillを先行実行せずStateとnodeを初期化する。識別子の捏造や通常モードへの黙示的降格を行わない。
- 高コスト処理は原則として、目的、対象、概算資源、期待する情報を提示して人間の承認を得る。ただし人間管理Catalogで`approval_policy=preauthorized_initial`と明記されたC002 MCSは、必須初手としてrunごとの承認を不要とする。
- 並列数は人間が指定した上限を超えない。
- Operatorの数値的観察とInterpretationの推論を混同しない。
- 相関を因果として断定しない。

## 3. 広く浅い探索

初手は「計算量を最小化するpass」ではなく「深掘り対象となるヒントを取りこぼさないpass」である。低～中コストの一種類だけで結論を出す狭く浅い解析を禁止し、互いに異なる情報軸、Grouping原理、Operator観点を最初から計画する。一定の計算コストは網羅性のための基礎費用として受け入れる。

初手の標準profileを`representative-family-wide-v1`とし、Catalog metadataの`default_wide_shallow`、`wide_shallow_axis`、`wide_shallow_sources`を正本とする。現行profileは次を必須代表とする。

### 3.1 Description

- D001 RDKit 2D: 2D物性・topological scalar
- D002 Morgan: 局所circular graph
- D003 MACCS: curated substructure key
- D004 Atom Pair: 長距離topological atom pair
- D007 RDKit Path: path・subgraph
- D013 USR/USRCAT: 3D shape・3D pharmacophore。3Dを初手から除外しない
- D017 Gobbi Pharm2D folded: 2D pharmacophore

高コストmodel依存・量子化学表現はこの標準profileへ自動投入しないが、D019、D020を含む未実行軸をcoverage auditへ明記する。追加価値が見込まれる場合は、初手結果の有無にかかわらず人間承認候補として提示する。

### 3.2 Grouping

Groupingは、入力と責務が異なる二系統を混同しない。

- direct structure GroupingはSMILESを直接入力し、Description vectorを生成・消費しない。
  - C001 Murcko: scaffold rule
  - C002 MCS: maximum common substructure。構造Groupingの中心的な確認軸として全runの初手に必ず計画・実行する。高コストだが`preauthorized_initial`であり、runごとの事前承認は不要
  - C003 BRICS: fragment decomposition
- Description-vector ClusteringはDescription SkillのCSV artifactだけを入力し、raw SMILESや内部生成fingerprintを使わない。
  - C005 vector Butina: D002 MorganをJaccard/Tanimoto相当のbinary vector空間で分割
  - C006 vector hierarchical: D001、D013、D017の各表現で別nodeとして実行
  - C007 vector DBSCAN: D001の連続値空間でdensity-based grouping
  - C009 vector Leiden: D002 Morganの類似graphでcommunity検出
- assay条件が複数ならC011 categoricalを追加する。

同一algorithmを全Descriptionへ総当たりしない一方、物性、2D fingerprint、3D shape、pharmacophoreという異なるvector空間と、similarity partition、hierarchy、density、graph communityという異なる原理を初手から観測する。各vector nodeは上流Descriptionを明示的にbindingし、最初に生成されたDescriptionへ暗黙接続しない。`structure-butina`のようにSMILESからfingerprintをSkill内部で生成する複合ラッパーはCatalogへ収載しない。

### 3.3 Operator

- A002 endpoint distribution、A003 pairwise structure space、A007 structure-based activity cliffを全体に実行する。
- A004 descriptor-activity associationをD001とD013へ実行する。
- A005 kNN activity consistencyをD004とD007へ実行する。
- A006 SALIをD002、D013、D017へ実行する。
- A001 group profileとA008 group enrichmentを初手の全Grouping nodeへ実行する。
- A009 group overlapを重複groupを生成するC003へ実行する。
- A010 group structural diversityをC001、C002、C003および各C006 nodeへ実行する。

これは全Description × 全Grouping × 全Operatorの総当たりではない。各情報軸を少なくとも一度観測し、重要な局所関係を独立表現で照合できる最小の網羅profileである。

### 3.4 Coverage audit

各初手nodeはStateで`phase=wide_shallow`と`coverage_axis`を持つ。OrchestratorはDescription、Grouping、Operatorの必須軸とsource bindingを確認し、初手nodeの未実行、失敗、skipを明示する。ある軸のSkillが失敗した場合は、同じ軸の代替Skillを検討してからcoverage不足を受容する。

「有望なヒントがない」という判断は、初手profileの成功または説明付き代替・skipを確認した後に限る。初手の一部結果だけを見て残りを打ち切らない。dataset規模によりmedium costが実質的に高コスト化する場合も、無言で除外せず、対象分割、近似、代替または人間承認を選ぶ。

Stateはrunnable nodeのうち`wide_shallow` phaseを`deep_dive`より優先する。Interpretation nodeは全初手nodeが`succeeded/failed/skipped`のいずれかへ到達するまで開始できない。C002 MCSは承認待ちにせず実行し、失敗した場合は具体的な理由を記録して、それだけに依存する下流nodeを理由付き`skipped`にする。

## 4. 深掘り判断

次のいずれかが観察された局所を深掘り候補とする。

- 十分なsample数を持つgroupで実用的なactivity shiftがある。
- 近傍で大きなactivity差があり、cliffが一件だけでなく再現している。
- 異なる表現familyまたは異なる原理のOperatorが同じ方向を支持する。
- 支持evidenceと矛盾evidenceが併存し、追加解析で識別可能である。
- 構造的に多様だがactivityが揃う、または構造的に近いのにactivityが割れる。
- 欠損やassay条件混在では説明できない例外が残る。

effect size、p値、固定閾値だけで自動判定しない。dataset size、測定精度、group定義、evidence依存性を併記して判断する。

## 5. 高コスト判定と人間確認

GPU、外部model weight、大規模pairwise計算、3D conformer大量生成、量子化学計算、Catalogで`high`または`very_high`とされたSkillは高コストとして扱う。原則として実行前に次を人間へ提示する。C002 MCSだけは、人間がCatalog方針として初手実行を事前許可した例外であり、dataset規模にかかわらずrunごとの承認を求めない。

- Skill名と対象node/group
- なぜ今必要か
- 既存evidenceでは何が不足しているか
- CPU/GPU、並列数、概算時間と保存量
- 実行しない場合の代替案

## 6. 失敗と再開

- optional Skillの失敗はrun全体を直ちに失敗させず、Stateへ記録して代替を検討する。
- 必須入力、ID一意性、endpoint、State整合性の失敗は停止する。
- 上流artifactが変われば下流を`stale`にする。
- resume時は`succeeded`かつhash一致のnodeを再実行しない。
- 同じ失敗を無制限に再試行しない。原因と代替案を人間へ示す。

## 7. Interpretationへの引き渡し

Interpretationには、注目結果だけでなく、矛盾、警告、失敗、未実行候補、evidence依存関係も渡す。Interpretation後に追加解析が推奨された場合はDAGへ新node候補として追加し、高コストなら改めて人間承認を得る。
