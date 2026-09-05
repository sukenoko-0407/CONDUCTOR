# CONDUCTOR 0.1.10 検証

```bash
pixi run --manifest-path .claude/skills/cs-conductor-runtime/env/pixi.toml python CONDUCTOR_modules/tools/verify_package_layout.py
pixi run --manifest-path CONDUCTOR_modules/tests/env/pixi.toml contracts
pixi run --manifest-path .claude/skills/cs-conductor-runtime/env/pixi.toml python .claude/skills/cs-conductor-runtime/scripts/build_catalog.py --check
```

静的検証ではCapability ID、選択Skill、必要file、Python syntax、Catalog/Profile Hash、共通実装の同期、基本計算範囲、MMP/On-demand契約を確認します。契約テストは入力ID、State transaction、Lease、Node既定値、Description Result、Cluster全化合物coverage、Series、A003、A009 Template／link／件数監査、Schema異常系を含みます。`CONDUCTOR_modules/tests/env/.pixi/`はmachine-local test環境としてGit管理しません。科学libraryとHPC並列処理を使う本番検証は各Skill LauncherとLinux Pixi環境で行います。
