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

Type-I/IIのHTML表示ではTargetを常にTo、NeighborをFromへ正規化し、Favorable deltaもNeighbor→Target方向へ揃える。同じTarget–Neighborの複数行は、より大きいCoreを持つ最小変換1件へ表示上だけ縮約する。Databaseと原本CSVは縮約しない。Target全体SMILESは示すがNeighbor全体SMILES文字列は示さず、最終sectionでNeighbor全体、置換前fragment、置換後fragmentの2D画像を1行3列で列挙する。
Type-I/IIでは対象接続CSV・HTMLだけを保存し、包括的Summary群とSQLiteはType-IIIだけが保存する。対象別HTMLはTarget／Neighborの2D構造、基本情報表、Core／置換詳細表の固定テンプレートを使い、完全列はCSVへ残す。
Type-IIは、人間が同一RunのType-III `mmp_database.sqlite`を明示した場合だけ再利用する。入力CSV、Endpoint列、Favorable方向が一致しなければ拒否する。
