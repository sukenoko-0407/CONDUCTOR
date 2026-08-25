# CONDUCTOR 局所改修計画：Packet CLI・MMP解釈性能・A005 Artifact

## 実装状況

2026-08-25に本計画のコード変更を実装した。Packet公開alias、A005単一OOF Artifact、MMPのClustering Node単位Pair投影と二段階集計を反映済みである。適格候補が揃う合成データでは旧実装と全出力Tableが一致した。12,000 MMP行、100 Cluster、低support Transform多数の合成条件では、新実装は約8.3秒で完了し、旧実装は90秒を超えても完了しなかったため中断した。この測定は実データ性能の保証値ではなく、Linux上の実Databaseで別途確認する。

## 1. 目的

現行設計を維持したまま、次の3点を局所的に是正する。

1. Runtimeが返す`packet_path`から、Main AgentがCLI引数`--packet`を安定して使用できるようにする。
2. 作成済みMMP Databaseに対する全Clustering surveyを、知見候補を失わず実用的な時間で完了できるようにする。
3. A005 Multi-description feature modelのCluster surveyで、`oof_predictions` Artifact typeの重複によりRuntime commitが失敗する問題を解消する。

本改修では、DAG、State、Round、Node ID、MMP Database schema、各科学計算の意味を変更しない。Description、Clustering、A014 MMP Database構築、通常Interpretation、Subagent構成も変更対象外とする。

## 2. 改修方針の要約

| 対象 | 原因 | 改修方針 | 主要な非対象 |
|---|---|---|---|
| `--packet` | JSONキー`packet_path`とCLI引数`--packet`の表記差をMain Agentが誤推測し得る | `--packet`を正本として維持し、公開`execute-packet`だけで`--packet-path`もaliasとして受理する。正確な実行例をOrchestrator文書へ追加する | Packet署名、hash、claim、内部Worker CLI |
| MMP解釈 | Clusterごとに全MMP行を走査し、ほぼ同じOutside統計を反復計算している | Clustering Node単位の一括Screeningと、適格候補だけの詳細計算へ分離する | SQLite schema、A014出力、既存Database |
| A005 | 複数のCluster OOFを同じArtifact typeで列挙するためRuntimeの一意性検査に違反する | Cluster OOFを`cluster_id`付きの単一CSVへ統合し、Eventには1 Artifactだけ登録する | モデル、fold、特徴量選択、評価指標 |

## 3. Packet CLIの局所是正

### 3.1 現状

正式な公開CLIは次である。

```bash
python <project>/.claude/skills/cs-conductor-runtime/scripts/launch.py state execute-packet \
  --run-root <run_root> \
  --packet <packet_path>
```

`prepare-execution-packet`の応答キーは`packet_path`である。これは値がファイルパスであることを表すJSONキーであり、CLI引数名ではない。現在のコードおよびGit履歴では、`--packet-path`を正式CLIとして採用した形跡はない。

### 3.2 変更内容

- 正式名称は`--packet`のままとする。
- 公開`execute-packet` parserだけは、`--packet-path`を同じ`args.packet`へ格納するaliasとして受理する。
- 内部`_worker-execute-packet`はRuntime自身しか呼ばないため、`--packet`だけを受理する。
- Orchestratorの`EXECUTE_RUNNABLE_BATCH`手順に、上記の完全なコマンド形を記載する。
- Runtime応答の`packet_path`キー、Execution Packet、署名、hash、TTLは変更しない。

このaliasは科学処理や状態遷移に分岐を追加せず、公開境界の入力表記だけを正規化する。現状維持も動作上は正しいが、Local LLMで実際に誤推測が発生したため、防御的aliasを採用する。

### 3.3 合格条件

- `--packet`と`--packet-path`が同一Packetを同じ`args.packet`として処理する。
- 同一Packetの再投入が二重実行を起こさない。
- 内部Worker commandは引き続き`--packet`を使用する。
- Orchestratorが長いCLIを推測せず、文書中の定型コマンドを使用できる。

## 4. MMP Interpretationの性能改修

### 4.1 変更しない契約

- A014が生成した既存`mmp_database.sqlite`をread-onlyでそのまま使用する。
- Database table、index、metadata、Transform、Exact Core、Environment radiusを変更しない。
- A014の再実行およびDatabase migrationを要求しない。
- `cs-analysis-interpret-mmp`は引き続き凍結Runだけを読み、`run_root/mmp_interpretation/`以外を変更しない。
- 既存の全survey、`--clustering-node-id`、`--cluster-id`、`--transform-id`の操作を維持する。

