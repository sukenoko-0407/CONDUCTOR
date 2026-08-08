# cs-conductor-run-audit

## SKILLの目的

CONDUCTOR RunのDAG、ID、単一Writer制御、実行attempt、artifact、Interpretation終端条件をState非変更で監査します。

## 想定利用シーン

- Round再開時のQuick Audit
- Agent停止・lease takeover後のFull Audit
- Round終了直前または人間からの明示的監査

## 環境構築

launcherがSkill内のPixi環境を自動構築・再利用し、cacheも `env/` 内へ置きます。

## 利用例

```bash
python .claude/skills/cs-conductor-run-audit/scripts/launch.py \
  --state results/CONDUCTOR/project/run/state.json --mode full
```

## 制約事項

Stateは変更しません。監査結果は科学的EvidenceやDAG Nodeではありません。

## 変更履歴

| Version | 変更内容 |
|---|---|
| 1.0.0 | Quick/Full Run監査を追加 |
