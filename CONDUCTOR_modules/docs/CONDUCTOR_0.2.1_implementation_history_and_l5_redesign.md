# CONDUCTOR 0.2.1 実装判断履歴と L5・全Lens性能再設計候補

作成日: 2026-09-19  
状態: **本番観測を受けた是正設計候補。未実装・未受入・独立レビュー待ち。**

## 1. この文書の目的

本書は、CONDUCTOR 0.2.1 の仕様概要・実装計画を受けて実装詳細仕様の作成から本番Runへ至るまでに、実装担当Agentが行った主要な判断、その根拠、後から判明した誤りを記録する。その上で、2026-09-19に顕在化したL5の本番規模性能問題を、既存実装の小修正ではなくデータ表現から再検討する。

本書では次を区別する。

- **確認済み事実**: repository、Git履歴、生成済み文書、sourceから確認できること
- **本番観測**: 利用者がUbuntu本番機で確認した実測事象
- **判断**: 実装担当Agentが採った設計・実装上の選択
- **再設計案**: まだ実装・受入されていない提案

本書に記載する解決案は、実装担当Agentがsourceを静的確認して作成した**一つの設計候補**であり、確定仕様ではない。別Agentによる独立レビュー、代替案との比較、production-scale benchmark、科学的同値性試験を経るまで採用を確定しない。「確認済みの問題」と「解決案としての判断」を混同しない。

科学的なL5契約、すなわち同一axis内の文脈ペア、Pearson相関、`|r| >= 0.3`、逆符号、Fisher z差、Murcko骨格内Endpoint並べ替え、段階的B=100/1000、BH補正は維持する。本書の主対象は、同じ統計量を重複なく計算するためのデータ表現、実行計画、checkpoint、Node管理である。

## 2. 結論

現在のL5問題は「64コアを使っていない」だけではない。次の三つが重なっている。

1. 0.1.xに存在した `compound x Cluster` Boolean行列のbatch計算資産を、0.2.1の文脈Artifactへ継承しなかった。
2. L5が、同じ `context x feature` 相関をcontext pairごと、さらにpermutationごとに再計算するアルゴリズムになった。
3. 実装詳細仕様にはpermutation並列が記載されたが、L5の`--workers`は計算関数へ接続されず、Runtimeもready Nodeを逐次実行した。

現時点の第一候補は、現在のloopをそのまま64分割する方式ではない。Phase 2で全contextのBoolean membership matrixをimmutable Artifactとして一度だけ構築し、L5を次の行列中心アルゴリズムへ置換する案である。

```text
compound x context membership M
compound x feature matrix X
compound x Endpoint vector y
              |
              v
context x feature correlation Rを各反復につき1回計算
              |
              v
同一axis内で R >= +0.3 のcontext集合と R <= -0.3 のcontext集合を直積
              |
              v
観測候補だけをB=100 -> 生存候補だけをB=1000まで検定
```

この案では、相関計算の重複を除去した後に、feature block、axis、permutation rangeを並列化できる可能性がある。ただし、単一processのcompiled/vectorized kernel、BLAS内部並列、candidate単位sharding等との実測比較は未実施であり、採用方式は独立レビューとprototype benchmarkで決める。

## 3. 実装と判断の履歴

### 3.1 2026-09-16: 設計正本の受領と実装計画の固定

利用者から0.2.1の仕様概要と実装計画を正本として受領し、実装は次の文書順序に従う方針とした。

- [`CONDUCTOR_0.2.1_specification_overview.md`](CONDUCTOR_0.2.1_specification_overview.md)
- [`CONDUCTOR_0.2.1_implementation_plan.md`](CONDUCTOR_0.2.1_implementation_plan.md)
- [`design/calibration_results.md`](design/calibration_results.md)
- 各design文書

Git履歴では、診断とnull calibrationが`e9f0f88`、実装計画が`2e5808f`、実装者向け指示が`470d312`に記録されている。

実装者向け指示では、0.1.xの設計思想を前提として読まず、0.2.1実装計画に明示された資産だけを流用するよう拘束した。これは科学的な旧仕様の混入を防ぐ意図だった。

### 3.2 2026-09-16〜17: 実装詳細仕様と質問票

実装担当Agentは、コード着手前に次を作成した。

