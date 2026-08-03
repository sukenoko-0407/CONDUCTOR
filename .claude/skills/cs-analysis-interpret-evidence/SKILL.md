---
name: cs-analysis-interpret-evidence
description: Explore SAR evidence across representations, groups, scopes, and Operators under the CONDUCTOR v4 Interpretation Policy; prepare an evidence relation graph, preserve contradictions and negative results, require falsification for every discovery, and generate agent JSON plus human Markdown/HTML. Use as the deterministic support Skill for the dedicated Claude Code Interpretation Agent, or for standalone evidence review. General mode is the default; use CONDUCTOR mode only with complete project, run, and node context.
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Policy-guided SAR evidence interpretation

## Purpose

Operator evidence、State上のprovenance、Group局所性を読み取り専用で整理し、専用Interpretation Agentが多面的探索を行うcontextと人間向けreportを作る。runnerは候補関係を機械的に抽出する準備層であり、最終的な意味判断を固定規則だけで確定しない。

## Required Policy

実行前に`references/interpretation_policy.md`を完全に読む。repository内では同内容の`docs/CONDUCTOR_v4_interpretation_policy.md`を正本として扱う。

## Input

- `--evidence`または`--evidence-dir`: 同一runの一つ以上のschema-valid `evidence.json`
- `--state`: CONDUCTORでは必ず指定し、coverage、失敗、skip、analysis signature、探索budgetを読み取る
- `--previous-interpretation`: iteration間比較に使用できる
- `--stage discovery|validation|mixed`
- `--seed`: random候補選択の再現用。省略時はState設定、次にrun ID由来値を使う

分子標準化、endpoint変換、Operator計算は行わない。

## Algorithm-specific options

`--stage`は発見・検証の位置づけ、`--seed`は探索候補選択の再現性、`--previous-interpretation`はiteration間比較を制御する。これらは解析結果を新たに計算する引数ではない。

## Required workflow

1. 通常モードかCONDUCTORモードかを決める。
2. Policy、State、Catalog、全evidenceを読む。CONDUCTORでは初手coverageがterminalであることを確認する。
3. runnerで`interpretation_context.json`とdraft `interpretation.json`を作る。
4. contextに記録されたartifact、Group候補、依存性候補、失敗、skip、過去iterationを比較する。
5. 一つの整合的説明へ収束させず、一致、重複、局所化、矛盾、例外、比較不能を並列に残す。
6. 注目した各discoveryへ少なくとも一つの`falsify` requestを持つ`exploration_plan.json`を作る。同じanalysis signatureを再要求しない。既存Groupingにないrandom、matched random、交差、差分、boundaryの切り出しは、requestの`scope`へ選択法、compound ID集合、元Group、選択理由を明記する。
7. `scripts/launch.py render --input interpretation.json --exploration-plan exploration_plan.json`でschema検証とMarkdown/HTML再生成を行う。
8. Interpretation AgentはStateを変更せず、Operatorを直接起動しない。Orchestratorへplanを返す。

## Exploration principles

- 多重探索の候補を抑制しない。DiscoveryとValidationを区別し、negative resultと全試行履歴を保存する。
- Groupはsample数が多いものを優先するが、30%超には局所性低下、50%超にはglobal近似の注意を付ける。
- 小Groupでも構造凝集性、明確なMCS、反復変換、再現Cliffがあれば候補に残す。
- 似たDescription間の一致を独立支持として数えない。異原理Description、Group外、matched control、別Operatorで反証する。
- SALIのglobal/local比較では同じendpoint、表現、Metric、global前処理基準を維持し、within/between/boundaryを区別する。

## Mode selection: mandatory

- 通常モードをdefaultとし、明示されない限り`--conductor`を付けない。
- CONDUCTORでは`--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID --state path/to/state.json`を指定する。
- CONDUCTOR contextが不足する場合はIDを捏造せず、Orchestratorでnodeを用意する。
- repository位置、artifact、出力先だけからCONDUCTORモードを推測しない。

## Output contract

- 通常モード: `results/interpretation/standalone/<skill>/<run-id>/`
- CONDUCTOR: `results/CONDUCTOR/<project>/<run-id>/interpretation/<skill>/<node-id-safe>/`

両モードで`interpretation.json`、`interpretation_context.json`、`interpretation.md`、`interpretation.html`を生成する。専用Agentは必要に応じてschema-valid `exploration_plan.json`を追加する。CONDUCTOR runnerは`execution_event.json`も生成する。

## Environment

`scripts/launch.py`を使う。共有Pixi `/home/open-share/claude_code/skills-assets/assets_pixi-binary/latest/pixi`を優先し、無ければPATH上のPixiを使う。`PIXI_HOME`、全`PIXI_CACHE_*`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`、XDG、temp、runtime cacheを`<skill>/env/`配下へ固定し、working directory外へ環境を書き込まない。

## General mode command

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --evidence-dir path/to/evidence --stage discovery
```

## CONDUCTOR mode command

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" --evidence-dir results/CONDUCTOR/PROJECT/RUN_ID/analysis --state results/CONDUCTOR/PROJECT/RUN_ID/state.json --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## Boundaries

- Interpretation nodeは読み取り専用の終端nodeとする。
- State更新、DAG node追加、Operator直接実行、approval判断、資源予約を行わない。
- 異なるrun IDのevidenceを混在させない。
- 具体的な新規SMILESや確定的SAR機序を生成しない。
- 矛盾や反証結果を削除しない。
