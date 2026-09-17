# CONDUCTOR 0.2.1 運用プロンプト集

Status: **0.2.1 正式運用テンプレート。**

本書は次の二種類のプロンプトを定義する。

1. 利用者が Main Agent へ渡す運用プロンプト
2. offline provider が Local LLM へ渡す内部タスクプロンプト

両者を混同しないこと。前者は Run の準備・実行・監査を依頼するための文章であり、後者は Phase 5/6 の JSONL call を拘束するための文章である。

## 1. 共通原則

- `<...>` を実値へ置き換えてから使用する。
- 入力、設定、Run root、Endpoint registry には絶対パスを使う。
- **1 Run = 1 Endpoint** とする。
- 0.1.10/0.1.11 の Description Database は変換せず、その場で再利用する。既定配置は `<PROJECT_ROOT>/data/description_database/<PROGRAM_NAME>/` とする。
- Database の再利用条件は、同一 Program、同一 compound ID、同一 canonical SMILES、同一 `calculation_version`、同一 calculation signature とする。
- 同一 Program 内の同一 compound ID・異構造は fail-fast とし、別IDへの置換やDatabase回避で続行しない。
- 0.1.x の Run state、Execution Request、解析成果物、レポートは0.2.1へ移行しない。
- 分子の塩除去、互変異性標準化、中和、立体補完を自動実行しない。入力構造の整備は人間の責務とする。
- Endpoint を補完しない。transform domain違反や非finite値を黙って除外しない。
- 設定済み閾値をRun中に下げない。`needs_design_review` では停止して報告する。
- 既存Run rootを上書きしない。再開時だけ、同じRun IDと同じRun rootを使用する。
- Phase 5/6を実行するRunでは、`llm.command` が設定済みであることを開始前に確認する。fallback文章は生成しない。
- 外部APIやWeb検索へデータを送らない。Local LLMはオフラインで運用する。

## 2. 置換項目

| 項目 | 意味 |
|---|---|
| `<PROJECT_ROOT>` | CONDUCTORを配置したProject root |
| `<INPUT_CSV>` | 本番または較正データCSV |
| `<PROGRAM_NAME>` | Description Databaseを分離するProgram名 |
| `<RUN_ROOT>` | 新規Runの出力先、または再開対象 |
| `<ENDPOINT_REGISTRY>` | Endpoint registry JSON |
| `<ENDPOINT_ID>` | 今回解析する単一Endpoint |
| `<CONFIG_PATH>` | 解決済み0.2.1設定YAML |
| `<ID_COLUMN>` | compound ID列名 |
| `<SMILES_COLUMN>` | SMILES列名 |
| `<WORKERS>` | worker数。`0`は実装既定値 |
| `<MEMORY_MB>` | Runへ割り当てるメモリ上限の記録値 |
| `<LLM_COMMAND>` | JSONL stdin/stdoutに対応するoffline provider command |
| `<NODE_ID>` | 診断対象のRuntime Node ID |
| `<CAPABILITY_ID>` | 対象DescriptionのD001〜D016、D019、D020 |
| `<COMPOUND_ID>` | 限定調査または無効化するcompound ID |
| `<CONFIGURATION_SIGNATURE>` | 対象recordの完全なcalculation signature |
| `<HUMAN_REASON>` | 人間が明示する変更理由 |
| `<OPERATOR_NAME>` | 監査ログへ記録する操作者名 |

## 3. 日常運用プロンプト

### 3.1 状態だけを確認

```text
CONDUCTOR 0.2.1のRun状態をread-onlyで確認してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>

runtime.sqlite、runtime_summary.json、各artifact_manifest.json、attemptのstdout/stderrだけを読み、Run全体の状態、Phase別・Node別状態、最新attempt、失敗またはneeds_design_reviewの理由を短く報告してください。Nodeの実行、再試行、設定変更、Database更新、成果物修正は行わないでください。
```

### 3.2 入力と既存Description DatabaseのPreflight

```text
CONDUCTOR 0.2.1のRunを開始せず、入力と既存Description Databaseをread-onlyで事前確認してください。

Project root: <PROJECT_ROOT>
入力CSV: <INPUT_CSV>
Program名: <PROGRAM_NAME>
Endpoint registry: <ENDPOINT_REGISTRY>
Endpoint ID: <ENDPOINT_ID>
設定: <CONFIG_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
予定Run root: <RUN_ROOT>

次を確認してください。
- 必須列、IDの欠損・空文字・重複
- SMILESの空欄、RDKit parse不能数
- Endpointのtransform domain、finite件数、欠測数
- Run rootが新規かつ空であること
- 設定schema_versionが0.2.1であること
- data/description_database/<PROGRAM_NAME>/ のDatabase schema_version
- 現行18 Descriptionのcalculation_versionとcalculation signature
- compound IDとcanonical SMILESの既存registryとの矛盾
- Description別の予想hit、miss、version mismatch、configuration mismatch
- Gobbi Pharm2DでSVDを使う場合のdataset signature一致

ファイル、Database、WAL、Run stateを変更せず、開始可否と問題点を報告してください。互換性がないrecordを削除、更新、invalid化しないでください。
```

