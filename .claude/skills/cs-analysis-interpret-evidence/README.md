# Policy-guided SAR evidence interpretation

## SKILLの目的

Operator evidence、Group局所性、依存関係、失敗を整理し、専用Interpretation Agentによる意味解釈を経て、人間が解析内容とSAR上の示唆を理解できるMarkdown/HTMLを作成します。

## 想定利用シーン

異なるDescription・Grouping・Operator間の一致、矛盾、例外、global/local差を比較し、反証を伴う追加解析候補を作る場合に使用します。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を作成または再利用し、cacheと環境をSkill内`env/`へ配置します。

## 利用例

一般利用:

```bash
python .claude/skills/cs-analysis-interpret-evidence/scripts/launch.py --evidence-dir path/to/evidence
```

CONDUCTOR:

```bash
python .claude/skills/cs-analysis-interpret-evidence/scripts/launch.py --evidence-dir path/to/evidence --state path/to/state.json --conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID
```

## 制約事項

- 専用Policyを読み、Interpretation nodeを読み取り専用の終端として扱います。
- 注目した全discoveryに反証要求を付け、同じanalysis signatureを再要求しません。
- 新しい切り出しはPlanの`scope`にcompound IDと選択法を記録し、membership生成はOrchestratorへ委ねます。
- 多重探索結果、negative result、矛盾を削除しません。
- runner直後の出力は`draft`です。専用AgentがObservationとInterpretationを分けて記載し、`agent_interpreted`へ最終化するまで正式レポートではありません。
- HはHypothesisのIDです。Evidenceごとの連番ではなく、検証可能な仮説が形成できる場合だけ付与します。
- 既存CONDUCTOR runの再InterpretationはSkillを直接起動せず、Orchestratorから新しい`I###` nodeとして登録します。前回reportはread-only contextとして引き継ぎます。
- HTMLは解釈サマリーと重要な示唆を本文に置き、Evidence indexや探索情報を付録にした人間向け解釈レポートです。
- State更新、Operator実行、承認判断、新規SMILES生成は行いません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.2.0 | 反復InterpretationのNode IDと前回report引継ぎを明記。 |
| 1.1.0 | 機械下書きとAgent解釈済み成果物を分離し、人間向け解釈項目、品質gate、意味別HTML配色を追加。 |
| 1.0.0 | Policy管理の専用Agent、scope比較、反証探索、探索contextへ対応。 |
