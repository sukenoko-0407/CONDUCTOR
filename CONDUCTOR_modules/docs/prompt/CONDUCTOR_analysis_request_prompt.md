# CONDUCTOR解析依頼プロンプト

Claude Codeを対象Projectのrootから起動し、以下のテンプレートを必要に応じて編集して使用する。

## 新しいCONDUCTOR Runを開始する

```text
このProjectに導入されている `cs-conductor-orchestrator` Agentを使用して、
CONDUCTORとしてSAR解析を開始してください。

解析対象は以下のCSVだけです。
- Input CSV: <INPUT_CSV_PATH>
- Compound ID列: <COMPOUND_ID_COLUMN>
- SMILES列: <SMILES_COLUMN>
- Endpoint列: <ENDPOINT_COLUMN>
- higher_is_better: <true または false>

Run設定:
- Project名: <PROJECT_NAME>
- 並列実行数: <PARALLEL_LIMIT>
- 分子標準化状況: <例: 人間により事前標準化済み>

`CONDUCTOR_modules/docs/CONDUCTOR_v4_policy.md`、
`CONDUCTOR_modules/docs/CONDUCTOR_v4_design_spec.md`、
`CONDUCTOR_modules/catalog/catalog.json`
を読んでから処理を開始してください。

初手はCatalogで定められた広域解析プロファイルを省略せず実行してください。
各解析Skillは必ずCONDUCTORモード、つまり `--conductor` を付けて実行し、
State DAGを通じて管理してください。

指定したInput CSVとCONDUCTORの管理ファイル以外については、
解析上の依存関係が明示されていない限り探索対象に含めないでください。

人間の承認が必要な高コスト処理に到達した場合は、
目的、期待される情報、計算資源、代替手段を説明して停止してください。
```

## 既存のCONDUCTOR Runを再開する

```text
`cs-conductor-orchestrator` Agentを使用して、
次のCONDUCTOR runを再開してください。

State:
<STATE_JSON_PATH>

新しいrunは作成しないでください。
最初にStateのstatus、未完了node、失敗node、approval待ちnodeを確認し、
既存のDAGとrun IDを維持したまま処理を継続してください。

並列実行数は<PARALLEL_LIMIT>です。
高コスト処理には既存の承認Policyを適用してください。
```

## 個別Skillを一般モードで利用する

CONDUCTOR runを作らず、単一の機能だけを利用するときのテンプレートである。

```text
これはCONDUCTOR runではありません。
`<SKILL_NAME>` Skillを一般モードで使用し、
<INPUT_PATHまたはSMILES>を処理してください。

`--conductor`は付けないでください。
```

## 指定時の要点

- CONDUCTOR全体を使う場合は、`cs-conductor-orchestrator`と「CONDUCTORとして実行」を明示する。
- Input CSV、endpoint、`higher_is_better`、並列実行数を指定する。
- Project内に無関係なファイルがある場合は、解析対象と探索範囲を明示する。
- 一般利用では「CONDUCTOR runではない」と明記し、`--conductor`を付けない。