### 4.2 現在のボトルネック

現在は各Clusterについて、全MMP行に対する2回の`isin`、Local／Boundary／Outside DataFrame作成、Local／Outside Transform集計、Core集合比較を繰り返す。Cluster数を`C`、MMP行数を`M`とすると、主要部は概ね`O(C × M)`である。

特に次が不要な計算である。

- 計算済み`local_summary`を`eligible_transform_count`のために再計算している。
- Local MMPが空でも、ほぼGlobal全体に相当するOutsideを作って集計している。
- Local supportが閾値未満でも、全TransformのOutsideとCore集合を計算している。
- 同一Clustering由来のClusterを個別に処理し、Clustering Node単位の一括計算を利用していない。

### 4.3 新しい二段階処理

#### Phase 1：全Clusterの軽量Screening

1. SQLiteから必要列を一度だけ読み、化合物、Transform、Coreを内部整数IDへ変換する。
2. 同一化合物ペアに由来するMMP instanceを識別し、Cluster所属判定をペア単位で一度だけ行う。
3. Cluster単位ではなくClustering Node単位で処理する。
4. 非重複Clusteringでは、ペア両端のCluster label一致からLocal Clusterを一括決定する。
5. 重複Clusteringでは、両化合物の所属Cluster集合の積集合を使用し、必要なLocal割当だけを生成する。
6. Local MMP instance数、ユニークPair数、Transform数、Core数、適格Transform数を算出する。
7. Local MMPが空、または`min_local_pairs`を満たすTransformがない場合は、Screening行だけを残して詳細処理へ進めない。

#### Phase 2：適格候補の詳細計算

Phase 1で`min_local_pairs`を満たした`Cluster × Transform`についてのみ、次を計算する。

- Local summary
- Global summaryとの比較
- Outside summary
- shared Exact Core
- Local minus Global／Outside
- IQR、MAD、分散縮小
- Transform方向反転
- Cluster固有効果候補

Global summaryは全処理を通じて一度だけ計算する。Outsideは適格Transformに限定し、Cluster内にMMPが存在しない場合には計算しない。Screeningで使用する件数は既存`local_summary`から再利用する。

### 4.4 出力と人間操作

既存の主要ファイル名とコマンドを維持する。

- `global_transform_summary.csv`
- `cluster_screening.csv`
- `cluster_transform_summary.csv`
- `clustering_transform_summary.csv`
- `candidate_variance_collapse.csv`
- `candidate_cluster_specific.csv`
- `candidate_direction_reversal.csv`
- Markdown／HTMLレポート

全Clusterは`cluster_screening.csv`に残す。低supportの組合せは適格性と件数を残すが、解釈に耐えないOutside／Core詳細を全件先行計算しない。人間が既存の`--cluster-id`または`--transform-id`を明示した場合は、対象を限定した詳細確認ができる。新しい必須引数や前処理は追加しない。

### 4.5 性能目標

実測前の目安として、次を期待する。

| 条件 | 想定高速化 |
|---|---:|
| 空または低supportのClusterが多い | 30～100倍以上 |
| 一般的な全Clustering survey | 10～50倍 |
| 重複Clusterが多く、多数が適格 | 2～10倍 |

これは保証値ではない。SQLite読込とGlobal summaryには最低1回分の時間が必要である。並列化は大きなDataFrameを複製してメモリを悪化させ得るため、まず計算量を削減し、必要な場合だけClustering Node単位の限定並列化を検討する。

### 4.6 科学的同等性と合格条件

同じDatabase、同じCluster集合、同じ閾値を使用し、旧実装と新実装を比較する。

- Global Transformの件数、中央値、IQR、MADが一致する。
- 適格`Cluster × Transform`のLocal／Outside件数、中央値、IQR、Core数が一致する。
- variance collapse、Cluster specific、direction reversal候補が同じ入力条件で一致する。
- 重複Clusteringを非重複と誤認しない。
- Run inventory検証がPASSし、元RunとDatabaseの内容・mtimeを変更しない。
- 全surveyの経過時間と最大メモリを記録する。
- 出力順序はNode ID、Cluster ID、Transform IDで決定論的に固定する。

## 5. A005 Artifact重複の是正

### 5.1 原因

A005はCluster surveyで成功した各ClusterのOOF予測を、すべてArtifact type `oof_predictions`としてExecution Eventへ追加する。RuntimeはArtifact typeを一意キーとして使用するため、成功Clusterが2個以上あるとcommit前に重複エラーとなる。

