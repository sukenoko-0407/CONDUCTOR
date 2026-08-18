# cs-conductor-dispatch

## SKILLの目的

人間の依頼をCONDUCTORのRound操作へ安全に変換し、Orchestratorの重複起動や自動新Round開始を防ぎます。

## 想定利用シーン

新Round開始、Active Round再開、同一Round継続、Interpretation修正、Round確定、状態確認に使用します。

## 環境構築

初回実行時にSkill内Pixi環境を自動構築します。

## 利用例

```bash
python scripts/launch.py verify-return --run-root /path/to/run
python scripts/launch.py verify-return --run-root /path/to/run --confirm-returned --owner-id session-001 --start-revision 42
```

## 制約事項

科学的な解析選択は行いません。人間の明示指示なしにRoundを開始・継続・確定しません。「次Round開始」が明示された場合も、前Round acceptと次Round authorizeを別Eventとして順に実施します。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | 初版 |
