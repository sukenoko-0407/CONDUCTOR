# SAR result interpretation

## SKILLの目的

専用Interpreterが作成したReview Bundleの絶対評価、または選抜ResultからのInsight案を検証し、Runtimeへ引き渡します。

## 想定利用シーン

探索中のGlobal／Local／sibling比較を複数軸で逐次評価する場合と、活性改善候補や文脈依存の違和感を正式解釈する場合に使用します。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-analysis-interpret-results/scripts/launch.py --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json --output-dir path/to/preview
```


CONDUCTORのInterpreter draftを事前検査する場合:

```bash
python .claude/skills/cs-analysis-interpret-results/scripts/launch.py --context path/to/context.json --draft path/to/draft.json --output-dir path/to/preview
```

## 制約事項

- 専用Policyを読み、Interpretation nodeを読み取り専用のRound commitとして扱う。
- 全Insight候補で反証を探索し、同じanalysis signatureを再要求しない。
- 多重探索結果、negative result、矛盾を削除しない。
- scope・Insight正式ID付与、State更新、Operator実行、approval判断、新規SMILES生成は行わない。
- 新しい科学計算が必要な場合は提案だけを記録し、Main AgentとRuntimeへ判断を戻す。
- 評価軸を合計点へ変換しない。機能しない解析は保存するが、単独Insightにはしない。
- 一次評価ではBundle固有の根拠Resultと理由を必須とし、Templateの一律複製を受け付けない。
- 累積Synthesisでは指定済みCLOSED Roundの最新一次評価を使い、正式Insightで使用済みBundleを除外する。
- historical re-Screeningでは元CLOSED Roundを変更せず、新Roundに固定された保存済みBundleだけを評価する。旧revisionは入力にしない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
| 1.1.0 | 0.1.7の少数Result逐次Screeningと選抜型Synthesis draft検証を追加。 |
| 2.0.0 | Review Bundle、絶対複数軸評価、design lead／contextual anomaly中心のSynthesisへ変更。 |
| 2.1.0 | Bundle固有根拠とTemplate複製防止、既報Bundleを除外する累積Synthesisへ対応。 |
| 2.1.1 | CLOSED Roundを変更しないhistorical re-Screening Roundへ対応。 |
