# CONDUCTOR 0.2.1 R1-3 実機チェックポイント用プロンプト

このプロンプトは、R1-1〜R1-3とR1.2のcensus/L1b identity修正をUbuntu本番機へ反映した後、
P03 workloadより先に全Lensの族サイズ・必要permutation・資源見積りを一括取得するために使う。
全Lensがadmissibleな場合だけP03 workloadへ進む。Phase 4以降には進まない。

旧期待値L5=52、L1b=84、L2a=117、L2b=75はexact acceptance valueではない。
これらとの差だけを理由に停止しない。L7=86を含め、旧値は比較用の履歴値としてのみ扱う。

## 再利用方針

- R1-1〜R1-3はDescriptionの`calculation_version`とcalculation signatureを変更していない。このため、同一Program、同一compound ID、同一canonical SMILES、同一`calculation_version`、同一calculation signatureを満たすDescription Database recordはcache hitとして再利用できる。Gobbi Pharm2DでSVDを使う場合はdataset signatureも一致させる。
- L5の`support_n`再発防止はLens実装、evidence、unit fixture、文書だけの変更であり、Descriptionの`calculation_version`、calculation signature、Database schema、既存recordを変更しない。これを理由にDescription Databaseを再計算またはinvalid化しない。
- M-17のConformer生成失敗SKIP対応もDescriptionの`calculation_version`、calculation signature、Database schemaを変更しない。既存の成功recordはそのまま再利用し、従来未登録だったConformer生成失敗だけを次回miss計算時に`outcome_status="skipped"`として登録する。全Description Databaseの再構築は不要である。
- 修正前Runの`runtime.sqlite`、Execution Request、Pipeline plan、P01/P02のrun-scoped成果物、検定結果、Findingは直接流用しない。修正前Runをresumeしない。
- 新しいRun IDとRun rootを使い、P01は既存Description Databaseからrun-scoped特徴量成果物を作り直す。互換recordは再計算せず、真のmissだけを計算する。P02とP03は新規計算する。
- Description Databaseを削除、移動、Archive、再構築しない。Program名を変更してcacheを回避しない。

## 置換項目

次の値を実機の絶対パスまたは実値へ置き換えてから、後段のコードブロック全体をClaude Codeへ渡す。

| 項目 | 内容 |
|---|---|
| `<PROJECT_ROOT>` | Git pull後のCONDUCTOR project root |
| `<INPUT_CSV>` | 961化合物の本番入力CSV |
| `<PROGRAM_NAME>` | 修正前Runと同じProgram名 |
| `<ENDPOINT_REGISTRY>` | Endpoint registry JSON |
| `<ENDPOINT_ID>` | 対象Endpoint ID |
| `<CONFIG_PATH>` | R1版`defaults.yaml`を反映済みの完全なresolved config |
| `<ID_COLUMN>` | compound ID列名 |
| `<SMILES_COLUMN>` | SMILES列名 |
| `<OLD_RUN_ROOT>` | 修正前に中断したRun root。比較のためread-onlyでのみ参照する |
| `<RUN_ROOT>` | 存在しない新規Run root |
| `<WORKERS>` | `64` |
| `<MEMORY_MB>` | Runへ割り当てるメモリ上限の記録値 |

`<CONFIG_PATH>`には少なくとも、R1の`runtime.budgets`、`runtime.progress`、6 Lensの`runtime.units_per_second`が解決済み値として含まれていなければならない。統計閾値やpermutation数をcheckpoint用に下げてはならない。

## Claude Codeへ渡すプロンプト

