# CONDUCTOR 0.2.1 利用者ガイド

## 1. 何をするシステムか

CONDUCTORは、低分子化合物の構造と単一Endpointを入力し、人間が事前に仮説化していない条件依存SARを
複数のLensで探索します。出力は単なる有意差一覧ではなく、次を一体化したFindingです。

- 何が、どの条件で、どちら向きに変化したかというclaim
- support、効果量、p/q値、多重性族
- 交絡・自明性の評価
- 固定templateによる追加検証と反証状態
- 元データ行へ戻れるcitation
- 人間が理解するためのLens固有HTML図

## 2. 入力

1 Runは1 Endpointです。最低限、次を用意します。

- CSV: 一意なcompound ID、SMILES、Endpoint列
- Endpoint registry: 単位、向き、transform、欠測規則
- Program名: Description Databaseの分離単位
- resolved config: 既定値と本番環境pathを解決したYAML
- provider config: 承認済み内部vLLM APIの接続情報
- Run Spec: 入力、出力、CPU、memory、設定を一意に束ねるJSON

CONDUCTORは塩除去、互変異性標準化、中和、立体補完を自動実行しません。入力構造の意味的整備は
利用者の責務です。RDKit parse不能、Endpoint transform domain違反、同一ID・異構造は黙って除外しません。

## 3. 実行前

新しいProgramへ全Descriptionを構築する場合は、運用プロンプト集の順に進めます。

1. 3.0 Run Spec作成
2. 3.2A 入力・新規Database Preflight
3. 3.2B Ubuntu本番fixture
4. 3.3 Local LLM provider probe
5. 3.4A 本番Run

既存の互換Description Databaseを使う場合は3.4が通常経路です。同じProgramと構造なら、別Endpointでも
構造依存Descriptionを再利用し、Endpoint依存のLens、score、deep dive、reportだけを再計算できます。

## 4. Phase 1～6

```text
入力・Endpoint
   │
   ▼
P01 18 Description／距離／構造表現
   │
   ▼
P02 fragment・MMP・context catalog
   │
   ▼
P03 6 Lensで候補FindingとEvidenceを生成
   │
   ▼
P04 固定gateと総合scoreで順位付け
   │
   ▼
P05 固定templateによる反証・追加検証
   │
   ▼
P06 引用検証、統合、HTMLレポート
```

RuntimeはDAG依存関係、retry、attempt、hashをSQLiteで管理します。workerはState DBへ直接書かず、
coordinatorだけが更新します。`workers`は全処理が常時占有するコア数ではなく、Nodeが使用できる上限です。

## 5. 6つのLens

| Lens | 問い | 主な図 |
|---|---|---|
| L1b | ある化合物の局所近傍でSARが外れるか | 注目化合物、距離順近傍、局所改善 |
| L2a | MMP変換の効果が特定文脈で変わるか | 変換前後構造、実測pair、効果分布 |
| L2b | fragment効果が系列を越えて一貫／不均一か | fragment、代表化合物、系列別寄与 |
| L4 | 未探索だが到達可能な候補領域はどこか | candidate、source、近傍Endpoint |
| L5 | featureとEndpointの関係が文脈で反転するか | 文脈内外の散布図と回帰線 |
| L7 | SARを系列間で移植できるか／順位が反転するか | core、共通R基、実測pair、系列対応 |

## 6. Local LLMの役割

`llm.command`はMCPでもClaude CodeのTool callでもありません。P05/P06が1 logical callごとに起動する
provider commandです。providerはstdinのJSON 1行を受け、内部vLLM APIへ送り、stdoutへschema-validな
JSON 1行だけを返します。

LLMが行わないこと:

- Description、距離、p/q値、効果量、scoreの計算
- Findingの発見や最終状態の決定
- OS command、解析Tool、外部検索の実行
- 引用にない数値・ID・事実の追加

## 7. 結果を確認する

P06成功後は`report.html`を入口にします。

- 1～10位: 表紙で図・説明・統計要約を確認。
- 11～20位: 表紙はタイトルだけ。link先の個別HTMLで全内容を確認。
- 上位20件: 全件にLens固有図を含む個別HTMLを生成。
- 20位より下: Finding IDを指定して受入済み成果物から追加HTMLを生成可能。

順位はp値だけでは決まりません。固定gate通過後に統計的強度、頑健性、非自明性、実行可能性、探索価値を
統合したscoreで並びます。HTMLの読み方は[レポートガイド](CONDUCTOR_0.2.1_reporting_guide.md)を参照してください。

## 8. 受入と保存

完走後は運用プロンプト3.8でread-only監査します。Run rootとDescription Databaseを変更せず保存し、
次のEndpointへ進みます。受入に必要なのは見た目だけではなく、artifact hash、Finding/test整合、citation、
HTML図の入力追跡、外部resource不使用まで含みます。

## 9. 停止時

- `failed`: 4.1でNodeをread-only診断。入力、環境、provider、schema、実装へ分類。
- `needs_design_review`: thresholdや成果物を自動修正せず、guard根拠を人間へ提示。
- 中断: 3.7で同一Runが稼働中でないことを確認して再開。

成功済みNodeを場当たり的に再実行したり、Runtime SQLiteを直接編集したりしないでください。
