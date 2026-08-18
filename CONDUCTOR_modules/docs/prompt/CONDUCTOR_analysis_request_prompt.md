# CONDUCTOR 解析依頼プロンプト

## Round 1

```text
cs-conductor-dispatch Skillを入口として、新しいCONDUCTOR RunのRND0001を開始してください。

入力CSV: <absolute path>
endpoint: <column name>
higher_is_better: <true/false>
project: <project name>
parallel_limit: <number>
Wall Time: <minutes>
高コスト基本計算一括承認: <yes/no>

契約案を人間依頼と照合してからauthorizeし、Orchestratorは一つだけ起動してください。基本計算、初期探索、Interpretation、Full Auditまで同じRoundで実行し、AWAITING_HUMAN_REVIEWになったら停止してください。Roundを自動acceptしないでください。
```

## Active Roundの再開

```text
cs-conductor-dispatch Skillを使い、次のRun Rootに存在するActive Roundを再開してください。
Run Root: <absolute path>

新Roundは作らず、同じRoundのrequired_actionから継続してください。live leaseがある場合は二つ目のOrchestratorを起動しないでください。InterpretationとFull Auditを含む人間レビュー状態まで進め、終了後にverify-returnしてください。
```

## Round 2以降

```text
cs-conductor-dispatch Skillを入口として、前Roundを人間の指示によりacceptして閉じた後、次のCONDUCTOR Roundの契約案を作成して開始してください。
Run Root: <absolute path>
期待する次Round No: <number>（実際の番号はControlで照合）
parallel_limit: <number>
Wall Time: <minutes>

人間の見解（任意）:
- INS######: <重視点、疑問、代替解釈>
- 対象Node／Cluster: <比較・深掘り希望>

過去の成功Nodeは再計算せず、現在Roundの再利用参照として扱ってください。過去の全artifactを読み直さず、Controlとbounded Working Setから未探索coverageと有望領域を選んでください。最後にInterpretationとFull Auditを作り、AWAITING_HUMAN_REVIEWで停止してください。
```

## 人間レビュー後

```text
Run Root <path> のRND####について、次の一つを実行してください。
- 同じRoundを継続: <残作業／追加指示>
- Interpretationを改訂: <修正理由>
- Roundを受理して閉じる

cs-conductor-dispatchを使い、明示していない別操作や新Round開始は行わないでください。
```
