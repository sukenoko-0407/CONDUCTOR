# CONDUCTOR 0.1.10 Policy

1. 人間の省略指示がない限り、全Description・全標準Clustering・A001/A002・C012を揃える。
2. FavorableはGlobal endpointの上位20%（`higher_is_better=false`は下位20%）。Cluster内で閾値を再定義しない。
3. 一次選抜Clusterと単独Cluster Seriesは既定N>=10かつFF>=0.50、複数Cluster SeriesはFF>=0.40。q値は補助表示でありgateではない。
4. C012は`min_ff_evaluate=10`のままLeiden resolutionを1.0～3.0で自動探索する。24件以下は自動進行する。該当がなければ`min_ff_evaluate=10,15,20,25,30`との全MatrixをSession内に示して人間が選ぶ。25～100件は人間承認可、101件以上は不可。
5. 定型解析はGlobalをcontrolとして必ず含める。Seriesの性能は独立検証とは表現しない。
6. 人間Reportは具体的な数値基準を示し、該当なしは一文と`参考・基準未達`一件に留める。
7. Failure時は同じNodeを修正・再試行する。Mainが独自CLIで代行しない。
8. Wall Time終了は同じRoundのpauseであり、自動で次Roundへ進まない。
9. MMP Type-I/II/IIIは1-cut、radius 0-2。観測データとAgent解釈を混同しない。
10. 定型MMP Type-Iは各Series／fallback Cluster Top 1だけを対象とする。上位K化合物の追加評価は、人間が対象IDを選びOn-demand Type-IIで実行する。
11. On-demandはREQ directoryだけへ書き、通常Stateを変えない。
12. DescriptionはProgram別Databaseから一致recordを再利用し、missだけを計算する。同一Programの同一ID・異構造はfail-fastとし、通常Runからrecordを上書き・削除しない。
