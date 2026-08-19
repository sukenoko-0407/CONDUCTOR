# CONDUCTOR 0.1.0–0.1.3 仕様変更履歴

## 1. この文書の目的

本書は、beta系列の`0.1.0`から`0.1.3`までにCONDUCTORの仕様がどのように変化したかを、科学機能と制御機能を分けて整理した履歴である。個々のfile差分を列挙するchangelogではなく、各Versionで何を解決し、何を維持し、次版へどの設計を引き継いだかを示す。

内容はGitの各Branch先端を直接参照し、主に各版の`CONDUCTOR_modules/docs/`、実装file差分、検証記録を照合して作成した。計画と実装記録が区別されている場合は、実装記録とBranch上の実体を優先した。調査中に作業Branchのcheckoutは行っていない。

| Version | Branch先端 | 日付 | 主題 |
|---|---|---:|---|
| 0.1.0 | `631e9ad` | 2026-08-10 | beta仕様の確立と科学機能・用語・Interpretationの再編 |
| 0.1.1 | `166e17c` | 2026-08-17 | Vector Clusteringの距離校正と手法別自動設定 |
| 0.1.2 | `d15117c` | 2026-08-18 | Runtime、State、Round管理の抜本再設計 |
| 0.1.3 | `2df3d94` | 2026-08-19 | Main Agent Orchestrationと実行contextの分離 |

## 2. 全体の変遷

```text
0.1.0  科学機能と用語をbeta仕様として再編
   |
   v
0.1.1  Vector ClusteringをDescription空間ごとに適応可能化
   |
   v
0.1.2  LLMが直接Stateを管理する負担をRuntimeへ移管
   |
   v
0.1.3  Main Agentを指揮者とし、実行と解釈を短命Subagentへ分離
```

大きな設計の流れは、科学Capabilityを増やす段階から、複数RoundをLocal LLMでも安定して運用するための制御境界を強化する段階へ移っている。

| 観点 | 0.1.0 | 0.1.1 | 0.1.2 | 0.1.3 |
|---|---|---|---|---|
| 主変更層 | 科学仕様・用語・Interpretation | Vector Clustering | Runtime・State・Round | Agent責務・実行protocol |
| Description | ID整理、D019拡充、D020固定 | 計算kernel維持 | 計算kernel維持 | 計算kernel維持 |
| Clustering | 用語統一、最小Cluster数5 | C005–C010を大幅校正 | 科学仕様維持、I/O簡素化 | 科学仕様維持 |
| Operator | A003–A005追加、ID再編 | 原則維持 | 科学仕様維持、Result Card化 | 科学仕様維持 |
| Interpretation | Insight／Next Actionへ整理 | 維持 | Result基準、固定品質gate、follow-up内包へ簡素化 | InterpreterをMainから分離し有限retry化 |
| 状態管理 | DAG、lease、attempt、短いbrief | Clustering品質summary追加 | Control／Ledger／DAG Snapshotへ責務分割 | compact APIと署名済みexecution packet追加 |
| Orchestrator | 専用Agent | 専用Agent | Dispatcher＋専用Agent | Main AgentがOrchestrator |
| Round開始 | 人間主導 | 維持 | 人間権限をRuntimeで強制 | 手動Skill起動としてさらに明確化 |

## 3. Version 0.1.0

### 3.1 位置づけ

alpha系列を基礎に、CONDUCTORのbeta仕様を確立したVersionである。名称、ID、科学Capability、Interpretation、Runtime契約、文書構成を広範囲に再編した。

### 3.2 主な変更

- `Grouping`／`Group`を廃止し、公開契約を`Clustering`／`Cluster`へ統一した。
- Node prefix、Cluster ID、path、manifest、membership等を新用語へ移行した。
- Description、Clustering、OperatorのCapability IDを機能の近い順に整理した。
- 全Clusteringで`min_cluster_size=5`をhard floorとし、4化合物以下の集合を正式Clusterとして登録しない仕様にした。
- PCA、UMAP、Multi-Description feature modelをAnalysis Capabilityとして追加した。
- GFN2-xTB Descriptionを、HOMO、LUMO、gap、dipole、charge、bond order等を含む回転不変scalar中心へ拡充した。
- pretrained embeddingをChemBERTa-100M-MLMへ固定し、offline・local weight・CPU実行を前提にした。
- 初期解析範囲を一つの`analysis_profile.json`から人間が調整できる構造にした。
- Interpretationでは独立Evidence entityを廃止し、Operator Nodeを根拠の正本とした。
- FindingとHypothesisを`Insight`へ、QuestionとAnalysis Requestを`Next Action`へ統合した。
- Insight／Next ActionのIDをRun全体で単調増加させ、Runtime commit時に附番する方式にした。
- 日本語Markdown／HTMLを固定rendererから生成し、Interpretation未完成時にRoundを閉じられないgateを強化した。
- Orchestratorが読む情報を当時の固定長brief JSONへ限定し、Runtimeが一度に一つの制御Actionを提示する設計にした。

