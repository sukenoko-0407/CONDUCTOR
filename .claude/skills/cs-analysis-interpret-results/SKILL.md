---
name: cs-analysis-interpret-results
description: Use when the dedicated Claude Code Interpreter must validate one bounded Review Bundle assessment draft or an ID-free Japanese Interpretation draft. It never executes new scientific analysis or mutates State.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# SAR result interpretation

## Purpose

Runtimeが比較可能なResult Cardから作ったReview Bundle評価draft、または評価索引から選抜したResultのInterpretation draftを読み取り専用で検証する。

## Input

`--context`、Interpreterが作成したID未付与の`--draft`、新規の`--output-dir`を指定する。Runtimeが対象result、scope、正式IDを管理する。 分子標準化、活性単位変換、pActivity変換は行わない。

## Required workflow

1. 実行前に通常モードかCONDUCTORモードかを決定する。
2. Runtimeが作成したcontextとdraftを確認し、`context.mode`が`screening`か`synthesis`かを最初に判定する。
3. algorithm固有optionが必要なら`python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --help`で確認し、根拠なくdefaultを変更しない。
4. `--output-dir`には存在しない新規directoryを指定する。既存出力を上書きしない。
5. 実行後にpreview JSON／Markdown／HTMLを確認する。正式成果物はRuntimeだけがcommitする。

## Algorithm-specific options

`screening`では各Review Bundle内へRuntimeが配置したOperator固有`evaluation_anchors`を使い、0～3の複数絶対軸で個別評価する。軸を合計せず、信頼性と分離する。各評価はBundle内のResultを最低1件引用し、実際のmetric/value、比較またはquality factに基づく固有理由を記載する。異なるBundleへ同一内容を複製しない。長文Insight、Markdown／HTML、正式ID、Candidate classを作らない。`synthesis`では`references/interpretation_policy.md`を完全に読み、`design_lead`と`contextual_anomaly`だけを主候補にする。各Insightには`review_bundle_ids`、内容を表す日本語表題、完全な文の`limitations`配列を付ける。

`--help`にはこのSkillで有効なoptionだけを表示する。CONDUCTORで同じcapabilityの異なるvariantまたはparameter setを比較する場合は、それぞれを別nodeとしてStateへ登録し、nodeの`parameters`と実行引数を一致させる。一般利用で比較する場合もrun IDまたは`--output-dir`を分ける。

`interpretation_scope=cumulative_unreported`では、Runtimeが指定した過去のCLOSED Roundにある各Bundleの最新一次評価だけを対象とする。過去の正式Insightで使用済みのBundleはRuntimeが除外する。`prior_reported_insights`は重複表現を避けるためだけに参照し、同じ知見を新規Insightとして言い換えない。

historical re-Screeningでは、Runtimeが新しいscreening Roundへ固定した過去のReview Bundleだけを評価する。`context.round_id`とBundleの`round_id`が異なるのは正常であり、元CLOSED RoundやResultを変更しない。旧Assessment revisionを参照せず、現在のResult factsと評価anchorから独立にdraftを作る。

## Mode selection

このSkillはID未付与draftの検査専用で、`--conductor`を受け付けない。正式なCONDUCTOR InterpretationはRuntimeがscopeとIDを確定してcommitする。一般利用でも既存の解析結果を読むだけでStateは作らない。

## Output contract

- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`へID未付与の検証済みpreview JSON／Markdown／HTMLを生成する。
- CONDUCTORではInterpreterがBundle assessmentまたはSynthesis draftを事前検査できる。評価索引、Candidate class、正式ID、scope、Markdown／HTML、Ledger commitは0.2.0 Runtimeだけが確定する。

構造化JSONではResult Card v2のtyped `comparison_metrics`と、必要最小限の`operator_details`を検証根拠として保持する。人間向けMarkdown／HTMLには数値を全展開せず、詳細は参照Operator report、元Artifact、またはConciergeで確認する。

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
- A014はRuntimeが渡すcompactなGlobal Result Cardだけを扱い、Databaseの存在、coverage、negative resultを認識する。Transform／Exact Core／Environment／Clusterの詳細比較は通常Interpretationで展開せず、人間が`cs-analysis-interpret-mmp`を明示起動する。