### 3.3 Local LLM providerのPreflight

```text
CONDUCTOR 0.2.1のoffline Local LLM providerをread-onlyで検査してください。

Project root: <PROJECT_ROOT>
設定: <CONFIG_PATH>
予定command: <LLM_COMMAND>

llm.commandが空でなくローカルで実行可能であることを確認し、schema-validな最小fixtureを使って select_deep_dive、summarize_deep_dive、compose_component_narrative の3タスクを各1回probeしてください。入力はJSONL stdin、出力は1 callにつきJSON object 1行だけであること、request_idをそのまま返すこと、llm_response.schema.jsonへ適合すること、Markdownや余分なstdoutがないこと、timeoutと終了codeを確認してください。

外部ネットワークへ接続せず、本番データ、Run state、Description Databaseを変更しないでください。各タスクの成否、応答時間、schema違反だけを報告してください。
```

### 3.4 既存Databaseを使う新規本番Run

```text
CONDUCTOR 0.2.1の新規本番Runを実行してください。

Project root: <PROJECT_ROOT>
入力CSV: <INPUT_CSV>
Program名: <PROGRAM_NAME>
Endpoint registry: <ENDPOINT_REGISTRY>
Endpoint ID: <ENDPOINT_ID>
設定: <CONFIG_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
Run root: <RUN_ROOT>
workers: <WORKERS>
memory_mb: <MEMORY_MB>

最初にread-only Preflightを行い、安全上または契約上の阻害要因がなければ同じ依頼の範囲で開始してください。0.1.10/0.1.11で構築した data/description_database/<PROGRAM_NAME>/ を変換せず再利用し、calculation signatureが一致するrecordはcache hit、その他はmissとして必要分だけ計算・登録してください。初回の0.2.1書込み前に、writerが存在しないことを確認してSQLite backup APIによる復旧可能なバックアップを作成してください。

0.1.xのRun成果物は入力にせず、0.2.1のExecution Request、Pipeline plan、DAGを新規作成してください。Phase 1からPhase 6までをcs-runtimeのsingle-writer coordinator経由で実行し、各Skillのlaunch.pyをRuntime外から場当たり的に直列実行しないでください。Phase 5/6では設定済みoffline providerだけを使用し、fallback文章を生成しないでください。

needs_design_review、同一ID・異構造、schema/hash/citation不整合では停止し、閾値変更や成果物の自動修正を行わないでください。終了時にRun状態、Phase別状態、Description別hit/miss/registered件数、Finding件数、上位10件、LLM logical call失敗率、引用検証結果、主要成果物の絶対パスを報告してください。
```

### 3.5 同じProgramで別Endpointの新規Run

```text
CONDUCTOR 0.2.1で、既存Programの構造依存資産を再利用して別Endpointの新規Runを実行してください。

Project root: <PROJECT_ROOT>
入力CSV: <INPUT_CSV>
既存Program名: <PROGRAM_NAME>
Endpoint registry: <ENDPOINT_REGISTRY>
新しいEndpoint ID: <ENDPOINT_ID>
設定: <CONFIG_PATH>
compound ID列: <ID_COLUMN>
SMILES列: <SMILES_COLUMN>
新規Run root: <RUN_ROOT>
workers: <WORKERS>
memory_mb: <MEMORY_MB>

同じProgramのDescription Databaseを再利用し、同一compound ID・異canonical SMILESはfail-fastとしてください。構造依存資産は契約とhashが一致するときだけ再利用し、Endpoint依存のEndpoint table、検定、score、deep dive、reportは新規に計算してください。旧RunのFinding、p/q値、narrativeを流用しないでください。

完了時に再利用した資産、再計算した資産、Description別hit/miss、Run状態、引用検証結果を報告してください。
```

### 3.6 較正データでの正式受入Run

```text
CONDUCTOR 0.2.1の正式受入として、較正データを用いたPhase 1〜6のRunを実行してください。

Project root: <PROJECT_ROOT>
較正CSV: <INPUT_CSV>
Program名: <PROGRAM_NAME>
Endpoint registry: <ENDPOINT_REGISTRY>
Endpoint ID: <ENDPOINT_ID>
設定: <CONFIG_PATH>
Run root: <RUN_ROOT>
workers: <WORKERS>
memory_mb: <MEMORY_MB>

既存Description Databaseは互換recordだけを再利用してください。閾値を較正結果へ合わせるために変更せず、現行設定のままL2b、L5、L1b、全lens、scoring K=10、deep dive、report、引用検証まで実行してください。

実装計画書8章の受入基準と比較し、L2b/L5/L1b enrichment、変換3クラスのpair数、文脈数、翻訳AUC、Finding件数、LLM call失敗率を表で報告してください。基準を外れた場合は実装不良とデータ差の可能性を分けて診断し、閾値を自動調整しないでください。
```

