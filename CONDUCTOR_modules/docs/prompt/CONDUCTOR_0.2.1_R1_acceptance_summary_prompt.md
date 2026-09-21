# CONDUCTOR 0.2.1 R1 正式受入サマリー取得プロンプト

正式受入済みRunから、設計文書へ記録する最小限の情報だけをread-onlyで取得するためのプロンプトである。

## 置換項目

- `<PROJECT_ROOT>`: 本番解析で使用したCONDUCTOR project rootの絶対path
- `<RUN_ROOT>`: 全13 Nodeが成功し、監査で正式受入可能と判定されたRun rootの絶対path

## Claude Codeへ渡すプロンプト

```text
CONDUCTOR 0.2.1 R1の正式受入記録に必要な情報をread-onlyで取得してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>

runtime.sqlite、runtime_summary.json、P03各Lensのartifact_manifest.json、P05/P06の
artifact_manifest.json、citation_validation.json、report.json、監査結果だけを読んでください。
Nodeの再実行、再キュー、設定変更、成果物修正、Database更新は行わないでください。

回答は次の形式だけで簡潔に返してください。値が記録されていない項目は推測せず「未記録」としてください。

受入サマリー
- Run ID:
- Git commit:
- Node状態: succeeded数/全Node数
- 最終監査判定: 受入可能 または 受入不可

P06
- component_count:
- logical_calls:
- semantic_retry_count:
- failed_logical_calls:
- failure_fraction:
- null narrative component数:
- citation_validation.status:
- citation_validation.errors件数:

P05
- logical_calls:
- failed_logical_calls:
- failure_fraction:

Lens telemetry
| Lens | engine/version | unit_count | estimated_seconds | actual_wall_seconds | observed_units_per_second |
|---|---|---:|---:|---:|---:|
| L1b | | | | | |
| L2a | | | | | |
| L2b | | | | | |
| L4 | | | | | |
| L5 | | | | | |
| L7 | | | | | |

最後に、citation_validation.json、P06 artifact_manifest.json、最終reportの絶対pathを1行ずつ示してください。
説明、原因分析、提案、長いログ引用は不要です。
```
