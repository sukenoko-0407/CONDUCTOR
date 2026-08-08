---
name: cs-conductor-result-concierge
description: Explain, trace, compare, and visualize existing results from an explicitly supplied completed CONDUCTOR run without changing State, DAG, scientific artifacts, or analysis decisions. Use only when a human asks to inspect a Finding, Hypothesis, Question, Evidence, Node, Group, Operator result, or relationship already present in a frozen run.
allowed-tools: Read, Write, Glob, Grep, Bash
---

# CONDUCTOR Result Concierge

既存の解析結果を人間の問いに沿って説明・比較・再可視化する。科学計算や次Roundの計画は行わず、`<run_root>/concierge/CRQ######/`以外を一切変更しない。

## 絶対条件

- 人間が`state.json`と依頼内容を明示した場合だけ使う。
- active Round、running Node、live Orchestrator leaseがある場合は開始しない。
- State、DAG、index、Description、Grouping、Operator、Interpretation、`CONDUCTOR_modules/`を変更しない。
- 新規Descriptor、Grouping、統計検定、Operator、Interpretation ID、Nodeを作らない。
- 既存値の抽出、並べ替え、比較、要約、provenance追跡、表・Figureへの再表現だけを行う。
- 追加解析が必要なら実行せず、任意の`next_round_prompt.md`として提案する。

## Workflow

### 1. Request workspaceを作る

launcherは共有Pixiを優先し、`PIXI_CACHE_DIR`と`UV_CACHE_DIR`をSkill内`env/`へ設定する。

```bash
python .claude/skills/cs-conductor-result-concierge/scripts/launch.py prepare \
  --state /path/to/run_root/state.json \
  --request "F012を根拠データまで遡って説明し、関連GroupとGlobalを比較する" \
  --focus-id F012 --explicit-request
```

返された`request_dir`、`context.json`、`response_draft.json`を使用する。要求IDは`CRQ######`であり、Node IDやInterpretation IDとは独立する。

### 2. 読むsourceを登録する

`context.json`にないartifactを読む前に登録する。

```bash
python .claude/skills/cs-conductor-result-concierge/scripts/launch.py add-source \
  --request-dir /path/to/run_root/concierge/CRQ000001 \
  --source analysis/.../operator_report.html \
  --source analysis/.../evidence_digest.json
```

登録済みsourceだけを根拠として使い、`response_draft.json`の`source_paths`にもrun-root相対pathを記録する。

### 3. Draftを書く

`response_draft.json`だけを編集する。問いへの直接回答、根拠、比較対象、限界を明記する。Figureは既存値を`bar`、`line`、`scatter`で再表現する仕様だけを記載する。

### 4. 固定reportを生成・検証する

```bash
python .claude/skills/cs-conductor-result-concierge/scripts/launch.py finalize \
  --request-dir /path/to/run_root/concierge/CRQ000001

python .claude/skills/cs-conductor-result-concierge/scripts/launch.py verify \
  --request-dir /path/to/run_root/concierge/CRQ000001
```

`response.md`、base64埋込みFigureを含む`response.html`、`figures/*.svg`、必要時の`next_round_prompt.md`を生成する。finalize直前にStateと参照sourceのhash、およびrun_root内の非concierge file inventoryを再検証する。

## 回答品質

- IDだけを並べず、「どの解析・どの表現・どの範囲・何が観測されたか」を平易に説明する。
- Global対Local、Group間、異なるDescription間の比較では、比較可能性とsample数を明記する。
- 相関、因果、仮説を混同しない。既存Evidenceを超える結論を作らない。
- 人間の意見はこのreport内で明示的に区別し、Stateへ反映しない。
- 次Roundへ渡す提案は、観察済み事実と追加してほしい解析を分けて書く。
