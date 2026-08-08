# CONDUCTOR結果コンシェルジュ依頼prompt

完了した解析を変更せず、既存結果の意味や根拠を詳しく確認したい場合に使う。active Roundがある間は使用せず、Round完了後に依頼する。

## 基本prompt

```text
cs-conductor-result-concierge Skillを使用してください。

State:
<run_root>/state.json

確認したい内容:
<Finding、仮説、Question、Evidence、Node、Group、Operator結果などへの具体的な質問>

注目ID（ある場合）:
<F012, H003, Q008, E0042, NG0012, ...>

既存artifactだけを読み取り、解析、State、DAG、indexを変更しないでください。
回答はrun_root/concierge/配下の新しいCRQ IDへMarkdownとHTMLで保存してください。
必要なら既存値を用いたFigureを作成してください。
追加解析が有益な場合も実行せず、次Roundへ渡すprompt案として分離してください。
```

## 比較を依頼する例

```text
cs-conductor-result-concierge Skillを使用してください。
Stateは <run_root>/state.json です。

F012について、根拠となったOperator結果まで遡り、Globalと対象Groupの差、sample数、反証Evidence、解釈上の限界を説明してください。同じ結論を支持する異種Descriptionと、見解が異なるDescriptionがあれば分けて示してください。既存結果だけを使い、新たな解析はしないでください。
```

## 次Roundへ人間の見解を渡す方法

コンシェルジュの`next_round_prompt.md`は提案であり、自動的にStateへ反映されない。採用する内容と人間自身の見解を選び、次Round開始時のOrchestrator依頼に添付する。Orchestratorはその全文をRound requestとして記録し、解析計画へ反映する。
