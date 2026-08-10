# CONDUCTOR Result Concierge

## SKILLの目的

完了済みCONDUCTOR RunのInsight、Next Action、Node、Cluster、Operator結果を、人間の問いに合わせて説明・比較・再可視化する。

## 想定利用シーン

Interpretation reportで気になった項目の根拠を詳しく確認したい場合、既存のGlobal／Local結果を比較したい場合、既存値から説明用Figureを作りたい場合に使用する。

## 環境構築

`scripts/launch.py`が`env/pixi.toml`から環境を自動作成または再利用する。cacheはすべて本Skillの`env/`配下に置かれる。

## 利用例

```bash
python .claude/skills/cs-conductor-result-concierge/scripts/launch.py prepare \
  --state results/CONDUCTOR/PROJECT/RUN/state.json \
  --request "INS0012の根拠と反証候補を説明する" --focus-id INS0012 --explicit-request
```

表示されたrequest directory内の`response_draft.json`を記入後、次を実行する。

```bash
python .claude/skills/cs-conductor-result-concierge/scripts/launch.py finalize \
  --request-dir results/CONDUCTOR/PROJECT/RUN/concierge/CRQ000001
```

## 制約事項

- active Roundや実行中NodeがあるRunでは開始しない。
- 出力先は`<run_root>/concierge/CRQ######/`に固定される。
- State、DAG、解析artifactを変更せず、新しい科学解析も実行しない。
- 追加解析は`next_round_prompt.md`として提案できるが、自動実行しない。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版。凍結済み結果の説明、provenance追跡、表・SVG Figure、自己完結HTMLを追加。 |
