# CONDUCTOR v4 出力契約

## 共通規則

- 文字コードはUTF-8、CSVはheader必須、JSONはUTF-8かつNaNを含めない。
- ID列は文字列として扱う。
- artifact pathはmanifestからの相対パスを優先する。
- timestampはUTC ISO 8601とする。
- schema versionとcapability versionを必ず分離する。

## 実行モード

- 通常モードをdefaultとし、`--conductor`を省略する。Description、Clustering、Operatorは主成果物だけを生成する。Interpretationは正本JSON、Agent用context、人間向けMarkdown/HTMLを生成する。
- CONDUCTORモードは明示的opt-inとする。`--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID`を一組として必須にし、schema検証済みのrun連携artifactを追加する。
- Orchestrator実行では同一Skillの複数source／parameter nodeが衝突しないよう、`results/CONDUCTOR/<project>/<run-id>/<stage>/<skill>/<node-id-safe>/`をnode固有`--output-dir`としてStateへ記録する。新規Node IDは段階別の`D###/G###/O###/I###`とし、旧形式IDに`:`がある場合だけ`node-id-safe`で`-`へ置換する。
- CONDUCTORモードのexecution eventは実引数の`configuration`と`config_hash`を持つ。State nodeに計画parameterがある場合、該当keyが一致しなければeventを記録しない。
- `--output-dir`は保存場所だけを上書きし、実行モードや成果物種別を変更しない。
- 通常モードで`--project`または`--node-id`を指定した場合、およびCONDUCTOR contextが不完全な場合は成果物を作らずCLI errorで停止する。

## Description

主CSVは`compound_id`、`input_smiles`、`mol_parse_ok`、`description_error`に続けてfeature列を持つ。入力構造を標準化しない。通常モードでは主CSV/Parquetだけを生成する。CONDUCTORモードでは`description_manifest.json`、`warnings.json`、`execution_event.json`を追加する。

## Clustering／Grouping

主CSVはlong形式の`cluster_membership.csv`とし、`cluster_id`、`compound_id`、`membership_value`、`membership_reason`を持つ。どのclusterにも所属しない入力行は`cluster_id`を空、`membership_value`を0とする。SMILES直接型ではinvalid SMILESを`membership_reason=invalid_smiles`として保持する。Description-vector型でも上流の`mol_parse_ok=false`を`invalid_smiles`、有効な数値vectorがない行を`missing_description_vector`として保持する。通常モードでは`cluster_membership.csv`と`cluster_summary.csv`だけを生成する。CONDUCTORモードでは`group_registry.json`、`grouping_manifest.json`、`warnings.json`、`execution_event.json`を追加する。

SMILES直接型はMurcko、MCS、BRICS、RECAPだけであり、Descriptionを内部生成しない。Description-vector型はDescription Skillの数値CSVだけを入力とし、raw SMILESを受け付けない。

CONDUCTORでは各Grouping nodeが`G_<node-id-underscore-safe>_<group-content-hash16>`形式のrun内一意Group IDを生成する（例: `G_G002_4A91C2D0870FB6E3`）。hashはGroupラベルとmember集合から決めるため、再計算で同じGroupはIDを維持し、内容が変わったGroupへ既存IDを流用しない。State Managerは成功eventのlong membershipを次のrun共通索引へ反映する。

- `grouping/group_index/group_registry.csv`: Group ID、ラベル、Grouping Capability、source node、source Description／Grouping、定義、sample数、状態
- `grouping/group_index/Cpd_Group_matrix_G000000_099999.csv`: 行をcompound ID、列をGroup IDとするBoolean membership matrix

Group列が10万を超えた場合は次のmatrix shardを追加する。`discarded`または`stale`となったGroupも監査用にmatrix列を保持し、状態はregistryで判定する。C012 meta-overlapは`--input`を反復指定して複数のlong形式membership artifactまたはBoolean wide matrix shardを入力できる。

## Operator

通常モードでは数値結果CSVだけを生成する。CONDUCTORモードでは共通`evidence.json`、`analysis_manifest.json`、`warnings.json`、`execution_event.json`を追加する。evidenceはglobal／within-group／between-groups、sample割合、compound集合hash、前処理referenceを持つ。Group単位の結果行は`generated_evidence`へ収載し、大規模pair表は`artifacts`からCSV/Parquetを参照する。

## Interpretation

`interpretation.json`を正本とし、`interpretation_context.json`、`interpretation.md`、`interpretation.html`を生成する。runner直後は`report_status=draft`の機械下書きであり、専用Agentがartifactを比較してObservation、Interpretation、注目理由、制約、矛盾評価を具体化し、`agent_interpreted`へ変更した後に最終renderする。Evidence一件ごとにHypothesisを自動生成しない。人間向けMarkdown/HTMLは解釈を本文、Evidence indexと探索情報を付録に置き、HTMLは外部CDNに依存しない。

Capability `I001`はInterpretation手法を表し、実行roundはrun内Node `I001`、`I002`、...として別directoryへ保存する。`interpretation_id`は`<run-id>:<I###>`とする。再Interpretationは前回Nodeのreportをread-only contextとして保持し、既存reportを上書きしない。

専用Agentは追加計算を直接行わず、schema-valid `exploration_plan.json`をOrchestratorへ返せる。Planは任意のrequestに明示`scope`を持ち、選択法とcompound ID集合を記録できる。Orchestratorは登録時にmembership内容とは別に選択法と元Groupも含む定義hashを作り、`interpretation/scopes/<group-definition-hash>.csv`へ固定する。同一compound集合の再解析判定には別のcompound-set hashを使う。CONDUCTORモードだけ`execution_event.json`を追加し、最終renderでInterpretation artifact hashを更新する。

## セッション引継ぎ

Orchestratorは人間確認による停止時またはInterpretation Round完了時に、run rootの`session_handoff.md`を更新する。これは新しいClaude Codeセッションが読むための簡潔な索引であり、State更新時刻、累積budget、前回の人間指示、主要なpositive/negative evidence、未解決矛盾、保留中承認、主要artifact pathを記載する。実行状態の正本は`state.json`、科学的根拠の正本は各artifactであり、handoffが古い場合は正本を優先する。
