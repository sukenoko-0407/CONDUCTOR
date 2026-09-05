# CONDUCTOR 0.1.10 実装計画書（承認内容反映版・実装記録）

## 1. 実装状態

本計画には事前協議で承認された設計判断を反映している。2026-09-04に人間から明示的な実装開始指示を受け、Phase 0のbaseline確認後、初回0.1.10実装を行った。2026-09-06に承認された追補修正も[`CONDUCTOR_0.1.10_patch_plan.md`](CONDUCTOR_0.1.10_patch_plan.md)に従って実装・検証を完了した。

初回実装前baselineは37 tests PASSであり、2026-09-04時点の初回実装は53 tests／6 subtestsとpackage verificationで検証した。追補修正後はA003、calculation version、Schema、C012境界、A009 Template／監査、Prompt contract、Description Database partial-hit再構成を含む60 tests PASS、package verification PASS、generated Catalog check PASSで検証した。

> **Version境界（2026-09-06）:** 本書のMMP項目は0.1.10で完了したReport baselineの実装記録である。2 Mode化、Global Top 1、Transformation evidence、1/2-cut、情報抽出、Interactive visualization等の追加改修は0.1.10追補では実装せず、0.1.11へ移管する。従来0.1.11で検討していた非MMP項目は0.1.12へ繰り越す。

## 2. 実装原則

- 科学計算KernelとRuntime orchestrationの責務を分離する。
- Description cacheはRuntimeが一元管理し、18 Skillへ別々のcacheロジックを複製しない。
- Run ArtifactはDatabaseに依存せず、完了後も自己完結して読めるようにする。
- C012のparameter探索は決定的で、同じ入力・seed・gridから同じ選択結果を得る。
- HTMLは要約、CSV／JSONは完全結果という役割分担を守る。
- 各Phaseでtestを通し、後段consumerを壊したまま次へ進まない。
- 0.1.9の完了Runを変更しない。

## 3. 変更対象の概略

主な変更対象は次である。

- `CONDUCTOR_modules/tools/runtime_controller.py`
- `CONDUCTOR_modules/catalog/analysis_profile.json`
- `CONDUCTOR_modules/schemas/`
- `CONDUCTOR_modules/tools/templates/series_batch_runner.py`
- `CONDUCTOR_modules/tools/templates/standard_summary_template.html`
- `CONDUCTOR_modules/tools/templates/series_detail_template.html`
- `.claude/skills/cs-analysis-*/`のcanonical copy
- `.claude/skills/cs-compute-clustering-meta-overlap/`
- `.claude/skills/cs-conductor-runtime/`
- `.claude/skills/cs-conductor-orchestrator/`
- A008 MMP renderer／template
- `CONDUCTOR_modules/tests/test_0110_contracts.py`と`test_0110_description_database.py`
- Version、catalog、README、user guide、quick reference

## 4. Phase 0: 承認内容の固定とbaseline

### 作業

1. 事前協議で確定した仕様概要書9節を含め、文書全体の実装開始承認を得る。
2. 承認時点の仕様書hashまたはGit revisionをbaseline記録に残す。
3. 現行branchのpackage verificationと全testを実行し、baselineを記録する。
4. 0.1.9の既存report fixtureまたは最小Run fixtureを保存し、意図しない退行を比較できるようにする。

### 完了条件

- 承認済み仕様に未決定markerが残っていない。
- 実装前baselineのtest結果が記録されている。

## 5. Phase 1: Versionと契約骨格

### 作業

1. Runtime、Skill capability、catalog、profileのVersionを0.1.10へ揃える。
2. 既存の`project`を正式な`program_name`として扱い、重複するCLI引数は追加しない。
3. `project`／`program_name`を一つの安全なpath componentとして検証し、Run内で変更不可にする。
4. control state、Execution Request、Description manifestへDatabase関連metadataを追加できるようschemaを更新する。
5. profileへ次を追加する。
   - Series member support分類とStandard／Supported Core rescue条件
   - Series parameter search grid
   - 自動進行unit上限
   - A003 correlation threshold 0.60
   - A005実施最小件数
6. Description capabilityへ計算ロジック固有の`calculation_version`を追加する。
7. D016、D019、D020の高コスト承認分岐、CLI、state、profile、promptを撤去する。
8. package verifierを0.1.10の契約へ更新する。

### Test

- `project`／`program_name`未指定、空白、path traversal文字を拒否する。
- 正常な日本語またはASCII名の扱いを仕様どおり検証する。
- Run開始後のProgram名変更とProgram間cache参照を拒否する。
- 高コストDescriptionが承認待ちを発生させず通常計画される。
- Version不一致SkillをRuntimeが拒否する。
- schema validationが旧／新フィールドを意図どおり扱う。

### 完了条件

- 新しいRoundを0.1.10契約で準備・承認できる。
- まだcache処理を有効にしない状態でも、既存Node計画が生成できる。

## 6. Phase 2: Description Database engine

