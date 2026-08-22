# CONDUCTOR modules

CONDUCTOR 0.1.5の共有定義packageです。Claude Codeが認識するAgent／SkillはProject rootの`.claude/`、Catalog、Policy、schema、Runtime、template、testは`CONDUCTOR_modules/`へ置きます。

```text
project/
├── .claude/agents/
├── .claude/skills/
└── CONDUCTOR_modules/
    ├── VERSION
    ├── catalog/
    ├── schemas/
    ├── docs/
    ├── tools/
    └── tests/
```

`catalog.json`は各Skill metadataから生成しますが、収載対象は人間管理の`included_skills.json`、初手解析範囲は`analysis_profile.json`で決まります。

解析中、このdirectoryと`.claude/`はread-onlyです。Control、DAG、artifact、Interpretation、audit、State report、Concierge responseはすべてRun Rootへ書きます。したがってRun停止中ならpackage一式を同じVersionへ差し替えられます。

各Skillは`env/pixi.toml`を持ちます。Linuxでは`/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、cacheとtemporary fileをSkillの`env/`配下へ限定します。

既存Projectへは`.claude/`をProject rootへ、modulesを`CONDUCTOR_modules/`へ配置します。詳細は[docs/README.md](docs/README.md)を参照してください。旧VersionのRun migrationは提供しません。
