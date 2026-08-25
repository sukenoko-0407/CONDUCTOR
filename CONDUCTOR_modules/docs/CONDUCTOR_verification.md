# CONDUCTOR 0.2.0 verification

## 必須検証

- Package、Catalog、Runtime、protocol、成果物manifestが0.2.0で一致する。
- A001～A014に有効なOperator Interpretation Profileがあり、Result Card v2が共通schemaを満たす。
- `higher_is_better=true/false`の両方でfavorable方向が正規化される。
- Global、Global–Local、sibling Cluster Review Bundleが決定論的に再生成される。
- comparator必須のLocal Resultは一致Globalがなければ`awaiting_comparator`となり、一次評価されない。
- metric、Description、Operator parameterが異なるResultを誤って同じcomparison familyへ入れない。
- sibling Clusterの重複を独立supportとして扱わない。
- 一次評価は0～3の絶対複数軸と信頼性を分離し、合計点を持たない。
- Candidate classはRuntimeの固定決定表だけが確定する。
- 正式Interpretationは`design_lead`と`contextual_anomaly`だけを単独Insight候補にする。
- Cluster-local ResultをGlobalと表示せず、比較claimがReview Bundle内のcomparatorを参照する。
- Insightがゼロ件でも日本語Markdown／HTMLを作り、negative resultを長く列挙しない。
- Result Card、Review Bundle、Assessment、Interpretationの全参照先がRun Root内に存在する。
- Main session中断、Packet再投入、Lease期限、Worker再接続で科学processを二重起動しない。

## 実行方法

```bash
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/build_catalog.py --check
pytest -q CONDUCTOR_modules/tests
```

環境依存の科学Skill試験は各SkillのPixi環境を使う。0.2.0は0.1.x Run Rootの継続を受入条件に含めず、新規RunでDescription → Clustering → Global Operator → Local Operator → Bundle assessment → Interpretation → Full Auditを確認する。

## 合格記録

Release時に実行日、platform、test件数、skip理由、E2E Run Rootの一時pathを追記する。未実施の試験を合格済みと記載しない。