### 6.1 Database schema

Runtime共通helperとして、次の責務を持つmoduleまたは関数群を追加する。

- Database path解決
- schema作成／migration拒否
- configuration signature生成
- compound ID batch lookup
- reusable status判定
- transactional upsert
- cache audit event記録
- Database integrity check
- recordのread-only inspectionと監査付きinvalidation

SQLiteの想定tableは次のとおりである。

```text
metadata
- schema_version
- capability_id
- skill_name
- created_at
- updated_at

feature_schemas
- schema_signature (PK)
- skill_version
- calculation_version
- configuration_signature
- feature_columns_json
- value_semantics
- natural_metric
- created_at

records
- skill_version
- calculation_version
- configuration_signature
- compound_id
- original_input_smiles
- original_input_smiles_sha256
- calculation_smiles
- calculation_smiles_sha256
- schema_signature
- common_fields_json
- vector_json_or_blob
- record_status
- computed_at
- source_run_id / round_id / node_id
- invalidated_at / invalidated_by / invalidation_reason
- PRIMARY KEY (...)
```

### 6.2 実行前cache plan

Description NodeのExecution Request作成前に次を行う。

1. 元DatasetからID、SMILES、入力順を取得する。
2. calculation version、parameter、環境lockfile、モデル識別子からconfiguration signatureを作る。Skill versionはprovenanceとして記録するが、再利用判定には使わない。
3. 入力SMILESをstereochemistryを保持したcanonical SMILESへ変換する。canonicalizeできない場合はraw SMILESを使う。元SMILESはprovenanceとして保持する。
4. Databaseをbatch lookupする。
5. 同一Program内の同一compound IDに異なる構造があれば、cache missにはせずfail-fastにする。
6. hit／miss／mismatchを分類する。
7. missがある場合だけ、実際の計算入力をcanonical SMILESとしたsubset CSVをscratch内へ作る。
8. Execution Requestのdataset Artifactをsubsetへ差し替え、cache planをrequestへ記録する。

cache planには元Dataset hash、元ID順、hit record識別子、miss ID、Database pathを含める。ただし巨大なvector自体はrequest JSONへ埋め込まない。

### 6.3 実行後merge

Skill成功後、final directoryへpromotionする前に次を行う。

1. 新規payloadとmanifestを検証する。
2. hit payloadをDatabaseから再読込する。
3. feature schema、semantics、metricを照合する。
4. hitとmissを元入力順にmergeする。
5. row重複、欠落、非数値feature、無限値を検査する。
6. 全件payload、manifest、warnings、execution eventのhashを再生成する。
7. Run固有Artifact契約を検証する。
8. 新規の再利用可能行をDatabaseへtransactionalに登録する。

miss 0件の場合は、現在のNode identityを持つmanifestとexecution eventをRuntimeがDatabaseから再構成し、科学計算processを起動しない。

バッチ依存設定ではchemical dataset signatureが完全一致した場合だけ全体を再利用し、部分cacheは行わない。

### 6.4 Database管理操作

1. Program、Description、compound IDを指定してrecordとhashをread-only表示する管理commandを追加する。
2. 人間がreasonを必須指定した場合だけrecordをinvalidateできる管理commandを追加する。
3. invalidateは物理削除や上書きではなく、再利用不可statusへの変更とする。
4. 操作者、理由、日時、旧record hashをauditへ追記する。
5. 次回Runではinvalidated recordをmissとして再計算する。

### 6.5 並行性と障害回復

- SQLite transactionとbusy timeoutを使う。
- 一つのNode内ではDatabase commitを一度にまとめる。
- 同じrecordが競合登録された場合は、同一payloadなら成功、異なるpayloadなら整合性errorとする。
- Node失敗時にscratchだけが残り、Databaseへpartial rowが残らないことをtestする。
- Database破損時はsilent miss扱いにせず、明示的に停止してrepairを求める。

### Test matrix

1. cold cache: 全件miss
2. warm cache: 全件hit、Kernel未起動
3. partial cache: missだけKernel入力
4. reportだけを変更したSkill version更新ではcache hitを維持
5. calculation version mismatchではcache miss
6. configuration mismatch
7. 同一ID／同一canonical構造だが異なるSMILES表記
8. 同一ID／異なるcanonical構造のfail-fast
9. feature schema mismatch
10. invalid SMILESの決定的再利用
11. transient calculation errorの非登録
12. 部分欠損のSkill別policy
13. 2 Run同時更新
14. hit＋miss再結合後の元入力順
15. CSV／Parquet payload
16. D001のbool共通列を含む再構成
17. D016、D019、D020のcustom runner出力
18. inspect／invalidateとaudit履歴
19. invalidated recordの次回再計算
20. バッチ依存設定のdataset完全一致／不一致

### 完了条件

- 18 Descriptionすべてが同一Runtime cache契約で動作する。
- warm cacheで特徴量Kernelが起動されないことをtestで確認できる。
- cache利用後も既存Vector Clusteringが変更なしで全件payloadを読める。

