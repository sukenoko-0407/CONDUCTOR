# CONDUCTOR 0.2.1 R1.5 P06限定復旧プロンプト

このプロンプトは、P01〜P05が成功済みで、P06 reportだけがLLM叙述中のevidence外数値に対する
citation validationでfailedとなった既存Run専用である。新規Run、P01〜P05の再実行、
Description Databaseの変更には使用しない。

## 1. 置換項目

- `<PROJECT_ROOT>`: R1.5修正後commitをpullしたCONDUCTOR project rootの絶対path
- `<RUN_ROOT>`: P06で停止した既存Run rootの絶対path
- `<OPERATOR_NAME>`: administrative auditに残す操作者識別子（個人名、社内ID等の一貫した値）

## 2. Claude Codeへ渡すプロンプト

```text
CONDUCTOR 0.2.1 R1.5のnarrative semantic validation修正後復旧として、既存RunのP06だけを
監査付きで再キューし、同じRunを最後まで再開してください。

Project root: <PROJECT_ROOT>
Run root: <RUN_ROOT>
operator: <OPERATOR_NAME>

この依頼は既存Runの限定復旧です。新しいRunを作らず、Description Database、成功済みNode、
frozen config、Pipeline plan、Execution Request、入力、P01〜P05成果物を変更しないでください。

最初にread-onlyで次を確認してください。
- 同じRunのcoordinator/worker processが動作していない
- `<RUN_ROOT>/runtime.sqlite`と`control/coordinator_request.json`が存在する
- P01〜P05がすべてsucceededで、attempt ID、manifest、artifact hashを取得できる
- skill_name=`cs-report`のP06がちょうど1件failedで、citation validation failureが記録されている
- 他にfailedまたはneeds_design_reviewのNodeがない
- HEADにR1.5のcomponent response validation、semantic retry、fail-closed null修正が含まれる

P06 Node IDは推測せず、runtime.sqliteからskill_name=`cs-report`かつstate=`failed`のexact値を取得してください。
次の管理commandをまず`--apply`なしで実行し、eligible=true、state=failed、skill_name=cs-reportを確認してください。

python "<PROJECT_ROOT>/CONDUCTOR_modules/tools/requeue_runtime_node.py" \
  --runtime-sqlite "<RUN_ROOT>/runtime.sqlite" \
  --node-id "<実測したP06_NODE_ID>" \
  --expected-skill-name "cs-report" \
  --operator "<OPERATOR_NAME>" \
  --reason "R1.5 P06 narrative semantic validation and fail-closed component recovery"

条件が全て一致する場合だけ、同じcommandへ`--apply`を追加してP06一件だけをretryableへ戻してください。
administrative_requeue event、旧attempt ID、対象Node IDを記録してください。

その後、production compilerを再実行せず、frozen coordinator requestで同じRunを再開してください。

python "<PROJECT_ROOT>/.claude/skills/cs-runtime/scripts/launch.py" \
  --request "<RUN_ROOT>/control/coordinator_request.json" \
  --output-dir "<RUN_ROOT>"

P01〜P05を再実行しないでください。P05の旧213失敗callの内訳は旧artifactに存在しないため、
内訳取得だけを目的にP05をrequeueしないでください。P05の既知値3470 logical calls、213 failures、
failure fraction 0.0614は最終報告へ品質情報として明記してください。

P06は各component応答を受理前に検証し、evidence外数値または`1連結成分`等の構造数値があれば
feedback付きで再生成してください。再生成後も不適合な成分はnarrative=null、citations=[]へ
fail-closed変換し、logical-call failureとして設定済み上限へ算入してください。引用検証器、
failure fraction上限、frozen configを変更しないでください。決定論的なFinding/evidence/hash/test
不整合をnull化して通過させないでください。

完了時に次を報告してください。
- Run ID、HEAD commit、最終Run状態
- administrative_requeue event、P06の旧/new attempt IDと状態
- P01〜P05のattempt IDとartifact hashが変化していないこと
- P06 component数、logical calls、provider attempts、semantic retry数、最終failed logical callsとfailure fraction
- nullへfail-closed変換したcomponent IDと件数
- `llm_narrative_failures.jsonl`、`citation_validation.json`、artifact manifest、reportの絶対path
- citation validationの最終statusとerrors
- Work estimate rateは変更していないこと

新しいblockerが出た場合は閾値やartifactを変更せず、Node、attempt、例外、stderr最終行、
関連manifest、再現条件を報告して停止してください。
```

## 3. 合格条件

- P06だけに`administrative_requeue`が1件記録される。
- P01〜P05のattempt IDとartifact hashが変化しない。
- evidence外の構造数値を持つ叙述が無検証でreportへ採用されない。
- semantic retryまたは成分単位のfail-closed nullにより、設定済みfailure fraction上限内でP06が成功する。
- strict citation validationが成功し、Runがterminal successになる。
- P05の6.14% failureを最終報告で明記し、旧P05を再実行しない。
