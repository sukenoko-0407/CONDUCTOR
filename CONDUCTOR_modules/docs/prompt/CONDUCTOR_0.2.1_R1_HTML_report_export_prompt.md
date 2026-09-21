# CONDUCTOR 0.2.1 受入済みRunのHTMLレポート出力

次の`<...>`を絶対パスへ置き換えて使用する。

```text
CONDUCTOR 0.2.1の受入済みRunから、人間が閲覧する静的HTMLレポートを作成してください。

Project root: <PROJECT_ROOT>
P06 artifact manifest: <P06_ARTIFACT_MANIFEST>
HTML出力先: <HTML_OUTPUT_PATH>

`CONDUCTOR_modules/tools/export_validated_report_html.py`を使用し、P06 manifestが
cs-report由来かつsucceededであること、report.json、final_findings.jsonl、
citation_validation.jsonのhashとstatusが正しいことを検証してから出力してください。

受入済みRun root、Description Database、既存成果物、Runtime stateは変更しないでください。
出力先はRun root外の新規ファイルとし、既存ファイルを上書きしないでください。
終了時は、成否、HTMLの絶対パス、SHA-256、Run rootが不変であることだけを簡潔に報告してください。
```

対応する直接実行例:

```bash
python <PROJECT_ROOT>/CONDUCTOR_modules/tools/export_validated_report_html.py \
  --artifact-manifest <P06_ARTIFACT_MANIFEST> \
  --output <HTML_OUTPUT_PATH>
```

今後の新規RunではP06が`report.html`を標準成果物として生成するため、この外部出力は
HTML実装前に完了した受入済みRunにだけ使用する。