```text
CONDUCTOR 0.2.1 R1-3の本番データチェックポイントを実行してください。

Project root: <PROJECT_ROOT>
入力CSV: <INPUT_CSV>
Program名: <PROGRAM_NAME>
Endpoint registry: <ENDPOINT_REGISTRY>
Endpoint ID: <ENDPOINT_ID>
設定: <CONFIG_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
修正前Run root: <OLD_RUN_ROOT>
新規Run root: <RUN_ROOT>
workers: <WORKERS>
memory_mb: <MEMORY_MB>

目的は、R1-1〜R1-3とR1.2のコードでPhase 1〜2を実行した後、全P03 Lensのwork censusを
workload前に一括取得することです。全Lensがadmissibleな場合だけPhase 3 workloadを実行し、
最大族サイズとFinding件数を測定してください。Phase 4〜6には進まないでください。

最初の確認は次の最小項目だけに限定してください。
1. Git pull後のworking treeとHEADを記録し、R1-1〜R1-3およびM-17の実装ファイル、L5のfinite support契約と部分NaN回帰fixture `test_l5_support_uses_feature_finite_observations_with_overlapping_contexts`、Conformer失敗のnegative-cache回帰fixture `test_conformer_failure_is_negative_cached_and_excluded_from_distance` が存在すること。開発側で全test成功済みなので、実機でtest suite全体を再実行しないこと。
2. `<CONFIG_PATH>`がschema_version 0.2.1で、次を解決済み値として含むこと。
   - runtime.budgets: node_wall_seconds=3600、run_wall_seconds=21600、peak_memory_bytes=68719476736、k_min=10、family_size=500（旧estimator fallbackのみ）
   - runtime.progress: min_seconds=5、min_fraction=0.01、stall_multiplier=20、stall_min_seconds=60、stall_max_seconds=600
   - runtime.units_per_second: l5=3650000、l1b=29800000、l2a=7230000、l4=31700、l2b=50858、l7=6004
   - lenses.l4.candidate_cap=100
3. `<PROJECT_ROOT>/data/description_database/<PROGRAM_NAME>/`が存在し、同じProgramのwriter/coordinator/workerが動作していないこと。
4. `<RUN_ROOT>`が存在しないこと。`<OLD_RUN_ROOT>`は変更しないこと。
5. 入力CSV、Endpoint registry、configのhashと、CPU affinityがworkers以上であること。

仕様書全体の再読、全Skill契約の再抽出、request fixture探索、Local LLM probe、Phase 4〜6契約の調査は行わないでください。R1-3のcheckpointではLocal LLMを呼びません。上記5項目に阻害要因がなければ、追加の確認待ちにせず開始してください。

修正前Runはresumeしないでください。新しいRun IDと`<RUN_ROOT>`を作成し、版管理された`CONDUCTOR_modules/pipeline/production_pipeline.v0.2.1.json`のP01〜P03に属する10 Nodeだけを、定義、依存関係、launch pathを変更せず機械的に使用してください。P04〜P06のNodeはこのcheckpoint planへ含めないでください。Execution RequestとPipeline planは新Run用に生成し、`cs-runtime`のsingle-writer coordinatorから実行してください。各Skillのrun.py/launch.pyをRuntime外から個別実行しないでください。

現行`cs-production-run`は「Database path不存在からPhase 1〜6を実行する3.4A専用」です。既存Databaseを使う今回のcheckpointには起動しないでください。checkpoint用のrequestとplanは`<RUN_ROOT>/control/`以下だけへ生成し、このためにrepositoryのsource、canonical blueprint、旧Runを変更しないでください。

Phase 1では既存Description Databaseを使用してください。同一Program、同一compound ID、同一canonical SMILES、同一calculation_version、同一calculation signatureのrecordをcache hitとし、Gobbi Pharm2DでSVDを使う場合はdataset signatureも一致条件に含めてください。互換recordを再計算しないでください。真のmissだけを計算・登録し、同一ID・異canonical SMILESではfail-fastしてください。Database、旧Run、旧成果物を削除、移動、invalid化しないでください。修正前RunのP01/P02成果物を新Runへ直接コピーまたは参照せず、新RunのP01成果物はDatabase recordから生成し、P02とP03は新規計算してください。

3D DescriptionでRDKit Conformer生成が決定論的に失敗した化合物は、Node失敗にしないでください。入力行と`description_error`を保持し、Description Databaseへ`outcome_status="skipped"`のactive recordとして登録し、auditへ`outcome_reason="conformer_generation_failed"`を記録してください。次回以降は同じ互換条件でcache hitとし、再計算しないでください。距離artifactでは全入力compound IDとの整列を保持しながら、その化合物の行列要素を非finiteにし、`eligible_compound_ids`から除外してください。Context、L1b、L4、L5は各Description空間のeligible化合物だけで解析し、他のDescription空間および後続Nodeは継続してください。未知の実装エラー、resource error、schema errorはterminal SKIPとして登録せず、従来どおり失敗または再試行可能missとして扱ってください。全化合物が不適格でfeature schemaを確定できないDescriptionは黙って成功させず、該当Descriptionと理由を報告して停止してください。

L5では`support_n`を特徴量とEndpointがともにfiniteで相関へ実際に使用した一意な化合物数として扱ってください。focal contextとaxis内補集合が非重複、`shared_n=0`、`support_n=n_a+n_b>=1`であることを置換loop開始前に検証してください。生のContext共通所属数を`n_a/n_b`から減算しないでください。不変条件違反時は長時間の置換loopへ入らず、入力と該当axis/context/featureを報告して停止してください。

Description Databaseへの最初の書込み可能性が生じる前に、同じProgramのwriterがいないことを再確認し、SQLite backup APIで復旧可能なbackupを1回作成してください。WAL/SHMをファイルコピーで個別に扱わないでください。

P03の全Lensがreadyになったら、各workloadを一件も起動する前にRuntimeのbatch work censusを完了してください。
`<RUN_ROOT>/work_census.json`へ全Lensのestimate、最大family key、family key別件数、configured/required final permutations、
peak memory、estimated seconds、guard理由を保存してください。一件のestimate errorまたはguard違反があっても、残りLensの
estimateを完了してから一度だけ停止してください。その場合、admissible Lensのworkloadも開始しないでください。

L4以外は`family_size ≤ report_q_max × (B+1) × k_min`をLensごとのBで評価してください。
peak_memory_bytes>68719476736、estimated_seconds>3600、または全Lens合計を含むRun予算超過もblockerです。
L4はfamily gateを免除しますが、manifestへfamily_gate="exempt_parametric"を記録してください。
旧期待値との差はwarningでありblockerではありません。閾値、permutation数、candidate cap、族定義をRun中に変更して通過させないでください。

censusにblockerがなければP03を実行し、P04へ進まず停止してください。その場合は各`*_tests.csv`について
family_key別件数を集計し、各`findings.jsonl`の行数をFinding件数として数えてください。
censusにblockerがあればtests/findingsが存在しないLensへ件数を要求せず、census値を次の表で報告してください。

| Lens | 最大family key | 最大族 | configured B | required B | 推定時間 | guard | Finding件数 |
|---|---|---:|---:|---:|---:|---|---:|
| L5 | census値 | census値 | census値 | census値 | census値 | admissible/blocked | 実行時のみ |
| L1b | census値 | census値 | census値 | census値 | census値 | admissible/blocked | 実行時のみ |
| L2a | census値 | census値 | census値 | census値 | census値 | admissible/blocked | 実行時のみ |
| L2b | census値 | census値 | census値 | census値 | census値 | admissible/blocked | 実行時のみ |
| L7 | census値 | census値 | census値 | census値 | census値 | admissible/blocked | 実行時のみ |

L4はparametric family gateの対象外なので、最大族サイズの期待値比較へ混ぜず、candidate数、Finding件数、family_gate、candidate_cap=100を別行で報告してください。

併せて次を報告してください。
- 新Run ID、HEAD commit、input/config/implementation hash
- P01〜P03のNode状態と所要時間
- Description別cache hit/miss/registered_count/registered_ok_count/registered_skip_count/registration_skipped_count/failed件数とcache_outcome_counts
- work_estimate、actual_wall_seconds、estimate_actual_ratio、progress_granularity、stalled warning
- 最大族サイズを生じたfamily_keyと件数
- 旧Runを変更していないこと
- Description Databaseの絶対パスと新Run主要成果物の絶対パス

Conformer生成失敗として正しく登録・除外されたterminal SKIPだけを理由にRunを停止しないでください。
旧期待族サイズとの差も停止理由にしないでください。未知のエラー、schema不整合、全化合物不適格、
統計・memory・時間予算超過は`work_census.json`に全件をまとめ、入力差、eligibility差、実装差、設計予算差へ分類してください。
その場でfamilyを追加分割、閾値変更、B変更、コード修正して通過させないでください。
```

## 終了条件

このcheckpointは次のいずれかで正常に目的を達成する。

1. censusにblockerがある場合: 全P03 Lensのcensusと全blockerを一括報告し、P03 workloadを開始せず終了する。
2. 全Lensがadmissibleな場合: P03を完了し、最大族サイズとFinding件数を報告して終了する。

一件ずつ問題を露出させる旧運用へ戻らない。結果を設計・実装担当へ返し、L5 M-5または次stageの判断を待つ。
