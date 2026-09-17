# CONDUCTOR 0.2.1 Local LLM provider

このdirectoryは、CPU機上のCONDUCTORと、別のGPUマシンで稼働する`vllm serve`のOpenAI互換APIを接続するproviderです。provider自身は推論や解析を行わず、Python標準ライブラリだけで動作します。

`llm.command`はMCP serverの登録ではありません。CONDUCTORが1 logical callごとにCPU機上で起動するcommand lineです。providerはstdinからrequest JSON 1行を受け、vLLMの`/v1/chat/completions`へ送信し、検証済みresponse JSON 1行だけをstdoutへ返します。

Claude Codeが同じvLLM APIへ接続済みでも、その接続設定や認証情報はproviderへ自動継承されません。CONDUCTOR用のprovider設定と、必要なら専用の環境変数をCPU機上で明示します。

LLMはOS commandや解析Toolを直接実行しません。許可済みtemplateの提案または引用付き文章だけを返し、template実行、統計計算、状態判定、引用検証はCPU機上の決定論的なCONDUCTOR codeが行います。

## 構成

- `provider.py`: stdin 1行を受け、stdoutへ応答JSON 1行だけを返すvLLM adapter。
- `prompts.json`: 0.2.1で固定したsystem/task prompt。
- `provider_config.example.json`: 接続先とmodel情報の雛形。

providerは次を強制します。

- 接続先hostnameを`approved_host`へ固定する。
- 非loopback接続は既定でHTTPSだけを許可する。信頼済み閉域網でHTTPが必要な場合だけ`allow_plaintext_http: true`を明示する。
- URLへの認証情報埋込み、query、fragment、HTTP redirect、system proxyを拒否する。
- API keyは設定fileへ書かず、`api_key_env`で指定した環境変数から読む。
- vLLMのJSON Schema structured outputを使い、さらにprovider側でCONDUCTOR固有の制約を再検証する。vLLMのxgrammarが未対応の`uniqueItems`は生成用schemaからだけ除き、重複禁止をprovider側で決定論的に強制する。
- `chat_template_kwargs.enable_thinking`を`false`に固定する。

## CPU機での準備

1. GPU側のvLLM管理者から次の非secret情報を確認する。

   - vLLM version
   - `/v1/chat/completions`の完全URL
   - URLのhostname
   - vLLMが公開する正確なmodel ID
   - model revisionまたはdeployment revision
   - quantization
   - API key認証の有無
   - `/health`を利用できるか

2. `provider_config.example.json`を`provider_config.json`へ複製し、placeholderを全て置換する。`provider_config.json`はGit管理しない。

3. `vllm serve --api-key ...`を使用している場合、CPU機上で専用の環境変数を設定する。値はfileやcommand lineへ書かない。

```bash
export CONDUCTOR_LLM_API_KEY='<secret>'
```

認証なしの場合は、設定を次のように変更します。

```json
"authentication": "none",
"api_key_env": null
```

4. vLLMがTLS終端なしの信頼済み閉域HTTPで公開されている場合だけ、URLを`http://...`へ変更し、`allow_plaintext_http`を`true`にする。インターネットや信頼できないnetworkでは使用しない。

5. CPU機上で設定とhealth endpointを確認する。

```bash
<PYTHON> <PROJECT_ROOT>/CONDUCTOR_modules/local_llm_provider/provider.py \
  --config <PROJECT_ROOT>/CONDUCTOR_modules/local_llm_provider/provider_config.json \
  --check
```

`health_endpoint`を`null`にした場合、`--check`は設定と認証環境変数だけを検証し、推論serverへは接続しません。

6. Project configの`llm.command`へ次を1行で設定する。

```yaml
llm:
  command: '"<PYTHON>" "<PROJECT_ROOT>/CONDUCTOR_modules/local_llm_provider/provider.py" --config "<PROJECT_ROOT>/CONDUCTOR_modules/local_llm_provider/provider_config.json"'
  timeout_seconds: 300
  schema_retries: 2
  max_failure_fraction: 0.20
```

`<PYTHON>`はCPU機上のPython 3.12 executableの絶対pathです。provider側のtimeoutを270秒、CONDUCTOR側を300秒とし、外側のtimeoutを長くします。GPU serverの混雑で不足する場合は両方を同じ比率で引き上げます。

sampling parameterはmodel運用値に合わせて固定し、provider metadataへ記録します。vLLMはOpenAI標準外の`top_k`と`min_p`もJSON bodyで受け取れます。model repositoryの`generation_config.json`との関係も含め、正式Runでは実際に適用される値をGPU server管理者と確認してください。

最後にプロンプト集3.3をCPU機上で実施し、実際のGPU modelへ3タスクを各1回だけprobeします。これは小さなrequest 3件だけであり、特徴量計算や本番Runは開始しません。

## 開発環境での最小テスト

本物のmodelやGPU APIへ接続せず、標準ライブラリの擬似OpenAI互換serverでJSONL/HTTP契約だけを検証できます。

```text
uv run --no-project --python 3.12 python -m unittest CONDUCTOR_modules.tests.unit.test_local_llm_provider_stdlib
```

このtestは3種類のrequestを1回ずつ通しますが、LLM推論は行いません。本番の3タスクprobeを代替しません。