## 7. Phase 3: C012 Series parameter search

### 7.1 計算ロジック分割

現行C012を次の純粋処理へ分ける。

1. Cluster選抜mask作成
2. overlap graph作成
3. Leiden partition
4. community union作成
5. Cross-representation Core／Core／Fringe分類
6. 3 member class、Supported Core、Unionの統計
7. Series採否判定
8. fallback展開
9. final analysis unit集計
10. configuration比較と選択

同一入力に対する各configuration評価を副作用なしの関数にし、unit test可能にする。

### 7.2 Grid評価

1. A001/A002の全Cluster統計を読み、各`min_ff_evaluate`で選抜maskを再生成する。
2. 各resolutionでLeidenを実行する。
3. Candidate Series内の化合物をCross-representation Core、Core、Fringeへ排他的に分類する。
4. `Union FF >= 0.50`をStandard acceptanceとする。
5. Standard不通過でも、`Union FF >= 0.30`、`Supported Core Endpoint-valid N >= min_ff_evaluate`、`Supported Core FF >= 0.50`をすべて満たす場合はSupported Core rescueとする。
6. Standardとrescueの両方を満たす場合はStandardを優先し、採用時はいずれもFringeを含むUnion全体をanalysis unitとする。
7. まず`min_ff_evaluate=10`でresolutionを小さい順に評価し、最初の24件以下をchosen configurationとする。
8. resolution変更だけで24件以下にならない場合に、全30 configurationを評価する。
9. 全gridの数値をRuntime内部の`series_parameter_search.json`へ保持する。
10. Runtime応答を受けたAgentが、行を`min_ff_evaluate`、列をresolution、各セルを`final unit数 / Cluster coverage / Compound coverage / fallback数`とするMarkdown TableをSession内に表示し、人間の選択を待つ。HTML reportや図は生成しない。
11. 各configurationについて、Default選抜Clusterに対するCluster coverageと、Default選抜Cluster和集合に対するCompound coverageを計算する。
12. 人間判断が必要な場合、探索段階ではcanonical Series Artifactを確定せず、候補summaryだけをRuntime内部stateへcommitする。
13. 人間が選択した条件でC012を再実行し、その条件だけのmembershipとcanonical Artifactを生成する。

### 7.3 Canonical Artifact

chosen configurationから既存Artifactを生成する。

- `series_registry.csv`
- `series_cluster_membership.csv`
- `compound_series_support.csv`
- `analysis_unit_membership.csv`
- `analysis_unit_registry.csv`
- `series_edges.csv`
- `series_summary.json`
- `selected_clusters_effective.csv`

`series_summary.json`には最終chosen condition、閾値、gate状態を記録する。全gridは解析結果Artifactに含めず、Runtime内部の途中判断stateとして`runtime/series_parameter_search.json`に保持する。

`compound_series_support.csv`にはsupport Cluster数、support representation数、sort済みrepresentation key一覧、member class、Endpoint-valid／Favorable flagを保存する。`series_registry.csv`と`series_summary.json`にはCross-representation Core、Core、Fringe、Supported Core、Unionのcompound count、Endpoint-valid N、Favorable N、FF、Supported Core coverage、`acceptance_mode`を保存する。`acceptance_mode`は`standard`、`supported_core_rescue`、`rejected`のいずれかとする。

### 7.4 Runtime gate

- gate判定はchosen C012 Artifactのlocal unit数を使う。
- approvalはC012 node IDとparameter／result signatureへ結び付ける。
- C012再計算、custom parameter採用、membership変化のいずれでもapprovalをresetする。
- resolution探索だけで24件以下にならないとき、Runtime応答へ全gridの数値を含め、AgentがSession内Tableとして提示できるようにする。
- 24件以下は自動進行、25件以上100件以下は人間承認、101件以上は選択不可とする。50件は目安であり停止条件にはしない。
- Session内Matrixから25～100件の条件を人間が明示選択した場合、その操作をparameter選択と超過承認の両方として記録し、同一C012結果について再確認しない。

### Test

- 同じseedとgridで完全に同じ結果になる。
- resolution上昇時にunit数が非単調なfixtureでも最終unit数で正しく選ぶ。
- Cross-representation Core、Core、Fringeが排他的かつ網羅的に分類される。
- 3 member class、Supported Core、UnionのFFがEndpoint-valid Nを分母として正しく計算される。
- Union FF 0.50、Union FF 0.30、Supported Core FF 0.50、Supported Core Nの各境界で採否が正しい。
- Standardとrescueを同時に満たす場合はStandardが優先される。
- rescue採用でもFringeを含むUnion全体がanalysis unitになる。
- `min_ff_evaluate`各段階で選抜Clusterが正しく変わる。
- `min_ff_evaluate=10`のresolution探索で最初の24件以下が自動選択される。
- resolution探索で24件以下にならない場合だけ全gridがSession提示対象になる。
- Cluster coverageとCompound coverageがDefault条件を100%として正しく計算される。
- 25～100件でhuman gate、101件以上で絶対停止になる。
- 25～100件のMatrix選択が一回の操作でparameter選択と超過承認を完了する。
- 再計算後に旧approvalが無効になる。

