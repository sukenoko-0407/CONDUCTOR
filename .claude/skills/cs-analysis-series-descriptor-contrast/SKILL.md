---
name: cs-analysis-series-descriptor-contrast
description: Batch A003 Global-versus-analysis-unit correlations for the fixed interpretable D001, D012, D015, D016, and D019 descriptor panel.
allowed-tools: Read, Bash
---

# A003 Series descriptor contrast

D001、D012、D015、D016、D019を用い、Globalと全analysis unitについてPearson/Spearman相関、相関gain、median shift/global IQRを一括計算する。D001・D012・D019は利用可能な全数値特徴量、D015はacid/base・元素組成・芳香族性・ring count・polarizability、D016は分子geometry・部分表面積の厳選特徴量を対象とする。相関hitは`|r|>=0.60`、gain>=0.20、BH q<=0.05とする。各Series／fallback Clusterでは`max(abs(Pearson r), abs(Spearman r))`上位3特徴量の単一特徴量–Endpoint散布図を一つのpanel PNGにし、Description ID、順位、特徴量をJSON索引へ保存する。
