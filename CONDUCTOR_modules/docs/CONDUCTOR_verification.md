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
- 一次評価は各Review Bundle内のResultを最低1件引用し、Bundle固有の数値・比較・品質事実を理由に含める。同一内容または同一理由を複数Bundleへ複製したdraftはcommitされない。
- Review BundleにOperator固有の評価anchorが同梱され、既定4 Bundleの小batchで評価される。
- Candidate classはRuntimeの固定決定表だけが確定する。
- 正式Interpretationは`design_lead`と`contextual_anomaly`だけを単独Insight候補にする。
- Cluster-local ResultをGlobalと表示せず、比較claimがReview Bundle内のcomparatorを参照する。
- Insightがゼロ件でも日本語Markdown／HTMLを作り、negative resultを長く列挙しない。
- 累積Interpretationは人間承認した報告専用Full Roundとして実行され、指定したCLOSED Roundの最新一次評価だけを参照する。過去の正式Insightに使用済みのReview Bundleは候補から除外され、Description、Clustering、Operator Nodeを追加しない。
- historical re-Screeningは明示されたCLOSED Roundの保存済みReview Bundleだけを対象にし、対象集合をRound contractでhash固定する。Operator Nodeを追加せず、Assessmentに実行RoundとSource Roundを記録し、元Roundを変更しない。
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