これはRuntimeの一意性検査の問題ではなく、A005が一つのEvent内へ同じ論理Artifactを複数登録していることが原因である。Global／Localでtypeを分けても、複数Local間の重複は解消しない。

### 5.2 変更内容

- Global modelは従来どおり`global_oof_predictions.csv`を一つ生成する。
- Cluster survey／within-clusterは、OOF行に`cluster_id`を付加して単一の`cluster_oof_predictions.csv`へ統合する。
- Execution Eventでは、役割にかかわらず`oof_predictions` Artifactを最大一つだけ宣言する。
- Cluster別`model_comparison.csv`と`operator_summary_collection`は維持する。
- Runtimeは宣言されたOOF Artifactをchecksum検証し、Node outputへ一度だけ昇格する。
- RuntimeのArtifact type一意性検査は緩和しない。

`oof_predictions_C000001`のような動的type、重複typeの後勝ち上書き、Runtimeによる暗黙の配列化は採用しない。

### 5.3 計算仕様への影響

次は変更しない。

- 固定Description panel
- outer fold
- fold内特徴量選択
- Ridge、PLS、条件付きSpline-Ridge
- RMSE、MAE、R2
- Global OOFとのLocal比較
- `min_local_samples`

変更するのはOOF予測の保存形式とArtifact宣言だけである。

### 5.4 合格条件

- Global、within-cluster、Cluster surveyの各roleでArtifact typeが重複しない。
- 2個以上の成功Clusterを含むsurveyがRuntime commitまで成功する。
- 統合OOF CSVに`cluster_id`があり、Clusterごとの行数と予測値が統合前ファイルと一致する。
- Runtime昇格後もGlobal OOFを後続Local A005が参照できる。
- Cluster Result Cardと`model_comparison.csv`の参照が実在する。

## 6. 修正対象

### 6.1 Skill

- `cs-conductor-orchestrator`: Packet実行コマンドの明記
- `cs-conductor-runtime`: 公開CLI契約の説明同期
- `cs-analysis-interpret-mmp`: 全Clustering survey集計の二段階化
- `cs-analysis-multidescription-feature-model`: OOF予測の単一Artifact化

### 6.2 CONDUCTOR_modules

- `tools/runtime_controller.py`: 公開Packet aliasとOOF Artifact昇格
- `tools/templates/multidescription_model_run.py`: A005本体との同期
- 関連Unit／integration test

### 6.3 Subagent

変更しない。Executorは既に正式な`--packet`コマンドを明記しており、Interpreterおよび他Subagentの責務にも変更はない。

## 7. 実装順序

1. Packet aliasとOrchestrator定型コマンドを実装し、parser／冪等再接続を検証する。
2. A005の単一OOF Artifact化をSkillとtemplateへ同時適用する。
3. RuntimeのOOF Artifact昇格をtypeベースへ変更し、複数Cluster surveyのcommit試験を追加する。
4. MMPの重複計算除去と空Local早期終了を先に実装する。
5. MMP投影をClustering Node単位へ変更し、非重複／重複Clusteringを分離して最適化する。
6. 旧実装との科学的同等性試験、性能測定、read-only inventory検証を実施する。
7. Skill文書、Catalog説明、検証文書を実装結果に合わせて更新する。

## 8. リスクと抑制策

| リスク | 抑制策 |
|---|---|
| 高速化で低support情報を誤って捨てる | 全ClusterのScreeningを保持し、適格判定前のLocal件数を記録する。明示指定による限定確認を維持する |
| 重複ClusteringのPairを一所属と誤認する | 非重複label経路と、所属集合の積集合を使う重複経路を分けてテストする |
| 集計順序変更による候補順位の変動 | exact median／quantileを維持し、決定論的sort keyを固定する |
| A005統合CSVでCluster由来を失う | 全行へcanonical `cluster_id`を必須付与する |
| Packet aliasが内部契約を曖昧にする | aliasは公開parserだけに限定し、文書と内部Workerは`--packet`に統一する |
| 大規模MMPを安易に並列化してメモリ不足になる | アルゴリズム改善を先行し、並列化は実測後の任意追加とする |

## 9. 完了条件

- 3件の回帰試験が追加され、既存Runtime／Skill testとともにPASSする。
- MMP Database、A014、DAG schema、State正本に変更がない。
- 既存MMP Databaseを再構築せず、新しいMMP Interpretationを実行できる。
- A005 Cluster surveyが複数成功Clusterを含んでもcommitできる。
- Main Agentが`--packet`／`--packet-path`のどちらを使用しても同一公開処理へ入り、正本表記は`--packet`として維持される。
- 人間向け操作に新しい必須手順を追加しない。
