---
name: cs-analysis-series-projection-panel
description: Fit Global D002 PCA and UMAP once, overlay each Series, and render individual and four-column contact-sheet images (A004).
allowed-tools: Read, Bash
---

# A004 Series projection panel

D002 Morgan空間へGlobal PCA/UMAPを一回だけfitし、同一座標上で各Seriesを強調する。SeriesごとのPCA、UMAP、左右連結図に加え、PCAとUMAPを別々の`ceil(K/4) x 4` contact sheetへまとめる。他のDescriptionは人間指示のOn-demand解析で扱う。
