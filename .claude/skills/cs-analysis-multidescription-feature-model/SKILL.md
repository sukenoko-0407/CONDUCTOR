---
name: cs-analysis-multidescription-feature-model
description: Build low-capacity OOF models for Global and every Series from the fixed D001/D002/D006/D013/D016/D019 panel (A005).
allowed-tools: Read, Bash
---

# A005 Series multi-Description model

固定6 Descriptionを結合し、GlobalとN>=30の全Seriesを一括処理する。低容量RidgeとOOF予測を用い、報告指標はOOF R2、OOF MAE、OOF Spearmanである。予測性能は独立Testではなく、Endpointで選抜したSeriesにはselection biasがある。