### 完了条件

- すべてのgrid値とchosen configurationをRuntime内部JSONから再現できる。
- A009がchosen configurationのeffective selectionを表示できる。

## 8. Phase 4: A003、A005、A006、A007のreport-ready出力

### A003

1. 対象を固定panel `D001、D012、D015、D016、D019`へ拡張する。
2. D001、D012、D019は全数値特徴量、D015はacid/base・元素組成・芳香族性・ring count・polarizability、D016はgeometry・部分表面積の厳選特徴量を使用する。
3. 既定correlation thresholdを0.40から0.60へ変更し、threshold値をsummary JSONへ保存する。
4. 出力へDescription IDと内部一意feature keyを追加する。
5. analysis unitごとの上位3featureを決定的にrankする。
6. 対象analysis unit内の点だけを使う簡潔なscatter plotとindex JSONを生成し、Global比較overlayは加えない。
7. 正式通過判定を`criteria_pass = correlation_hit`へ統一し、旧`strict_hit`を残さない。
8. median shift関連の計算、判定、出力、説明、near-miss sort要素を削除する。
9. `sample_count`を各featureのfiniteなEndpoint／feature pair数とし、相関とp値を計算したNへ一致させる。

### A005

1. 実施条件を`Model N >= 30`に統一する。
2. `Model N`を、Endpointが有効で、DescriptionとのID結合に成功し、少なくとも一つのmodel featureを利用できる所属化合物数として共通helperで算出する。
3. 部分欠損featureはtraining fold内でimputeし、それだけを理由に化合物をModel Nから除外しない。
4. `Member N`、`Model N`、条件値をsummary JSONへ保存する。
5. `not_applicable` reasonをmachine-readableに統一する。
6. 各local unitについて、Localを左、同一化合物に対するGlobalを右にしたOOF予測値対実測値の1×2散布図とJSON indexを生成する。
7. LocalとGlobalが同じ候補Description panelから始まり、training-fold-onlyの列除外とF-testを独立fitすることをmetadataと説明文へ記録する。

### A006

1. D002がECFP4（Morgan radius 2、2048 bit）であることを固定し、Tanimoto similarity thresholdを0.75へ変更する。
2. similarity、Endpoint delta、support、direction thresholdをsummaryへ保存する。
3. `boundary_favorable_count`を結果へ保存し、HTMLは`Favorable件数 / Boundary cliff件数`で表示する。
4. report rendererが内部の`strict_boundary_hit`名を人間向けに出さず、具体値へ展開できるようにする。
5. SALI単独の絶対cutoffがないことを表示用metadataへ明示する。

### A007

1. 描画対象上位5件をsupport順に選ぶ。
2. SMILESとSMARTSを適切にparseして2D画像を生成する。
3. 画像index JSONをArtifactとして登録する。
4. 描画不能行もreport全体を失敗させず、行単位reasonを残す。

### Test

- A003 0.59／0.60境界
- A005 Model N=29／30境界、およびMember NとModel Nが異なるcase
- A006各threshold境界
- A007 SMILES、SMARTS、invalid structure描画
- 全analysis unitで同じ上位3feature選択が再現されること

## 9. Phase 5: A009 Standard Summary再設計

### 作業

1. templateを仕様書4.2節の7 Sectionへ再構成し、見出しと説明文を日本語、ID・統計指標・化学用語を英語表記とする。
2. Report scope、Execution status、Full tables and limitationsを削除する。
3. Executive summaryをmetric cardで表示し、各itemの意味だけを折り畳みにする。列説明は置かない。
4. Endpoint histogramの重複stats表示を一つにする。
5. Histogram直後に、縦軸Endpoint、横軸Global／採用Series／fallback Clusterの横長Boxplotを追加する。
6. HistogramとBoxplotを本文幅より小さく中央配置する。BoxplotはGlobalを灰、Seriesを青、fallback Clusterを橙とし、図全体の横幅と高さをHTML表示幅内に固定する。group数が多い場合は各Boxの幅とlabelを調整して一つの横長図へ収め、Favorable／Unfavorable cutoffを破線と凡例で示す。図から自明な重複見出しと判定式の折り畳みは置かない。
7. selected Cluster TableをID中心の固定列へ制限する。
8. 使用IDだけのDescription／Clustering凡例を折り畳み領域として自動生成する。構造クラスタリングではDescriptionを非該当として表示しない。
9. Series plotを削除し、Candidate Series mapは全Candidateを含むcompact Tableにする。Table本体をCandidate ID、source Cluster数、Union N／FF、Supported Core Endpoint-valid N／FF、acceptance mode、最終unitへ限定し、source Cluster ID一覧と3 member classのN／FFは折り畳む。
10. Section 4のmetric card直下に各itemの説明を折り畳みで置き、固定の重複見出しとfallback説明を削除する。
11. Standard analysis resultsはA003、A005、A006だけを表示し、折り畳み名を`解析内容`へ統一する。A003／A006の評価件数・near-miss定型文は表示せず、A005は評価可能な全analysis unitについて最良modelを1件ずつ表示する。
12. A004、A007、A008をStandard analysis resultsへ重複表示せず、A007の導線も置かない。
13. Agent向け文言と「strict／厳格基準」を削除する。
14. PCA／UMAP一覧はA004の図、analysis unit ID、個別レポートlinkだけを表示する。
15. 個別analysis unitレポート一覧には最終的な採用Seriesとfallback Clusterだけを載せ、候補Seriesや採用Seriesの構成元Clusterを重複掲載しない。