- [`CONDUCTOR_0.2.1_implementation_questions.md`](CONDUCTOR_0.2.1_implementation_questions.md)
- [`CONDUCTOR_0.2.1_implementation_detail_spec.md`](CONDUCTOR_0.2.1_implementation_detail_spec.md)

L5については、重複する文脈間で通常の独立2群Fisher z近似を使えない問題をQ-009として挙げ、Fisher z差を観測統計量、Murcko骨格内並べ替えを経験p値とする判断を採用した。この統計判断は妥当であり、今回変更しない。

一方、実装詳細仕様はmembershipをlong tableとして固定し、「配列位置を永続IDにしない」ことを優先した。計算用のwide Boolean matrixとID indexを併設する契約までは作らなかった。

また、同書9章にはpermutationを`candidate chunk x iteration range`で並列化すると書いたが、並列task、checkpoint、merge、実worker消費を受入試験へ具体化しなかった。

### 3.3 2026-09-17: 段階7〜11の実装

L5、L1b、L2a、L7、L4、scoring、Deep Dive、report、Runtimeを実装し、小規模fixtureと契約試験を通した。当時の判断は[`CONDUCTOR_0.2.1_stage11_implementation_report.md`](CONDUCTOR_0.2.1_stage11_implementation_report.md)に記録した。

ここで「worker数1/N一致」と「並列化仕様」を十分に区別しなかった。実際にworker数差のbyte-identical確認が強く行われたのはfragment engine等であり、L5がN workerを消費していることを確認する本番規模testは存在しなかった。L5 CLIは`--workers`を受け取るため、境界が存在することを実並列化と誤認した。

### 3.4 2026-09-18: 最初の3.4A本番障害

961化合物の本番Runにより次が判明した。

- D015/D016の構造的NaNを全行失敗として扱い、登録0件となった。
- L4が約25万候補を生成し、全候補を全Tierへ再記述しようとしてKILLされた。
- identity bridge、distance配置、Pixi asset fallback、再queue等に実運用上の欠陥があった。

「実装適合性完了」という判断を撤回し、[`CONDUCTOR_0.2.1_production_remediation_report.md`](CONDUCTOR_0.2.1_production_remediation_report.md)へR-01〜R-08を記録した。

R-03では`resources.workers`をExecution Request、CLI、環境変数へ一貫して伝播させた。しかし、これはCPU予算の**伝達**だけを検証しており、各Skillがその値を実際のprocess/thread数へ変換することまでは検証しなかった。この判断は不十分だった。

### 3.5 2026-09-18〜19: 起動経路とLocal LLM運用の整備

本番前確認の重複を減らすため、versioned blueprintとRun Specから固定DAGを生成するproduction compiler、Preflight receipt、短縮した3.4A運用経路を整備した。Local LLMについては、CPU機上のprovider processから別GPU機上のOpenAI互換vLLM APIを呼び出す構成を整備した。

これらは起動契約とPhase 5/6の安全性を改善したが、Phase 3の数値計算kernelがworker予算を消費するかは解決していなかった。

### 3.6 2026-09-19: L5の本番規模性能問題

利用者のUbuntu専用機で次が観測された。

- 論理CPU 64コア
- RAM total 755 GiB
- 同居する別利用者ジョブなし
- LLM推論は別GPUサーバ
- L5が8時間経過後も実質1コアで実行中

source確認により、L5 CLIは`--workers`をparseするが`run_l5()`へ渡しておらず、calibration、screen、finalが通常のPython loopで逐次処理されることを確認した。また、Runtimeはready Nodeを列挙した後も一つずつ`subprocess.run()`している。

この時点で、L5の統計結果が最終的に得られることと、0.2.1が明示する「Phase 3 L5は分割軸単位で完全並列」を満たすことは別問題であると訂正した。現実装は科学的手続きの形は保持するが、運用実装として受入不可である。

## 4. 0.1.xに存在したBoolean matrix資産

0.1.9/0.1.10/0.1.11では、各Clustering Nodeがlong membershipを出力し、RuntimeがGlobal Cluster IDへ統合して次を正本としていた。

```text
行: compound_id
列: Global Cluster ID
値: Boolean membership
```

