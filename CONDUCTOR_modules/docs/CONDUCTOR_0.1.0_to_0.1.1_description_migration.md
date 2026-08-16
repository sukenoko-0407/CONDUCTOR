# Description限定Migrationガイド

## 目的

CONDUCTOR 0.1.0 Runで成功済みのDescription artifactだけを、新規0.1.1 Runへ引き継ぎます。Description CSVはbyte単位で同一に保ち、0.1.1用manifest、execution event、Stateを新しく構築します。

Clustering、Analysis、Interpretation、Cluster、Insight、Next Actionは一切引き継ぎません。移行元Runはread-onlyで、移行先directoryは事前に存在していてはいけません。

## 移行後の意味

- `RND0001`のみが存在し、`closed`です。
- RND0001は「基本計算中にVersion移行のため終了したRound」です。
- 成功済みDescription NodeだけがRND0001に存在します。
- `active_round_id=null`、`next_round_number=2`です。
- RND0002の作成、Orchestrator起動、Clustering実行はMigrationに含みません。

人間が後からRND0002を明示的に開始し、通常の基本計算planを実行します。Runtimeは同じsignatureのDescriptionを再利用し、構造Clusteringと新仕様のVector Clustering以降を追加します。

## 推奨手順

Claude Codeでは`cs-conductor-description-migrator` Agentへ移行元・移行先を指定します。Agentは決定論的Patchを`scan`、`apply`、`verify`の順で実行します。

```bash
python CONDUCTOR_modules/tools/migrate_description_010_to_011.py scan \
  --source-run-root /path/to/0.1.0/run

python CONDUCTOR_modules/tools/migrate_description_010_to_011.py apply \
  --source-run-root /path/to/0.1.0/run \
  --target-run-root /path/to/new/0.1.1/run

python CONDUCTOR_modules/tools/migrate_description_010_to_011.py verify \
  --source-run-root /path/to/0.1.0/run \
  --target-run-root /path/to/new/0.1.1/run
```

入力CSVの保存場所だけが変わった場合は、内容が同一であることをSHA-256で検証するため、各commandへ`--input /new/path/input.csv`を追加できます。

## RND0002の開始

Migration verificationがすべてPASSした後、次を別途依頼します。

```text
cs-conductor-orchestrator Agentを使い、移行済みRunのRND0002を開始してください。
state.json: <target_run_root>/state.json
parallel_limit: <number>
Wall Time: <minutes or hours>

RND0001で引き継いだ成功済みDescriptionを再計算せず再利用し、未完了の基本計算から通常のCONDUCTOR解析を継続してください。最後にInterpretationとFull Auditまで完遂してください。
```

RND0001にOperator resultがないため、Migration自体はInterpretationを生成しません。RND0002では通常どおり、解析後のInterpretationがRound終了条件です。
