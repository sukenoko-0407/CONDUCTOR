---
name: cs-analysis-series-descriptor-contrast
description: Batch A003 Global-versus-Series D001 descriptor shifts and descriptor-endpoint correlations.
allowed-tools: Read, Bash
---

# A003 Series descriptor contrast

D001のみを用い、Globalと全解析単位についてPearson/Spearman相関、相関gain、median shift/global IQRを一括計算する。人間向けhitは`|r|>=0.4`、gain>=0.2、q<=0.05、または`|median shift/global IQR|>=0.75`かつq<=0.05に限定する。該当なしでも最も近い一件だけを短く示す。