### 3.7 中断Runの安全な再開

```text
CONDUCTOR 0.2.1の既存Runを安全に再開してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>

最初に同じRunを実行中のcoordinatorまたはworker processが存在しないことを確認してください。存在する場合は二重実行せず状態だけを報告してください。存在しない場合はruntime.sqlite、Pipeline plan、config hash、code version、入力hashを確認し、同じRun ID、同じRun root、同じplanでpending/retryable Nodeから再開してください。新しいRunを作らず、成功済みNodeを再実行しないでください。

failedまたはneeds_design_reviewのNodeは勝手に状態変更せず、原因と必要な人間判断を報告して停止してください。成果物やDatabase recordを削除しないでください。
```

### 3.8 完走結果と引用の監査

```text
CONDUCTOR 0.2.1 Runをread-onlyで監査してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>

runtime state、全artifact manifest、input/config/code hash、Finding schema、test値、entity ID、table_ref、row_id、narrative内の[[citation_id]]、数値と引用行の一致を検証してください。Description Database、Run state、report、Findingを変更せず、Runが正式受入可能かを判定してください。

失敗時は、Node、artifact、Findingまたはcomponent、期待値、実値を特定してください。文章や数値を自動修正せず、再実行が必要な最小範囲だけを示してください。
```

## 4. 特別対応プロンプト

### 4.1 Failed Nodeの診断

```text
CONDUCTOR 0.2.1の失敗Nodeを診断してください。

Run root: <RUN_ROOT>
Node ID: <NODE_ID>

runtime.sqlite、対象Nodeの最新attempt、Execution Request、stdout/stderr、artifact_manifestの有無、入力/config/code hashをread-onlyで確認してください。原因を入力、環境、provider、schema、実装のいずれかへ分類し、再実行可能性と影響する下流Nodeを報告してください。この依頼では修正、状態変更、再実行、Database更新を行わないでください。
```

### 4.2 Description recordの限定無効化

```text
既存Description Databaseのrecordを限定的に無効化してください。

Project root: <PROJECT_ROOT>
Program名: <PROGRAM_NAME>
Capability ID: <CAPABILITY_ID>
compound ID: <COMPOUND_ID>
configuration signature: <CONFIGURATION_SIGNATURE>
理由: <HUMAN_REASON>
operator: <OPERATOR_NAME>

まずread-onlyで対象record、canonical SMILES、calculation_version、configuration signature、record statusを表示し、指定条件で対象が一意であることを確認してください。対象外recordを変更しないことを確認した後、監査理由とoperatorを記録してactive recordだけをinvalidatedへ変更してください。物理削除やDatabase再構築を行わず、変更件数とaudit entryを報告してください。
```

### 4.3 Local LLM失敗の切り分け

```text
CONDUCTOR 0.2.1のLocal LLM logical-call失敗を診断してください。

Run root: <RUN_ROOT>
設定: <CONFIG_PATH>

失敗したrequest JSONL、provider stderr、終了code、timeout、各retryのschema validation errorを確認し、task別に件数を集計してください。本番Evidenceを外部へ送らず、narrativeを手書きで補完せず、失敗原因をprovider起動、モデル出力、JSON parse、response schema、引用制約に分類してください。この依頼ではRunを再実行しないでください。
```

## 5. Local LLM内部プロンプト契約

### 5.1 providerの役割

`llm.command` のproviderは、stdinから1行ずつ `llm_request.schema.json` のJSON objectを受け取り、各入力行に対して `llm_response.schema.json` のJSON objectをstdoutへ1行だけ返す。ログはstderrへ出す。providerは次の共通system promptと、`task` に対応するtask promptを結合してモデルへ渡す。

モデル名、quantization、sampling parameter、prompt templateの版はprovider側で固定して記録する。providerの変更で出力意味が変わる場合は、provider versionを更新する。

### 5.2 共通system prompt

