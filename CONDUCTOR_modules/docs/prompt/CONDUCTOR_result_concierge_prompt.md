# Result Concierge依頼プロンプト

```text
cs-conductor-result-concierge Skillを使用してください。
state.json: <absolute path>
確認したい対象: <INS#### / ACT#### / CL###### / NA######@ATT#### / Node ID>
依頼: <説明、比較、既存値からのFigure化など>

解析Runは完全にfreezeし、State、DAG、既存artifact、CONDUCTOR_modulesを変更しないでください。書き込みはrun_root/concierge/CRQ######/だけに限定し、追加科学計算が必要なら実行せずnext_round_prompt.mdとして提案してください。
```
