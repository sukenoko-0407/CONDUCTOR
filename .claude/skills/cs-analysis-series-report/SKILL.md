---
name: cs-analysis-series-report
description: Render deterministic A009 overall and per-Series HTML reports after all standard batch Operators finish.
allowed-tools: Read, Bash
---

# A009 Standard Series report

固定HTMLテンプレートの7 Sectionへcanonical artifactの値を差し込む。全体Summary冒頭には全Cluster、一次選抜Cluster、Candidate Series、通常／緩和採用Series、fallback Cluster、最終analysis unit、使用parameterをcardで示し、各itemの説明だけを折りたたむ。Endpointヒストグラム内へMean、Median、Favorable／Unfavorable cutoffを1行表記のLegendとして描画し、その直後にGlobal、採用Series、fallback Clusterの表示幅固定・横長Boxplotを置く。両図は本文幅より小さく中央配置し、Boxplotにも両cutoffを点線とLegendで示す。選抜Cluster一覧とCandidate Series mapは固定列だけを表示し、全行はA009成果物内のCSVへ保持する。標準解析結果はA003、A005、A006に限定し、具体的な数値基準を示す。A005は基準未達を含め各analysis unitの最良結果を1件ずつ掲載する。実行状況Sectionは表示しない。

A001、A002、確定済みC012は必須入力とする。A003-A007は成功した成果物だけを掲載し、一部が明示waiveされてもPartial reportを完成させる。個別Series／fallback Clusterでは最大20化合物の2D構造、PCA／UMAP（対象はMatplotlib orange `#ff7f0e`）、Description ID付きA003表と上位3散布図、A005のLocal（左）／Global（右）OOF予測比較図、A006、A007 support上位5構造を示す。A006はD002 ECFP4、Tanimoto>=0.75、absolute Endpoint差>=Global Endpoint IQRでcliff pairを定義し、Boundary favorable directionは件数／Boundary cliff全件数で表示する。A007では、C001–C004の構造由来Clusterはクラスタリング手法が登録したKey構造だけを示し、説明には`C001：Murcko scaffold`のようにIDと手法名を併記する。C005–C010のvector由来ClusterだけSource ClusterごとにMurckoとMCSを導出する。Series全体の和集合を個別Source Clusterの代用にしてはならない。画像LegendはSource Cluster IDとし、件数captionは出さない。各Sectionは主要Table／画像を見出し直後に置き、解析内容と判定基準はその下の折り畳みに置く。ただしA007の由来説明は画像直下に常時表示する。Description／ClusteringのID説明はTableの直下に`特徴量／クラスタリングの説明`として折りたたみ、構造クラスタリングには非該当のDescriptionを表示しない。Analysis unit Tableは初期表示し、その他の長いTableは初期状態を折りたたむ。全Tableへ列説明とclient-side sortを付け、各詳細CSVリンクはSection末尾に置く。A008の小さなindexがあればTop 1 compound IDと専用MMP HTMLへのlinkを付け、pair CSVを本文へ読み込まない。
