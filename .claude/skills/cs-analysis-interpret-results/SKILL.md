---
name: cs-analysis-interpret-results
description: Use when the dedicated Claude Code Interpreter must validate an ID-free Japanese draft built from a Runtime-bounded evidence set. It compares existing Operator results but never executes new scientific analysis or mutates State.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# SAR result interpretation

## Purpose

専用Interpretation Policyに従い、複数Operator result、Cluster局所性、依存関係、失敗を読み取り専用で比較する。

## Input

`--context`、Interpreterが作成したID未付与の`--draft`、新規の`--output-dir`を指定する。Runtimeが対象result、scope、正式IDを管理する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. Runtimeが作成したcontextとdraftを確認し、許可されたOperator resultだけを扱う。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. `--output-dir`には存在しない新規directoryを指定する。既存出力を上書きしない。
5. 実行後にpreview JSON／Markdown／HTMLを確認する。正式成果物はRuntimeだけがcommitする。

## Algorithm-specific options

`references/interpretation_policy.md`を完全に読む。summaryはnavigationにだけ使い、保持するInsightは原数値artifactを確認する。矛盾、negative result、反証探索を記録し、State更新とOperator実行はRuntime／Orchestratorへ委ねる。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

## Mode selection

このSkillはID未付与draftの検査専用で、`--conductor`を受け付けない。正式なCONDUCTOR InterpretationはRuntimeがscopeとIDを確定してcommitする。一般利用でも既存の解析結果を読むだけでStateは作らない。

## Output contract

- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`へID未付与の検証済みpreview JSON／Markdown／HTMLを生成する。
- CONDUCTORではInterpreterがこのSkillでdraftを事前検査できる。正式ID、scope、Markdown／HTML、Ledger commitは0.1.6 Runtimeだけが確定する。

構造化JSONには検証用`key_metrics`を保持するが、人間向けMarkdown／HTMLには全展開しない。数値詳細は参照Operator report、元Artifact、またはConciergeで確認する。

`<node-id-safe>`はnode IDの`:`を`-`へ置換したdirectory名であり、同一Skillの複数node間の出力衝突を防ぐ。

`--output-dir`は両モードの既定出力先より優先するが、モード自体は変更しない。

## Environment

`scripts/launch.py`を使用し、`pixi`を直接実行しない。launcherは共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上の`pixi`を使う。Skill directoryからmanifest、lock、runnerの絶対パスを作るため、呼出し元のworking directoryに依存しない。起動前に`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、一時領域、主要な実行時cacheを`<skill>/env/`配下へ強制し、system/user Pixi configを読み込まない。`pixi.lock`がない初回だけ`pixi install`でlockと環境を作成し、以後は`--locked`で再利用する。環境実体は`<skill>/env/.pixi/envs/default/`へ置く。

## General mode command

CONDUCTOR利用が明示されていない場合はこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json --output-dir path/to/preview
```

## CONDUCTOR mode command

明示的なCONDUCTOR利用で、project、run、nodeが確定している場合だけこちらを使う。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --context path/to/context.json --draft path/to/draft.json --output-dir path/to/preview
```

## Boundaries

- 最終的なSAR機序を断定しない。
- 入力CSVを変更しない。
- 重複IDを自動修正しない。
- invalid SMILESを黙って除外しない。
- Description、Clustering、Operatorを実行しない。追加計算が必要なら`recommended_followups`として提案する。
- A014ではExact Core、Environment radius、CONDUCTOR Clusterを混同せず、radius行を独立supportとして数えない。