### 3.3 維持した契約

- Description、Clustering、既存Operatorの科学計算kernelは、明示した追加・拡充箇所以外では原則維持した。
- 一般利用をdefaultとし、`--conductor`を明示的opt-inとする境界を維持した。
- Skill単独コピー可能性、Skill-local Pixi環境、Skill-local cacheを維持した。
- Runtime single writer、lease、DAG、Node内attempt分離を維持・強化した。
- 一Run一endpoint、`higher_is_better`必須、分子標準化とID／SMILES品質は人間の責務とした。

### 3.4 互換性と検証

- alpha系列Runの暗黙migrationは提供せず、0.1.0で新規Runを開始する方針とした。
- Branch内の実装記録では、Catalog、Package layout、Python構文、17件の自動testに合格した。
- Linux共有Pixi、実ChemBERTa weight、実tblite、HPC end-to-endは配布先での受入項目として残した。

## 4. Version 0.1.1

### 4.1 改良理由

0.1.0のVector Clusteringでは、異なるDescription空間へ固定的な閾値を適用した結果、次の両極端が確認された。

- RDKit 2D、USR／USRCAT、Mordred 3D等で過剰に断片化し、正式Clusterがほぼ生成されない。
- hashed atom-pair countをCosineで扱う例では、全化合物が一Clusterへ崩壊する。

このため、MetricはDescription表現の意味から固定しつつ、近傍・切断parameterをデータと手法に応じて校正する設計へ変更した。

### 4.2 主な変更

- 対象をVector Clustering `C005`–`C010`へ限定した。
- Tanimoto、Cosine、Euclidean、Manhattanをnative distanceとして扱い、距離を一律の擬似similarityへ変換する処理を廃止した。
- 共通の距離profileとして距離分布、k近傍距離、距離集中、重複Vector等を診断するようにした。
- 手法ごとに異なる自動parameter選択を実装した。
  - Butina: 近傍距離に基づくcutoff候補
  - Hierarchical: linkage gapに基づく切断候補
  - DBSCAN: k-distanceとrobust分位点に基づく`eps`
  - Louvain／Leiden: weighted mutual-kNN graphと`resolution`
  - Connected Components: percolationを考慮したradius cutoff
- `--parameter-mode auto`をdefault、`fixed`を人間overrideとして導入した。
- Endpointをparameter選択へ使用せず、Clustering結果に都合のよい活性分離を探索しない契約を明文化した。
- Clusterを無理に作らず、適切なpartitionがなければ、計算成功のnegative resultとして`no_usable_partition`を返せるようにした。
- 未所属理由をinvalid、missing、noise、singleton、小Cluster、partition不成立に分けた。
- 一般利用では主要CSV、CONDUCTOR利用では距離profile、manifest、registry、warning、execution eventを追加出力する境界を明確にした。

### 4.3 維持した契約

- Description計算kernelと既存Description artifactの意味は変更しなかった。
- 構造Clustering `C001`–`C004`、categorical／meta Clustering、Operator、Interpretationは原則変更しなかった。
- `min_cluster_size=5`、Runtime single writer、DAG、Node／attempt／Cluster ID管理を維持した。
- 一般利用default、`--conductor`明示opt-inを維持した。

### 4.4 Migrationと検証

- 0.1.0から0.1.1へは、成功済みDescriptionだけを移す決定論的Migrationを用意した。
- 移行先RND0001を「基本計算途中で終了」として閉じ、RND0002やOrchestratorをMigration中に開始しない仕様とした。
- 0.1.0のClustering、Analysis、Interpretationは再利用対象外とした。
- Version固有の実装記録では26 test合格、2,000化合物のsynthetic fixtureで距離行列と候補探索の計算境界を確認した。

## 5. Version 0.1.2

### 5.1 改良理由

DAG、Node状態、Round進行、Skill command、並列実行、失敗処理、Interpretation終端をOrchestratorへ負わせすぎた結果、Local LLMで次の問題が起きやすかった。

- Wall Timeや未完了Taskが残っていてもRoundを切り上げる。
- Nodeを誤ってTerminal状態へ変更する。
- Interpretation HTML完成前に終了する。
- 人間の許可なく次Roundを開始する。
- 新しいsessionが巨大なStateや複数の長文資料を読む必要がある。

0.1.2では科学的選択と決定論的制御を分け、DAGを保持しながらLLMの直接操作対象から外した。

### 5.2 主な変更

