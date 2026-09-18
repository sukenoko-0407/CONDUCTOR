# CONDUCTOR 0.2.1 本番Run障害・是正報告

作成日: 2026-09-18

## 1. 結論

3.4A本番Runで確認された事象により、従来の「実装完了」という判断は撤回する。実装詳細仕様書は存在したが、Description互換境界、Mordred欠測契約、L4計算量、Runtime復旧の受入試験が本番規模を拘束できていなかった。961化合物でP01/P02は完了した一方、D015/D016のcache登録が0件となり、P03-L4が約25万候補を無上限に全Tierへ再記述してKILLされたことは、実装適合性の欠陥である。

修正後も、停止した今回のRunをそのまま再開してはならない。P01/P02が旧Mordred登録契約で成功済みのため、P03だけを再開するとD015/D016が未登録のDatabaseを残す。Ubuntu本番機へ修正を反映し、下記の限定検証を通した後、部分構築Databaseを入力にした新しい回復Runを作成する。

## 2. 原因と修正

| ID | 原因 | 修正 | 受入条件 |
|---|---|---|---|
| R-01 | 0.2.1 identityを0.1.x Skillへ直接渡した | `identity_bridge.py`で旧patternへ決定論的に写像し、Phase 1とL4で共用 | `RNDdddd`、`Ndddddd`、`ATTdddd`に適合し、同じ入力から同じID |
| R-02 | 距離Artifactの配置を実行側が保証していなかった | canonical `description_node.py`を追加し、`<output>/distance/`へ固定 | 18空間の`.npy`とmetadataが同directoryに存在 |
| R-03 | CPU予算が子processへ一貫して伝播しなかった | Runtimeから解決済みRequest、CLI、`CONDUCTOR_AVAILABLE_CPU_CORES`、`CONDUCTOR_NODE_CPU_CORES`へ同じ値を注入 | `resources.workers=64`なら全境界で64、OS affinity超過は起動前拒否 |
| R-04 | 7 Skill launcherに共有Pixi fallbackがなかった | L1b/L4/L5/L7/scoring/deepdive/reportへ共有asset pathを追加 | `CONDUCTOR_PIXI`、共有asset、PATHの順で解決 |
| R-05 | failed P03-L7を正規に再キューできなかった | failed限定・Skill一致・操作者/理由必須のadministrative requeueを追加 | 他stateは拒否し、旧attemptと理由をeventへ保存 |
| R-06 | cache miss subsetをoutput配下へ先に作成した | output外の`TemporaryDirectory`へ変更 | Skill起動時にoutput directoryが不存在または空 |
| R-07 | Mordredの構造的NaNを全行失敗と扱った | D015/D016だけ部分有限値登録を許可し、calculation versionを2へ更新 | 50%以上有限ならnull保持で登録、全NaN/計算失敗は拒否 |
| R-08 | L4に候補capと再記述cost guardがなかった | 支持順位で既定100候補、最大900 Description行、最大10,000 cost units | 超過時はSkill起動前に`needs_design_review` |

## 3. D015/D016の契約

D015/D016はSe/Pb/Sn/As等の構造的に該当しないdescriptorを0へ変換しない。payloadとDatabaseではnullを保持する。1行のfeatureの50%以上かつ1件以上が有限なら登録し、全feature非有限または`description_error`を持つ行は登録しない。距離計算時は全化合物で常に非有限の列を除外し、残る欠測だけを観測中央値で補完する。

この契約変更によりD015/D016の`calculation_version`は`2`となる。旧version 1 recordをversion 2のcache hitとして扱ってはならない。

## 4. L4 scale contract

L4はone-step候補を次のstable順で並べる。

1. 異なる到達経路数の降順
2. 利用変換の観測pair数合計の降順
3. 到達元化合物数の降順
4. candidate IDの昇順

既定では上位100候補だけを9個のTier 1/2空間へ流すため、再記述上限は900行である。さらにcost classを`low=1, medium=4, high=16, very_high=64`で重み付けし、10,000 cost unitsを上限とする。cap除外は`reason=scale_cap`としてauditへ残す。予定行数またはcost unitsがhard上限を超える場合は`needs_design_review`で停止し、自動的にcapまたは上限を変更しない。

## 5. 回復Run前の限定検証

1. 修正をUbuntu本番機へ反映する。
2. `resources.workers`を明示値（当該機では最大64）にする。
3. D015/D016の2〜3化合物fixtureで、部分NaN行が登録され、全NaN行が拒否されることを確認する。
4. L4の生成だけを実行し、生成総数、選択数≤100、予定行数≤900、予定cost units≤10,000を確認する。候補Descriptionはこの確認より前に起動しない。
5. KILLされたRunのRuntime stateと部分構築Description Databaseをread-onlyでinventoryし、writerがいないことを確認してSQLite backup APIでバックアップする。
6. KILLされたRunは再開せず、新しいRun ID/Run rootを作る。部分Databaseの互換16 Descriptionはhit、D015/D016は`calculation_version=2`のmissとして計算・登録し、P01以降のRun Artifactは全て新規作成する。
7. 全Descriptionを再びhit=0でやり直す必要がある場合だけ、部分Databaseを復元可能に退避し、既定pathが不存在であることを確認して3.4Aを新規実行する。物理削除はしない。

`requeue_runtime_node.py`は、入力・config・計算契約が変わらず、Pixi launcher解決だけが原因で`failed`になったP03-L7等の限定復旧用である。今回のようにP01の計算契約が変わったRun全体の復旧には使用しない。

## 6. 検証状況

- Python構文検査: 合格
- identity bridge単体試験: 合格
- Runtime state/requeue単体試験: 合格
- Runtime CPU予算注入integration試験: 合格
- Mordred/L4/RDKitとPhase 1〜6のsmall fixtureを含むworkspace回帰: 101件合格
- Ubuntu本番機固有のPixi環境、Linux CPU affinity、64コア予算、実データ規模については、本番開始前の限定fixtureと3.2Aで確認する。

したがって本報告時点の状態は「修正実装と自動回帰は合格、Ubuntu本番機固有の限定受入待ち」である。限定受入と3.2A/3.3が合格した後は、全件再構築なら3.4A、部分Databaseを保持するなら3.4Bへ進む。
