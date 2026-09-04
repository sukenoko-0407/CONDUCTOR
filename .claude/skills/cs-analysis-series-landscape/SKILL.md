---
name: cs-analysis-series-landscape
description: Compare D002 Tanimoto SALI and strict internal/boundary cliff signals across Global and every Series (A006).
allowed-tools: Read, Bash
---

# A006 Series landscape

D002 ECFP4（Morgan radius 2、2048 bit）にはTanimotoだけを用いる。Globalと各analysis unitのSALIを計算し、Tanimoto>=0.75かつabsolute Endpoint差>=Global Endpoint IQRをCliff候補とする。条件を満たすinternal／boundary pairは`A006_cliff_pairs.csv`へ保存する。境界Cliffはsupport>=3かつunit側へのFavorable方向率>=0.8だけをhitとする。Summary CSVにはFavorable方向の件数も保持し、HTMLでは`Favorable件数 / Boundary cliff件数`で示す。
