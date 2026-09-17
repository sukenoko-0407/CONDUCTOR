# CONDUCTOR 0.2.1 JSON contracts

`*.schema.json` は JSON の形式を検証するための JSON Schema、`*.example.json` はその Schema に適合する最小限の具体例です。

## 利用者が準備するファイル

- `endpoint_registry.example.json`: 実データの列名、単位、変換、向きを記入して `endpoint_registry.json` として保存します。CONDUCTOR 0.2.1 の通常運用で、利用者が事前に作成する必須 JSON はこれだけです。

## Local LLM provider の実装・疎通確認に使うファイル

- `llm_request.example.json`: provider が stdin から受け取る JSONL 1行分の例です。
- `llm_response.example.json`: provider が stdout へ返す JSONL 1行分の例です。

## Runtime が生成するファイル

次の例は契約確認、テスト、障害調査用です。通常運用で利用者が手書きして Runtime に渡すものではありません。

- `artifact_manifest.example.json`
- `context.example.json`
- `deep_dive_node.example.json`
- `execution_event.example.json`
- `execution_request.example.json`
- `finding.example.json`
- `mpo_contract.example.json`
- `runtime_state.example.json`

例に含まれる ID、path、hash、日時、列名、単位、数値はすべて説明用です。本番値へ置き換えてください。Schema ファイル自体は編集しません。
