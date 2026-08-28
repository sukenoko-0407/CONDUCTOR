# CONDUCTOR 0.1.8 深度検証レポート

検証日: 2026-08-27

## 結論

主要なCONDUCTOR実行経路、代表的なDescription・Clustering・Operator、状態遷移、SchemaおよびInterpretation関連契約を確認した。検出した5件の実不具合と1件の手順不整合は局所修正し、全回帰試験を通過した。

本検証機はWindowsであり、Linux実機での長時間HPC計算までは実行していない。Linux互換性については、全SkillのPixi platform、共有Pixiパス、Skill-local cache/tmp、CLI契約およびPOSIXプロセス制御を静的・自動試験で確認した。

## 実施シナリオ

| シナリオ | 対象 | 結果 |
|---|---|---|
| Runtime E2E | Run初期化、Round準備・承認・再開、基本計算計画、Packet生成、D001実行、成果物promote、State更新 | PASS |
| Description | D001 RDKit 2D、D002 Morgan | PASS |
| 構造Clustering | C001 Murcko、C002 MCS | PASS |
| Vector Clustering | D001由来dense vector、D002由来binary vectorをC005へ入力 | PASS |
| Metric契約 | denseはEuclidean、Morgan binaryはTanimoto | PASS |
| Operator | A001の一般利用・CONDUCTOR利用、追加Operator試験群 | PASS |
| Interpretation | screening、再Screening、累積Interpretation、HTML renderer、MMP read-only Interpretation | PASS |
| 入力異常 | 無効SMILESを行保持して警告、重複IDをhard error | PASS |
| Schema/Version | producer/consumer、local `$ref` registry、Result Card、Assessment、MMP | PASS |
| Packet/State | Packet署名・hash・TTL、Lease、失敗分類、Round終了条件 | PASS |
| Linux配備契約 | 53 Skillの`linux-64`/`win-64`、共有Pixi、Skill-local cache/tmp | PASS（静的確認） |

### 実データ簡易試験

リポジトリのJAKデモCSV（231化合物）を使用した。

- D001 Runtime E2E: 231行、217特徴量を生成し、Nodeを`succeeded`として登録。
- C002 MCS: 100ペアをseed固定の一様ランダム・非復元抽出で評価し、28 Clusterを生成。未所属0、重複所属を保持。
- D002 → C005: Tanimotoで14 Cluster、162 membership、69 unassignedを生成。
- 無効SMILES: 3入力行を維持し、該当行へ`invalid_smiles`を記録。
- 重複ID: 非ゼロ終了し、結果を確定しないことを確認。

## 検出・修正した問題

### 1. Windows legacy code pageでのRuntime出力失敗

Runtime自身または子Skillが、CP932に存在しない記号を標準出力へ書くと、計算やState更新が完了していても表示段階で失敗し得た。

対策:

- Runtime CLIのstdout/stderrをUTF-8へ統一。
- Runtime WorkerおよびSkill子プロセスへ`PYTHONUTF8=1`と`PYTHONIOENCODING=utf-8`を明示。
- ログの正本をUTF-8に固定する回帰試験を追加。

### 2. MMP InterpretationのWindows `--help`失敗

argparse説明文のen dashがCP932で出力できなかった。ASCII hyphenへ変更し、CP932を明示したsubprocess試験を追加した。

### 3. 現在Roundの再Screeningに関するOrchestrator手順の矛盾

詳細手順では再Screeningを許可していた一方、冒頭の依頼分類と`AWAITING_HUMAN_REVIEW`規則から欠落していた。分類と許可操作を一致させ、契約試験を追加した。

### 4. read-only MMP InterpretationのVersion不一致

I002はRunの`conductor_version`を厳密確認する一方、Skill内定数とCapability metadataが`0.1.6`のままであり、`0.1.8` Runを拒否していた。双方を`0.1.8`へ揃え、Package Version、Capability Version、実行時定数の一致を検証する契約試験を追加した。

### 5. Result ConciergeのVersion不一致

read-only Conciergeも`0.1.6/0.1.7`だけを許可しており、現行`0.1.8` Runを拒否していた。Capability metadata、実行時定数、Skill説明を`0.1.8`へ統一し、Run Versionを厳密確認するread-only Skillを横断して検査する契約試験へ拡張した。

### 6. adapter同期ツールの旧Version書戻し

開発用adapter同期ツールがVersionを`0.1.6`へ固定しており、再実行するとCapabilityとArtifact Schemaを旧版へ戻す状態だった。Packageの`VERSION`を一度読み、その値を全生成先へ使う実装へ変更し、旧Version literalが再導入されていないことを契約試験へ追加した。

## 回帰試験

- 中央テストスイート: 177件PASS、25件SKIP。
- Vector Clustering専用環境: 10件PASS、1件SKIP。
- Analysis追加機能: 9件PASS。
- MMP統合: 5件PASS。
- tracked Python 203ファイル: compile error 0。
- Package layout: PASS。
- Catalog: allowlist 49 capabilitiesを検証。

SKIPは、専用の科学計算依存環境を必要とする試験、またはこのWindows機では実施不能なLinux限定経路である。機能失敗としてのSKIPではない。

## Linux実機での最終受入項目

次の処理は計算資源またはモデル資産に依存するため、Linux本番機で最終確認する。

1. D019 xTB、D016 Mordred 3D、C002 MCSのCPU利用上限と長時間完走。
2. D020 ChemBERTaのローカルWeight読込と、ネットワークdownloadが発生しないこと。
3. A014 Global MMPの実規模Database容量、完走時間およびread-only MMP Interpretation。
4. screening batchの並列評価と直列commit、正式Interpretation、Full Audit、`AWAITING_HUMAN_REVIEW`到達。

## 残存する運用上の注意

53個の`pixi.toml`に対して、リポジトリ内の`pixi.lock`は14個である。lockがないSkillは初回起動時にPixiがlockと環境を作成し、以後は`--locked`で再利用する設計であり、通常運用上の不具合ではない。ただし、完全offlineの初回構築には事前の環境構築またはlock整備が必要である。