- Round制御の正本を短い`conductor_control.json`とした。
- 詳細履歴を`event_ledger.jsonl`、依存関係を`dag_snapshot.json`、検索用結果を`result_index.jsonl`へ役割分離した。
- OrchestratorはControlとbounded Working Setを読み、全DAG、全Ledger、全Artifactを通常は読まない構造にした。
- Round状態を`ACTIVE`、`FINALIZING`、`AWAITING_HUMAN_REVIEW`、`CLOSED`へ整理した。
- 新Round開始を人間権限とし、中断後の同一Round再開と明確に分離した。
- Main Agent用入口`cs-conductor-dispatch`と、科学判断を担うOrchestrator Agentを分離した。
- Node状態を`pending`、`running`、`succeeded`、`failed`、`cancelled`の5種類へ限定した。
- 候補、未選択、適用不能をNodeにせず、実行を正式決定した計算だけをNodeとした。
- 技術的再試行をNodeとは別のAttemptとしてRuntime管理へ移した。
- 専門SkillのCONDUCTOR出力を、科学payloadとcanonical `result.json`を中心とする形へ簡素化した。
- Analysis結果ごとに短いResult Cardを作り、Runtime queryが必要な結果だけをWorking Setへ載せる方式にした。
- Insightの注目度を`pinned`、`active`、`watch`、`background`として可変管理し、全結果を保存しながら通常読取量を抑えた。
- 永続的なNext Action ledgerを廃止し、follow-up提案をInsight内へ内包した。人間が採用した内容だけを次Round Contractへ移す形へ簡素化した。
- `analysis_subject`をRuntimeが確定し、GlobalとCluster-localの誤表示、Cluster IDやsample数の不一致をQuality gateで拒否するようにした。
- Interpretation JSON／Markdown／HTML、quality検査、Full Auditが揃うまでRoundを人間レビュー状態へ進めない仕様を強化した。
- Conciergeを`run_root/concierge/`だけへ書込可能な、解析State非変更の補助機能として整理した。
- 異常Nodeを人間が明示的に検査・是正する`cs-conductor-node-review`を追加した。

### 5.3 維持した契約

- 基本計算、初期探索、追加探索、深掘り解析という科学waveを維持した。
- Global対Cluster-local、Description横断、Cluster間、Operator横断、反証探索を維持した。
- Descriptionごとのnatural metric、0.1.1のVector Clustering校正、Cluster最小サイズ5、MCS random pair samplingを維持した。
- 一般利用のCLIおよび`--conductor`による明示的なCONDUCTOR利用境界を維持した。

### 5.4 互換性と検証

- 0.1.1 Runとの再開互換性を提供せず、0.1.2では新規Runを開始する方針とした。
- Windows開発環境では23 test合格、7件skipと記録されている。skipはsystem PythonにRDKitがない場合の実計算で、Skill専用Pixi環境で別途確認する扱いとした。

## 6. Version 0.1.3

### 6.1 改良理由

0.1.2では専用Orchestrator Agentが科学判断だけでなく、実際のSkill Tool call、引数不整合への対応、実行logの受領まで担う場面が残った。Tool callの失敗と再試行が長期contextを消費し、本来の指揮責務を不安定にする可能性があった。一方、Main AgentはOrchestratorの終了を待つだけになりやすかった。

0.1.3では、Main Agent自身をOrchestratorとし、計算実行とInterpretation draft作成を短命な兄弟Subagentへ分離した。

### 6.2 主な変更

- Main Agentで手動起動する`cs-conductor-orchestrator` Skillを新設した。
- 同名のOrchestrator Agentと`cs-conductor-dispatch`を廃止し、起動入口と実行主体の混同を解消した。
- `cs-conductor-executor`を、一つのRuntime actionまたは一つのbatchだけを処理する短命Subagentとして追加した。
- `cs-conductor-interpreter`をMain Agentが直接起動する兄弟Subagentとして維持し、Executorからの入れ子起動を前提にしない構造にした。
- Main Agentは科学候補の選択、Round指揮、終端確認へ集中し、専門Skill、raw log、全Stateを直接扱わない契約にした。
- Runtime応答を16 KiB以下のcompact envelopeと詳細pointerへ分けた。
- Executor用に署名済み、Control revision固定、Action-scoped、期限付きのexecution packetを導入した。
- Mainのlease tokenをExecutorへ渡さず、packetの二重利用をRuntimeが拒否するようにした。
- 標準実行1回と最大2回の補正実行、合計最大3 Attemptの有限retryを導入した。
- 引数名、path、format、working directory等の機械的不整合だけを、Node専用scratch内で適応的に回復できるようにした。
- 回復処理による科学parameter、対象compound、endpoint、metric、scope、seedの変更を禁止した。
- Interpretation品質不合格を同一Interpretation Nodeの有限Attemptとして扱い、無制限retryや未完成での正常終了を防いだ。
- Main sessionが中断しても、別Main sessionが同じActive Roundとrequired actionを再開できる仕様にした。

