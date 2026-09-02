---
name: cs-analysis-matched-molecular-pairs
description: Perform one-cut human-centred MMP Type-I, Type-II, or Type-III analysis with radius 0-2 (A008).
allowed-tools: Read, Bash
---

# A008 MMP

- Type-I: Globalおよび各解析単位のFavorable Top K（既定5）へ接続するMMPを列挙する。MMP 0件のTop化合物を補充しない。
- Type-II: 人間指定のRun内`compound_id`周辺SARをOn-demandで表示する。near-coreはTanimoto>=0.70かつ両側MCS coverage>=0.60。
- Type-III: 人間が明示した場合だけ、Spotfire/再利用用の網羅CSVと派生SQLiteを作る。

全roleで1-cut、radius 0-2を標準とする。Type-I/IIの主役は観測MMPであり、Agentは最終化学判断を指定しない。
Type-I/IIでは対象接続CSV・HTMLだけを保存し、包括的Summary群とSQLiteはType-IIIだけが保存する。
Type-IIは、人間が同一RunのType-III `mmp_database.sqlite`を明示した場合だけ再利用する。入力CSV、Endpoint列、Favorable方向が一致しなければ拒否する。
