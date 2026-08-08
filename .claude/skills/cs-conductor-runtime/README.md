# cs-conductor-runtime

## SKILLの目的

CONDUCTORのDAG、Node ID、Round、単一Writer lease、実行attempt、Interpretation終端条件を決定論的に管理します。通常は `cs-conductor-orchestrator` Agentから内部利用します。

## 想定利用シーン

- 新規Runの初期化と複数Roundの継続
- Description / Grouping / Operator / Interpretationの部分追加
- Agent停止後の安全な再開
- Round終端前の状態確認

## 環境構築

launcherがSkill内のPixi環境を自動的に作成または再利用します。Linuxでは共有Pixiバイナリを優先し、cacheはすべて `env/` 内へ置きます。

## 利用例

```bash
python .claude/skills/cs-conductor-runtime/scripts/launch.py state bootstrap \
  --state results/CONDUCTOR/project/run/state.json --owner-id session-01
```

返されたlease tokenを、そのセッションのState変更コマンドへ `--lease-token` として渡します。

## 制約事項

一般解析用Skillではありません。Stateの直接編集、複数Writer、InterpretationなしのRound完了は許可されません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | v4.3.1の決定論的Runtimeとして名称と責務を分離 |
