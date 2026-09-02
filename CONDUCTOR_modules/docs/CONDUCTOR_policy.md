# CONDUCTOR 0.1.9 Policy

1. 人間の省略指示がない限り、全Description・全標準Clustering・A001/A002・C012を揃える。
2. FavorableはGlobal endpointの上位20%（`higher_is_better=false`は下位20%）。Cluster内で閾値を再定義しない。
3. Series候補は既定N>=10かつFF>=0.5。q値は補助表示でありgateではない。
4. Series数24以下は定型解析へ自動進行し、超過時だけ人間へ確認する。parameterを自動調整しない。
5. 定型解析はGlobalをcontrolとして必ず含める。Seriesの性能は独立検証とは表現しない。
6. 人間Reportは厳格hitだけを強調し、該当なしは一文とnear-miss一件に留める。
7. Failure時は同じNodeを修正・再試行する。Mainが独自CLIで代行しない。
8. Wall Time終了は同じRoundのpauseであり、自動で次Roundへ進まない。
9. MMP Type-I/II/IIIは1-cut、radius 0-2。観測データとAgent解釈を混同しない。
10. On-demandはREQ directoryだけへ書き、通常Stateを変えない。