実装はGit ref `0.1.11:CONDUCTOR_modules/tools/runtime_controller.py` の`promote_cluster_runtime()`に残っている。long tableを`pivot_table`でwide化し、`runtime/cluster_membership/Cpd_Cluster_matrix_C000001_099999.csv`と`index.json`をatomicに昇格していた。

文書上の契約は次に残っている。

- `0.1.11:CONDUCTOR_modules/docs/CONDUCTOR_0.1.9_specification_overview.md` 4.3節
- `0.1.11:CONDUCTOR_modules/docs/CONDUCTOR_0.1.9_implementation_plan.md` 6章

この行列は、全Cluster batch survey、intersection count、Jaccard計算をPythonのCluster pair loopから行列積へ移すために使われた。

0.2.1のL5は0.1.xに存在しなかったため、旧L5実装をそのまま流用できるわけではない。しかし、membershipを一度だけBoolean matrixへcompileし、下流がbatch演算に使うアーキテクチャは直接再利用できる。

### 4.1 当時の判断の問題

実装担当Agentは「0.1.xの科学的思想を継承しない」という指示を、計算表現と運用上の成功例まで積極的に参照しない方針として適用した。これは範囲を広く取りすぎた。

正しくは次のように分離すべきだった。

- FF事前選抜、旧Series定義、旧統計判断: 0.2.1へ持ち込まない
- Boolean membership matrix、shard index、atomic promotion、batch行列演算: 科学的意味に依存しない実装資産として評価する

この分離をしなかったことが、現在のlong-only ArtifactとL5の重複計算につながった。

## 5. 現行L5の計算上の課題

### 5.1 相関の重複計算

現在は同一axis内の全context pairを作り、その内側で全featureを走査する。

```text
for context pair (A, B):
    for feature F:
        r(A, F)を計算
        r(B, F)を計算
```

同じ`r(A,F)`が、Aと組み合わされる相手contextの数だけ再計算される。context数をC、feature数をFとすると、相関計算が概ね`O(C^2 * F)`へ膨らむ。本来必要なのは`O(C * F)`の相関表を一度作ることである。

### 5.2 Global相関の重複

`global_r`もcontext pairとfeatureのrow生成中に計算されるため、featureごとに一度でよい値が繰り返し計算される。

### 5.3 calibrationとscreenの重複

最初の20反復では、全universeをcalibration用に評価した後、そのsubsetである観測候補をscreen用に再評価する。calibration計算結果をscreenへ再利用していない。

### 5.4 並列化の未接続

`cs-lens-l5/scripts/run.py`は`--workers`を受け取るが、`run_l5()`にworker引数がない。process pool、thread pool、vectorized batchのいずれも存在しない。

### 5.5 checkpointと進捗の欠如

観測候補、calibration 20、screen 100、final 1000の間に永続checkpointがない。長時間NodeをKILLするとL5を最初からやり直す。Runtimeはworkerのstdout/stderrをprocess終了後にまとめて保存するため、進捗、RSS、完了反復数を運用中に監査できない。

### 5.6 Node管理の欠陥

- ready Nodeは逐次実行される。
- 全Nodeへ同じRun上限worker数を渡すだけで、Node別grantがない。
- `memory_mb`は記録値であり、admission controlにもRSS監視にも使われない。
- lease既定値は1時間だが、長時間subprocess中にleaseを延長しない。
- heartbeat eventは定義されているが、現実装ではlease期限を更新しない。
- Node内部taskの状態がなく、部分再開できない。

## 6. 全Lens横断の静的監査

### 6.1 監査範囲と限界

次の実装をsourceレベルで確認した。

- `.claude/skills/cs-lens-l1b/python/conductor_lens_l1b/l1b.py`
- `.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2a.py`
- `.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2b.py`
- `.claude/skills/cs-lens-l4/python/conductor_lens_l4/l4.py`
- `.claude/skills/cs-lens-l4/scripts/run.py`
- `.claude/skills/cs-lens-l5/python/conductor_lens_l5/l5.py`
- `.claude/skills/cs-lens-l7/python/conductor_lens_l7/l7.py`
- `.claude/skills/cs-stat-core/python/conductor_stat_core/statistics.py`
- `.claude/skills/cs-runtime/python/conductor_runtime/dag.py`
- 各Lensの`scripts/run.py`と既存unit/integration test

