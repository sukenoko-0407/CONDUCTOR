# CONDUCTOR 0.2.1 R1.3 本番完走用プロンプト

> **R1.5復旧案内:** P01〜P05が成功し、P06だけが構造数値を含む叙述のcitation validationで
> failedとなった既存Runは、新規Runを開始しない。修正後codeをpullして
> `CONDUCTOR_0.2.1_R1_P06_recovery_prompt.md`を使用する。

> **R1.4復旧案内:** このプロンプトでP01〜P03が成功し、P04 scoringだけが
> `No columns to parse from file`でfailedとなった既存Runは、新規Runを開始しない。
> `CONDUCTOR_0.2.1_R1_P04_P06_recovery_prompt.md`を使い、P04一件だけを監査付きで
> 再キューして同じRunをP04〜P06へ再開する。

> ファイル名には履歴上`stage3_production_checkpoint`を残すが、このプロンプトは旧R1-3
> checkpointの再実行用ではない。既知のL5統計予算不足を解消したR1.3コードで、既存の
> Description Databaseを再利用し、Phase 1〜6を完走させるために使う。

## 1. 事前準備

`CONDUCTOR_modules/schemas/run_spec.existing_database.example.json`を複製し、実機の値へ
置き換えたRun Specを用意する。次を必須とする。

- 全pathは絶対path。
- `mode`は`existing_database`。
- `preflight_receipts`は空配列。
- `run_root`は存在しない新規path。停止した旧Runをresumeしない。
- `program_name`は既存Description Databaseと同じ値。
- `workers`は利用上限。64 coreを割り当てる場合は`64`。
- `memory_mb`はRunへ割り当てる上限。700 GiB中640 GiBを割り当てる場合は`655360`。

resolved configには、少なくとも次が反映されていることを確認する。

```yaml
statistics:
  final_permutations: 1000
lenses:
  l5:
    final_permutations: 5000
    permutation_batch_size: 64
runtime:
  budgets:
    k_min: 10
    family_size: 500
```

L5以外の統計予算を5000へ増やさない。L4のcandidate cap、Runtimeのmemory/time予算、
Lens別`units_per_second`もR1版defaultsを反映した解決済み値を使用する。

## 2. Claude Codeへ渡すプロンプト

次の`<...>`を実値へ置き換え、コードブロック全体をClaude Codeへ渡す。

```text
CONDUCTOR 0.2.1 R1.3の本番完走Runを実行してください。

Project root: <PROJECT_ROOT>
Run Spec: <RUN_SPEC>

このRunの目的はcheckpointや追加調査ではなく、既存Description Databaseを再利用して
canonical Phase 1〜6を完走し、最終成果物と引用を監査することです。

最初にRun Specをread-onlyで読み、次の最小開始条件だけを確認してください。
- schema_version=0.2.1、mode=existing_database、preflight_receipts=[]
- Run Spec内の絶対pathが解決でき、resolved configとprovider configが存在する
- Run Specのproject_root/program_nameから決まる既存Database directoryとdatabase_manifest.jsonが存在する
- 同じProgramのwriter/coordinator/workerが動作していない
- 新規run_rootが存在しない
- workersがCPU affinityの範囲内である
- resolved configでL5だけがfinal_permutations=5000、permutation_batch_size=64である

開始条件を満たしたら、下記のversioned launcherをそのまま使用してください。

python "<PROJECT_ROOT>/.claude/skills/cs-production-run/scripts/launch.py" --run-spec "<RUN_SPEC>"

production compilerがcanonical blueprint、Execution Request、Pipeline plan、DAGを生成し、
cs-runtime single-writer coordinatorへ委譲します。下流Skill契約の再抽出、request templateの
自作、fixture planの探索、ad-hoc plan/launcherの作成、各run.pyのRuntime外実行は行わないでください。

Description Databaseの互換recordはcache hitとして再利用し、真のmissだけを計算・登録してください。
Conformer生成不能としてterminal SKIP登録済みのrecordも互換hitとして扱い、当該Description空間から
除外しつつ他のDescription空間と後続解析を継続してください。旧Runのruntime state、run-scoped artifact、
検定、Findingは流用しないでください。

P03 batch work censusは起動前の安全確認であり、このRunの終了目的ではありません。L5は
matrix_blas_v1とB=5000で最大族2092のrequired B=4183を満たす想定です。旧期待族サイズ
L5=52、L1b=84、L2a=117、L2b=75、L7=86との差は履歴比較用warningとし、差だけを理由に
停止しないでください。

入力/hash/schema/identity不整合、未知の実装エラー、統計予算不足、設定されたmemory/time予算超過、
引用不整合など、実際の安全・正確性blockerが生じた場合だけ停止してください。閾値、permutation数、
candidate cap、guardをRun中に変更して通過させないでください。

完了時に次を報告してください。
- Run ID、HEAD commit、Run状態、Phase別・Node別状態とwall time
- Description別hit/miss/registered OK/terminal SKIP/failed件数
- 全Lensの最大family key・最大族サイズ・configured/required B・Finding件数
- L5のcorrelation_engine、permutation batch size、CPU thread上限、work estimateと実時間
- Phase 4〜6の成果物、P05 LLM logical-call失敗率とtask/error type別内訳、P06 semantic retry・
  fail-closed null件数、引用検証結果
- runtime_summary.json、work_census.json、主要artifact manifest、最終reportの絶対path
```

## 3. 合格条件

- production compilerが既存DBモードを受理し、固定13 NodeのPhase 1〜6 DAGを生成する。
- Description Databaseを再構築せず、互換recordを再利用する。
- L5 censusがconfigured B=5000で統計予算を満たし、workloadが実行される。
- 旧期待族サイズとの差だけでは停止しない。
- Phase 1〜6がterminal successとなり、最終reportと引用監査結果が得られる。

真のblockerで停止した場合は、設定をその場で変更せず、該当Node、guardまたは例外、入力寸法、
work estimate、stderr最終行、生成済みmanifestの絶対pathを報告する。