### 表示制約

- HTML Tableはrendererごとのallowlist列だけを許可する。
- Tableは初期状態で折り畳み、列headerから昇順／降順sortできるようにする。各Table直下に、列の意味を説明する折り畳み領域を置く。
- 長いID列は折り返す。
- CSVへのlinkは`詳細CSVリンク`と表記し、各Sectionの主要Table／画像の後に置く。
- 各Sectionは主要Table／画像を見出し直後に置き、説明文と判定条件はその下の折り畳みに置く。
- viewport外へTableがはみ出さないCSS testを用意する。
- 画像はoffline self-containedを維持する。

### Test

- Sectionの存在／不存在と順序をtemplate testで固定する。
- 見出しと説明文が日本語であり、ID・統計指標・化学用語の表記が維持される。
- 禁止文言`厳格基準`、`strict hit`、Agent向け選択文がないことを検査する。
- selected Cluster Tableに名称全文が混入せず、ID凡例が存在する。
- Series plot要素がなく、Candidate Series mapがある。
- Candidate Series mapが全Candidateを含み、Standard／Supported Core rescue／Rejectedを正しく区別し、source Cluster ID一覧と3 member classのN／FFを折り畳む。
- Endpoint図内の統計blockが一つだけである。
- Boxplotが横長で縦軸Endpointとなり、Global、Series、fallback ClusterのDOM／描画順と色が正しい。
- Boxplotに採用Seriesの構成元Clusterが重複表示されない。
- unit数が増えても図全体の幅と高さがHTML表示幅内に固定され、各Boxが狭くなって一図へ収まる。
- Favorable／Unfavorable cutoffの破線と凡例が両方表示される。
- Standard analysis resultsにA004、A007、A008が表示されない。
- PCA／UMAP一覧と個別report一覧に最終analysis unitだけが重複なく表示される。
- A003／A006の解析内容折り畳みに評価件数やnear-miss名が混入しない。
- 0件、1件、多数件、fallbackのみのfixtureでrenderできる。

## 10. Phase 6: A009 個別レポート再設計

### 作業

1. Source Cluster Table直下にDescription／Clustering説明を生成する。
2. Membership Support TableをHTMLから削除する。
3. stable seedを`global_seed + stable_hash(analysis_unit_id)`から作り、最大20化合物を抽出する。
4. RDKitで4×5の2D galleryを生成し、compound IDをcaptionにする。
5. A003 TableをFeature、Description ID、N、Pearson r、Spearman r、Max |r|の6列へ制限し、上位3散布図を表示する。
6. A005では`Member N`と`Model N`を表示し、`not_applicable`ではTableを出さず、両Nと一行reasonを表示する。評価可能なら基準未達でもunitごとの最良modelを表示し、Local／Global OOF予測比較図を置く。
7. A006のboundary pairがunit内1化合物とunit外1化合物の比較であること、Favorable方向率が全化合物の優劣を意味しないこと、ECFP4・0.75・Endpoint差条件を表示する。折り畳み名は`解析内容`とし、評価件数定型文は置かない。
8. A007上位構造画像galleryを表示し、captionはCluster IDに限定して件数captionを除く。構造由来Clusterは登録Keyだけ、vector由来ClusterだけSource Cluster membershipからMurcko／MCSを導出し、由来説明は折り畳まず表示する。
9. A008 report indexからTop 1 compoundとMMP linkを表示する。
10. Analysis unit Tableだけは初期表示し、各詳細CSVリンクは必ず該当Section末尾へ置く。
11. Series ReportではCross-representation Core、Core、FringeのN／FFを表示し、membershipとPCA／UMAPを`#c2185b`／`#ff7f0e`／`#7f7f7f`の固定3色と凡例で区別する。Global背景点は`#d9d9d9`とする。fallback Cluster ReportではSeries member classを流用しない。

### Test

