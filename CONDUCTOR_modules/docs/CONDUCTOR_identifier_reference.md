# CONDUCTOR identifier reference

| ID | 意味 | 例 | 発行主体 |
|---|---|---|---|
| `D###` | Description capability | D002 | Catalog／人間 |
| `C###` | Clustering capability | C005 | Catalog／人間 |
| `A###` | Operator capability | A008 | Catalog／人間 |
| `I###` | Interpretation capability | I001 | Catalog／人間 |
| `O###` | 制御・補助capability | O001 | Catalog／人間 |
| `RND####` | 人間が開始した解析Round | RND0002 | Dispatcher／Runtime |
| `N######` | Run全体で一意の実行Node | N000125 | Runtime |
| `ATT####` | 同一Node内の実行attempt | ATT0002 | Runtime |
| `C######` | Run全体で一意のCluster | C000041 | Runtime |
| `INS######` | Run全体で一意のInsight | INS000023 | Runtime commit |
| `REQ######` | Concierge依頼 | REQ000004 | Concierge |

旧alpha版の`ND/NC/NA/NI`、`F/H/E/Q/R/ACT`体系は使用しません。追加解析案はInsight内の文章であり、独立した永続IDやstatusを持ちません。
