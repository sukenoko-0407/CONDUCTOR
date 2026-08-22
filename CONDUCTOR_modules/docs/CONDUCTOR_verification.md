# CONDUCTOR 0.1.5 verification

## 必須確認

- Package、Catalog、Capability、Artifact Manifestのversionが0.1.5として整合する。
- 全科学Capabilityに`conductor_request` metadata、adapter、共通launcherがある。
- 各launcherが同一Skillの並行初回起動を排他し、`pixi.lock`と環境ready markerが一致したときだけ再利用する。
- Request schemaがidentity、input hash、columns、endpoint、scope、parameter、resources、outputをfail closedで検証する。
- packet作成後にinputまたは上流成果物を変更すると、Skill process開始前にSHA-256不一致で拒否される。
- Runtime commandが全Skillで`--conductor-request`固定形となり、Python絶対path差をcommand hashへ混ぜない。
- packetは署名、Control revision、lease hash、Request hash、期限で一回の実行へ固定される。
- Skill output directoryは起動前に存在せず、Runtime管理fileと衝突しない。
- one-use Action token、Executor token、adaptive command recovery、Skill別Runtime CLI builderが残っていない。
- Operator探索は`exploration`一種類で最大100 Node、Global優先、履歴バランス、成功済みsignature除外を満たす。
- Local Analysisは対応Global comparatorを持つ。
- Global deliverableはGlobal scopeだけで満たされ、基本計算は計画Node集合すべての完了で判定される。
- Failed Nodeは成功済み探索履歴へ数えられず、再試行時にもNode IDを増やさない。契約・列・path不良は自動反復しない。
- Result Indexの全artifact linkがRun Root相対の正規形で、実在し、Run Root外へ解決されない。
- 長時間processのstdout/stderrは逐次logへ書かれ、timeout時に子孫process treeが残らない。
- RoundはInterpretation JSON／Markdown／HTMLと登録済Full Auditなしにhandoffできない。
- Executorはpacketを一回実行して終了し、InterpreterはStateを変更しない。

## MMP確認

- 標準defaultがcuts 2、radius 0～2、core heavy atoms 8、core fraction 0.5、variable heavy atoms 10である。
- 3 cutsまたはradius 3～5が`extended_search`なしに拒否される。
- 全詳細CSV、正規化SQLite、全Summary、reference card、storage profile、HTMLが生成される。
- Native work DBが完成後に削除される。
- Native context JOINを全件DataFrame化せず、SQLite cursorのbounded `fetchmany()`で処理する。
- SQLite fact tableが反復構造文字列を保持せず、joinで詳細行を再構成できる。
- CSV／SQLiteのPair ID集合とrow countが一致する。
- radius contextがpair supportを水増ししない。
- Local screen／detailがGlobal DBを変更しない。
- qualifying pairゼロが正常なnegative resultになる。

## 試験コマンド

```bash
python -m pytest CONDUCTOR_modules/tests/test_runtime_015.py -q
python -m pytest CONDUCTOR_modules/tests/test_runtime_014.py -q
python -m pytest CONDUCTOR_modules/tests/test_mmp_014.py -q
python -m pytest CONDUCTOR_modules/tests -q
python CONDUCTOR_modules/tools/verify_package_layout.py
python .claude/skills/cs-conductor-runtime/scripts/launch.py catalog --check
```

2026-08-22のWindows全回帰結果は`92 passed, 9 skipped, 5 subtests passed`です。skipは旧0.1.2／0.1.3専用protocolまたは環境依存試験であり、現行0.1.5のRequest、Round、MMP、Interpretation契約は現役試験で検証します。

Linux受入では、Pixi共有binary、read-only network条件、複数Round再開、Executor中断、6時間実行、CPU上限も確認します。Windows試験は契約・schema・small fixtureを中心とし、HPC性能の代替にはしません。
