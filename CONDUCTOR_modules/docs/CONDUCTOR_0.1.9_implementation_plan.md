# CONDUCTOR 0.1.9 実装計画書

## 1. 目的

0.1.9を新規Run専用の実装として構築する。全Description／Clustering、A001／A002、C012 Series形成を基本計算とし、Global controlとSeriesを比較するbatch Operator、MMP Type-I、定型レポート、軽量Interpretationを定型解析とする。追加解析はRound外のOn-demand記録へ分離する。

0.1.8以前の成果物、State、Schema、Node ID、Interpretationとの互換処理は実装しない。

## 2. 実装原則

- Description／Clusteringの科学計算kernelは必要最小限の変更に留める。
- 旧互換wrapper、旧Schema reader、旧ID aliasを残さない。
- 基本計算と定型解析の計画はRuntimeへ固定し、Orchestratorの判断負荷を小さくする。
- Cluster／SeriesごとにNodeを作らず、batch Node内のResultとして管理する。
- 完全表、LLM入力、人間向け表示を分離する。
- Global control、provenance、Favorable方向を全Operatorで統一する。
- On-demandをRound、DAG、通常Node番号、Runtime Leaseから分離する。
- 科学的Negative Resultと実装失敗を明確に区別する。

## 3. Phase 1: 旧仕様の除去とVersion境界

1. Product Versionと`conductor_version`を0.1.9へ更新する。
2. 0.1.8以前のRun受理、Migration、Schema fallbackを削除する。
3. 旧Operator IDと新IDのaliasを作らない。
4. 旧初期探索／追加探索、Operator予算、Result Assessment、再Screening、累積Screeningを削除する。
5. 旧Insight Registryと`INS######`管理を削除する。
6. 旧Concierge名と旧On-demand Round案を削除する。
7. Catalog、Schema、Skill producer／consumer、prompt、Subagent文書のVersionを静的に照合する。

完了基準：Package validationで旧Version用分岐と廃止IDの参照が0件になる。

## 4. Phase 2: CatalogとOperator再附番

次のIDへCatalog、Capability、Profile、Skill文書を統一する。

| ID | Capability |
|---|---|
| A001 | Cluster profile survey |
| A002 | Cluster enrichment survey |
| A003 | Series descriptor contrast |
| A004 | Series projection panel |
| A005 | Series multi-description feature model |
| A006 | Series landscape |
| A007 | Series structural signature |
| A008 | Matched molecular pair analysis |
| A009 | Standard Series report |

1. 旧A007 kNN Skillを削除する。
2. 重複する旧Operator Skillは新batch Skillへ統合する。
3. 各Skillの`capability.json`、SKILL.md、README.md、pixi環境、Catalog metadataを一致させる。
4. 一般利用と`--conductor`利用の分離を維持する。

## 5. Phase 3: 基本計算Profile

1. 全18 Descriptionを基本計算へ登録する。
2. C001～C004を直接構造Clusteringとして登録する。
3. C005～C010を全18 Descriptionへ適用する。
4. A001、A002、C012を基本計算waveへ登録する。
5. 高コストDescriptionを含む一括承認contractを維持する。
6. `min_cluster_size=5`と`min_ff_evaluate=10`を別parameterとしてSchema化する。
7. `min_ff_evaluate`変更を新しいA001／A002／C012 revisionへ反映する。

## 6. Phase 4: Cluster Registryとmembership

1. 全Clusteringのlong membershipをGlobal Cluster IDへ統合する。
2. compound × Cluster Boolean matrixを正本とする。
3. Cluster列数に応じてID範囲でshard化する。
4. shard `index.json`へpath、ID範囲、形状、hashを保存する。
5. compound ID重複、未知ID、Registry不一致、shard重複を明示エラーにする。
6. Cluster RegistryへDescription、Clustering、source Node、input kind、parameterを保存する。
7. State JSONへmembership本体を埋め込まない。

## 7. Phase 5: A001 batch profile

