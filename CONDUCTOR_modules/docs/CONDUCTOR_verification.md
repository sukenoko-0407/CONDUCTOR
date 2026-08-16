# CONDUCTOR 0.1.1 検証項目

## 現在の検証結果

- Catalog: 47 allowlisted Capabilityの生成・整合性検査に合格
- Package: 48 Skill、2 Agentを独立Projectへ試験導入し、導入先layout検査に合格
- Python: Skill／Runtime／tool sourceの構文検査に合格
- Test suite: 17件すべて合格
- 文書整理: 配布対象docsにPNG／PPTXなし

指定共有Pixi binary、Linux/HPC、実ChemBERTa weight、実tbliteを必要とする検査は本番環境での受入項目です。未実施項目を成功扱いしません。詳細は`CONDUCTOR_0.1.1_vector_clustering_refactoring_plan.md`を参照してください。

## Package

- `.claude/skills/`の全Skillに`SKILL.md`、`README.md`、`capability.json`、launcher、`env/pixi.toml`がある。
- `.claude/agents/`にはOrchestratorとInterpreterだけがある。
- Catalog allowlist、Capability ID、analysis profile、schemaが一致する。
- `CONDUCTOR_modules/`へruntime結果を書かない。

## 用語・ID

- 公開契約にGrouping／Group／NG／G######が残っていない。
- Node、Cluster、Insight、Next Action IDはRuntimeだけが発行する。
- Insight／Next Action番号はRoundを越えて単調増加する。

## 実行

- 一般利用では`--conductor`なしで主成果物だけを生成する。
- CONDUCTOR利用ではNode／attempt directoryにmanifest、event、Operator reportを生成する。
- structure Clusteringはcompound ID/SMILES CSV、Vector ClusteringはDescription vectorを受け取る。
- C005～C010はnative distanceと手法別`auto` calibrationを使用し、endpoint列をparameter選択へ使わない。
- Cluster構造が弱い入力では、Clusterを強制せず診断付き`no_usable_partition`を返せる。
- 0.1.0→0.1.1 MigrationはDescriptionだけをRND0001へ移し、RND0002や解析を開始しない。
- 全Clusteringで`min_cluster_size >= 5`を拒否不能な下限とする。
- MCS pair上限は1000、pair samplingはseed付き一様ランダム非復元抽出である。
- binary/MorganのmetricはTanimotoから変更できない。

## Orchestration

- leaseなしにStateを変更できず、二重Orchestratorが同時commitできない。
- retryは同一Nodeの新attemptとなり、旧attempt eventはcommitできない。
- briefに必ず一つの`required_control_action`があり、サイズ上限を超えない。
- Round終端はcurrent Interpretation JSON／Markdown／HTMLとFull Audit passを要求する。

## 新規Analysis

- PCA／UMAPはAnalysis artifactであり、標準Clustering入力へ接続されない。
- Cluster overlayはGlobal projectionを再fitしない。
- A005はD001/D002/D006/D013/D016/D019を固定panelとし、Localは30化合物以上、feature selectionはfold内だけで行う。

## Interpretation

- draftは正式IDを持たず、Runtime commitがINS/ACTを割り当てる。
- HTML／Markdownは固定rendererから毎回同じsection順・themeで生成する。
- reportは作業記録ではなく、観察、解釈、反証、限界、Next Actionを示す。
- Insightがゼロのreportを有効なnegative resultとして扱える。
