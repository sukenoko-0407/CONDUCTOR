# CONDUCTOR 4.3.0 SAR解析基盤：合意事項

この文書は構想議論から確定した設計判断を簡潔にまとめる。詳細仕様は[設計仕様](CONDUCTOR_v4_design_spec.md)、行動規則は[Orchestration Policy](CONDUCTOR_v4_policy.md)と[Interpretation Policy](CONDUCTOR_v4_interpretation_policy.md)を正本とする。

## 1. 目的

単一の全体説明を作ることではなく、複数DescriptionとGroupingを使って全体／局所の変化を検出し、異なる表現、Operator、Groupを突き合わせて人間が見落としやすいSAR上の知見候補を発見する。

## 2. 複数Round

1 Runは複数Roundを前提とする。Roundは人間の指示からOrchestratorの成果またはcheckpointまでであり、同じStateを別Claude Code sessionから継続できる。Round間ではFinding、Hypothesis、Question、Relationをrun-global IDで引き継ぐ。

## 3. 解析Phase

- **基本計算**: 全実行可能Descriptionと、異なるDescription family代表に対する全適用可能Grouping。高コストDescriptionを含み、Runごとに一括承認する。
- **初期探索**: 全体の全applicable Operator、Grouping-wide screen、各Groupingの代表Groupに対する全applicable local Operator。
- **追加探索**: 未実行cellをcoverage不足で層化したseed付きランダム非復元抽出。
- **深掘り**: FindingやQuestionから、同一Groupの別Operator、sibling Group、global comparator、異Description、反証を比較する。

基本計算・初期探索・追加探索はcoverage中心、深掘りはQuestion中心とする。

## 4. 計算Skill

Description、Grouping、Operatorの科学計算Kernelは現行機能を原則維持する。変更の中心はCONDUCTOR adapter、metadata、Evidence、report、State連携である。新しい数値計算が必要な場合は既存手法の意味を黙って変更せず、別Operatorまたはaggregatorとして追加する。

各Skillは単独コピー可能であり、一般利用では`--conductor`を付けない。

## 5. Group

Direct structure GroupingとDescription-vector Clusteringを分ける。Groupは排他的とは限らず、一化合物の複数所属を許容する。run-global Group ID、Boolean membership matrix、registryで由来と所属を管理する。

排他的partition、重複Group、noiseを区別する。代表Groupは通常2～4で、サイズ、局所性、構造凝集性、Endpoint dispersion、既選択Groupとの重複を役割として選ぶ。

## 6. OperatorとLandscape

Operatorは全体だけでなくGroup内・Group間へ適用する。metricは入力Descriptionの性質から決定する。SALIはLandscapeの平滑性・起伏としてmedian、upper tail、有効pair、top pairを確認し、異metricのraw値を直接比較しない。

排他的Groupingでは、同じDescription・metricのGroup別SALIやEndpoint varianceを比較し、局所化によるLandscape変化をrankingする。重複Groupを母集団partitionとして扱わない。

## 7. Interpretation

Interpretationは作業記録ではなく人間向けの解釈reportである。全Evidence全文を毎回読まず、全digestを確認してから新規・重要・未評価・Question関連・反証候補へdrill-downする。

Finding、Hypothesis、Question、Relationを区別する。Questionはすべて深掘りせず、人間が`allow/skip/defer`を指定できる。重要度は可変で、routine Evidenceも後の関係から再昇格できる。

## 8. State

DAGは計算依存と再開を管理する。Round、coverage、Question、salienceは別ledgerで管理する。Stateは小さいcontrol planeとし、巨大なmembership、全Evidence本文、過去Interpretation全文を格納しない。

## 9. 成果物

人間の主成果物は`interpretation.md/html`である。個別Operator HTMLへ遡れる。Agentの次Round入口は`state_summary.json`、`round_summary.json`、`next_round_brief.json`、Evidence digestである。

## 10. 互換性

旧Stateと旧成果物は新Runへimportしない。旧runはread-onlyで保存できるが、新仕様は最初から再実行する。後方互換層やmigration utilityは実装しない。

## 11. 実行環境

Linux HPCを標準とし、CPU処理は64 cores、GPU処理はA100 1枚＋CPU 8 coresを想定する。各Skillは`env/pixi.toml`を持ち、共有Pixi binary、Skill内cache、Skill内environmentを使用する。Windowsではplanning、schema、主要な小規模実行に対応する。
