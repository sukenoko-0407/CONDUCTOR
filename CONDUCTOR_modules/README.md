# CONDUCTOR modules

このdirectoryはCONDUCTOR 0.1.1の共有定義packageです。Claude Codeが認識するAgent／Skill本体はProject rootの`.claude/agents/`と`.claude/skills/`に置き、ここにはCatalog、analysis profile、schema、Policy、template、検証toolを置きます。

## 構成

```text
CONDUCTOR_modules/
├── VERSION
├── catalog/
│   ├── catalog.json
│   ├── included_skills.json
│   └── analysis_profile.json
├── schemas/
├── docs/
├── tools/
└── tests/
```

`catalog.json`は各Skillの`capability.json`から生成しますが、収載対象は人間管理の`included_skills.json`で決まります。初手の基本計算・初期探索範囲は`analysis_profile.json`が正本です。

## Runtime write boundary

通常の解析中、`CONDUCTOR_modules/`はread-onlyです。State、artifact、Interpretation、audit、State report、Concierge responseはすべて`results/CONDUCTOR/<project>/<run-id>/`へ保存します。そのためRun停止中であれば、このdirectoryと対応する`.claude/skills/`／`.claude/agents/`を同じpackage版へ一括差し替えできます。

## Install

既存Projectへ組み込む場合は、`.claude/skills/`、`.claude/agents/`をProject rootへ配置し、このdirectoryを`<project>/CONDUCTOR_modules/`として配置します。`tools/install_into_project.py`と`tools/verify_package_layout.py`を利用できます。

## Environment

各Skillは`env/pixi.toml`とlauncherを持ちます。Linuxでは共有Pixi binaryを優先し、環境・cache・temporary fileをSkillの`env/`配下に限定します。初回にlock／environmentを構築し、以後はlocked environmentを再利用します。

詳細は[docs/README.md](docs/README.md)を参照してください。alpha版Runの汎用migrationは提供しません。0.1.0から0.1.1へは、成功済みDescriptionだけを新規Runへ引き継ぐ専用Patchがあります。
