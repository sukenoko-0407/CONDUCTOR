# CONDUCTOR v4 検証記録

検証日: 2026-08-04

## 自動試験

Windows、Python 3.12.12の既存`.venv`で、State、Repository契約、Runtime smokeを分割して実行した。OneDrive配下ではSkillごとのprocess起動が遅いため、Runtime smokeは全methodを複数batchに分けた。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_state_manager -v
.\.venv\Scripts\python.exe -m unittest tests.test_v4_contracts.RepositoryContractTests -v
# RuntimeSmokeTestsの全methodを複数batchで実行
```

結果: 33 tests passed（State 12、Repository契約6、Runtime smoke 15）。

確認範囲:

- allowlist収載42 Skillの自己完結構成、命名、Linux/Windows Pixi platform
- Catalogと人間管理allowlistの一致、capability ID一意性、高コスト承認属性、およびC002の`preauthorized_initial`例外
- root JSON Schemaの構文
- CSVと複数SMILES入力
- Description、Clustering、Operator、Interpretationの通常モードがCONDUCTOR補助artifactを出さないこと
- 不完全な`--conductor` context、通常モードへの`--project`／`--node-id`混入、廃止済み`--metadata`をCLIが拒否すること
- D001 → C001 → A002 → I001のCONDUCTOR artifact chain
- execution eventがproject、run ID、node IDを持ち、State contextと照合されること
- State dependency、承認gate、downstream traversal
- `representative-family-wide-v1`がDescription 7、Grouping 9、Operator 36の計52 nodeへ展開され、3DのD013と承認不要の必須初手C002 MCSを含むこと
- C005、C006、C007、C009、A001、A004、A006等がCatalog指定sourceへ個別bindingされ、vector Clusteringがrun元CSVや最初のDescriptionへ暗黙接続されないこと
- A005/A006の表現別parameter overrideがStateへ保存され、初手でD004→cosine、D007→Tanimoto、D002→Tanimoto、D013→Manhattan、D017→Tanimotoとなること
- vector Clusteringの`auto` Metricが表現に追従し、binaryまたは既知のbit fingerprintへTanimoto以外を拒否すること
- MCS pair capがseed付き一様ランダム非復元抽出であり、先頭pair抽出を行わないこと
- pairwise構造Operatorのpair capもseed付き一様ランダム非復元抽出であること
- direct structure Grouping 4 SkillがSMILES入力かつDescription非依存、Description-vector Clustering 6 SkillがDescription CSV入力かつDescription依存であること
- 旧SMILES-to-Morgan clustering wrapper 6 Skillが現役directoryとallowlistに存在しないこと
- 初手DAGの再計画がnodeを重複生成せず、node固有`<node-id-safe>`出力先が衝突しないこと
- `wide_shallow` nodeが`deep_dive`より優先され、初手がterminalになるまでInterpretationを開始できないこと
- manifest、evidence、execution event、InterpretationのJSON Schema検証
- `chemble_jak2.csv`全231行のD001 regression
- Orchestrator SubagentのSkill呼出し権限と人間確認権限
- invalid SMILESのDescription／Grouping行保持と重複ID拒否
- C012 meta-overlapがoverlapを持つlong形式membership、およびcompound IDがshard間で反復するBoolean wide matrixを受理すること
- binary DescriptionへのTanimoto clustering、binary vectorへの非Tanimoto metric拒否、raw SMILESのvector Skill入力拒否
- 承認対象の高コストnodeの拒否または上流失敗時に、実行不能な下流nodeを理由付き`skipped`へ伝播すること
- Stateの`start`による並列slot消費、`failed`の自動再試行抑止
- 上流変更時のdomain/evidence graph node stale化
- Morgan chiralityとGobbi Pharm2D SVDが統合Skillのparameter variantとして動作すること
- Stateが計画と異なるvariant configurationを拒否すること
- Group IDがrun内で一意であり、`group_registry.csv`とBoolean `Cpd_Group_matrix_*.csv`へ記録され、discardが履歴を削除しないこと
- A006がMorgan表現をTanimotoへ自動解決し、Morganへのcosine指定を拒否すること。SALIの中央値・上側分位点・上位pairがevidenceへ残り、I001へfocus pairとして伝わること
- A006をglobal、within-group、between-groupsで実行し、scope、標本数、global前処理基準、固有evidence ID、およびI001のglobal-local関係候補が保持されること
- 専用Interpretation Agent、正本Interpretation Policy、Skill内Policy snapshot、探索Plan schemaの整合
- Interpretation探索budget、seed、iteration、必須反証、analysis signature重複拒否、terminal Interpretation依存拒否のState制御
- matched random等の明示compound scopeがrun inputと照合され、content-addressed membershipとして記録され、同一scopeの再登録が拒否されること
- capability別`--help`が無関係なalgorithm optionを表示しないこと
- 全42 Skillの人間向けREADMEが指定6 section、利用例、version 1.0.0の変更履歴を持ち、60行以内であること

追加の静的確認:

- `.claude`、`tools`、`tests`の現役Python 94 fileに対する書込みなし構文検査
- 全42 Pixi manifestのTOML parse
- 全Pixi manifestが`linux-64`と`win-64`を宣言
- Catalog builderによる42 capability metadata検証とGrouping taxonomy検証
- 全41個別実行Skillのmode文書、algorithm固有option、CLI guard、runner/template/schema整合
- 全41個別実行Skillと開発templateのCONDUCTOR既定出力が`<skill>/<node-id-safe>/`で一致すること
- 全41実行Skillの`--help`およびOrchestrator管理CLIのhelp成功
- UTF-8 modeでSkill Creator validatorを実行し、全42 Skillが成功

## 手動smoke test

`tests/data/small_sar.csv`と`chemble_jak2.csv`を使用した。Grouping整理後、実Description artifactを生成して現役Groupingを横断smoke testした。

- Description: D001～D010、D012～D015、D017 folded、D017 SVD
- Grouping: C001～C011を実Descriptionまたは元SMILES／カテゴリ入力で実行。C002 MCSは必須初手かつ承認不要であることをsmall SAR入力で確認。C012 meta-overlapはlong membership fixtureとBoolean wide matrix shardで実行
- Operator: A001～A010
- Interpretation: I001のJSON、Markdown、HTML生成、HTMLの全監査section、およびJSON編集後の再render。代表reportをローカルEdgeで描画し、探索概要、発見候補、矛盾、反証、negative result、監査情報の視認性を目視確認
- State: init、plan-wide、record、runnable、resume、入力・設定変更による下流stale化
- State: 承認対象高コストnodeの承認拒否と上流failureによるblocked descendant skip伝播
- domain graphへのgroup登録とevidence graphへのevidence依存登録
- 一般モードでのMorgan chiral variantとGobbi Pharm2D SVD variant
- CONDUCTOR Stateでのvariant parameter記録、event configuration照合、mismatch拒否
- D002 Morgan bit CSVからC005/C008/C009/C010へTanimoto入力し、D001のdense continuous CSVからC006/C007へ標準化Euclideanを自動選択するartifact chain

## 意図的に未実行の項目

- D016 Mordred 3D: 高コスト
- D019 pretrained embedding: GPUおよびローカルmodel weightが必要
- D020 tblite/xTB: 非常に高コスト

上記はPolicyにより人間承認前に実行していない。C002 MCSはこの対象から外し、承認不要の必須初手として実行検証した。実装、capability別CLI、manifest、Catalog収載、Pixi環境定義は静的検証対象に含めた。D011とD018はそれぞれD002、D017へ統合したため実行対象の欠落ではなく、IDを欠番として保持している。旧`structure-butina`等6 SkillはMorgan生成とvector Clusteringの責務重複を解消するため、`Archive/v4-retired-clustering-wrappers/`へ退避した。

## 環境に関する制約

検証WindowsマシンにはPixi実行ファイルがなく、Linux用共有パスも存在しないため、各`pixi.toml`の実solveと環境作成は未検証である。全launcherが共有Pixiを優先し、Skill内manifestを絶対パス指定し、Pixi/uv等のcacheと一時領域を`<skill>/env/`配下へ強制することは静的検証した。受入時にLinux HPC/SIFでlauncher経由の`--help`と代表Skillのsmoke testを行い、`<skill>/env/.pixi/envs/default/`と`<skill>/env/cache/`が作成されること、processのfile write監査でworking directory外への書込みがないことを確認する。Windows対応を検証する場合はPATH上にPixiを導入して同じ試験を行う。
