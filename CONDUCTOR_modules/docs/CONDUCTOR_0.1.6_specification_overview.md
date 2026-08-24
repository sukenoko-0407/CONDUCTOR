# CONDUCTOR 0.1.6 仕様概要

## 位置づけ

0.1.6は、0.1.5で導入した共通Execution Requestと単一explorationを維持し、実運用で顕在化したExecutor早期終了、Packet再投入、長時間process所有、再試行後の品質状態を頑健化した受入Versionです。科学Skillの意味や一般利用CLIを作り替えるVersionではありません。

Mordred 3Dの複素数変換警告と入力依存の欠損Descriptorは現行挙動として受容し、0.1.6では科学kernelを変更しません。

## 実行責務

| Component | 責務 |
|---|---|
| Human | Round開始、CPU・並列数・時間予算、継続／停止、修正後の再試行を承認する |
| Main Agent / Orchestrator Skill | Runtimeの一つの`required_action`に従い、科学的な対象選択とInterpreter起動を行う |
| Runtime | Control、Node ID、Attempt、DAG、Packet、成果物昇格、Interpretation gateの唯一のWriter |
| Runtime Worker | 署名済みPacketを原子的にclaimし、科学processを完了まで所有する |
| Executor Subagent | 通常は使用しない互換attachment。指定PacketをRuntimeへ一度渡すだけで、DAG判断やCLI修正をしない |
| Interpreter Subagent | boundedなResult集合をread-onlyで比較し、Interpretation draftを返す |

通常経路では、Mainが`prepare-execution-packet`後に`execute-packet`を一度呼びます。Runtime WorkerはMainのTool callやsessionから独立して継続します。同じPacketの再投入は既存Workerへの再接続または保存済みterminal結果の返却となり、科学processを二重起動しません。

## 状態遷移と異常時の境界

- live Workerまたは科学processが存在する間は`WAIT_RUNNING`であり、Mainは代行実行や短間隔pollをしない。
- Workerと科学processの双方が消失した場合だけ`RECONCILE_RUNNING`を一度実行する。
- 一時障害は同じNode IDの新Attemptとして扱い、契約・入力・実装不良を無限再試行しない。
- 人間がRoundを開始しない限り、RuntimeもMainも新Roundを作らない。
- 再試行成功時は過去Attemptの失敗品質を残さず、成功成果物から`result_quality`を確定する。
- Interpretation JSON／Markdown／HTMLとFull Auditが揃うまで`AWAITING_HUMAN_REVIEW`へ進まない。
- Windows／同期対象directoryで一時fileの原子的置換がscanner等に短時間占有された場合、原子性を保ったまま`PermissionError`だけを最大5秒の範囲で再試行する。別種のI/O errorは隠蔽しない。

## 維持する科学・探索仕様

- Description、Clustering、Operator、Interpretationの疎結合構造
- `--conductor-request`と一般利用CLIの分離
- 一Round最大50 Analysis Node、通常Interpretation最大50 Result Card、Global優先、成功済みsignatureの非復元選択
- Local Analysisに対応Global comparatorを要求する原則
- A014 MMPの全詳細CSV、正規化SQLite、Summary、Reference Card、および人間起動のread-only Global–Local MMP解釈
- ConciergeのRun State非干渉と`run_root/concierge/`限定書込み
- 並列Skillの内部worker数を`available_cpu_cores`内へ制限する資源契約

## 0.1.6で確認すること

0.1.6の受入では、小規模fixtureだけでなく、JAK2実データを用いてRuntime経路、複数種類のDescription／Clustering／Operator、Interpretation、Full Auditまでを一つのRoundとして確認します。WindowsではxTB native環境の既知制約を分離し、Linux HPCでは共有Pixi、xTB、長時間process、CPU上限を最終確認します。

旧Runのmigrationと後方互換は提供しません。新規Runとして開始します。