### 6.3 維持した契約

- `conductor_control.json`、Runtime single writer、5種類のNode状態、DAG snapshot、lease、Action tokenを維持した。
- Round開始は人間の明示指示だけとし、失敗や未完了を理由に自動的に次Roundを作らない。
- InterpretationとFull AuditをRound終端の必須gateとして維持した。
- 基本計算、初期探索、追加探索、深掘り解析の範囲と科学的判断原則を維持した。
- Description、Clustering、Operatorの科学計算kernelには、Version契約以外の一括変更を加えなかった。
- 一般利用defaultと明示的`--conductor` opt-inを維持した。
- Conciergeは引き続きRun Root内の専用directoryだけへ書き込み、正式な解析Stateを変更しない。

### 6.4 互換性と検証

- 0.1.2以前のControlを暗黙変換せず、0.1.3の受入は新規Runを前提とした。
- Windows開発環境では35 test合格、Leiden依存関係の1件をskipした。
- Package layout、47件のallowlisted Capability、installer、Python compile、全JSON Schema、`git diff --check`に合格した。
- Linux共有filesystem上の一Round end-to-endは配布先での受入項目として残した。

## 7. 変わらなかった中核方針

各Versionで実装構造は変化したが、次の中核方針は0.1.0から0.1.3まで一貫している。

- 多数の専門Skillを疎結合に接続する。
- 同じRunで人間主導の複数Roundを重ねる。
- GlobalとCluster-localの差を探索する。
- 異なるDescription、Clustering、Operatorの一致、矛盾、反証候補を比較する。
- 科学的negative resultを技術的失敗と区別して保存する。
- RuntimeだけがID、状態、DAG、正式Artifactを確定する。
- 人間の明示指示なしに次Roundを開始しない。
- 一般利用とCONDUCTOR利用を`--conductor`で明確に分ける。
- `CONDUCTOR_modules/`をRuntimeから書き換えず、解析結果はRun Rootへ保存する。

## 8. `--conductor`契約の推移

`--conductor`の基本的な意味は全Versionで維持されている。

### 一般利用: `--conductor`なし

- Skillを単独で使用する。
- CSV、HTML、診断file等、そのSkillの人間向け主要成果物を生成する。
- CONDUCTOR専用のNode、Round、Attempt、execution event、State更新を要求しない。

### CONDUCTOR利用: `--conductor`あり

- RuntimeがRun、Round、Node、Attempt、入力Artifact、出力scratchを拘束する。
- SkillはCONDUCTOR用manifest／eventまたはcanonical resultを返し、Runtimeが検証後に正式Artifactへcommitする。
- Versionが進むにつれ管理fileの責務は専門SkillからRuntimeへ移ったが、一般利用とCONDUCTOR利用を分けるopt-in境界自体は変わっていない。

## 9. 現行0.1.3を理解するための読み順

1. `CONDUCTOR_overview.md`: 科学的な全体像
2. `CONDUCTOR_user_guide.md`: 人間による開始、継続、レビュー
3. `CONDUCTOR_design_spec.md`: Main Agent、Executor、Interpreter、Runtimeの責務
4. `CONDUCTOR_0.1.3_main_orchestrator_overview.md`: 0.1.2から0.1.3へ変更した理由
5. `CONDUCTOR_output_contract.md`: Run RootとArtifact境界
6. `CONDUCTOR_identifier_reference.md`: 現行ID体系
7. `CONDUCTOR_verification.md`: 現行受入条件と検証結果

過去版の計画書は各Version Branchに保持されている。旧Versionを実行するときは、現行文書で推測せず、そのBranchのRuntime、Skill、schema、文書を一式で使用する。

## 10. 主な調査資料

| Branch | 主に参照した文書 |
|---|---|
| `0.1.0` | `CONDUCTOR_0.1.0_refactoring_plan.md`、`CONDUCTOR_overview.md`、`CONDUCTOR_design_spec.md`、`CONDUCTOR_verification.md` |
| `0.1.1` | `CONDUCTOR_0.1.1_vector_clustering_refactoring_plan.md`、`CONDUCTOR_0.1.0_to_0.1.1_description_migration.md`、`CONDUCTOR_verification.md` |
| `0.1.2` | `CONDUCTOR_runtime_redesign_overview.md`、`CONDUCTOR_runtime_redesign_plan.md`、`CONDUCTOR_design_spec.md`、`CONDUCTOR_verification.md` |
| `0.1.3` | `CONDUCTOR_0.1.3_main_orchestrator_overview.md`、`CONDUCTOR_0.1.3_implementation_plan.md`、`CONDUCTOR_design_spec.md`、`CONDUCTOR_verification.md` |

これらに加え、各Branch間の`git diff --stat`、`git diff --name-status`、Agent／Skill／schema／testの配置を照合した。