- N<20、N=20、N>20のgallery件数
- 同じunit IDでsampleが再現すること
- 別unit IDでseedが衝突しないこと
- invalid SMILESがあっても残りを描画すること
- Membership Support Table、Correlation BH q、Strict hit、median_shift_global_iqr列がHTMLにないこと
- PCA／UMAPのanalysis unit所属点がorange `#ff7f0e`であること
- 構造由来Clusterが登録Key 1件だけを示し、vector由来ClusterがMurcko／MCSの両方を示すこと
- 構造クラスタリングのDescriptionがHTMLで非該当となり、ID説明が折り畳まれること
- A005でMember NとModel Nが正しく表示され、対象外時に空Tableがないこと
- Top 1 targetとlinkが正しいこと
- 個別レポート末尾に独立した`Full tables and limitations` Sectionがないこと
- Seriesの3 member class表示と凡例がcanonical membershipに一致し、fallback Clusterに誤適用されないこと

### A009共通Template契約と生成後監査

1. A009全体／個別Reportは承認済みTemplateから`Template.substitute()`で生成し、full HTMLの代替生成経路を作らない。
2. 必須placeholder、`template_id`、`template_version`、`template_sha256`を検証・記録する。
3. Template契約違反、未解決placeholder、local link切れ、directory traversal、canonical Artifactとの主要件数不一致ではA009を成功確定しない。
4. 監査結果をA009配下の`report_audit.json`へ保存し、失敗時はRuntime Full AuditもFAILとする。
5. 自動監査はlink確認と件数確認だけとし、LLM Vision、Screenshot比較、AIによる外観評価を使用しない。

### Template／監査Test

- 通常、0件、一部未実施、fallbackのみのfixtureが同じTemplate構造から生成される。
- placeholder欠落、重複、未解決値、Template metadata不一致を拒否する。
- link切れ、directory traversal、主要件数不一致でA009とFull AuditがFAILする。
- 正常Reportの`report_audit.json`がPASSとなる。

## 11. Phase 7: MMPレポートとA009導線（実装済baseline・追補対象外）

### 11.1 A008 index

1. target選択時に`analysis_unit_id`、target ID、Endpoint、pair count、report relative pathを記録する。
2. 同じtargetが複数unitで選ばれた場合、target reportを一つだけ生成し、indexには複数行を許可する。
3. RuntimeはA009へMMP完全pair CSVではなくindex Artifactだけを渡す。

### 11.2 4画像visual transformation

1. 個別MMP HTMLを、`TargetおよびNeighbor化合物の2D構造`、`基本情報Table`、`変換詳細Table`、`Exact Core別Visual transformations`の4 Sectionへ固定する。
2. 基本情報TableをMMP ID、Neighbor ID、Target ID、両Endpoint、Favorable deltaへ限定する。
3. 変換詳細TableをMMP ID、Exact Core、Before fragment、After fragment、Target全体SMILESへ限定し、Neighbor全体SMILESは表示しない。
4. Visual transformationへTarget全体画像を追加し、表示順をNeighbor、Target、Before、Afterへ固定する。
5. 共通coreを基準にNeighborとTargetの2D描画方向を揃える。
6. narrow viewportでは意味順を維持して縦へwrapする。
7. 各構造のlabelを画像直上または直下に固定する。
8. core画像を小さめに左へ置き、MMP rowsとMax Favorable Δのcardを右側へ縦に配置する。
9. MMPが0件でも`MMP該当なし`HTMLを生成し、A009からlinkできるようにする。
10. 全体レポートSection 2へanalysis unitごとのTarget構造を4列で表示する。
11. 個別レポートSection 1はTargetを単独行にし、TargetへalignしたNeighborを4列の折り畳み領域に表示する。
12. Section 4は`表示内容`と`掲載範囲`を別々の折り畳みにし、詳細CSVリンクをSection末尾へ置く。

### 11.3 Exact Core grouping

1. HTML表示用に最小変換選択とTarget→To正規化を先に行う。
2. 可能ならcoreをcanonical SMILES相当へ単純に正規化し、attachment pointを含めた値をgroup keyにする。複雑な構造同値判定は導入しない。
3. 共通core画像とgroup summaryを生成する。
4. group内変換を方向正規化済みFavorable delta降順で決定的にsortする。
5. Favorable delta上位5件を展開し、6件目以降を同じHTML内で折り畳む。
6. CSV／Databaseの原データは変更しない。
7. 検出一意MMP数、整理後の掲載数、初期表示数、折り畳み数を実数で示し、全件掲載／一部折り畳み／0件で説明文を切り替える。

### Test

