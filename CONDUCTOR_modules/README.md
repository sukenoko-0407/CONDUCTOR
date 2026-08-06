# CONDUCTOR package

このディレクトリは、既存ProjectへCONDUCTORを組み込むための管理moduleである。Claude Codeが自動検出するAgentとSkillだけをProject直下の`.claude/`へ置き、その他のCONDUCTOR固有資産をここへ集約する。

## 配置

```text
<project-dir>/
├── .claude/
│   ├── agents/cs-conductor-*.md
│   └── skills/cs-*/
├── CONDUCTOR_modules/
│   ├── catalog/
│   ├── docs/
│   ├── schemas/
│   ├── tools/
│   ├── tests/
│   ├── pyproject.toml
│   └── uv.lock
└── results/CONDUCTOR/       # run開始後に生成
```

`.claude/`を`CONDUCTOR_modules/`の下へ移動しない。SkillとSubagentがClaude CodeからProject local componentとして検出されなくなる可能性がある。

## 既存Projectへの導入

このrepositoryをsource packageとして、対象Projectに未導入の場合は次を実行する。既定はdry-runであり、`--apply`を付けるまで書き込まない。

```bash
python CONDUCTOR_modules/tools/install_into_project.py --target /path/to/project
python CONDUCTOR_modules/tools/install_into_project.py --target /path/to/project --apply
```

installerは既存の`.claude/`自体を置換せず、CONDUCTORの2 Agent、allowlist収載Skill、`CONDUCTOR_modules/`だけを追加する。同名のAgent、Skill、moduleがすでに存在する場合は停止するため、既存内容とのmergeは人間が判断する。

手動導入では、Project rootへ`.claude/agents/cs-conductor-*.md`、allowlist収載された`.claude/skills/cs-*`、`CONDUCTOR_modules/`を同じ相対配置でコピーする。

一般利用だけが目的なら、必要な個別Skillを`.claude/skills/`へ単独コピーして実行できる。Skillは自身が置かれた最も近いProjectを出力先として認識する。`--conductor`を使う全体運用では、Agent群と`CONDUCTOR_modules/`を含む完全配置を使用する。

導入先の`.gitignore`には、必要に応じて`CONDUCTOR_modules/gitignore.snippet`の内容をmergeする。installerは既存Projectの`.gitignore`を自動変更しない。

## 配置確認

対象Projectのrootで次を実行する。

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-orchestrator/scripts/launch.py catalog --check
```

後者は各SkillのPixi環境を使用する。Linuxでは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先する。

## 実行時の保存先

管理資産は`CONDUCTOR_modules/`に置くが、解析結果はProjectの成果物として`<project-dir>/results/CONDUCTOR/<project>/<run-id>/`へ保存する。一般モードの各Skillも従来どおり`<project-dir>/results/<stage>/`を既定とする。

通常の解析runでは`CONDUCTOR_modules/`を読み取り専用として扱う。State、Group index、Evidence、Interpretation、session handoffを含むrun固有情報はすべて`results/CONDUCTOR/`側へ保存するため、停止中であれば解析履歴を失わずにこのdirectoryを丸ごと差し替えられる。ただし、Project rootの`.claude/skills/`と`.claude/agents/`はmodule内のCatalog・Schema・Policyと同じpackage版へそろえて更新する。

例外は人間が明示的に行うpackage保守操作である。`catalog --write`はCatalogと生成Markdownを更新し、`tools/scaffold_v4_skills.py`はSkill雛形と未設定の収載リストを生成し得る。installer、test、検証toolも導入先やPython cacheへ書き込む場合がある。これらは解析runの一部として実行しない。

## カスタマイズ

- Skill収載対象: `catalog/included_skills.json`
- 機械Catalog: `catalog/catalog.json`
- Orchestration Policy: `docs/CONDUCTOR_v4_policy.md`
- Interpretation Policy: `docs/CONDUCTOR_v4_interpretation_policy.md`
- Claude Codeへの解析依頼テンプレート: `docs/prompt/CONDUCTOR_analysis_request_prompt.md`
- セッション引継ぎテンプレート: `docs/prompt/CONDUCTOR_session_handoff_template.md`
- Skill生成・保守: `tools/`と`schemas/`

Catalog収載変更後はOrchestratorの`catalog --write` commandで再生成し、差分を確認する。引数なし、または`--check`は読み取り専用の検証である。

## Windowsでの注意

Windowsでは、Projectを深い階層へ配置すると、Skill名とCONDUCTORのrun出力階層を合わせたパスが環境側の長さ制限に達する場合がある。可能な限り短いProject pathを使用し、必要に応じてOSとPythonでlong pathを有効化する。
