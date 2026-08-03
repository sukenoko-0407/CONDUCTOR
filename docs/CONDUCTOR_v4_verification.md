# CONDUCTOR v4 検証記録

検証日: 2026-08-03

## 自動試験

Windows、Python 3.12.12の既存`.venv`で次を実行した。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

結果: 19 tests passed。

確認範囲:

- allowlist収載48 Skillの自己完結構成、命名、Linux/Windows Pixi platform
- Catalogと人間管理allowlistの一致、capability ID一意性、高コスト承認属性
- root JSON Schemaの構文
- CSVと複数SMILES入力
- Description、Clustering、Operator、Interpretationの通常モードがCONDUCTOR補助artifactを出さないこと
- 不完全な`--conductor` context、通常モードへの`--project`／`--node-id`混入、廃止済み`--metadata`をCLIが拒否すること
- D001 → C001 → A002 → I001のCONDUCTOR artifact chain
- execution eventがproject、run ID、node IDを持ち、State contextと照合されること
- State dependency、承認gate、downstream traversal
- manifest、evidence、execution event、InterpretationのJSON Schema検証
- `chemble_jak2.csv`全231行のD001 regression
- Orchestrator SubagentのSkill呼出し権限と人間確認権限
- invalid SMILESのDescription／Grouping行保持と重複ID拒否
- C018がoverlapを持つlong形式membershipの反復compound IDを受理すること
- Stateの`start`による並列slot消費、`failed`の自動再試行抑止
- 上流変更時のdomain/evidence graph node stale化
- Morgan chiralityとGobbi Pharm2D SVDが統合Skillのparameter variantとして動作すること
- Stateが計画と異なるvariant configurationを拒否すること
- capability別`--help`が無関係なalgorithm optionを表示しないこと

追加の静的確認:

- `.claude`、`tools`、`tests`のPython 106 fileに対する書込みなし構文検査
- 全48 Pixi manifestのTOML parse
- 全Pixi manifestが`linux-64`と`win-64`を宣言
- Catalog builderによる48 capability metadata検証
- 全47個別実行Skillのmode文書、algorithm固有option、CLI guard、runner/template/schema完全一致
- 全48 Skillの`--help`またはOrchestrator管理CLIのhelp成功
- UTF-8 modeでSkill Creator validatorを実行し、全48 Skillが成功

## 手動smoke test

`tests/data/small_sar.csv`と`chemble_jak2.csv`を使用した。統合・CLI絞り込み後に、承認対象を除く43実行を再度横断smoke testした。

- Description: D001～D010、D012～D015、D017 folded、D017 SVD
- Grouping: C001、C003～C018
- Operator: A001～A010
- Interpretation: I001のJSON、Markdown、HTML生成、およびJSON編集後の再render
- State: init、plan-wide、record、runnable、resume、入力・設定変更による下流stale化
- domain graphへのgroup登録とevidence graphへのevidence依存登録
- 一般モードでのMorgan chiral variantとGobbi Pharm2D SVD variant
- CONDUCTOR Stateでのvariant parameter記録、event configuration照合、mismatch拒否

## 意図的に未実行の項目

- C002 structure MCS: 高コスト
- D016 Mordred 3D: 高コスト
- D019 pretrained embedding: GPUおよびローカルmodel weightが必要
- D020 tblite/xTB: 非常に高コスト

上記はPolicyにより人間承認前に実行していない。実装、capability別CLI、manifest、Catalog収載、Pixi環境定義は静的検証対象に含めた。D011とD018はそれぞれD002、D017へ統合したため実行対象の欠落ではなく、IDを欠番として保持している。

## 環境に関する制約

検証WindowsマシンにはPixi実行ファイルがなく、Linux用共有パスも存在しないため、各`pixi.toml`の実solveと環境作成は未検証である。全launcherが共有Pixiを優先し、Skill内manifestを絶対パス指定し、Pixi/uv等のcacheと一時領域を`<skill>/env/`配下へ強制することは静的検証した。受入時にLinux HPC/SIFでlauncher経由の`--help`と代表Skillのsmoke testを行い、`<skill>/env/.pixi/envs/default/`と`<skill>/env/cache/`が作成されること、processのfile write監査でworking directory外への書込みがないことを確認する。Windows対応を検証する場合はPATH上にPixiを導入して同じ試験を行う。