- TargetがFrom／To双方の原データで表示方向が同じになる。
- Favorable deltaの符号がNeighbor→Target方向で正しい。
- 同一Target–Neighborの包含coreから最大coreだけを表示する。
- 異なるMMP IDでも同一coreが一つのgroupになる。
- 異なるcoreを誤結合しない。
- attachment pointが異なるcoreを誤結合しない。
- 各groupでFavorable delta上位5件だけが初期展開される。
- 個別MMP HTMLが指定4 Sectionだけを指定順で持つ。
- 基本情報Tableと変換詳細Tableがallowlist列だけを持ち、Neighbor全体SMILESを含まない。
- 4画像のDOM順とcaptionが仕様どおりである。
- NeighborとTargetが共通coreを基準にalignされる。
- 全体レポートにanalysis unitごとのTarget galleryが4列で生成される。
- 個別Section 1でTargetが単独表示され、Neighbor galleryが初期状態で折り畳まれる。
- core画像と縦積みmetric cardのlayoutが存在する。
- MMP件数に応じて表示範囲の説明文が正しく切り替わる。
- Section 4の`表示内容`、`掲載範囲`、詳細CSVリンクがこの順で並ぶ。
- 一つのtargetを参照する複数A009 unitからlinkできる。
- MMP 0件でも`MMP該当なし`HTMLとA009からのlinkが生成される。

## 12. Phase 8: 同期、文書、package verification

### 作業

1. canonical runner／templateを対象Skillへ同期する。
2. すべての`capability.json`を0.1.10へ揃える。
3. catalogを再生成する。
4. user guide、overview、output contract、skill catalog、quick referenceを更新する。
5. Description Databaseの運用手順をuser guideへ追加する。
6. Series grid、Standard／Supported Core rescue／fallback、human gateの操作例をprompt／guideへ追加する。
7. 日常Promptへ入力preflight、Report監査、Series support確認、calculation version確認、release smoke test、Round完走後の終了処理を必須項目として揃える。
8. Promptに記載したSkill、Runtime subcommand、required action、parameterが実装に存在することをcontract testで検証する。
9. MMPとA009間のnavigationをoutput contractへ追加する。0.1.11のMMP新仕様は0.1.10 Promptへ先行記載しない。
10. package verifierでcanonical copy差分、Version不一致、必要Artifactを検査する。

### 完了条件

- canonical templateと各Skill copyに差分がない。
- catalog、profile、capability、RuntimeのVersionが一致する。
- 操作例だけでcold cache、warm cache、Series human gate、Round完走後の終了処理を再現できる。

## 13. Phase 9: End-to-end検証

### 最小fixture

- cache hit／missが混在する小規模Dataset
- 同一ID／異なるSMILESを含む拒否fixture
- Standard acceptance、Supported Core rescue、Rejectedの各Series fixture
- Union FF 0.30／0.50、Supported Core FF 0.50、Supported Core Endpoint-valid Nの境界fixture
- resolutionごとにfallback数が非単調になるfixture
- final unit数が24以下になるfixture
- 全gridで24超になるfixture
- local unit数が25、100、101となるgate fixture
- A005 Model N=29と30、およびMember NとModel Nが異なるunitを含むfixture
- Global、Series、fallback Clusterを含むEndpoint Boxplot fixture
- 同一MMP targetが複数unitのTop 1になるfixture
- 同一core／異なるMMP IDを含むfixture
- MMP pairが0件のTop 1 target fixture
- A003／A005／A006の基準通過が0件となるfixture
- A003固定panelのD001／D012／D015／D016／D019と、D015／D016の非採用特徴量を含むfixture
- A005 Local／Global OOF比較図を生成できるfixture
- A006 Tanimoto 0.75境界とBoundary favorable件数表示のfixture

### E2E確認項目

1. cold cache ROUND1完走
2. Endpointだけを変えたwarm cache ROUND1完走
3. Description payloadの科学的同一性
4. C012 gridとchosen condition
5. human gateとapproval reset
6. A003–A009標準解析完走
7. A009からMMPへのlink切れがないこと
8. offline HTMLの画像／CSS／Table表示
9. 日本語見出しと説明文がUTF-8で文字化けせず表示されること
10. full audit PASS
11. package verification PASS

## 14. 実装順序とcheckpoint

推奨順序は次のとおりである。

1. Phase 0: 仕様承認とbaseline
2. Phase 1: Version／schema骨格
3. Phase 2: Description Database
4. Phase 3: C012 parameter search
5. Phase 4: 各Operatorのreport-ready出力
6. Phase 7前半: A008 indexとMMP renderer
7. Phase 5: Standard Summary
8. Phase 6: 個別A009とMMP導線
9. Phase 8: 同期と文書
10. Phase 9: E2E

Phase 2、Phase 3、Phase 7の終了時に中間レビュー可能なcheckpointを置く。とくに科学基準を変えるPhase 3は、fixture上のgrid比較表を確認してからA009表示へ進む。

## 15. 主なリスクと対策