```text
あなたはCONDUCTOR 0.2.1の制約付きoffline reasoning componentです。入力JSON 1件だけを処理してください。

規則:
1. evidenceに明示された情報だけを使う。外部知識、Web、記憶、推測で事実や数値を追加しない。
2. 発見、順位付け、p/q値計算、効果量計算、深堀状態判定を行わない。
3. 入力のrequest_idを変更せず返す。
4. 出力はUTF-8のJSON object 1行だけとする。Markdown、code fence、前置き、後書き、コメントを出さない。
5. 出力fieldはschema_version、request_id、selections、narrative、citationsだけとし、schema_versionは"0.2.1"とする。
6. evidenceに存在しないID、template、parameter、citationを作らない。
7. 根拠不足の場合は空のselections、nullのnarrative、空のcitationsを返す。内容を水増ししない。
8. narrativeの既定言語は日本語とする。数値を記述する場合は、同じ数値を含む引用可能行のcitation markerを同じ文へ付ける。
9. citation markerは[[citation_id]]形式とし、citations配列には本文で使用したIDだけを重複なく入れる。
10. 応答前にJSONとしてparseでき、指定schemaへ適合することを確認する。
```

### 5.3 `select_deep_dive`

```text
目的: 既存Findingを反証または精緻化するため、次に実行する固定templateを0〜3件選ぶ。

規則:
- allowed_templatesに含まれるtemplateだけを選ぶ。
- parametersのIDまたは値はevidence内に明示された候補またはFinding.falsification.parametersからだけ選ぶ。
- 同じtemplate_idと同じparametersの組を重複させない。
- 新しい検定を発明せず、深堀状態を予測しない。
- 有効なparameterを構成できないtemplateは選ばない。
- 反証力が高く、既実行treeと重複しない選択を優先する。適切な選択がなければ0件とする。

parameter契約:
- T01: {"axis_id": <ID>, "level": <VALUE>}
- T02: {"axis_id": <ID>}
- T03: {"context_ids": [<ID>, ...]}、1〜3件
- T04: {"target_ids": [<ID>, ...]}、1〜3件
- T05: {} または {"iterations": <INTEGER>}
- T06: {"context_id": <ID>, "transformation_id": <ID>}
- T07: {"confounders": [<NAME>, ...]}
- T08: {"unit_type": <NAME>}
- T09: {"sample_n": <INTEGER>} またはこれにiterationsを追加
- T10: {"counterexample_rule": <RULE>}

出力:
{"schema_version":"0.2.1","request_id":"<入力値>","selections":[{"template_id":"Txx","parameters":{}}],"narrative":null,"citations":[]}
```

### 5.4 `summarize_deep_dive`

```text
目的: 1件のFindingと、その深堀treeで実行済みの結果を短く要約する。

規則:
- 元Findingの主張、実行したtemplate、決定論層が付けたSURVIVED/WEAKENED/REFUTED/INCONCLUSIVEを変えない。
- 原因を推測しない。treeが示す「何を検証し、何が残り、何が弱まったか」だけを書く。
- 引用可能なcitation_idがない場合、事実を補わずnarrativeをnullとする。
- selectionsは必ず空配列とする。

出力:
{"schema_version":"0.2.1","request_id":"<入力値>","selections":[],"narrative":"<引用marker付きの短い日本語>","citations":["<使用したcitation_id>"]}
```

### 5.5 `compose_component_narrative`

```text
目的: entity共有グラフの1連結成分に属するFindingを、引用付きの1段落へ統合する。

規則:
- findingsとciteable_rowsだけを使う。
- Findingの順位、state、effect direction、p/q値を変更しない。
- 共通entityによる接続、各Findingの意味、反証後にも残った範囲、データから直接導ける次の検証候補を簡潔に記述する。
- 全ての事実主張に[[citation_id]]を付ける。
- 本文中の全数値は、citations配列が指すrow内に同じ値が存在する場合だけ使う。章番号、箇条書き番号、概数を新たに書かない。
- citations配列は本文で実際に使ったIDだけを本文出現順で返す。
- 引用だけでは安全な統合文を書けない場合はnarrativeをnullとする。
- selectionsは必ず空配列とする。

出力:
{"schema_version":"0.2.1","request_id":"<入力値>","selections":[],"narrative":"<引用marker付きの日本語1段落>","citations":["<使用したcitation_id>"]}
```

## 6. 受入条件

プロンプト運用は次を全て満たしたときに受入可能とする。

- operator promptから、対象Program、Run、Endpoint、入力、設定が一意に決まる。
- read-only依頼がRun stateやDatabaseを変更しない。
- 新規Runが既存Run rootを上書きしない。
- 0.1.10/0.1.11 Description Databaseの互換recordがhitとして再利用される。
- 同一ID・異構造がfail-fastする。
- 3種類のLLM taskがrequest/response schemaへ適合する。
- provider stdoutにJSON以外が混入しない。
- narrativeの引用markerとcitations配列が一致する。
- 引用できない主張や数値を生成せず、根拠不足時に空/nullを返せる。
- Phase 6の引用検証が不整合を自動修正せずfail-closedする。
