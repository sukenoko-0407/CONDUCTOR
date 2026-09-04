---
name: cs-analysis-multidescription-feature-model
description: Build low-capacity OOF models for Global and every Series from the fixed D001/D002/D006/D013/D016/D019 panel (A005).
allowed-tools: Read, Bash
---

# A005 Series multi-Description model

固定6 Descriptionを結合し、GlobalとN>=30の全analysis unitを一括処理する。LocalとGlobalは同じ候補Description群から開始するが、欠損・定数列の除外とunivariate F-test上位最大24特徴量の選択は、各analysis unit・各outer foldのtraining dataだけで独立にfitするため、最終採用特徴量は異なり得る。低容量RidgeとOOF予測を用い、報告指標はOOF R2、OOF MAE、OOF Spearmanである。各local unitについて、Local（左）と同一化合物に対するGlobal（右）のOOF予測値対実測値を比較図へ保存する。
