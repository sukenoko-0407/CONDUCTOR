# Result Concierge依頼プロンプト

対象Version: `0.1.4`

既存Runを変更せず、Interpretationや個別結果を詳しく確認するためのプロンプトである。Conciergeの処理と出力は正式DAGへ登録されない。

```text
/cs-conductor-result-concierge

Run Root: <absolute path>
確認したい対象: <INS###### / C###### / N###### / RND#### / artifact relative path>
依頼:
<説明、根拠追跡、Global対Cluster比較、Description横断比較、既存値の追加集計、表・Figure作成など>

期待する成果物（任意）:
- report.md
- report.html
- figures/<希望する図>

最初にRunの状態をread-onlyで確認してください。AWAITING_HUMAN_REVIEW、CLOSED、またはActive Roundなしの場合だけ開始し、ACTIVE／FINALIZING中ならREQを作成せず人間へ報告してください。

既存のCONDUCTOR解析はFreezeしてください。conductor_control.json、runtime/、rounds/、description/、clustering/、analysis/、interpretation/、CONDUCTOR_modules/を変更しないでください。書き込みは新しく割り当てるrun_root/concierge/REQ######/の中だけに限定してください。

既存artifactの抽出、filter、依頼固有の記述統計、比較、既存値からのFigure作成は実行して構いません。補助Pythonが必要ならREQ directory内のscratch/へ置き、可能な限りConciergeのrun-helperを使用してください。/tmpは既定の作業場所にしないでください。

新しいDescription、Clustering、Operator、予測model、Insight、Node、Stateは作成しないでください。正式な追加解析が必要な場合は実行せず、任意のnext_round_prompt.mdとして人間へ提案してください。

Reportには、使用したsource、手法、表現、対象scope、sample数、観察、解釈、限界を明記してください。Cluster結果をGlobalと表示せず、相関から因果を断定しないでください。最後に保護対象のhashが変化していないことをverifyしてください。
```
