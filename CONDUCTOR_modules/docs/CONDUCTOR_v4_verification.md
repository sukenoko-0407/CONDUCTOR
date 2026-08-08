# CONDUCTOR 4.3.1 検証記録

## 1. 結果概要

2026-08-08にWindows開発環境で自動試験を実施し、**41件すべて合格**した。内訳はState／control／migration 16件、Repository契約10件、科学計算Smoke 15件である。

```text
State/control/migration: OK (16 tests)
Repository contracts:   OK (10 tests)
Scientific smoke:       OK (15 tests, 259.277s)
Validated 44 allowlisted capabilities
CONDUCTOR package layout is valid
```

テストは `uv run --with jsonschema python -m unittest ...` で実行した。Description／Grouping／Operatorの数値Kernelは変更せず、CONDUCTOR manifest versionだけを4.3.1へ同期した。

## 2. 確認済み項目

| 領域 | 確認内容 |
|---|---|
| 単一Writer | bootstrap lease取得、別Orchestratorのread-only退出、heartbeat、token付き変更 |
| State／DAG | schema 2.1、atomic write、cycle拒否、Node ID一意性、依存関係、stale処理 |
| Node retry | 同じNode ID内の`TRY###` attempt追加、parallel limitのstart時再検査 |
| bounded状態 | `state_summary.json`と`orchestrator_brief.json`、固定action code、phase順序 |
| Round | deadline、Interpretation reserve、stop reason、複数Round、handoff |
| Interpretation gate | 成功Operator後、JSON／Markdown／HTMLなしのcheckpoint／completed拒否 |
| Audit | Quick／Full、`run_root/audit/<timestamp>/`、State非変更、artifact検査 |
| 基本・初期探索 | 全Description、MCSを含むGrouping、Global全Operator、Local batch計画 |
| 追加探索 | Round累積上限、seed付きbalanced非復元抽出、candidate pool exhaustion |
| Group／Metric | Run-global Group ID、Boolean matrix、binary=Tanimoto、表現semantics優先 |
| Operator | 一般モード主要CSV、CONDUCTORモードCSV／Evidence／digest／HTML／manifest／event |
| 移行 | source非変更、dry-run、旧→新Node ID対応、検証済みartifact copy、旧Interpretation除外 |
| Package | 44 Catalog Skill、1 maintenance Skill、3 Agent、installer／layout検証 |
| End-to-end | Description → Grouping → Operator → Interpretation → State登録 |

## 3. v4.3.0移行試験

合成した旧Runの`ND0999`と`NO1500`を、新run rootの`ND0001`と`NO0001`へ依存順に再附番した。旧`NI0900`はactive DAGへ入れず参照用とし、新`RND0002`でfresh Interpretationを必須にした。

移行前後でsource `state.json` hashが不変であることを確認した。またscan後にsource artifactを変更したケースでは、target作成前にapplyが拒否されることを確認した。Groupingを含むケースでは、Group registry、Group件数、Node別membership索引を新run rootに再構築できることも確認した。

## 4. 科学Kernel回帰

- 複数SMILES、invalid SMILES保持、重複compound ID拒否
- Description variant、JAK2 fixture回帰、Gobbi Pharm2D SVD
- Direct／Vector Clustering、MCS seed乱択とpair上限、meta overlap
- binary fingerprintのTanimoto強制、SALI representation metric
- Operator一般出力、CONDUCTOR Evidence／HTML
- end-to-end artifact chainと未計画variant拒否

## 5. 未実施の環境検証

Linux HPCへ配置後、次を受入試験する。

- 共有Pixi binary `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`
- Skill `env/`内のPixi／uv cacheと複数利用者共有
- CPU 64 core、A100 1枚＋CPU 8 core
- D019、D020／tbliteの長時間実行
- shared filesystem上のlease、atomic replace、異常停止、takeover
- 1,000～2,000化合物、多数Group／Node／Evidenceでの性能benchmark

## 6. 既知の制約

- Migrationは4.3.0／State schema 2.0.0だけを対象とする。重複Node ID、cycle、重複Evidence ID、検証不能artifactは推論で修復せず停止または除外する。
- 旧Interpretationは4.3.1のactive knowledgeとして信用せず、新しいInterpretationを作成する。
- Wall Timeは最大予算であり、OS job schedulerそのものではない。Runtimeはdeadlineとreserveで新規科学実行を停止するが、外部HPC jobの強制終了は行わない。
- `routine`分類は削除や永久除外ではなく、後続Evidenceから再昇格できる。

## 7. Linux HPC受入後の完了条件

未実施項目をHPCで確認し、共有filesystemと長時間jobに固有の問題を記録する。失敗時は科学Kernel、Runtime制御、Pixi環境、scheduler連携を分けて修正し、該当試験と全契約試験を再実行する。
