# MMP深掘り解析プロンプト

対象Version: `0.1.5`

初回Global MMP解析で作成済みのデータベースを再利用し、特定Clusterや既存のInsightを起点にMMPを深掘りするための例です。Globalデータベースは再構築せず、読み取り専用で参照します。

```text
/cs-conductor-orchestrator

操作: 人間が承認した次Roundを開始し、MMP深掘りを実施
Run Root: <absolute run_root>
開始するRound: <RND####>
Wall Time: <minutes>
parallel_limit: <number>
Available CPU Cores: <number; 省略時8>

MMP深掘りの起点:
- 対象Cluster: <C###### または複数ID>
- 関連するInsight／Node: <INS###### / N######; 任意>
- 注目するendpoint変化、Transform、Exact Core、化学系列: <具体的な観点>

要求:
- 既存のA014 Global MMPデータベースを読み取り専用で再利用する
- Globalと対象ClusterのTransform effectを比較する
- Exact CoreとEnvironment radiusを区別し、支持Pair数、化合物数、効果量、ばらつき、符号反転を示す
- 対象Clusterに該当情報がない場合もnegative resultとして明記する
- Global MMPデータベースを再構築・変更しない
- 対象外Clusterを無制限に展開しない
- 通常どおりInterpretationとFull Auditまで同じRoundで完了し、AWAITING_HUMAN_REVIEWで停止する
- Roundを自動受理せず、さらに次のRoundを開始しない

最初にconductor_control.jsonを確認し、Active Roundがなく、直前RoundがCLOSEDであり、人間が指定したRound番号がnext_round_noと一致する場合だけprepare／authorizeしてください。
```

Clusterを限定せず再調査したい場合は、対象を「既存MMP screening上位候補」と指定します。その場合もRuntimeの上限内で代表候補を選び、一度に全ClusterのDetail Nodeを作りません。
