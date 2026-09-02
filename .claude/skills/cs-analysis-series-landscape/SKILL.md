---
name: cs-analysis-series-landscape
description: Compare D002 Tanimoto SALI and strict internal/boundary cliff signals across Global and every Series (A006).
allowed-tools: Read, Bash
---

# A006 Series landscape

D002 MorganにはTanimotoだけを用いる。Globalと各解析単位のSALIを計算し、Tanimoto>=0.8かつEndpoint差>=Global IQRをCliff候補とする。条件を満たすinternal／boundary pairは`A006_cliff_pairs.csv`へ保存する。境界Cliffはsupport>=3かつSeries側へのFavorable方向率>=0.8だけを人間向けhitとする。該当なしは最も近い一件だけを報告する。