以下の判定は静的監査に基づく。L5以外については961化合物の本番完走時間、候補数、peak RSS、平均CPU使用数が揃っていないため、「遅いはず」「十分速い」とは断定しない。各Lensを次の三分類で扱う。

- **確認済みで問題ない契約**: sourceまたはtestから維持すべき挙動を確認できる。
- **確認済みの課題**: sourceから逐次loop、重複計算、worker未接続等を確認できる。
- **未確認リスク**: 計算量上の懸念はあるが、本番benchmarkなしでは障害と断定できない。

### 6.2 全Lens共通で問題ないこと

- L1b、L2a、L2b、L5、L7はscreen後に生存testだけをfinal反復へ進める段階検定を持つ。
- seedは`derive_seed()`で候補またはblockとglobal iterationから導出され、現行逐次実行では再現可能である。
- BH補正はLensごとのfamilyに分離し、全p値確定後に適用する。
- L1bはcontext membershipとdistanceを固定し、EndpointだけをMurcko block内で並べ替える。
- L2aはcontextをまたぐcrossing pairをinside/outsideの双方から除外する。
- L2bはseries内部の寄与を対象にし、screen/finalを分離する。
- L4は候補数、Description行数、cost unitsのguardを持ち、guard合格後だけ候補Descriptionを開始する。候補には近似値ではなくTier 1/2の実Descriptionを使う。
- L7はR基label permutationと対応付きscaffold label交換を分離する。
- L1a、L3、L6は0.2.1では診断扱いであり、独立した大量Findingを生成しない。これらをL1b/L2/L5の入力filterに使わない契約は維持すべきである。

これらは科学的・監査上の契約であり、高速化のために変更しない。

### 6.3 全Lens共通で確認した課題

L1b、L2a、L2b、L5、L7のCLIはすべて`--workers`をparseするが、計算関数はworker引数を受け取らず、process/thread poolも使用しない。したがって、これらのLensについてはCPU予算64の**伝播**は実並列を意味しない。

また、長時間Lensに共通するtask checkpointがなく、RuntimeはNode内部のpermutation進捗を管理しない。既存testは科学的な小規模fixtureを中心とし、次を検証していない。

- `workers=1/2/64`の結果同一性
- 実際のprocess/thread数とCPU使用率
- production-scale wall-clock、peak RSS、候補数
- worker、親Node、coordinatorのKILL後の部分再開
- 同じ中間統計量が候補間で何回再計算されたか

これは「全Lensが遅い」との結論ではなく、速さと頑健性を受入済みと判断する根拠がない、という課題である。

### 6.4 Lens別の現状、課題、第一候補案

| Lens | 確認済みで問題ないこと | 確認済みの課題 | 未確認リスク | 実装担当Agentの第一候補案 |
|---|---|---|---|---|
| L1b | distance固定、self除外、Murcko block null、段階検定 | 各permutation・各contextで固定distanceを再sortし、最初のcalibration 20ではuniverse計算後にcandidateを再計算する。worker未接続 | context数、Tier 1/2 space数、context sizeに応じてL5に次ぐ律速になる可能性 | 各`space x context x target`のneighbor indexを一度だけcompileし、Endpoint配列のgather/mean/errorをvectorizeする。calibration計算をscreenへ再利用し、permutation rangeをshard化する |
| L2a | crossing pair除外、pair deltaは各permutationにつき一度生成、二つのquestionを分離 | 候補生成が`transformation x context x pair`のPython set/DataFrame loopで、candidate統計も逐次。worker未接続 | transformation/context/candidate数が大きい場合の候補構築と1000反復 | Boolean context matrixからpair-inside/outside matrixをcompileし、候補indexを固定する。permutationごとのpair delta生成とcandidate reduceをblock化する |
| L2b | series内寄与、screen/final、calibrationを保持 | 全series寄与をpermutationごとに再構築し、questionを逐次評価する。worker未接続 | L5のような二乗爆発は見当たらず、現規模では十分速い可能性もある | series layoutをarray indexへcompileし、まずbenchmarkする。必要な場合だけ共通permutation task runnerへ載せる。根本的なmatrix化を前提にしない |
| L4 | candidate/row/cost guard、support順の決定論的cap、実candidate Description、distanceの一部は行列演算。CPU予算は全Description subprocessへ環境変数で伝播する | cap適用前に全変換×sourceを逐次生成し、Description spaceを一つずつ起動する。D016/D019には明示的なcompound並列parameterを設定するが、Lens本体のgeneration/scoreはworker未接続 | raw候補が数十万〜数百万へ増える場合のRDKit処理、audit、dedup、Euclidean一時tensor | transformation shardごとのcandidate生成とprivate出力、disk-backed集約でsupport/dedup後にcapする。Description spaceはNode resource profileの範囲で並行化し、distanceはcandidate blockで計算する |
| L5 | 科学的検定、同一axis、逆符号、段階検定 | `context pair x feature x permutation`の重複相関、worker未接続、checkpointなし。本番で実質1コア8時間以上を観測 | 新engineの最適なshard軸とprocess/BLAS構成 | 第7章のmatrix-first案をprototype候補とし、他方式とbenchmark比較する |
| L7 | 共通R基5個以上、二つの帰無分布、段階検定 | 全series pairを`combinations`で列挙してset intersectionし、candidate×permutationを逐次処理。worker未接続 | series数が少なければ現方式で十分な可能性。series数増大時は`O(S^2)`列挙が支配 | `fragment_id -> series_ids`のinverted indexで共通R基数を集計し、閾値到達pairだけmaterializeする。必要ならcandidate/permutation shard化する |
| L1a/L3/L6 | 診断値のみでFindingを生成しない | 現時点でL5同等の長時間実測障害は確認していない | 診断集計の実測時間を記録していない | 独立した大規模engineへ拡張せず、計測を追加する。閾値超過時だけ個別最適化を検討する |

