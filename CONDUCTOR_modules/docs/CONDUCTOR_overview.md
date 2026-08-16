# CONDUCTOR 概要

CONDUCTOR 0.1.1は、化合物ごとの一つのendpointを、多数の分子表現とCluster、解析視点から反復的に調べるClaude Code向けSAR解析基盤です。一回で結論を出すのではなく、人間がInterpretationを確認し、次のRoundへ観点を渡しながら解析の完全性と質を高めます。

## 四つの科学段階

1. **Description**: 2D物性、fingerprint、部分構造、pharmacophore、3D、量子化学、ChemBERTa embeddingを計算する。
2. **Clustering**: SMILESを直接扱う構造Clusteringと、Description vectorを扱うVector Clusteringから、重複を許す多様なClusterを作る。Vector ClusteringはDescriptionごとに固定されたMetricを使い、各アルゴリズムが距離・近傍構造から固有parameterを自動校正する。
3. **Operator**: GlobalまたはCluster-localで分布、相関、射影、近傍整合性、SALI、cliff、Cluster特性、簡潔な複数Descriptionモデル等を計算する。
4. **Interpretation**: 異なる表現・Cluster・Operator・Roundの一致、相違、矛盾、negative resultを比較し、人間向けInsightとNext Actionを報告する。

## 解析Round

一つの「人間の指示→Orchestratorの実行→Interpretation→監査」を一Roundとします。初回は原則として全Descriptionとprofileで指定した構造／Vector Clusteringを揃え、Globalでは適用可能な全Operator、Localでは代表Clusterを広く調べます。次のRoundでは、未実施領域を偏りなく追加する探索と、既存Insightを別の表現・scope・Operatorで検証する深掘りを組み合わせます。

Vector Clusteringが安定した分割を見つけられない場合、Clusterを強制せず`no_usable_partition`を成功したnegative resultとして残します。Orchestratorは距離診断を保持しつつ、そのNodeからCluster-local解析を計画しません。

## DAGの意味

State内のDAG（有向非巡回グラフ）は、各Nodeがどの上流artifactを使ったかを一方向に記録します。循環を許さないため、由来追跡、再計算範囲、実行順、重複防止が明確です。DAGは科学的判断を固定する仕組みではなく、疎結合な計算のprovenanceと実行状態を管理する骨格です。

## 頑健性とシンプルさ

- Stateを書けるOrchestratorはleaseを持つ一つだけです。
- RuntimeがNode／Cluster／Insight／Next Action ID、依存関係、attempt、並列上限、Round gateを決定論的に管理します。
- Orchestratorは短い`orchestrator_brief.json`から始め、必要な情報だけをqueryします。
- 同じNodeの再試行は新しい`ATT####`として分離され、古いattemptの遅延結果は採用されません。
- Roundは最新InterpretationとFull Auditが揃うまで閉じられません。
- `CONDUCTOR_modules/`は実行中read-onlyで、結果はrun rootだけへ保存されます。

## 人間向け成果物

主成果物は各Roundの`interpretation.md`と`interpretation.html`です。個別Operatorには数値CSV、`operator_summary.json`、drill-down用`operator_report.html`があります。解析を進めず既存結果だけを詳しく調べる場合はResult Conciergeを使用できます。
