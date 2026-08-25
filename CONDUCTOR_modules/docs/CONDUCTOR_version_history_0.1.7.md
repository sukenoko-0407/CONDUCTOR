# CONDUCTOR 0.1.7 変更履歴

0.1.7は、0.1.6の科学計算・Result Card・MMP Databaseを維持し、Operator探索とInterpretationの間へ少数Result逐次Screeningを追加したVersionです。50件一括読込というLocal LLMの認知上限を、Roundあたりの探索上限として使わないことが主目的です。

## Version推移

| Version | 主な変更 |
|---|---|
| 0.1.0 | beta基盤、Clustering呼称、PCA／UMAP、複数Description model |
| 0.1.1 | Vector Clustering calibrationとDescription限定migration |
| 0.1.2 | compact Control正本、Runtime中心のRound管理 |
| 0.1.3 | Main Agent Orchestrator、短命Executor／Interpreter、共通Runtime制御 |
| 0.1.4 | A014 MMP DatabaseとGlobal–Local解析基盤 |
| 0.1.5 | 共通Execution Request、単一exploration、省容量MMP |
| 0.1.6 | OS Runtime Worker、冪等packet再接続、同一Node repair、受入E2E |
| 0.1.7 | 逐次Result Screening、可変Operator予算、選抜型Synthesis、screening／full Round |

## 0.1.7の変更

- 人間指定のOperator予算をprofile安全上限500まで許可し、最大25 Nodeずつ遅延計画する。
- 成功Result Cardを最大8件ずつScreeningし、5項目合計0～10点の確認優先度と独立した証拠強度を記録する。
- Run-wide正本`runtime/result_assessment_index.jsonl`、Round別CSV、compact Screening Summaryを追加する。
- `report_mode=screening`では正式Interpretationを省略し、広い探索を効率化する。
- `report_mode=full`では、評価上位だけでなくScope／Operator多様性と関連結果を含む最大50 Resultを正式Synthesisへ渡す。
- 既存Interpreterを`screening`と`synthesis`の二モードにし、別Agent種別を増やさない。
- 0.1.6進行Roundは従来のfull gateを維持し、0.1.7方式は新Roundから使用する。

## 変更しないもの

- Description、Clustering、Operatorの科学kernelと一般利用CLI。
- Canonical Description／Clustering／Analysis ResultおよびResult Card schema 1.0.0。
- A014 MMP Databaseの正本、全詳細CSV、read-only Global–Local専用解釈。
- 5状態Node、DAG、単一Writer lease、Execution Request、署名付きPacket、OS Runtime Worker。
- 人間だけがRoundを開始、受理、次Round作成する権限境界。

## 互換性

0.1.6のRun成果物は変換・再計算せず参照できます。`report_mode`のない0.1.6進行Roundはfullとして完了し、途中でScreening gateへ切り替えません。0.1.7の評価索引は必要なResult Cardから遅延生成されます。