### 6.5 L1bの重複計算はL5とは別に優先調査する

L1bのdistanceとcontext membershipは全permutationで不変である。しかし現実装の`local_flatness()`は、各targetについて距離を毎回`lexsort`し、上位neighborを選び直す。固定neighbor indexを事前計算すれば、各permutationで必要なのはEndpoint値のgather、平均、二乗誤差だけになる。

第一候補案は次である。

```text
Phase 2/3 preparation:
    neighbor_index[space, context, target, k] を一度だけ作る

each permutation:
    predictions = mean(y_perm[neighbor_index], axis=k)
    squared_error = (y_perm[target_index] - predictions) ** 2
    lambda = 1 - mean(squared_error) / global_variance
```

これはBoolean membership matrixだけでは解決せず、distance由来neighbor graphのcompileが必要である。L5 engineと同じkernelへ無理に統合しない。

### 6.6 L2a/L2b/L7には共通task protocolだけを共有する

三Lensはpermutationを持つが、統計kernelは異なる。共有候補は計算式そのものではなく、次の実行protocolである。

```text
task_key = lens | stage | candidate_or_block_range | permutation_start | permutation_stop
seed     = derive(global_run_seed, scientific_key, global_iteration)
output   = finite_count + extreme_count + optional calibration aggregate
merge    = stable task_key order
```

このprotocolを`cs-stat-core`に置く案は有力だが、汎用化による複雑化もあり得る。L2bが短時間で完了するなら、array layoutだけ改善して逐次のままにする選択肢も残す。

### 6.7 L4で維持するguardと変更候補を分離する

L4の`candidate_cap`、`max_candidate_description_rows`、`max_candidate_description_cost_units`は、過去の25万候補障害に対する有効なfail-closed契約であり、並列化後も削除・自動拡大しない。

一方、guardは全raw候補生成後に適用される。raw候補生成自体が高コストになる規模では、次を比較する必要がある。

1. transformation rangeをprocess shardへ分割し、各shardをprivate SQLite/Parquetへ書く。
2. candidate ID単位でdisk-backed mergeし、source/path/supportを集約する。
3. stable support順位を確定後にcapする。
4. cap内candidateだけをDescription計算へ渡す。

全raw candidateとauditをRAM上のPython dict/listへ保持する現方式とのwall-clock・peak RSS比較が採用条件になる。

### 6.8 優先順位案

この順序も提案であり、benchmarkで変更する。

1. 全Lensへdry-run complexity reportと実測telemetryを追加する。
2. 本番障害が確認済みのL5をprototype比較する。
3. 固定neighbor sortの重複が明白なL1bを改善する。
4. L2a/L2b/L7を同一production-scale fixtureで測定し、閾値を超えたLensだけ並列task化する。
5. L4 raw candidate生成をstress fixtureで測定し、必要ならdisk-backed shardingへ移行する。
6. Lens内部taskが安定してからRuntimeのNode間並列を有効化する。

