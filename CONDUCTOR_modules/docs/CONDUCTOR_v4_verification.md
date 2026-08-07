# CONDUCTOR 4.3.0 検証記録

## 1. 結果概要

2026-08-07にWindows開発環境で自動試験を実施し、**34件すべて合格**した。Catalog検証、Package配置検証、Skill環境を除くPython実装の構文検査も合格した。

```text
Ran 34 tests in 368.551s
OK
Validated 43 allowlisted capabilities
CONDUCTOR package layout is valid
```

本記録は、新しいRunを対象とするcontrol plane、代表的な科学計算Smoke、一般利用／CONDUCTOR利用の契約を確認した結果である。旧Stateのmigrationや後方互換は対象外である。

## 2. 確認済み項目

| 領域 | 確認内容 |
|---|---|
| State／DAG | schema検証、atomic write、lock、cycle拒否、依存関係、stale処理 |
| Round／ID | 複数Round、checkpoint/handoff、`ND/NG/NO/NI`、Run-global `G/E/F/H/Q/REL/REQ`の継続 |
| 基本計算 | 全Description計画、Direct structure Grouping、代表Description × Vector Clustering、高コスト一括gate |
| 初期・追加探索 | Global全Operator role、代表Group local計画、seed付きbalanced非復元抽出、重複signature回避 |
| 深掘り | Question gate、対象Group、兄弟Group、Global、Group間controlの比較bundle |
| Group管理 | Run-global Group ID、単一Boolean matrix、registry、compound ID保持 |
| MCS | `max_pairs <= 1000`、seed付きランダムpair sampling、`max_core_groups=300`既定 |
| Metric | 表現semantics優先。binary fingerprint=Tanimoto、D001=Euclidean、D017 SVD=Cosine |
| Operator | 一般モードの主要CSVのみ、CONDUCTORモードのCSV／Evidence／digest／HTML／manifest／event |
| Interpretation | State予約ID、selective Evidence、Markdown／HTML、Agent finalization、State ledger登録 |
| Package更新 | hash差分検出、未承認時のNode計画・実行停止、承認後の新snapshotと履歴 |
| 説明HTML | inline CSS、base64画像、主要なRun／Round／DAG／解析phase記載 |
| End-to-end | Description → Grouping → Operator → Interpretation → State登録の一連動作 |

## 3. 回帰確認の範囲

- 複数SMILES入力、invalid SMILES保持、重複compound ID拒否を確認した。
- Description variant、MCS乱択、Vector Clustering metric、SALI landscape Evidenceを確認した。
- JAK2 fixtureによるDescription回帰と、小規模SAR fixtureによる全体連鎖を確認した。
- Description／Grouping／Operatorの計算Kernelは、Metric判定の不備修正を除き変更していない。
- D001中の`FpDensityMorgan*`列名をfingerprintと誤認しないよう、Metric判定を列名依存からCatalog表現semantics優先へ修正した。

## 4. 静的整合性

- 43のallowlisted Skillが自己完結に必要な`SKILL.md`、`README.md`、code、schema、Pixi定義を持つ。
- `analysis_profile.json`が基本計算と初期探索の唯一の実行profileであり、旧`wide_shallow`固定選択はCapability metadata、Catalog、scaffoldから除去した。
- State、Evidence、Interpretation、profileの正本schemaとSkill内copyを同期した。
- `CONDUCTOR_modules/`はruntime read-onlyで、Run artifactは指定Run rootへ出力する。

## 5. 未実施の環境検証

次はWindows開発機では確認できていない。Linux HPCへ配置後の受入試験として実施する。

- 共有Pixi binary `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`
- Skill `env/`内のPixi環境、Pixi cache、uv cacheの実作成と複数利用者共有
- CPU 64 coreでの並列実行
- A100 1枚＋CPU 8 coreでのD019
- D020／tbliteのHPC実行
- shared filesystem上のlock、中断、長時間Roundのpause/resume
- 1,000～2,000化合物、多数Node／Evidenceでの性能benchmark

また、説明HTMLはDOM文字列、埋込み画像、link構造を自動検証したが、この環境ではbrowser接続を利用できなかったため実ブラウザでの目視確認は未実施である。

## 6. 既知の注意点

- 全Description、特に高コスト3D／学習済み／量子化学表現の全組合せgolden試験はHPC側で追加確認する。
- Package差分を同一Runへ承認して混在させる場合、以前のsnapshotも履歴へ残る。科学的比較ではNodeごとのRound、Capability version、artifact provenanceを確認する。
- `routine`分類は削除や永久除外ではない。新しいRelationや人間指示により再昇格できる。
- 多重探索による候補増加は設計上許容するが、Findingには比較経路、制約、反証状況を残す。

## 7. Linux HPC受入後の完了条件

未実施項目をHPCで確認し、環境差による既知問題を記録する。失敗時は科学計算Kernelとadapter／環境問題を分離して修正し、該当試験と全契約試験を再実行する。
