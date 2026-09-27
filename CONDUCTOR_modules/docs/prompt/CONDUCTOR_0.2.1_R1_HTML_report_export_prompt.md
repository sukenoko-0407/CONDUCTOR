# CONDUCTOR 0.2.1 受入済みRunの人間向けHTMLレポート出力

このプロンプトは、HTML可視化実装より前に完走・受入済みとなったRunへ今回だけ適用する。
解析、P06、LLM callを再実行せず、hash検証済みの既存成果物からRun root外へHTMLを派生出力する。

次の`<...>`を絶対パスへ置き換えて使用する。`<PIXI>`は本番CPU機にある`pixi` executableの絶対パスである。

```text
CONDUCTOR 0.2.1の受入済みRunから、人間が知見を理解するための静的HTMLレポートを作成してください。

Project root: <PROJECT_ROOT>
受入済みRun root: <RUN_ROOT>
HTML出力先: <HTML_OUTPUT_PATH>

最初にruntime.sqliteとruntime_summary.jsonをread-onlyで照合し、P06-REPORTの受入済みsucceeded
attemptを一意に特定してください。そのattemptのartifact_manifestについてproducerのrun_id、node_id、
attempt_idがRuntimeと一致し、cs-report由来かつsucceededであることを確認してください。ファイル名や
更新日時だけでmanifestを選ばないでください。

そのmanifestを`CONDUCTOR_modules/tools/export_validated_report_html.py`の`--artifact-manifest`へ渡し、
report.json、final_findings.jsonl、citation_validation.jsonのhashとstatusを検証してから出力してください。
HTML実装前のP06 manifestにscore_observationsが直接列挙されていない場合は、同manifestに記録済みの
P03 artifact_manifestをhash検証して辿る既存exporter経路を使用してください。Run成果物の探索結果を
新しい入力として捏造したり、入力hashを省略したりしないでください。

全体HTMLには重要なFindingの具体的な内容を先に示し、監査用の全Finding表は付録にしてください。
設定済み`scoring.display_k`件について、効果、p/q値、support、score、deep dive、反証条件、
引用Evidenceを説明する個別HTMLも作成してください。各個別HTMLにLens固有の科学図があることを確認し、
L1bでは注目化合物と固定距離順近傍、L2aではMMP変換前後と代表実測pair、L2bではfragmentと代表化合物、
L4では候補とsource、L5では文脈内外の実測散布図、L7では両core・共通R基・同一R基の代表実測pairが
表示されることを確認してください。
文章だけの個別HTMLを成功として扱わないでください。新しい解析やLLM callは行わないでください。

受入済みRun root、Description Database、既存成果物、Runtime stateは変更しないでください。
P06を再実行せず、Node stateやattemptを追加しないでください。出力先はRun root外の新規ファイルとし、
既存ファイルを上書きしないでください。
個別HTMLは`<HTML_OUTPUT_PATH>`のstemに`_findings`を付けた隣接directoryへ出力されます。
出力後は全体HTMLから全個別HTMLへのlink、個別HTMLから全体HTMLへのlink、外部画像・script・network
resourceがないことを検査してください。終了時は、使用したP06 manifest、全体HTMLの絶対パス、
個別HTML件数とLens別件数、失敗または不足artifact、Run root不変の成否だけを簡潔に報告してください。
```

Agentが上記手順で`<P06_ARTIFACT_MANIFEST>`を特定した後の直接実行例:

```bash
<PIXI> run --manifest-path <PROJECT_ROOT>/.claude/skills/cs-report/env/pixi.toml --locked \
  python <PROJECT_ROOT>/CONDUCTOR_modules/tools/export_validated_report_html.py \
  --artifact-manifest <P06_ARTIFACT_MANIFEST> \
  --output <HTML_OUTPUT_PATH>
```

今後の新規RunではP06が`report.html`と上位`scoring.display_k`件の個別HTMLを標準成果物として
Run root内へ生成し、artifact manifestへ登録する。この全体出力経路を新規Runで別途実行しない。
後述のFinding ID指定経路は、新旧どちらの受入Runでも人間が追加指定したFindingだけに使用できる。

## 人間が指定したFindingの個別HTMLを追加出力

重要知見を確認後、別のFindingも詳しく読みたい場合は次の`<...>`を置き換えて使用する。

```text
CONDUCTOR 0.2.1の受入済みRunから、指定Findingの個別HTMLを1件だけ作成してください。

Project root: <PROJECT_ROOT>
P06 artifact manifest: <P06_ARTIFACT_MANIFEST>
Finding ID: <FINDING_ID>
HTML出力先: <FINDING_HTML_OUTPUT_PATH>

`CONDUCTOR_modules/tools/export_validated_report_html.py`へ`--finding-id`を指定してください。
P06 manifest、正本成果物、引用Evidenceのhashとstatusを検証し、指定Findingの意味、効果、
p/q値、support、score、deep dive、反証条件、引用行、Lens固有の科学図を含む自己完結型HTMLを作成してください。
L2a/L2b/L4/L7で化学構造図が必要な場合はRDKitの実構造SVGを使用してください。
L1bの近傍順は保存済みscore observationを使用し、再探索しないでください。L7のR基構造はhash検証済み
mmp_databaseから解決してください。
図の入力が不足する場合は文章だけで代替せず、どのartifactが不足したかを報告して停止してください。
LLM call、再解析、Run rootやDatabaseの変更、既存ファイルの上書きは行わないでください。
終了時は成否と出力HTMLの絶対パスだけを簡潔に報告してください。
```

直接実行例:

```bash
<PIXI> run --manifest-path <PROJECT_ROOT>/.claude/skills/cs-report/env/pixi.toml --locked \
  python <PROJECT_ROOT>/CONDUCTOR_modules/tools/export_validated_report_html.py \
  --artifact-manifest <P06_ARTIFACT_MANIFEST> \
  --finding-id <FINDING_ID> \
  --output <FINDING_HTML_OUTPUT_PATH>
```
