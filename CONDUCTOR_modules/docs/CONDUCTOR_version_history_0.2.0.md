# CONDUCTOR 0.2.0 変更概要

0.2.0は、広いOperator探索の結果から「favorableな活性改善候補」と「Global–Local／Cluster間の注目すべき違和感」を安定して抽出するため、ResultとInterpretationの契約を作り直した破壊的Versionです。0.1.x Runの継続や成果物変換は行わず、新規Runとして開始します。

## 主な変更

- Result Cardをv2へ更新し、Operator固有の自由形式数値と比較用のtyped metricを分離しました。
- A001～A014にOperator Interpretation Profileを定義し、評価軸、比較指標、Global comparator、最低支持条件をSkill側の契約にしました。
- 一次評価の単位を単独ResultからReview Bundleへ変更しました。
- Global、Global–Local、sibling ClusterをRuntimeが決定論的に構成します。必要なGlobalがないLocalは`awaiting_comparator`です。
- `higher_is_better`をRuntimeがfavorable方向へ正規化します。
- 0～3の複数絶対軸と独立した信頼性を保存し、0～10点等の単純合計を廃止しました。
- Runtimeが`design_lead`、`contextual_anomaly`、`supporting_evidence`、`background`等へ分類します。
- 正式Interpretationは`design_lead`と`contextual_anomaly`を中心に構成し、機能しない解析を単独Insightとして列挙しません。
- Orchestration session leaseとRuntime Workerの役割は維持し、旧Runを暗黙更新する経路を廃止しました。

## 維持したもの

- Description、Clustering、Operatorの科学計算kernel
- 一般利用CLIと`--conductor`の基本的な出力切替
- DAG、Node／Cluster／Round ID、append-only索引
- Run Root外への書込み禁止
- A014 Global MMP Databaseと人間起動のread-only MMP Interpretationの分離

## 互換性

0.1.xの`conductor_control.json`、Result Card、Assessment、進行中Roundは受理しません。RuntimeはVersion不一致を明示エラーにし、旧Runを部分的に更新しません。

## 検証

Package layout、Catalog／Interpretation Profile、schemaのoffline解決、Result Cardのfavorable正規化、Global comparator不足、sibling比較、絶対評価、Interpretation gate、既存Skill実行契約を自動試験で確認します。
