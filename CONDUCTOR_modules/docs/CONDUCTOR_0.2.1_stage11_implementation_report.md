# CONDUCTOR 0.2.1 段階11 実装チェックポイント

作成日: 2026-09-17  
対象: 段階7〜11（段階6停止後に明示承認を受けて着手）

## 結論

段階7〜11の Skill、公開契約、合成データ回帰、Runtime の基本経路まで実装した。catalog の checkpoint は `stage11_runtime` で、Description 18件と pipeline 12件を収録する。

実装適合性残件は追加実装と回帰試験を完了した。正式受入には、実データ較正と実際の offline provider を用いた運用確認が残るため、配布判定は引き続き保留する。

## 実装済み

| 段階 | 実装 |
|---|---|
| 7 | L5、L1b、L2a、L7、L4。候補、検定、Finding、scoring observation、CLI/manifest を実装 |
| 8 | 5軸 score、固定 gate、重複 Finding 保持、K=10 未達時の `needs_design_review` |
| 9 | T01〜T10 executor、決定論 judge、深さ/分岐/検定予算、offline JSONL Local LLM、再試行・失敗率判定 |
| 10 | typed entity graph、Run 内 path/hash/row、数値1%、compound/pair registry、test p/q/statistic の fail-closed 検証 |
| 11 | SQLite WAL state、lease、late event 隔離、1回再試行、DAG依存解決、resume、監査 event |

L7 の系列平均差は R 基 label 並べ替えでは不変になるため、主効果のみ対応 R 基内の骨格 label 交換へ補正した。詳細仕様書7.7節と Q-011 に反映済みである。

## 検証済み

- `CONDUCTOR_modules/tests`: 75 tests passed
- package layout: Description 18件、pipeline 12件で catalog と filesystem が一致
- 新規 pipeline Skill の `SKILL.md` / `capability.json` / Pixi manifest / lock を配置
- 配布対象30 Skillの `pixi lock --check` と、pipeline 12 Skillの隔離環境 smoke test が成功
- Runtime の成功 node 再利用と依存待ちを統合テスト
- Local LLM の schema 不正再試行と全試行失敗を subprocess fixture で確認
- 引用の数値許容差、hash不一致、pair registry 不在を fail-closed で確認
- L4 は生成候補を Phase 1 と同一パラメータの全 Tier 1/2 Description Skill で再記述し、候補―観測化合物間距離を Phase 1 の特徴列・補完・標準化で算出
- scoring の `E_adj` は L1b/L2a/L2b/L4/L5/L7 ごとの最小観測単位で Endpoint を残差化し、元のレンズ効果統計を再計算
- Deep Dive の T03/T04/T07/T08 は親レンズ別 replay adapter による再実行へ置換
- Hammett は一つの芳香族6員環上で置換位置と対象置換基が一意に meta/para へ対応する場合だけ自動採用し、それ以外は Gasteiger fallback
- fragment engine の worker数1/2で SQLite と全CSVの byte-identical を確認
- 小規模 fixture による Phase 1→6（表現、文脈、Lens、scoring、DeepDive、引用検証）の一気通しを確認

## 正式受入までの残件

### 外部入力を要するもの

1. 較正961化合物の実データで L2b、L5、L1b、全 lens、K=10 を再現する。
2. Ubuntu CPU機で`llm.command`とvLLM接続設定を行い、別GPU機上の実modelへ3タスクをprobeした後、Phase 5〜6をend-to-end実行する。

### Local LLM provider準備状況

- 別GPU機上の承認済み`vllm serve` OpenAI互換APIへ接続する標準ライブラリ実装を`CONDUCTOR_modules/local_llm_provider/`へ追加した。接続先固定、credentialの環境変数取得、proxy/redirect拒否、JSON Schema structured outputを含む。
- JSONL 1入力/1出力、固定・記録したmodel推奨sampling、固定seed、response schema拘束、request ID、task別出力、citation IDをfail-closedで検証する。
- model hash、量子化、backend版、prompt hash、provider config hashをstderrへ出し、Skill attempt logへ保持するようにした。
- 開発機ではWindows Application Controlがuv管理Pythonを拒否したため、JSONとGit差分の静的検証まで実施した。擬似OpenAI互換serverによる3タスクtestと、CPU機から実GPU modelへのprobeは未実施である。

### 実装適合性の完了項目

1. L4 の source-neighborhood proxy を廃止し、候補 Description の二段実行と exact cross-distance に置換した。
2. scoring の交絡説明率による縮約を廃止し、承認済みのレンズ別 residualized Endpoint 再実行に置換した。
3. Deep Dive の T03/T04/T07/T08 を親レンズ固有の効果統計 replay に置換した。再実行情報が不足する場合は proxy に戻さず `not_testable` とする。
4. Hammett の一意 meta/para 自動対応と Gasteiger fallback を実装し、両経路を検証した。
5. worker数1/Nの byte-identical 比較と Phase 1→6 小規模E2Eを追加した。

したがって、次の工程は上記外部入力2項目を用いた本番相当実行である。閾値は変更せず、生 Artifact と監査情報を保持して較正結果を評価する。
