---
name: cs-analysis-matched-molecular-pairs
description: Perform one-cut human-centred MMP Type-I, Type-II, or Type-III analysis with radius 0-2 (A008).
allowed-tools: Read, Bash
---

# A008 MMP

- Type-I: 各Series／fallback ClusterのFavorable Top 1へ接続するMMPを列挙する。Globalは自動Targetに含めず、MMP 0件でも次順位を補充しない。
- Type-II: 人間指定の一つ以上のRun内`compound_id`周辺SARをOn-demandで表示する。定型Top 1より多い上位K化合物は、対象IDを明示してType-IIで調べる。near-coreはTanimoto>=0.70かつ両側MCS coverage>=0.60。
- Type-III: 人間が明示した場合だけ、Spotfire/再利用用の網羅CSVと派生SQLiteを作る。

全roleで1-cut、radius 0-2を標準とする。Type-I/IIの主役は観測MMPであり、Agentは最終化学判断を指定しない。

Type-I/IIのHTML表示ではTargetを常にTo、NeighborをFromへ正規化し、Favorable deltaもNeighbor→Target方向へ揃える。同じTarget–Neighborでは包含される小さいCoreを除き、包含関係にない最大Coreはすべて残す。Databaseと詳細CSVは縮約しない。Target全体SMILESは示すがNeighbor全体SMILES文字列は示さない。全体レポートは各analysis unitのTarget構造を4列で示す。対象別レポートの最上部には、Targetを中心、Attachment pointを含むExact Coreを中間、Neighborを外周とするMMP relationship mapを必ず置く。Neighbor cardには置換前fragment、Endpoint、改行したFavorable deltaを示し、Targetは紺、Exact Coreは緑、Neighborはオレンジで区別する。関係図は本文幅内の横長表示とし、Favorable delta順でExact Core上位3件・各CoreのNeighbor上位3件へ表示を限定した場合は、その掲載範囲を図中に明記して完全表示のSection 4へ誘導する。対象別レポートSection 1はTargetを単独行に置き、その下の折り畳み領域へNeighborを4列で並べ、すべて同じTarget座標を基準に整列する。Attachment pointを含むExact Coreごとにcard化し、Favorable delta上位5件を展開して残りを折りたたむ。各変換はNeighbor全体、Target全体、置換前fragment、置換後fragmentの1行4列で示し、Target全体の2D座標は共通構造を使ってNeighborへ整列する。Core画像は小さく左へ、MMP件数と最大Favorable deltaは右へ縦配置する。Section 4は主要galleryを先に置き、`表示内容`と`掲載範囲`を別々の折り畳みにし、詳細CSVリンクをSection末尾へ置く。掲載範囲には検出一意MMP数、最小変換への整理後件数、初期表示／折りたたみ件数、詳細CSVの接続行数を実データに応じて明記する。
Type-I/IIでは対象接続CSV・HTMLと`mmp_report_index.json`だけを保存し、包括的Summary群とSQLiteはType-IIIだけが保存する。対象別HTMLはTarget／Neighborの2D構造、基本情報表、Core／置換詳細表の固定テンプレートを使い、完全列はCSVへ残す。A009はindexから各analysis unitのTop 1 IDと対象別HTMLへの導線を作る。
Type-IIは、人間が同一RunのType-III `mmp_database.sqlite`を明示した場合だけ再利用する。入力CSV、Endpoint列、Favorable方向が一致しなければ拒否する。