| リスク | 対策 |
|---|---|
| 同じIDに異なる構造を誤再利用 | canonical SMILESを比較し、mismatchはcache missにせずfail-fastして監査記録 |
| 同じ計算Versionでも条件違いを誤再利用 | configuration signatureを必須化 |
| reportだけのSkill version更新で不要なcache失効 | Skill versionはprovenanceに限定し、calculation versionで計算ロジック変更を判定 |
| cache mergeで入力順やdtypeが変化 | 元ID順によるone-to-one検証と全件contract test |
| 並列RunでDatabaseが競合 | SQLite transaction、busy timeout、payload一致検証 |
| Database破損をsilent missとして隠す | integrity errorで停止し、repairを要求 |
| FringeによってUnion FFが低下する | StandardはUnion FF 0.50を維持し、Union FF 0.30以上かつ十分なNとFFを持つSupported Coreがある場合だけrescueする |
| resolution増加でunit数が逆に増える | `min_ff_evaluate=10`では全resolutionを実測し、最初の24件以下だけを自動選択 |
| min FF引上げで有用な小Clusterを失う | Session内MatrixへCluster／Compound coverageを併記し、人間が選択 |
| A009が再び横長になる | renderer列allowlistとDOM／viewport test |
| MMP groupingが情報を隠す | 詳細CSV維持、group summary、折り畳み件数表示 |
| A009が巨大MMP CSVを読み込む | 小さなMMP report indexだけを依存Artifactにする |
| 0.1.9 Runへ新契約を混入 | 新規0.1.10 Run限定、旧Artifact read-only |

## 16. Definition of Done

次をすべて満たすまで0.1.10を完了扱いにしない。

- 仕様概要書10節の完了条件を満たす。
- unit、contract、renderer、integration、E2E testが全件PASSする。
- 18 Descriptionおよびcustom runnerを含むcache matrixがPASSする。
- A003が`criteria_pass = correlation_hit`だけで判定され、feature別`sample_count`がfinite pair数と一致する。
- 全Descriptionの`calculation_version`必須化とRuntime／package verificationのfail-fastがPASSする。
- Runtime core JSON Schemaのpositive／negative fixtureとFull Auditの要求が一致する。
- C012 gridの選択結果をfixtureから手計算で照合できる。
- Cross-representation Core／Core／Fringe、Supported Core／UnionのN・FFとStandard／rescue／fallbackをfixtureから手計算で照合できる。
- 追補対象であるA009の主要画面を人間がレビューし、可読性を承認する。MMPは既存baselineの回帰確認だけとする。
- A009が承認済みTemplateだけから生成され、link／件数監査がPASSする。監査不合格時はA009とFull Auditを成功扱いにしない。
- Runtime full auditがPASSする。
- package layout verificationがPASSする。
- user guideとquick referenceが実装と一致する。
- 0.1.9の既存Runおよび原本CSVを変更していない。
- 0.1.11向けMMP追加改修が0.1.10追補へ混入していない。

## 17. 実装結果（2026-09-04）

- Description Database、Runtime cold／partial／warm cache経路、監査付きinvalidateを実装した。
- 初回baselineではC012のFF 0.50／0.40区分、resolution自動探索、30条件Matrix、人間選択、24／50／100件の境界を実装した。FF 0.40区分は2026-09-06追補で廃止し、Standard／Supported Core rescueへ置換した。
- A003、A005、A006、A007、A009およびMMP Type-Iの承認済みreport仕様を実装した。
- canonical Runner／Templateを対象Skillへ同期し、42 Capabilityのcatalogを再生成した。
- 自動検証は53 tests／6 subtests PASS、42 Capabilityのpackage layout verification PASSを確認した。
- Windows Pixi上で`chemble_jak2_download_01.csv`（231化合物）を使用し、D001／D002／D012／D015／D016の実計算とA003–A009／MMPの実rendererを通した。Series membershipはreport仕様確認用の決定論的fixtureであり、A005には高コストDescriptionの代替blockを使用したため、科学的結論の検証には用いない。D019はWindows nativeの`tblite`計算processがaccess violation（exit `-1073741819`）で終了するため、この検証reportのA003入力は既存D001結果を使用した。D019を含む固定panel全体のA003計算ロジックはcontract testで確認し、実データE2EはLinux本番環境の確認事項とする。
- Description Databaseは、先行Runの60化合物を再利用し、未登録171化合物だけを追加計算して231化合物のD001 vectorを完成できることを確認した。再利用60行は全列一致し、入力ID順も維持された。
- A009全体／個別とMMP HTMLはEdge headlessでUTF-8、固定幅Boxplot、両cutoff、折り畳み／sort可能Table、orange PCA／UMAP、A007 caption、MMP描画align、core header、件数別説明文、相互導線を視認し、ローカル参照40件にlink切れがないことを確認した。確認時に発見したfallback ClusterのSource Cluster説明欠落と欠損値を含むA007 caption生成も修正した。さらに、構造由来Clusterへvector由来fallback構造を誤表示しないようA007の由来判定をCluster Registry基準へ変更し、構造由来は登録Keyだけ、vector由来はSource Cluster別Murcko／MCSとなることを実データで再確認した。MMP全体の4列Target galleryと、個別レポートのTarget単独行／Target-aligned折りたたみNeighbor galleryもブラウザで確認した。
- Linuxでの全Descriptionを含む新規0.1.10 ROUND1、Runtime full audit、利用者による最終HTML承認はrelease前の運用確認として残す。
