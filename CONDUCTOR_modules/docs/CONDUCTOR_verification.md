# CONDUCTOR 0.1.10 検証

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
uv run pytest -q tests/test_0110_contracts.py tests/test_0110_description_database.py
python .claude/skills/cs-conductor-runtime/scripts/build_catalog.py --check
```

静的検証ではCapability ID、選択Skill、必要file、Python syntax、Catalog/Profile Hash、共通実装の同期、基本計算範囲、MMP/On-demand契約を確認します。契約テストは入力ID、State transaction、Lease、Node既定値、Description Result、Cluster全化合物coverage、Series、MMP、On-demandの異常系を含みます。科学libraryとHPC並列処理を使う本番検証は各Skill LauncherとLinux Pixi環境で行います。