Node間並列を先に有効化すると、各Nodeへ64 workerを渡したままoversubscriptionを起こし得る。まずNode別resource profileとNode内実消費を確立する。

## 7. L5再設計の第一候補

### 7.1 Phase 2 Artifactを再設計する

全contextについて、次の三表現を同時に生成する。

```text
context_catalog.csv                    # ID、axis、provenance、eligibility
context_membership.csv                 # true行だけのlong形式。監査・join用
context_membership_matrix/
├─ compound_ids.csv                    # matrix row順
├─ context_ids.csv                     # matrix column順
├─ values.bool.npy                     # N x C、read-only mmap可能なBoolean行列
├─ Cpd_Context_matrix_<range>.csv       # 0.1.x互換のshard済みwide監査表
└─ index.json                           # shape、dtype、ID hash、file hash、catalog hash
```

永続IDはCSVの行番号やmatrix位置ではなく、`compound_ids.csv`と`context_ids.csv`の値である。matrix位置は同じindex Artifact内だけで有効とする。これにより、0.2.1のID監査性と0.1.xのbatch計算性能を両立する。

`values.bool.npy`を計算用正本、long/wide CSVを監査viewとする。全fileはstaging directoryで完成・検証してからatomicに昇格する。

### 7.2 観測相関表を一度だけ作る

feature matrixを`X: N x F`、membershipを`M: N x C`、Endpointを`y: N`とする。feature欠測を考慮し、有限値mask `V` とNaNを0へ置いた `X0` を作る。

各context×featureについて、次の十分統計量をfeature block単位の行列演算で求める。

```text
n      = M.T @ V
sum_x  = M.T @ X0
sum_x2 = M.T @ (X0 ** 2)
sum_y  = M.T @ (V * y[:, None])
sum_y2 = M.T @ (V * (y[:, None] ** 2))
sum_xy = M.T @ (X0 * y[:, None])
```

これらからPearson rの`R: C x F`を一度だけ計算する。全欠測、定数、`n < min_endpoint_n`はNaNとする。Global rもfeatureごとに一度だけ計算する。

### 7.3 候補pairを符号集合から生成する

各axisとfeatureについて、次を作る。

```text
positive = contexts where R[:, feature] >= +0.3
negative = contexts where R[:, feature] <= -0.3
candidates = positive x negative
```

これにより、全context pairを列挙してから符号判定する必要がない。共有化合物数`shared_n`は観測候補についてだけmembership列のdot productで求める。

### 7.4 calibration 20を全pair列挙なしで数える

各permutationで`R_perm`を一度作る。axis×featureごとの符号矛盾候補数は、

```text
count_positive * count_negative
```

で得られる。calibrationでは候補rowを全件materializeする必要がない。20反復のcountだけをcheckpointする。

### 7.5 screen/finalは観測候補に必要なcellだけ計算する

観測候補に現れる一意な`(context_id, feature_id)`を抽出する。各permutationではこのcell集合のrだけを一度計算し、candidate index arrayでFisher z差をまとめて作る。

```text
0..19    calibration全体 + screen候補。候補cellはcalibration結果を再利用
20..99   screen候補cellだけ
100..999 screen生存候補cellだけ
```

p値には全null値配列を保存せず、候補ごとの`finite_count`と`extreme_count`を保持する。`+1/+1`、screen判定、BH familyは現契約を維持する。

### 7.6 並列化

task keyを次で固定する。

```text
stage | axis_id | feature_block | permutation_start | permutation_stop
```

- seedはglobal iteration番号から導出し、worker番号や完了順へ依存させない。
- process並列を使い、各processのBLAS/OpenMP threadは1に固定する。
- `X`、`M`、定数十分統計量はread-only memory mapで共有する。
- worker出力はprivate shardへatomic writeする。
- mergeはtask keyのstable sort順で行う。
- BHだけは全candidate p値確定後に単一coordinatorで行う。

Ubuntu本番機では64 CPU tokenを上限とする。task数が64未満ならtask数まで、メモリ見積りが上限を超える場合は安全なworker数まで減らす。

## 8. 計算資源の修正契約

対象機の前提を次へ訂正する。