1. shard readerを実装し、全Clusterを一つのNodeで処理する。
2. Global Endpoint分布とFavorable／Unfavorable閾値を一度だけ計算する。
3. 全Clusterの記述統計、Favorable count／fractionを完全CSVへ保存する。
4. Cluster provenanceを各行へjoinする。
5. `min_ff_evaluate`以上のFF順位表と選抜flagを作る。
6. `higher_is_better=false`、境界同値、Endpoint欠損を検証する。
7. 一般利用CLIを維持し、CONDUCTOR batch modeだけを追加する。

## 8. Phase 6: A002 batch enrichment

1. Cluster内／外の2×2表、Odds ratio、Fisher p値を一括計算する。
2. Mann–Whitney U、median shiftを計算する。
3. Benjamini–Hochberg q値を単純な補助列として追加する。
4. q値を自動選抜条件へ使用しない。
5. 小Cluster、Endpoint欠損、全体に近いClusterへ診断flagを付ける。
6. A001と同じmembership revision、閾値、方向を検証する。

## 9. Phase 7: C012 weighted Leiden

1. FF適格Clusterだけをvertexとして受け取る。
2. Boolean行列積でintersection countを一括計算する。
3. JaccardをPrimary edge weightとする。
4. A側／B側包含率とoverlap coefficientを補助列へ保存する。
5. 共通化合物0のpairはEdgeを作らない。
6. 初期仕様ではJaccard cutoffを設けない。
7. fixed seed、記録済み`leiden_resolution`でweighted Leidenを実行する。
8. source Cluster × Series、edge list、graph diagnosticsを出力する。
9. isolated Clusterもsingleton Seriesとして保持する。
10. Series数を目的にparameterを自動調整しない。
11. Series数24超でhuman gate、24以下で自動進行とする。

## 10. Phase 8: Series Registryとanalysis unit

1. `S######` Series IDを発行する。
2. Series membershipをsource Clusterの和集合で作る。
3. compoundごとの`support_count`／`support_fraction`を保存する。
4. Series unionのFFを再計算する。
5. FF 0.5未満のSeriesを不採用とし、構成元FF適格Clusterへ自動fallbackする。
6. Series 0件時はFF適格Clusterへ自動fallbackする。
7. Seriesとfallback Clusterを`analysis_unit`へ統合し、`scope_kind`を必須とする。
8. SeriesがGlobal endpoint-valid Nの50%超なら`global_like_series`警告を付けるが停止しない。
9. Series revisionを定型Operator signatureへ含める。
10. 通常Cluster RegistryとSeries Registryを混在させない。

## 11. Phase 9: Series batch Operator

### 11.1 共通基盤

1. 1 capability／1 parameter set＝1 batch Nodeとする。
2. Global controlを一度だけ計算する。
3. analysis unitごとの成功、`not_applicable`、失敗を独立記録する。
4. 一単位の失敗でbatch全体を失敗させない。
5. 結果pathとartifact typeをanalysis unit IDで一意化する。
6. 選抜biasの固定limitationを全結果へ付ける。

### 11.2 A003 descriptor contrast

1. D001を標準入力とする。
2. Global／SeriesのPearson、Spearman、相関増分を計算する。
3. Series／non-Series median shiftとIQR effectを計算する。
4. 相関hitを`abs(r)>=0.4`、Global比0.2増加、`q<=0.05`で絞る。
5. median hitをIQR比0.75以上、`q<=0.05`で絞る。
6. 全特徴量CSVと決定論的near-missを出力する。

### 11.3 A004 projection panel

1. D002を標準入力とする。
2. PCA／UMAPをGlobalで一度だけfitする。
3. 同じ座標へ各analysis unitをoverlayする。
4. PCA、UMAP、combined PNGを各単位に生成する。
5. PCA／UMAPそれぞれの4列contact sheetを作る。
6. 別Description指定時はsemanticsに対応するmetricを使い、別Nodeにする。

### 11.4 A005 feature model

1. Global OOF modelを一度構築する。
2. Series N>=30だけをLocal OOF評価する。
3. feature selectionをouter training fold内へ限定する。
4. 同一化合物上のGlobal OOFと比較する。
5. N不足、Endpoint variation不足を`not_applicable`にする。

### 11.5 A006 landscape

