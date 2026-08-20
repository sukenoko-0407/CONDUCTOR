# CONDUCTOR 0.1.3 verification

## Package

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/launch.py catalog --check
```

全schemaのJSON parse、CatalogのID一意性、Skill／Agent参照、Version統一を確認します。

## Runtime

`CONDUCTOR_modules/tests/test_runtime_013.py`は0.1.3固有の境界を、既存Runtime回帰testは基本状態管理を検証します。

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
- OrchestratorがAgentではなく手動起動Main Skillとしてだけ存在する。
- Executor packetが署名、revision、Action token、期限へ結び付けられ、二重利用できない。
- ExecutorへMain lease tokenを渡さず、Runtime応答が16 KiB以下に収まる。
- Interpretation quality失敗が同じNodeの有限Attemptとして記録され、正常終了扱いにならない。
- Analysis Nodeが1 Round最大200件、1回の計画登録最大50件、初期Global最大100件に制限され、Local解析用容量が残る。
- 未Node化候補が次の人間承認Roundで成功済みsignatureを除外して決定論的に再構成される。

## Scientific Skills

既存のDescription、Clustering、Operatorテストにより一般利用CLIと計算結果を確認します。Vector Clusteringは手法別auto calibration、endpoint非依存、minimum Cluster size、negative partition保持を確認します。

## Human report

Interpretation HTMLは日本語、固定section、低彩度配色、print CSS、scope fact panel、evidence link、coverage、未確認範囲を持つことを確認します。scope、Cluster ID、sample count、Operator、Result別sample数はResult Cardから再計算して照合し、artifact linkはFull Auditで存在確認します。Operator reportとState reportの表示は導入先smoke testでも目視確認します。

配布前にWindows開発環境の自動testに加え、Linux共有filesystem上で小規模RunをDescriptionからInterpretation／Full Auditまで通すsmoke testを行います。

## 0.1.3実装時の確認結果

- Windows開発環境: `35 tests OK`、`1 skipped`
- skip対象: Leiden（共通開発環境に`igraph`／`leidenalg`がないため。Skill専用Pixi環境が正本）
- Package layout: PASS
- Catalog: allowlist 47件を検証、PASS
- Installer: 空のProjectへのdry-runおよび実copy後のPackage検証、PASS
- Python compile、全JSON Schema parse、`git diff --check`: PASS

Linux共有filesystem上での一Round end-to-end smokeは、配布先での受入試験として残します。
