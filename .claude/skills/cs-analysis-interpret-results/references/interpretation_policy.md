# CONDUCTOR Interpretation Policy

## 目的

Interpretationは作業記録ではない。Endpointをfavorableな方向へ改善する設計候補、またはその候補へ接続し得るGlobal–Local・Cluster間の違和感を、人間が検討できる形へ整理する。InterpreterはStateや計算Nodeを変更せず、Runtimeが用意したbounded contextだけを読む。

## Review Bundle一次評価

評価軸、Candidate class、対象外条件、Assessment SummaryとFull Reportの選定差の詳細は、[CONDUCTOR 一次評価ガイド](CONDUCTOR_assessment_guide.md)を正本とする。

- 評価単位は単独Result Cardではなく、Runtimeが作るReview Bundleである。
- Bundleは`global`、`global_local`、`sibling_cluster`、将来の`cross_evidence`のいずれかである。
- 活性関連のLocal Resultは、Interpretation Profileが要求するGlobal comparatorなしに評価しない。`awaiting_comparator`は低評価ではなく未評価である。
- 一回に既定4 Bundleだけを読み、Bundle内のOperator固有`evaluation_anchors`に従う。他Bundleの得点分布を基準にしない。
- `favorable_evidence`、`context_contrast`、`evidence_specificity`を0～3または`not_applicable`で記録する。単純合計点は作らない。
- 合成可能性や化学的実行可能性は採点しない。Interpreterは具体的な構造・特徴・Transform・Core・化合物Pairを提示し、最終判断をMedicinal Chemistへ委ねる。
- 各評価はBundle内のResultを最低1件引用し、実際のmetric/value、比較またはquality factに基づく固有理由を持つ。異なるBundleへの同一評価内容の複製はcommitしない。
- sample support、comparator validity、Cluster overlapはRuntimeが決定する。Interpreterはeffect stabilityとevidence independenceだけを判断する。
- 長文Insight、正式ID、Candidate class、Markdown／HTMLは一次評価段階で作らない。

## Candidate classと掲載原則

Runtimeは固定決定表で`favorable_clue`、`contextual_clue`、`supporting_evidence`、`background`、`not_scorable`、`awaiting_comparator`へ分類する。

- `favorable_clue`: favorable方向のEvidenceと、Chemistが確認できる具体的対象が接続する候補。
- `contextual_clue`: Global–Localまたはsibling間で解釈が変化する明示的な違和感。`favorable_evidence`が適用可能ならFavorable方向への接続を必要とする。SALI等の非方向性Operatorでは、十分に具体的で有効な文脈差を候補とし、活性改善への接続は人間またはFull Interpretationで検討する。
- `supporting_evidence`: 他候補を支持・制限・反証する結果。単独Insightにはしない。
- `background`: 実行済みだが人間の視線を誘導しない結果。索引には残す。

正式Reportは原則として`favorable_clue`と`contextual_clue`だけを掲載する。相関がない、Cluster差がない、投影が分離しないなどのnegative resultを単独Insightにしない。ただし、掲載候補の反証や限界として必要なら参照する。

## 基本姿勢

- GlobalとCluster-localの変化、同一Clustering内のsibling Cluster差を優先する。
- Cluster-localを単独でGlobal相当と解釈しない。
- 類似Description同士の一致を独立支持として過大評価しない。
- 注目候補には必ず反証・例外・不一致を探索し、見つからない場合も探索範囲を限界として記す。
- 観察事実と説明仮説を分離し、因果やSAR機序を断定しない。
- 重複Clusterは独立再現ではない。5化合物未満はClusterとして登録しない。

## 正式Synthesis

1. Runtime shortlistのReview Bundle、canonical scope、Cluster ID、sample、Operator、Description、comparison metric、信頼性を確認する。
2. `favorable_clue`を先に、`contextual_clue`を次に検討する。
3. comparative claimにはBundle内のcomparator Resultを必ず参照する。
4. 支持、反証、Cluster overlap、sample制約を同じInsightに結び付ける。
5. 「どの解析の、どのscopeで、Globalまたはsiblingから何が変わり、活性改善へどう接続し得るか」を日本語で具体的に記す。
6. Insightがなければ無用なnegative resultを列挙せず、その旨を短く報告する。

各Insightは内容固有の日本語表題、`review_bundle_ids`、支持・比較・反証Result、観察、解釈、完全な文の限界配列を持つ。主要数値の大量展開は行わず、詳細は個別Operator report、Artifact、Conciergeへ委ねる。Cluster-local結果をGlobalと記載したReport、根拠のない比較、日本語本文のないReportはcommitしない。

全選抜BundleについてSynthesis dispositionを一件ずつ残す。Insightに使用したBundleは`reported_as_insight`または`merged_into_insight`、見送ったBundleは`rejected_by_counterevidence`、`redundant_evidence`、`deferred_by_detail_limit`、`not_reportable`のいずれかとし、短い理由をReview Manifestへ記録する。

## 累積Synthesis

複数のScreening Roundを終えた後、人間が明示的に累積Interpretation Roundを開始できる。これは科学計算を行わない報告専用Roundである。Runtimeは指定されたCLOSED Roundに`source_round_id`で属する各Bundleについて最新かつcurrentな一次評価を走査し、historical re-Screening前の旧revisionと過去の正式Insightで使用済みのBundleを除外する。全一次評価を一括でLLMへ渡さず、共通の`candidate_priority_v3`によりbounded shortlistを作る。Interpreterは既報Insightを言い換えて新規Insightにせず、未報告の`favorable_clue`と`contextual_clue`だけを検討する。対象総数、既報除外数、選抜・非選抜範囲はreview manifestへ残す。

## MMP

A014の通常Round InterpretationではcompactなGlobal Result CardからDatabaseの存在、coverage、negative resultだけを認識する。Transform、Exact Core、Environment、ClusteringによるGlobal–Local変化は、人間がread-only `cs-analysis-interpret-mmp`を明示起動して確認する。専用Reportを次Roundへ反映する場合は、人間がその視点を依頼へ添付する。

## 境界

- InterpreterはControl、DAG、Cluster索引、Result索引、Assessment索引を更新しない。
- 正式ID、scope、sample、Candidate classはRuntimeだけが確定する。
- 新規Description、Clustering、Operatorを実行しない。
- 解析結果を削除・上書きしない。
- full RoundはInsightがゼロ件でも固定Reportを作る。screening Roundは評価索引、compact summary、Full Auditを必須とする。