```text
専用Ubuntu機
logical CPU: 64
RAM total: 755 GiB
別利用者job: なし
LLM inference: 別GPU server
```

Runの初期hard limit案は次とする。

```text
cpu_cores: 64
memory_limit_mib: 716800  # 700 GiB。hostに約55 GiBを残す
```

既存`memory_mb`は名称を維持する場合も単位をMiBと明記し、単なる記録値からRun全体の強制上限へ変更する。NodeごとのExecution Requestには、Run上限ではなくschedulerが実際にgrantした値を保存する。

Node resource profileは少なくとも次を持つ。

```text
min_workers
max_workers
fixed_memory_mib
memory_per_worker_mib
native_threads_per_worker
exclusive
checkpoint_capable
```

profile未較正Nodeは`exclusive=true`として安全側で単独実行する。

## 9. RuntimeとNode管理の再設計

### 9.1 二層の並列化

1. **Node内並列**: L5等がgrantされたCPUを実際に使う。
2. **Node間並列**: DAG上で独立なNodeを、未使用CPU/memory tokenの範囲だけ同時実行する。

最初にNode内並列を受け入れ、Node間並列は後から有効化する。重いL5が64 CPUをgrantされた場合は自然に単独実行となり、軽いNodeに余剰tokenがある場合だけ同時実行する。

### 9.2 Resource admission

Nodeの実worker数は次で決める。

```text
min(
    node.max_workers,
    free_cpu_tokens,
    floor((free_memory - fixed_memory) / memory_per_worker),
    runnable_task_count
)
```

UbuntuではattemptごとのCPU affinityとcgroup v2 memory high/maxを設定する。cgroupが利用できない環境ではprocess tree RSSを監視し、hard limitを越える前に新規task投入を停止する。

### 9.3 Leaseとheartbeat

- blockingな`subprocess.run()`を廃止し、`Popen`と監視loopを使う。
- 30秒ごとにunique heartbeat eventを記録し、lease期限を延長する。
- Runtime stateにhostname、PID、process start time、granted resourcesを記録する。
- coordinator再起動時はPIDだけでなくstart timeとattempt tokenを照合する。
- processが生存中なら同じNodeを二重起動しない。
- process死亡かつlease失効時だけ`retryable`へ遷移する。
- 古いattemptから届いたlate event/artifactは正本へ昇格しない。

### 9.4 Node内部task state

長時間Nodeは`node_tasks`を持つ。

```text
pending -> running -> checkpointed -> succeeded
                    |-> retryable
                    |-> failed
```

task rowはtask key、入力/config/code hash、seed範囲、checkpoint path/hash、attempt ID、progressを持つ。workerはRuntime SQLiteへ直接書かず、coordinatorだけがsingle writerとしてeventを適用する。

### 9.5 OOM・KILL・再開

- 完了shardはhashが一致するときだけ再利用する。
- SIGTERM/SIGKILL、worker異常終了、OOMを別reasonで記録する。
- memory pressure時は新規task投入を停止し、未完了taskを少ないworker数で再計画できる。
- input/config/code hashが変わったcheckpointは再利用しない。
- 全task、merge、schema、hash検証が完了するまでNodeを`succeeded`にしない。
- 最終Artifactはstagingからatomic renameで昇格する。

## 10. 受入条件

### 10.1 科学的同値性

- 最適化対象Lensごとに現実装をscalar referenceとして保存し、candidate key、観測統計量、screen/final p値、BH q値、Finding、evidence rowを比較する。
- L1bではneighbor IDと順序、lambda、calibration countを一致させる。
- L2aではcrossing pair除外、inside/outside pair ID、二つのquestionを一致させる。
- L2bではseries residualとcalibration、L4ではcandidate support順位とscale guard、L5ではr/shared n/calibration、L7ではcommon R基と二つの帰無分布を一致させる。
- `workers=1,2,64`で同じglobal seed streamを使い、許容誤差またはbyte一致のどちらを要求するかArtifactごとに先に定義する。
- 欠測、重複/包含context、定数列、最小n、同順位、空candidate/survivorを含む。
- 現行961化合物データについて、旧実装が完了可能なsubsetをoracleにして差分を保存する。

### 10.2 性能

