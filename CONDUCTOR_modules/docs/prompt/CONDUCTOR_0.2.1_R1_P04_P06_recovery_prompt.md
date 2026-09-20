# CONDUCTOR 0.2.1 R1.4 P04〜P06限定復旧プロンプト

このプロンプトは、P01〜P03が成功済みで、P04 scoringだけが
`EmptyDataError: No columns to parse from file`によりfailedとなった既存Run専用である。
新規Runの開始、Description Databaseの再構築、P01〜P03の再実行には使用しない。

## 1. 置換項目

- `<PROJECT_ROOT>`: 修正後commitをpullしたCONDUCTOR project rootの絶対path
- `<RUN_ROOT>`: P04で停止した既存Run rootの絶対path
- `<OPERATOR_NAME>`: administrative auditへ記録する操作者名

## 2. Claude Codeへ渡すプロンプト

```text
CONDUCTOR 0.2.1 R1.4のzero-row artifact修正後復旧として、既存RunのP04だけを
監査付きで再キューし、同じRunをP04〜P06まで再開してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>
operator: <OPERATOR_NAME>

この依頼は既存Runの限定復旧です。新しいRunを作らず、Description Database、成功済みNode、
frozen config、Pipeline plan、Execution Request、入力、P01〜P03成果物を変更しないでください。

最初にread-onlyで次を確認してください。
- 同じRunのcoordinator/worker processが動作していない
- `<RUN_ROOT>/runtime.sqlite`、`control/coordinator_request.json`、`control/pipeline_plan.json`が存在する
- P01〜P03の全Nodeがsucceededで、manifestとartifact hashが存在する
- skill_nameが`cs-scoring`であるNodeがちょうど1件failedで、stderrに
  `No columns to parse from file`が記録されている
- P05/P06が未実行であり、他にfailedまたはneeds_design_reviewのNodeがない
- HEADにR1.4のzero-row修正が含まれ、限定fixtureが合格する

P04 Node IDは推測せず、runtime.sqliteからskill_name=`cs-scoring`かつstate=`failed`のexact値を取得してください。
次の管理commandをまず`--apply`なしで実行し、eligible=true、state=failed、skill_name=cs-scoringを確認してください。

python "<PROJECT_ROOT>/CONDUCTOR_modules/tools/requeue_runtime_node.py" \
  --runtime-sqlite "<RUN_ROOT>/runtime.sqlite" \
  --node-id "<実測したP04_NODE_ID>" \
  --expected-skill-name "cs-scoring" \
  --operator "<OPERATOR_NAME>" \
  --reason "R1.4 zero-row score_observations compatibility fix"

条件が全て一致する場合だけ、同じcommandへ`--apply`を追加してP04一件だけをretryableへ戻してください。
administrative_requeue event、旧attempt ID、対象Node IDを記録してください。

その後、production compilerを再実行せず、frozen coordinator requestを使って同じRunを再開してください。

python "<PROJECT_ROOT>/.claude/skills/cs-runtime/scripts/launch.py" \
  --request "<RUN_ROOT>/control/coordinator_request.json" \
  --output-dir "<RUN_ROOT>"

P01〜P03は再実行せず、P04の新attempt、P05、P06だけを進めてください。L4 Finding 0件は
正常な0件として扱い、他LensのFindingを含めてscoringしてください。閾値、permutation数、guard、
frozen configを変更しないでください。P04以外のNodeを手動でrequeueしないでください。

完了時に次を報告してください。
- Run ID、HEAD commit、最終Run状態
- administrative_requeue event、P04の旧/new attempt IDと状態
- P01〜P03が再実行されていないこと
- Lens別Finding入力件数、P04 candidate/gate-pass/reportable件数
- P05 logical call/failed call/failure fraction
- P06 report、citation validation、主要manifestの絶対path
- P03各Lens manifestのunit_count、estimated_seconds、actual_wall_seconds、
  estimate_actual_ratio、observed_units_per_second（存在する値だけ。推測しない）

新しいblockerが出た場合は追加変更せず、Node、attempt、例外、stderr最終行、関連manifest、
再現条件を報告して停止してください。
```

## 3. 合格条件

- P04だけに`administrative_requeue`が1件記録される。
- P01〜P03のattempt IDとartifact hashが変化しない。
- L4の1 byte CSVで`EmptyDataError`が再発しない。
- P04、P05、P06が順に実行され、Runがterminal successへ到達する。
- reportとcitation validation結果を監査できる。
