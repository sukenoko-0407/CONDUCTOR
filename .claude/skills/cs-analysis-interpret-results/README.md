# SAR result interpretation

## SKILLの目的

専用Interpretation Agentが作成したInsight／Next Action案を検証し、Runtimeによる正式な通しID付与と人間向け固定report生成へ引き渡す。

## 想定利用シーン

異なるDescription・Clustering・Operator間の一致、矛盾、例外、global/local差を比較し、反証を伴う次の解析候補を作る場合。

## 環境構築

`scripts/launch.py`を実行すると、`env/pixi.toml`から環境を自動作成または再利用する。Linuxでは共有Pixiを優先し、cacheと環境はこのSkillの`env/`配下に置かれる。

## 利用例

一般利用（主成果物のみ）:

```bash
python .claude/skills/cs-analysis-interpret-results/scripts/launch.py --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json
```


CONDUCTORのState nodeとして利用する場合:

```bash
python .claude/skills/cs-analysis-interpret-results/scripts/launch.py --context path/to/interpretation_context.json --draft path/to/interpretation_draft.json --state path/to/state.json --conductor --project PROJECT --run-id RUN_ID --round-id RND0001 --node-id NODE_ID --attempt-id ATT0001
```

## 制約事項

- 専用Policyを読み、Interpretation nodeを読み取り専用の終端として扱う。
- 全Insight候補で反証を探索し、同じanalysis signatureを再要求しない。
- 多重探索結果、negative result、矛盾を削除しない。
- InsightとNext Actionの正式ID付与、State更新、Operator実行、approval判断、新規SMILES生成は行わない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。人間向けの目的、利用例、制約事項を整理。 |