1. D002／Tanimotoを標準とする。
2. Global／Series SALIを同じ定義で計算する。
3. internal／boundary cliffを区別する。
4. Tanimoto 0.8、Endpoint差Global IQR、支持3 pair、方向80%の表示基準を実装する。
5. kNN専用機能は実装しない。
6. 完全pair tableと決定論的near-missを出力する。

### 11.6 A007 structural signature

1. source C001～C004の構造定義を全件表示する。
2. 構造sourceがないSeriesだけMurcko／MCSを実行する。
3. timeout、coverage、自明coreを明示する。
4. 一Seriesの失敗を他Seriesから分離する。

## 12. Phase 10: A008 MMP

### 12.1 共通科学契約

1. Type-I／II／IIIをすべて1-cutに限定する。
2. Environment radius 0～2を実装する。
3. Pair × directed Transform × Exact Coreを一意化し、radiusでsupportを水増ししない。
4. raw Endpoint deltaとFavorable方向へ正規化したdeltaを併記する。
5. Exact Core、fragment、attachment、support、反証例を保持する。
6. 0 pairを成功したNegative Resultとして扱う。

### 12.2 Type-I

1. Global Top 5と各analysis unit Top 5を選ぶ。
2. tieを`compound_id`で解決する。
3. MMP 0件でもK+1位を補充しない。
4. 全対象を一つのbatch Nodeで処理する。
5. Type-IIIなしで実行できるようにする。入力全体のfragmentation／Pair抽出は行うが、包括的Summary群とSQLiteは保存せず、対象接続成果物だけを永続化する。
6. Summary HTML、対象別HTML、完全CSV、SVG／PNGを生成する。

### 12.3 Type-II

1. run内`compound_id`だけを受理する。
2. 外部SMILES queryを拒否し、具体的なエラーを返す。
3. Exact Core direct pairを主証拠とする。
4. near-coreをTanimoto 0.70、両側MCS coverage 0.60、attachment topology一致で選ぶ。
5. near-coreを別table／別表示に保つ。
6. effect labelを`favorable_observed`、`mixed`、`no_favorable_observed`に限定する。
7. evidence不足を別軸`underexplored`で示す。
8. Agent結論より完全MMP map／tableを主成果物とする。

### 12.4 Type-III

1. 人間指定時だけ1-cut、radius 0～2で網羅計算する。
2. canonical complete CSVと再生成可能なSQLite indexを作る。
3. pair、transform、core、transform-core、context、coverageを出力する。
4. HTMLをDatabase品質／coverage報告に限定する。
5. Type-I／IIや標準Interpretationを自動実行しない。
6. Type-Iからの自動DB探索を実装しない。
7. Type-IIでの再利用は人間がDB pathを明示した場合だけ許可する。

## 13. Phase 11: A009 Reporting

1. canonical artifactだけを読む独立Skillを作る。
2. Summary HTML 1件とanalysis unit詳細HTML K件を生成する。
3. Summaryの主表を全FF適格Cluster一覧とする。
4. Description、Clustering、N、Favorable count／fraction、OR、p、q、Seriesを表示する。
5. Endpoint overview／histogramを追加する。
6. Compact Series mapを追加する。
7. 実行時間と状態件数を簡潔に表示する。
8. Series詳細へD001、projection、model、landscape、structureを表示する。
9. MMPをSeries詳細へ含めない。
10. hit 0件でも決定論的near-missを一文表示する。
11. HTMLをoffline self-containedとし、画像をbase64埋め込みする。
12. section順、配色、必須labelをrenderer testで固定する。

## 14. Phase 12: 軽量Interpretation

1. 固定SummaryとSeries比較表だけを入力とする。
2. Enriched Cluster／Seriesの全体傾向を簡潔に説明する。
3. GlobalとSeriesの差、一致、不一致を少数提示する。
4. 数表を定型Reportと重複掲載しない。
5. 完全CSVをLLM contextへ投入しない。
6. 正式Insight IDを発行しない。
7. 旧一次採点、再Screening、累積Screeningを実装しない。
8. 追加候補はOn-demand依頼案としてだけ記載する。
9. Markdown／HTMLの生成と監査を定型workflow完了条件にする。

## 15. Phase 13: On-demand

