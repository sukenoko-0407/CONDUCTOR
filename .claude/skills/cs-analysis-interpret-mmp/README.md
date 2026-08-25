# Read-only MMP Global–Local interpretation

## SKILLの目的

既存A014 Global MMP Databaseを、CONDUCTORが登録したCluster membershipでread-onlyに切り分け、Transform効果のGlobal–Local差を人間向けに整理します。DAG、State、正式Insightは変更しません。

## 想定利用シーン

Round終了後に、ClusteringによってTransform効果の分散が小さくなるか、特定Clusterだけで効果が増幅・反転するかを確認するときに使います。Survey後はClustering Node、Cluster、Transformを指定して絞り込めます。

## 環境構築

`scripts/launch.py`がSkill内のPixi環境とcacheを自動構築・再利用します。Linuxでは共有Pixi binaryを優先します。

## 利用例

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" prepare \
  --run-root /path/to/run --round-id RND0001 --explicit-request
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" finalize \
  --request-dir /path/to/run/mmp_interpretation/MMPREQ000001
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" verify \
  --request-dir /path/to/run/mmp_interpretation/MMPREQ000001
```

`prepare`後、Agentはbounded contextを読み、同じrequest directoryの`mmp_interpretation_draft.json`だけを必要に応じて改善します。

## 制約事項

対象Roundで新たに成功したGlobal A014 Nodeが必要です。過去Nodeの再利用は人間がNode IDを明示した場合だけ許可します。LocalはGlobal DBの既存MMP pairをCluster membershipで絞り込む派生集計であり、MMP fragmentationを再実行しません。重複Clusterの分散縮小は独立な分散分解として扱いません。

全surveyはClustering Node単位でPairを一括投影し、全ClusterのsupportをScreeningした後、基準を満たすTransformだけOutside／Exact Core詳細を計算します。既存Databaseの再構築や追加操作は不要です。低support結果はScreeningに残りますが、未評価のOutside詳細は空値になり得ます。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | read-only Global–Local MMP survey、Clustering／Cluster／Transform focus、固定Markdown／HTML reportを追加。Clustering Node単位の高速Screeningと適格候補限定の詳細集計へ更新 |
