# Interpretation日本語版作成プロンプト

対象Version: `0.1.4`

現行CONDUCTORの標準Interpretationは日本語で生成される。このプロンプトは、例外的に英語で作成された既存Reportから、日本語HTMLを追加作成するときだけ使用する。CONDUCTOR Stateや既存Reportは変更しない。

```text
Plan modeで実施してください。

指定したinterpretation.mdを内容の正本、interpretation.htmlをlayout／CSSのtemplateとして、日本語のinterpretation_jp.htmlを同じdirectoryに新規作成してください。

入力Markdown: <absolute path>/interpretation.md
参照HTML template: <absolute path>/interpretation.html
出力: <same directory>/interpretation_jp.html

最初に入力Markdownと参照HTMLをread-onlyで確認してください。Markdown本文がすでに日本語なら、重複fileを作らずその旨を報告してください。出力fileがすでに存在する場合は、上書きせず人間へ確認してください。

翻訳対象はMarkdownの人間向け文章です。見出し構造、INS######、N######、C######、RND####、Capability ID、数値、単位、metric、sample数、Operator result reference、相対リンク、警告、limitations、recommended follow-upsを省略・追加・再解釈しないでください。現行仕様に存在しないACT IDや新しいInsightを生成しないでください。

HTMLのsection順、低彩度配色、table、fact panel、print CSS、埋め込みassetを参照HTMLから維持してください。大容量HTML本文を翻訳元にせず、内容はMarkdownから取得してください。外部CDN、外部font、network取得を追加しないでください。

既存のinterpretation.json、interpretation.md、interpretation.html、quality report、Runtime、DAG、State、その他のartifactは一切変更しないでください。書き込みはinterpretation_jp.htmlの新規作成一回だけとし、実行前に計画と書き込み対象を人間へ示してください。
```
