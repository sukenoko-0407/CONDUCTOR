# CONDUCTOR 識別子リファレンス

IDはRun内で通し番号を引き継ぎ、Roundが変わっても再初期化しません。

| ID | 対象 | 発行主体 |
|---|---|---|
| `RND####` | 解析Round | Runtime |
| `ND######` | Description Node | Runtime |
| `NC######` | Clustering Node | Runtime |
| `NA######` | Operator／Analysis Node | Runtime |
| `NI######` | Interpretation Node | Runtime |
| `ATT####` | 同一Node内の実行attempt | Runtime |
| `CL######` | Run-global Cluster | Clustering成功commit時のRuntime |
| `NA######@ATT####` | Global Operator result reference | Operator／Runtime |
| `NA######@ATT####/CL######` | Cluster-local Operator result reference | Operator／Runtime |
| `INS####` | Interpretation Insight | Interpretation commit時のRuntime |
| `ACT####` | Next Action | Interpretation commit時のRuntime |
| `CRQ######` | read-only Concierge request | Concierge |

`D###`、`C###`、`A###`、`I###`、`O###`はCatalogのCapability IDです。これらは実行instanceではありません。旧alpha版の`G`、`NG`、Finding／Hypothesis／Question／Evidence用IDは0.1.0では使用しません。