1. 現行Conciergeを`cs-conductor-on-demand-analysis`へ改名・再定義する。
2. On-demand IDを`REQ######`だけに統一し、通常`N######`を発行しない。
3. `run_root/on_demand/index.jsonl`とREQ directoryを記録正本にする。
4. Round、DAG、State、Lease、通常Node counterを変更しない。
5. Round状態にかかわらず実行可能にする。
6. committed artifactだけをread-only sourceとして許可する。
7. request原文、source path／hash、method、result、artifact manifestを保存する。
8. 書込みを当該REQ directoryへ限定する。
9. helper codeを`REQ/scratch/`で許可し、再現に必要なものを保存する。
10. 固定の広いPixi環境を用意し、network installを禁止する。
11. 一依頼一REQとし、複数成果物でIDを増やさない。
12. 同一依頼の再実行は新REQとし、過去結果を上書きしない。
13. per-request lockとOn-demand index専用lockを実装する。
14. 標準Interpretation、Insight、自動planningへ投入しない。
15. Type-II／IIIをOn-demand内から明示実行できるようにする。

## 16. Phase 14: RuntimeとOrchestrator

1. Runtimeに「基本計算→定型解析→Report→Interpretation→Audit」の固定workflowを実装する。
2. Orchestratorには開始、継続、repair指示とcompact status確認だけを担わせる。
3. 計画Nodeをすべて試行する。
4. 科学的Negative Result／`not_applicable`と実装失敗を分離する。
5. 実装失敗をrepair対象とし、人間waiveなしに完了扱いにしない。
6. wall time時は同一Roundをpauseし、次Roundを自動開始しない。
7. 再開時は成功済Nodeを再計算しない。
8. A009とInterpretationが生成される前にRoundを閉じない。
9. 人間だけがRound開始、waive、終了を指示できる。
10. On-demandはこのworkflow controllerを通さない。

## 17. Phase 15: 文書とprompt

1. Overview、Policy、User Guide、Catalog説明を0.1.9へ更新する。
2. 基本計算開始、pause／resume、repair、parameter変更のpromptを更新する。
3. On-demand依頼、MMP Type-II、Type-IIIのpromptを追加する。
4. 旧探索、再Screening、旧Concierge、Migration promptを削除する。
5. 全Skill README／SKILL.mdへ入力、出力、失敗分類を簡潔に明記する。

## 18. 検証計画

### 18.1 基本計算

1. 全18 Descriptionが一度ずつ計画される。
2. C005～C010が全18 Descriptionへ計画される。
3. C001～C004を含む成功Clusteringがmembershipへ反映される。
4. A001／A002がCluster別Nodeを作らない。
5. provenanceとCluster Registryが一致する。
6. `higher_is_better=false`でもFavorable方向が正しい。
7. `min_cluster_size`と`min_ff_evaluate`が独立する。
8. BH q値が正しく再現され、選抜gateには使われない。

### 18.2 C012／Series

1. Jaccardが対称でmembershipから再現できる。
2. 共通0のpairにEdgeがなく、共通1以上のpairに連続weightが付く。
3. 同じseedとresolutionで同じpartitionになる。
4. Series union、support、再計算FFが再現できる。
5. FF低下Seriesがsource Clusterへfallbackする。
6. Series 0件時に自動fallbackする。
7. Series 24超だけがhuman gateになる。
8. Global 50%超は警告だけで停止しない。

### 18.3 定型Operator／Report

1. 各Operatorが一つのbatch Nodeで全analysis unitを処理する。
2. Global controlが各Local結果と同じ定義で存在する。
3. PCA／UMAPをSeriesごとに再fitしない。
4. Seriesごとの3 PNGと2 contact sheetが生成される。
5. A005 N<30が`not_applicable`になる。
6. A003／A006の厳格hitとnear-missが決定論的である。
7. 構造sourceありSeriesで不要なMurcko／MCSを再実行しない。
8. Summaryが全FF適格Clusterをprovenance付きで表示する。
9. 詳細Reportが対象をGlobalと誤表示しない。
10. MMPをSeries詳細へ混入させない。

### 18.4 MMP

