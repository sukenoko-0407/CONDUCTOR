---
name: cs-analysis-series-report
description: Render deterministic A009 overall and per-Series HTML reports after all standard batch Operators finish.
allowed-tools: Read, Bash
---

# A009 Standard Series report

固定HTMLテンプレートの必須sectionへcanonical artifactの値を差し込む。全体Summaryの冒頭には全Cluster数、選抜Cluster数、基準合格Series数、fallback Cluster数、active解析単位数だけの簡略表を置く。続くEndpointヒストグラム内へMean、Median、Favorable top-20% cutoff、Unfavorable bottom-20% cutoffを方向依存で数値描画する。選抜Cluster一覧をDescription、Clustering、N、FF、odds ratio、p/q、Series付きで示し、HTMLの表示列は定義済みの要約列へ限定する。省略列と完全行はA009成果物内のCSVへ保持する。全体Summary HTMLを一つ、各Series詳細HTMLをK個生成する。A003-A007の厳格hitを掲載し、該当なしでもsectionを残して評価件数、非検出、決定論的near-miss一件、未達基準を示す。MMPは専用HTMLを参照し、Series詳細へ重複収載しない。

A001、A002、C012は必須入力とする。A003-A007は成功した成果物だけを掲載し、一部が明示waiveされてもPartial reportを完成させる。個別Series／fallback ClusterのA003 sectionはFeature、N、Pearson r、Spearman r、Max |r|、correlation BH q、strict hitの7列へ限定し、相関上位3特徴量の散布図panelを埋め込む。
