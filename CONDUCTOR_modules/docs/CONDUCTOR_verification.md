# CONDUCTOR 0.1.2 verification

## Package

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/launch.py catalog --check
```

全schemaのJSON parse、CatalogのID一意性、Skill／Agent参照、Version統一を確認します。

## Runtime

`CONDUCTOR_modules/tests/test_runtime_012.py`は次を検証します。

- 人間authorizeなしにRoundを開始できない。
- live leaseとone-use Action tokenが二重Writerを防ぐ。
- Node IDがRun全体の単調連番で、状態が5種類に限定される。
- 中断後も同じRoundを再開し、勝手に次Roundを作らない。
- InterpretationとFull Auditなしにhuman reviewへ移行できない。
- Cluster scopeをGlobalとするdraft、誤ったCluster ID、sample不整合を拒否する。
- partial Ledgerを伴うpending transactionとstale writer lockを復旧できる。
- Working Setが設定上限を超えない。
- 過去Roundの成功Nodeが次Roundの明示的な再利用参照となる。
- Interpretation review contextがScope／Operatorを偏らせず上限内に収まる。

## Scientific Skills

既存のDescription、Clustering、Operatorテストにより一般利用CLIと計算結果を確認します。Vector Clusteringは手法別auto calibration、endpoint非依存、minimum Cluster size、negative partition保持を確認します。

## Human report

Interpretation HTMLは日本語、固定section、低彩度配色、print CSS、scope fact panel、evidence link、coverage、未確認範囲を持つことを確認します。scope、Cluster ID、sample count、Operator、Result別sample数はResult Cardから再計算して照合し、artifact linkはFull Auditで存在確認します。Operator reportとState reportの表示は導入先smoke testでも目視確認します。

Windows開発環境での最終回帰結果は`23 passed, 7 skipped`です。skipされた7件はsystem PythonにRDKitがない場合のVector Clustering実計算であり、各SkillのPixi環境とLinux／共有filesystemは本番導入時に別途smoke testを行います。