1. 全Typeで1-cutだけが生成される。
2. radius 0～2が保存され、supportを水増ししない。
3. Type-IがGlobal／各analysis unit Top 5を正しく選ぶ。
4. 0件targetを補充せずNegative Resultにする。
5. Type-IIがrun内compound IDだけを受理する。
6. near-coreが0.70／0.60条件とtopologyを満たす。
7. effect labelと`underexplored`が決定論的に一致する。
8. Type-IIIなしでもType-Iが完了する。
9. Type-IIIが自動実行されない。
10. SQLiteを削除してもcanonical CSVから再構築できる。

### 18.5 Interpretation／On-demand／Runtime

1. Interpretationが固定された小さい入力だけを読む。
2. `INS######`とassessment成果物を生成しない。
3. REQ作成が通常Node counter、State、Round、Leaseを変更しない。
4. REQがactive／closed／review待ちのいずれでも実行できる。
5. On-demandがREQ directoryと専用`on_demand/index.jsonl`以外へ書き込まない。
6. source manifestのhashが成果物と一致する。
7. network installが拒否される。
8. wall time時に同一Roundがpauseされる。
9. Report／Interpretation前にRoundが閉じない。
10. Runtime／Main Agentが次Roundを自動開始しない。

## 19. 主なリスクと対策

| リスク | 対策 |
|---|---|
| 基本計算Node増加 | 固定workflow、成功済み再利用、pause／resumeを実装する |
| Clustering一部失敗 | 全計画を試行し、repairまたは人間waive後に後段へ進む |
| FF偶然濃縮 | N、support、p、BH qを併記し、候補過多時は人間がNを変更する |
| Series unionでFF低下 | 再計算FF 0.5未満をsource Clusterへ自動fallbackする |
| Weighted graph過密化 | densityとweight分布を診断するが、初期仕様で自動cutoffを導入しない |
| Series数過多 | 24超だけhuman gateとし、自動parameter調整を禁止する |
| Operator Node爆発 | capability単位のbatch Nodeにする |
| Endpoint選抜bias | 全Reportへ固定limitationを表示する |
| 弱い知見でHTMLが肥大化 | 厳格hitと一件のnear-missへ限定する |
| MMPの解釈複雑化 | 全Typeを1-cutに限定し、raw map／tableを主成果物にする |
| MMP 0件を失敗扱い | 成功したNegative Resultとして保存する |
| Type-III DB肥大化 | CSVを正本、SQLiteを再生成可能なindexにする |
| InterpretationのLLM負荷 | 定型Summaryだけを読ませ、旧Screeningを削除する |
| On-demandがRunを汚す | REQ名前空間、read-only source、directory境界を強制する |
| On-demandとactive Roundが競合 | DAG／Lease／Node counterを共有せず、専用lockだけを使う |

## 20. 主な変更対象

- `CONDUCTOR_modules/catalog/`
- `CONDUCTOR_modules/schemas/`
- `CONDUCTOR_modules/tools/runtime_controller.py`
- Runtime helper、validation、renderer、package検証コード
- `.claude/skills/cs-analysis-cluster-profile/`から再編するA001
- `.claude/skills/cs-analysis-cluster-enrichment/`から再編するA002
- `.claude/skills/cs-compute-clustering-meta-overlap/`
- A003～A009として再編／新設するOperator Skill
- `.claude/skills/cs-conductor-runtime/`
- `.claude/skills/cs-conductor-orchestrator/`
- `.claude/skills/cs-conductor-result-concierge/`を置き換えるOn-demand Skill
- Interpretation Skill、Policy、Subagent
- Overview、User Guide、Catalog説明、prompt集

DescriptionとC001～C010の科学計算kernelは、入力／出力契約上必要な変更以外は原則として維持する。

## 21. 実装順序と完了判定

実装はPhase 1から順に進める。各Phaseで静的検証と単体検証を行い、後段consumerを先に作らない。

最終完了条件は次のとおりである。

1. 0.1.9新規Runで基本計算からInterpretationまで完走する。
2. 旧Version互換分岐が残っていない。
3. Catalog、Schema、Skill、Runtime、Reportの契約が一致する。
4. ReportとInterpretation生成前にRoundが終了しない。
5. On-demandが通常DAGとStateを変更しない。
6. 検証計画の必須項目がPASSする。
