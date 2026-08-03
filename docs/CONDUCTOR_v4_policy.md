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
- 高コスト処理は、目的、対象、概算資源、期待する情報を提示して人間の承認を得る。
- 並列数は人間が指定した上限を超えない。
- Operatorの数値的観察とInterpretationの推論を混同しない。
- 相関を因果として断定しない。

## 3. 広く浅い探索

最初の探索では、入力要件を満たす低～中コストSkillから、互いに情報源の異なる表現と解析を選ぶ。単一の表現familyに偏らない。すべてを実行する必要はなく、dataset規模、欠損、既存artifact、計算資源を踏まえて代表Skillを選ぶ。

初期候補は次の順に検討する。

1. 入力品質とendpoint分布
   - assay条件列が指定され、同一endpoint列に複数条件がある場合は、全体解析に加えて条件別Groupingを計画する。
2. 解釈可能な2D descriptor
3. 代表的な2D fingerprint
4. 構造based Groupingとvector based Groupingの代表
5. group profileとactivity enrichment
6. kNN activity consistency、SALI、activity cliff
7. descriptor-activity association

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

GPU、外部model weight、大規模pairwise計算、大規模MCS、3D conformer大量生成、量子化学計算、Catalogで`high`または`very_high`とされたSkillは高コストとして扱う。実行前に次を人間へ提示する。

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