最適化前に、全Lensで同じproduction-scale fixtureを使い、stage別wall-clock、CPU time、平均/最大busy CPU、peak RSS、候補数、permutation数、再計算counterを測定する。測定前に全Lensへ一律の高速化倍率を要求しない。

- L5の`workers=64`対`workers=1`で8倍以上は**初期比較目標**であり、確定受入条件ではない。prototype結果と独立レビューで妥当性を決める。
- L1bはneighbor sort回数が観測準備時の一回に減ったことをcounterで確認する。
- L2a/L2b/L7は、本番baselineが許容時間内なら複雑な並列化を追加しない選択肢を認める。
- L4はraw candidate数を増やすstress fixtureで、cap前生成のwall-clockとpeak RSSが設定した運用上限内か確認する。
- runnable taskが十分ある並列区間ではCPUを実消費することを確認する。task数やmemory制約が小さいNodeへ64コア利用を強制しない。
- 同じ中間統計量が複数candidateのために再計算されないことをLens別counterで確認する。
- 30秒以内の間隔でstage、完了task、完了permutation、RSS、worker数を報告する。

正式なwall-clock上限とspeedup下限は、baselineと少なくとも二つのprototypeを比較してから本書へ追記する。根拠なく「64倍」や特定実装方式を受入条件にしない。

### 10.3 Resource safety

- process/threadの計算token合計が64を超えない。
- Run process treeのhard memory limitが700 GiBを超えない。
- native libraryの隠れた多重threadを検出する。
- cgroup limit、CPU affinity、実測peak RSSをmanifestへ記録する。

### 10.4 復旧

- 運用上のcheckpoint閾値を超える長時間Nodeについて、worker 1件KILL、Node親process KILL、coordinator KILLを個別fixtureで再現する。
- 再開時に完了shardを再計算せず、未完了shardだけを実行する。
- 同一Nodeの二重実行、late event採用、破損checkpoint再利用が起きない。
- `succeeded` Artifactは全shardのhash集合から再現可能である。

## 11. 現在のRunと移行方針

現在8時間実行中と報告されたL5は、完了すれば現行統計手続きに基づく結果を生成し得るが、並列化契約と運用受入条件を満たさない。新engineへ実装を変更するとimplementation fingerprintが変わるため、同じattemptを新codeで継続してはならない。

安全な移行は次とする。

1. 現Runのstate、attempt、PID、stdout/stderrをread-onlyで保存する。
2. 現L5を停止する場合は、旧Runをaborted/failedの監査対象として保持する。
3. Boolean context matrixと新L5 engineを実装・fixture受入する。
4. 新しいRun IDとRun rootを作る。
5. calculation signatureが変わらないDescription Database recordは再利用できる。
6. Phase 2は新しいmembership matrix Artifactを生成するため再実行する。
7. 旧Runの未完了L5内部状態は新engineへ移行しない。

## 12. 実装担当Agentの是正判断

実装担当Agentは、次を明示的に訂正する。

- 小規模fixtureの成功を、本番規模の計算量受入と同一視してはならなかった。
- `workers`の伝播試験を、CPU利用試験の代替にしてはならなかった。
- 実装詳細仕様に「完全並列」と書くだけでなく、task分割、worker消費、checkpoint、mergeを公開契約とtestへ落とすべきだった。
- 0.1.xの科学的判断を排除することと、実証済みのBoolean matrix計算基盤を捨てることを分離すべきだった。
- L4障害後の是正で、他の高コストNodeについても計算量式と本番規模dry-runを横断的に実施すべきだった。
- RAM前提を32 GiB級として考えた期間があったが、正しくは755 GiBの専用機である。現在の律速はメモリ不足ではなく、重複計算と1コア逐次実行である。

以上を踏まえ、L5については、Boolean membership matrix、相関表の一回計算、符号集合による候補生成、streaming permutation accumulator、checkpoint可能なtask engineを第一prototype候補とする。ただし、これは実装担当Agentの一案である。現行loopの安全なsharding、compiled single-process kernel、BLAS内部並列、別のsparse表現を含む代替案を排除せず、独立レビューと同一benchmarkで比較してから仕様を確定する。

独立レビューには[`prompt/CONDUCTOR_0.2.1_performance_redesign_independent_review_prompt.md`](prompt/CONDUCTOR_0.2.1_performance_redesign_independent_review_prompt.md)を使用する。
