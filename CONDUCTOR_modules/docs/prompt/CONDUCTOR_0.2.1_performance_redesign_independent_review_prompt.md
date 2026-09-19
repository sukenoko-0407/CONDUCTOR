# CONDUCTOR 0.2.1 性能再設計・独立レビュー依頼プロンプト

作成日: 2026-09-19  
用途: 先行Agentが作成したL5および全Lens性能再設計案を、別Agentが独立に評価し、代替案を提示する。

以下のtext blockを別Agentへそのまま渡す。別環境でrepositoryのmount pathが異なる場合だけ、先頭の`PROJECT_ROOT`と、それをprefixに持つ絶対pathを実在pathへ機械的に読み替える。

```text
あなたはCONDUCTOR 0.2.1の性能・頑健性再設計を独立評価するReview Agentです。先行Agentの案を承認することが目的ではありません。repositoryの仕様、実装、testを自分で確認し、事実、問題がない部分、確認済みの問題、測定不足、あなた自身の代替案を分離してください。

PROJECT_ROOT:
C:/Users/kimot/coding_workspace/CONDUCTOR

重要な前提:
- 対象本番機はUbuntu、logical CPU 64、RAM total 755 GiB、他利用者jobなしです。
- LLM推論は別GPUサーバであり、Lens計算はCPU機で行います。
- 対象データは961化合物です。
- 本番観測として、現行L5は実質1コアのまま8時間以上継続しました。
- 過去にL4が約25万raw候補を生成し、全候補再記述を計画してKILLされたため、現在はcandidate/row/cost guardが追加されています。
- 先行Agentのmatrix-first案は一つの案にすぎません。採用済み仕様として扱わないでください。

最初に必ず読む文書:
1. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_specification_overview.md
2. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_plan.md
3. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md
4. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/design/discovery_lenses.md
5. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_stage11_implementation_report.md
6. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_production_remediation_report.md
7. C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_history_and_l5_redesign.md

必ず確認する実装:
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-context-builder/python/conductor_context_builder/builder.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-stat-core/python/conductor_stat_core/statistics.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l1b/python/conductor_lens_l1b/l1b.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l1b/scripts/run.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2a.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2b.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l2/scripts/run.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l4/python/conductor_lens_l4/l4.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l4/scripts/run.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l5/python/conductor_lens_l5/l5.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l5/scripts/run.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l7/python/conductor_lens_l7/l7.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-lens-l7/scripts/run.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-runtime/python/conductor_runtime/dag.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/.claude/skills/cs-runtime/python/conductor_runtime/state.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/tools/production_run.py

必ず確認するtest:
- C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/tests/unit/test_stage7_lenses.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/tests/unit/test_l2b.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/tests/integration/test_runtime_dag.py
- C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/tests/integration/test_production_run.py

0.1.x Boolean membership matrixの履歴も、科学的仕様ではなく計算基盤の比較対象として確認してください。Git ref 0.1.11が存在する場合は次をread-onlyで確認してください。
- 0.1.11:CONDUCTOR_modules/tools/runtime_controller.py の promote_cluster_runtime()
- 0.1.11:CONDUCTOR_modules/docs/CONDUCTOR_0.1.9_specification_overview.md の4.3節
- 0.1.11:CONDUCTOR_modules/docs/CONDUCTOR_0.1.9_implementation_plan.md の6章

評価対象:
- L1b
- L2a
- L2b
- L4
- L5
- L7
- 診断扱いのL1a/L3/L6
- cs-stat-coreのpermutation共通基盤
- cs-runtimeのCPU/memory admission、Node内/Node間並列、heartbeat、checkpoint、KILL復旧

必須の評価方法:
1. 各Lensの候補生成、観測統計、screen、final、BH、出力生成を処理段階へ分解してください。
2. 入力規模を表す変数を定義し、時間・メモリ計算量を可能な範囲で式にしてください。
3. --workersがparseされることと、実kernelがworkerを消費することを区別してください。
4. 固定入力から再利用できる中間量と、permutationごとに再計算が必要な量を区別してください。
5. 現行testが科学的正しさ、決定性、性能、resource safety、復旧のどこまでを保証しているか確認してください。
6. production benchmarkがない事項を性能問題と断定しないでください。逆に、小規模fixture合格を本番性能合格と扱わないでください。
7. 科学的契約を変える提案と、同じ統計量を速く計算する提案を明確に分けてください。

先行Agent案の評価:
- Boolean context membership matrix
- L5 context×feature相関表の一回計算
- 符号集合からの候補生成
- L1b neighbor indexの事前compile
- L2a pair-inside/outside matrix
- L2a/L2b/L7の共通permutation task protocol
- L4のdisk-backed candidate集約とsharding
- process並列、BLAS/OpenMP thread=1、read-only mmap
- Runtime resource token、Popen監視、heartbeat、node_tasks checkpoint

これらについて、それぞれ次を判定してください。
- 正しい
- 条件付きで妥当
- 不要な複雑化
- 誤りまたは科学的同値性を壊す
- 証拠不足

あなた自身の解決案:
- 先行Agent案とは独立に、少なくとも1つの代替アーキテクチャを提示してください。
- 可能なら、(A) matrix/process-shard、(B) compiled/vectorized single processまたはBLAS並列、(C) candidate/iteration分割など複数案を比較してください。
- Lensごとに同じ方式を強制せず、現行のまま維持する選択肢も評価してください。
- 変更量、科学的同値性、期待speedup、peak memory、checkpoint容易性、Windows/Linux再現性、実装・test工数を比較してください。
- 根拠のないspeedup倍率を断定しないでください。

出力形式:
1. Executive summary
2. 確認した事実とsource path/line
3. 現状で問題ないこと
4. 確認済みの課題
5. benchmarkが必要な未確認事項
6. Lens別評価表
7. 先行Agent案への賛否と理由
8. あなた自身の代替案
9. 比較表と推奨する実験順序
10. 仕様変更が必要な事項と、実装だけでよい事項
11. 科学的同値性・性能・resource safety・KILL復旧の受入条件
12. 現Runを止める／保持する／新Runへ移る判断

各主張には可能な限り絶対pathとline番号を付けてください。事実と提案を同じ文で混ぜないでください。

初回レビューでは既存ファイルを変更しないでください。レビュー結果は新規文書として次へ作成してください。
C:/Users/kimot/coding_workspace/CONDUCTOR/CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_independent_performance_review.md

先行Agentの文書は上書きしないでください。実装変更はレビュー提出後、人間が採用方針を決めてから行ってください。
```
