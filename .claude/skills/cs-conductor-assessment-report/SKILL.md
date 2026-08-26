---
name: cs-conductor-assessment-report
description: Summarize existing CONDUCTOR 0.2.0 primary Result Assessments as a read-only, self-contained HTML dashboard. Use only when a human explicitly supplies a Run Root and asks to visualize assessment distributions or promising candidates; never use it as a DAG Node or as part of a Round.
allowed-tools: Read, Bash
---

# CONDUCTOR Assessment Report

人間が明示したRun Rootについて、既存の一次評価正本を読み取り専用で集計する。

```bash
python "${CLAUDE_SKILL_DIR}/scripts/launch.py" \
  --run-root /path/to/run --explicit-request
```

特定Roundだけを見る場合は`--round-id RND0003`を追加する。複数指定も可能である。`--top-n`の既定値は10、上限は50である。

出力は`<run_root>/assessment_reports/<UTC timestamp>/`のみに新規作成する。`runtime/result_assessment_index.jsonl`、`runtime/review_bundle_index.jsonl`、`runtime/insight_index.jsonl`を変更せず、Lease取得、Node登録、Round遷移、State更新を行わない。

「総合評価」は科学的な合計点ではない。5つの絶対評価軸を加算せず、Runtime確定のCandidate class分布として表示する。有望候補は`design_lead`と`contextual_anomaly`だけを、Candidate class、sample support、chemical actionability等の決定論的な表示順で最大N件示す。この順位を新しい科学評価としてStateへ戻してはならない。

Full Interpretationへの収載有無は、最新の`runtime/insight_index.jsonl`で各`bundle_id`が`review_bundle_ids`から参照されているかにより判定する。レポートには評価軸ヒストグラム、Candidate class分布、信頼性分布、Round推移、Operator別内訳、Full report収載率、Top候補、未収載候補を含める。

