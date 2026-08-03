# CONDUCTOR v4 出力契約

## 共通規則

- 文字コードはUTF-8、CSVはheader必須、JSONはUTF-8かつNaNを含めない。
- ID列は文字列として扱う。
- artifact pathはmanifestからの相対パスを優先する。
- timestampはUTC ISO 8601とする。
- schema versionとcapability versionを必ず分離する。

## 実行モード

- 通常モードをdefaultとし、`--conductor`を省略する。Description、Clustering、Operatorは主成果物だけを生成する。Interpretationは正本JSONと人間向けMarkdown/HTMLを生成する。
- CONDUCTORモードは明示的opt-inとする。`--conductor --project PROJECT --run-id RUN_ID --node-id NODE_ID`を一組として必須にし、schema検証済みのrun連携artifactを追加する。
- CONDUCTORモードのexecution eventは実引数の`configuration`と`config_hash`を持つ。State nodeに計画parameterがある場合、該当keyが一致しなければeventを記録しない。
- `--output-dir`は保存場所だけを上書きし、実行モードや成果物種別を変更しない。
- 通常モードで`--project`または`--node-id`を指定した場合、およびCONDUCTOR contextが不完全な場合は成果物を作らずCLI errorで停止する。

## Description

主CSVは`compound_id`、`input_smiles`、`mol_parse_ok`、`description_error`に続けてfeature列を持つ。入力構造を標準化しない。通常モードでは主CSV/Parquetだけを生成する。CONDUCTORモードでは`description_manifest.json`、`warnings.json`、`execution_event.json`を追加する。

## Clustering／Grouping

主CSVはlong形式の`cluster_membership.csv`とし、`cluster_id`、`compound_id`、`membership_value`、`membership_reason`を持つ。どのclusterにも所属しない入力行は`cluster_id`を空、`membership_value`を0とし、invalid SMILESは`membership_reason=invalid_smiles`として保持する。通常モードでは`cluster_membership.csv`と`cluster_summary.csv`だけを生成する。CONDUCTORモードでは`group_registry.json`、`grouping_manifest.json`、`warnings.json`、`execution_event.json`を追加する。

## Operator

通常モードでは数値結果CSVだけを生成する。CONDUCTORモードでは共通`evidence.json`、`analysis_manifest.json`、`warnings.json`、`execution_event.json`を追加する。大きな配列やpair表はJSONへ埋め込まず、`artifacts`からCSV/Parquetを参照する。

## Interpretation

`interpretation.json`を正本とし、`interpretation.md`と`interpretation.html`を派生生成する。HTMLは外部CDNに依存しない。CONDUCTORモードだけ`execution_event.json`を追加する。
