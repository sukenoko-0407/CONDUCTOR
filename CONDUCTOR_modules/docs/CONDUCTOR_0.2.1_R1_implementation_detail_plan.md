# CONDUCTOR 0.2.1 R1 実装詳細計画

## 0. 文書状態

- 状態: **実装前レビュー用**
- 対象: `CONDUCTOR_0.2.1_R1_implementer_brief.md` が定義する R1.1
- 作成日: 2026-09-19
- この文書の作成時点では、R1 のコード変更を開始していない。
- 未解決事項は `CONDUCTOR_0.2.1_R1_implementation_questions.md` に分離した。blocking 質問に依存する部分は、回答前に実装へ移さない。

## 1. 正本と優先順位

実装判断には、次の順序を用いる。

1. `CONDUCTOR_0.2.1_R1_implementer_brief.md`
2. `CONDUCTOR_0.2.1_R1_remediation_plan.md`
3. `CONDUCTOR_0.2.1_specification_overview.md` の R1/R1.1 追補
4. `design/discovery_lenses.md`
5. 現行コード、テスト、既存の実装計画・履歴文書

R1.1 は、単なる速度改善ではない。まず統計的 family を意味のある単位へ分割し、次に同じ検定をより少ない計算で実行し、最後に Runtime が実行前に時間・メモリ・多重性を判定できるようにする。

## 2. 変更境界

### 2.1 変更対象

- `.claude/skills/cs-runtime/python/conductor_runtime/dag.py`
- `.claude/skills/cs-runtime/python/conductor_runtime/state.py`
- `.claude/skills/cs-runtime/scripts/run.py`
- `.claude/skills/cs-lens-l1b/python/conductor_lens_l1b/l1b.py`
- `.claude/skills/cs-lens-l1b/scripts/run.py`
- `.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2a.py`
- `.claude/skills/cs-lens-l2/scripts/run.py`
- `.claude/skills/cs-lens-l4/python/conductor_lens_l4/l4.py`
- `.claude/skills/cs-lens-l4/scripts/run.py`
- `.claude/skills/cs-lens-l5/python/conductor_lens_l5/l5.py`
- `.claude/skills/cs-lens-l5/scripts/run.py`
- 各 Lens の `launch.py`（estimate mode の引数透過に必要な最小変更）
- `CONDUCTOR_modules/config/defaults.yaml`
- Runtime/Lens の unit・integration・performance test
- R1 の運用・実装文書

### 2.2 原則として変更しない対象

- stat-core の検定、p 値、BH 実装
- `.claude/skills/cs-lens-l2/python/conductor_lens_l2/l2b.py`
- `.claude/skills/cs-lens-l7/python/conductor_lens_l7/l7.py`
- context builder
- scoring、deep dive、report の意味論
- ProcessPool、shard、resource token、mmap、checkpoint の新設

L2b/L7 へ work estimate と progress をどこまで適用するかは、引き継ぎ書内の「全 Lens」と「l2b.py/L7 を変更しない」の両方を満たす必要があるため、Q-002/Q-003 の回答後に確定する。

## 3. 共通実装契約

### 3.1 WorkEstimate wire contract

stdlib のみへ依存する共通モジュール `CONDUCTOR_modules/tools/work_contract.py` を新設する。Skill の Pixi 環境からも file path で import できるよう、各 `scripts/run.py` が `CONDUCTOR_modules/tools` を明示的に `sys.path` へ加える。推定処理は出力 directory、Database、Runtime state を作成・変更しない。

```python
@dataclass(frozen=True)
class WorkEstimate:
    unit_count: int
    family_size: int
    peak_memory_bytes: int
    detail: dict[str, int]

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkEstimate": ...
```

JSON は次の固定 field だけを stdout へ1行で返す。

```json
{"unit_count":0,"family_size":0,"peak_memory_bytes":0,"detail":{}}
```

各 Lens runner の CLI を次のように拡張する。

```python
# before
execute(args: argparse.Namespace) -> dict[str, str]

# after
estimate(args: argparse.Namespace) -> WorkEstimate
execute(args: argparse.Namespace) -> dict[str, str]
# --estimate-work のとき estimate() だけを呼び、成果物を作らない。
```

Runtime は通常 workload と同じ request/config/input hash、同じ Skill 環境を使って `launch.py ... --estimate-work` を先に一度実行する。成功した estimate は attempt directory の `work_estimate.json`、Runtime event、最終 manifest の `metrics.work_estimate` に残す。

### 3.2 Runtime gate

```python
# new in PipelineCoordinator
_estimate_node_work(node, resolved_request_path, attempt_dir) -> WorkEstimate
_evaluate_work_guard(node, estimate, pending_estimates) -> GuardDecision
_write_guard_manifest(...) -> Path
```

判定順は固定する。

1. `family_size > 500` かつ L4 ではない場合は `needs_design_review`。
2. `peak_memory_bytes > 64 * 1024**3` なら `needs_design_review`。
3. `unit_count / units_per_second > 3600` なら node を `needs_design_review`。
4. 当該 Run の実績時間と未実行 node の推定時間の合計が 21600 秒を超えるなら、次 node を開始せず `needs_design_review`。
5. 閾値変更、candidate 削減、permutation 削減を Runtime が自動実行しない。

guard 停止時は Skill workload を開始せず、coordinator 所有の `artifact_manifest.json` を node output に作り、`status=needs_design_review`、estimate、limit、判定理由を記録する。

### 3.3 Progress/heartbeat contract

stdout/stderr 契約を汚さないため、Runtime が attempt ごとに空の progress path を割り当て、`CONDUCTOR_PROGRESS_PATH` として child process へ渡す。Lens は同一 filesystem 上で一時ファイルから atomic replace し、次の JSON object を書く。

```json
{"completed_units":12,"total_units":100,"elapsed_seconds":3.4}
```

更新は「直近更新から5秒以上」または「総量の1%以上進んだ」の**遅い方**、すなわち両条件を満たした時だけ行う。Runtime は `subprocess.Popen` で process を監視し、stdout/stderr は別 thread で drain して deadlock を防ぐ。

heartbeat がない時間の閾値は `clamp(20 * observed_interval, 60, 600)` 秒とする。超過時は node state を変更・kill せず、`heartbeat` event の payload に `stalled=true` を記録する。進捗再開時は `stalled=false` を記録する。

現行 `_event()` の ID は同一 type の反復 event を一意化できないため、次へ変更する。

```python
# before
_event(node_id, attempt_id, event_type, payload) -> dict

# after
_event(node_id, attempt_id, event_type, payload, *, sequence: int = 0) -> dict
```

`RuntimeStateStore.apply_event()` は heartbeat を state transition なしで保存する。`runtime_summary.json` は node ごとに最新 progress と stalled flag を表示する。

### 3.4 family key の正規形

family key は tuple を canonical JSON array として artifact に記録し、内部 BH grouping も同じ構成要素を使う。

- L5: `(lens_id, axis_id, question)`
- L1b: `(lens_id, space_id, question)`
- L2a: `(lens_id, transformation_class, transformation_id, question)`
- L2b: 現行のまま
- L7: 現行のまま

M-3/M-4/M-10b/M-11b を一つの統計契約変更として同一 stage で適用する。この stage より前の Run は resume せず、新しい Run ID/root で再実行する。

## 4. Lens 別 work estimate 式

全式で `B` は final permutation 数（既定1000）、実計算には観測統計1回を含むため `B1 = B + 1` とする。`family_size` は設定値からの粗い上限ではなく、入力を read-only で走査して実際の eligibility predicate と family key を適用した最大 family 件数とする。

### 4.1 L5

記号:

- `N`: finite endpoint compound 数
- `C`: M-3 後に成立する context-vs-axis-complement 比較数
- `F`: M-6 後の代表 feature 数（M-6 前は全 feature 数）
- `K`: Murcko block 数
- `H5`: 同一 `(L5, axis, question)` に属する candidate test の最大数

式:

```text
unit_count = B1 * C * F
family_size = H5
peak_memory_bytes = 8 * (4*N*F + C*N + 8*C*F + 2*F + 2*K)
```

`detail` は `compound_count, comparison_count, feature_count, block_count, permutations` を持つ。null distribution 全体を保持せず exceedance counter を更新する設計を前提とする。Python object/ID table 用の安全係数は上式へ 1.25 を掛け、ceil した値を最終 `peak_memory_bytes` とする。

### 4.2 L1b

記号:

- `N`: finite endpoint compound 数
- `S`: eligible space 数
- `T`: 全 space・context の eligible member 数合計
- `K`: neighbor_k
- `H1`: 同一 `(L1b, space, question)` の candidate test 最大数

式:

```text
unit_count = B1 * S * T
family_size = H1
peak_memory_bytes = 8 * (S*N*N + S*T*K + 4*S*T + 2*N)
```

float32 distance artifact も guard では float64 相当で保守的に数える。M-10a 後は space ごとの stable neighbor table を一度だけ作る。M-6 を L1b へ適用する具体的意味は Q-004 の回答で確定する。

### 4.3 L2a

記号:

- `N`: finite endpoint compound 数
- `P`: eligibility 後の pair 数
- `G`: `series_members` の全 member 数合計
- `Q`: test record 数
- `H2`: 同一 `(L2a, class, transformation, question)` の test 最大数

式:

```text
unit_count = B1 * P
family_size = H2
peak_memory_bytes = 8 * (N + 6*P + G + 3*Q)
```

`detail` は `pair_count, transformation_count, class_count, series_member_count, test_count, permutations` を持つ。

### 4.4 L4

記号:

- `C4`: 選択 candidate 数
- `S4`: D019 を除く eligible space 数
- `N`: endpoint observation 数
- `Fmax`: 1 space 当たり最大 feature 数
- `W`: candidate description cost unit 合計

M-12 前の現行アルゴリズムを guard する式:

```text
unit_count = C4 * S4
family_size = C4  # L4 は family_size gate の例外
peak_memory_bytes = 8 * (C4*N*Fmax + C4*Fmax + N*Fmax)
```

M-12a 後の式:

```text
unit_count = C4 * S4
family_size = C4
peak_memory_bytes = 8 * (C4*N + C4*Fmax + N*Fmax + 4*C4)
```

`detail` は `candidate_count, space_count, observation_count, max_feature_count, description_cost_units` を持つ。`C4*S4` と description cost `W` を一つの node wall-time estimate へ結合する方法は Q-006 の回答で確定する。

### 4.5 L2b/L7

family size と peak memory は read-only prepass で記録可能である。一方、R1.1 が採用する `units_per_second` が定義されていないため、3600秒 gate の式は Q-002 の回答待ちとする。未回答のまま未知の速度を仮定して合格させない。

## 5. M-1〜M-16 実装項目

### M-1 WorkEstimate

- 対象: 共通 `work_contract.py`、4 Lens の core/runner、Runtime `PipelineCoordinator.execute_node()`。
- before: Runtime は node 起動前に input-dependent workload を知らず、`subprocess.run()` で直ちに workload を開始する。
- after: 各 Lens の `estimate(args) -> WorkEstimate` を副作用なしで実行し、Runtime gate 合格後だけ workload を起動する。
- 新規状態: attempt 単位の estimate、guard decision、estimated seconds。
- artifact: `attempts/<id>/work_estimate.json`、event payload、manifest metrics。
- estimate 式: 4章の式を使用する。
- test:
  - dataclass JSON round-trip、負値/未知 field 拒否。
  - estimate mode が output directory、DB、Runtime state を作らない。
  - threshold の境界値 `==` は合格、`>` は停止。
  - Skill subprocess が呼ばれないことを mock で確認。
- validation: fixture の estimate と actual unit の一致、estimate/actual ratio を収集。

### M-2 Progress/heartbeat/stalled

- 対象: Runtime `dag.py/state.py`、対象 Lens の長時間 loop と runner。
- before: `subprocess.run()` 終了時まで Runtime から内部進捗を観測できない。
- after: `Popen`、atomic progress file、反復 heartbeat event、stalled warning を使用する。
- core signature:

```python
# before
run_l5(..., config: Mapping[str, Any]) -> L5Result

# after
run_l5(..., config: Mapping[str, Any], progress: ProgressCallback | None = None) -> L5Result
```

  同じ keyword-only callback を L1b/L2a/L4 へ追加する。
- artifact/state: latest progress、heartbeat interval、stalled warning。node state は `running` のまま。
- test: 5秒/1% throttling、60/600秒 clamp、反復 event ID、停滞後復帰、stdout/stderr 大量出力時の deadlock 回避。
- validation: 既知時間の slow fixture で Runtime summary が単調増加し、stall が process kill を起こさない。

### M-3 L5 context-vs-complement

- 対象: `conductor_lens_l5.l5.run_l5()`。
- before: context pair を総当たりで比較する。
- after: 各 focal context を同じ axis の union から focal context を除いた complement と比較する。
- 新規データ: axis ごとの boolean membership matrix、`condition_id="<context_id>|complement"`。
- evidence: entity は focal context のみ。complement を別の context entity として捏造しない。
- estimate: 4.1 の `C` を使用。
- test: 3 context の axis fixture で比較数が3、complement membership が厳密、他 axis compound を含まない、空/不足 complement を skip。
- validation: planted sign conflict の direction/p 値を手計算 fixture と照合。

### M-4 L5 family

- 対象: `run_l5()` の candidate record と BH grouping。
- before: L5 全 candidate を単一または過大な family として補正する。
- after: `(L5, axis_id, correlation_sign_conflict)` ごとに BH 補正する。
- artifact: finding/evidence の `family_key`、calibration summary の family count。
- estimate: `family_size=max_axis_candidate_count`。
- test: 2 axis fixture で一方の candidate 数が他方の q 値へ影響しない。
- validation: current 556,189 candidate caseを axis 52 程度へ縮小できるか scale fixture で検証。

### M-5 L5 vectorization

- 対象: `_feature_matrix()`, `_correlation()`, `run_l5()`。
- before: context・feature・permutation の Python loop 内で相関を反復計算する。
- after: feature matrix と membership matrix を一度構築し、中心化、分子、分母を BLAS/GEMM で一括計算する。permutation ごとは endpoint vector の置換と行列積だけを行う。
- global correlation `global_r` は観測データで一度計算し calibration/final で再利用する。
- state: exceedance counter、valid-count counter。null matrix は保持しない。
- estimate: 4.1。BLAS thread は `CONDUCTOR_AVAILABLE_CPU_CORES` 以下。
- test: scalar reference と statistic の relative difference `<=1e-9`、p 値/Finding 集合は exact 一致、worker 1/2/64 一致。
- validation: representative production slice で wall/CPU/RSS を測る。

### M-6 Correlation deduplication

- 対象: L5 と L1b。共通 helper と mapping artifact を追加する。
- before: Tier1/2 の高相関 feature をすべて計算対象にする。
- after: pairwise finite Pearson の `abs(r)>=0.95` を edge とする connected component を作り、`tier` 昇順、次に feature ID lexical の代表だけを計算する。
- artifact: `feature_representative_map.jsonl`。各 row に `excluded_feature_id, representative_feature_id, component_id, abs_correlation, rule_version`。
- estimate: L5 の `F` は代表数。L1b の扱いは Q-004 回答に従う。
- test: chain A-B/B-C で A-C が閾値未満でも1 component、tie-break、NaN pair、入力列順非依存。
- validation: representative 数、family size、Finding の科学的差分を明示し、単なる性能同値とは扱わない。

### M-7 Calibration signature

- 対象: L1b/L2b/L5 calibration artifact、runner manifest、Runtime warning。
- before: calibration artifact が descriptor/space/k/B/alpha の完全な意味署名を持たない。
- after: canonical JSON と SHA-256 で次を署名する。
  - descriptor set
  - space list
  - Tier1/2 feature count
  - k grid
  - minimum context size
  - B
  - alpha
- artifact: `calibration_signature` object と `calibration_signature_sha256`。
- mismatch: warning only。threshold を自動変更しない。
- test: field/順序変更、同値 canonical JSON、warning-only。
- validation: reference の置き場所と比較主体は Q-005 回答後に固定。

### M-8 Calibration regeneration

- 対象: 運用 stage。コードの閾値自動更新は行わない。
- before: R1 前 family/feature set の calibration が残る。
- after: M-3〜M-7 適用後、正式較正データで calibration を再生成し、旧版と別 path/hash で保存する。
- artifact: new calibration JSON、signature、比較 report。
- test: calibration command の deterministic rerun。
- validation: 人間が enrichment/Finding 数/偽陽性挙動をレビューして採否を決定。

### M-9 Worker acceptance

- 対象: performance test と受入 report。
- before: worker 数を指定できても、計算 kernel がそれを利用した証拠が不足する。
- after: worker 1/2/64 で同一 input/seed を走らせ、Finding、p/q、artifact hash（時刻等を除く）を比較する。
- metrics: wall time、process CPU time、`CPU time / wall time`、peak RSS、busy core 相当値。
- 合格: Finding exact、数値契約を満たし、parallel section の `CPU time / wall time >= workers*0.5`。speedup 倍率自体は保証しない。
- test/validation: 専有 Ubuntu 64-core/755 GiB 機で実測し、Windows 開発機の値を受入値にしない。

### M-10a L1b stable neighbor table

- 対象: `local_flatness()`, `run_l1b()`。
- before: context/permutation の内側で距離順序と近傍抽出を反復する。
- after: space ごとに stable exact sort した full neighbor table を一度作り、context member index を連結して利用する。距離 tie は compound ID lexical で決定する。
- signature:

```python
# before
local_flatness(distance, endpoint, indices, *, neighbor_k, global_variance)

# after
build_neighbor_table(distance, compound_ids, *, neighbor_k) -> NeighborTable
local_flatness_from_neighbors(neighbors, endpoint, indices, *, global_variance)
```

- state: `neighbor_indices`, `neighbor_distances`, context member offsets。
- estimate: 4.2。
- test: old exact sort reference と lambda relative difference `<=1e-9`、p/Finding exact、distance tie の再現性。

### M-10b L1b family

- 対象: `run_l1b()` BH grouping。
- before: space をまたぐ family。
- after: `(L1b, space_id, question)`。
- artifact: family key と per-space family count。
- test: 2 space fixture で q 値が互いに干渉しない。
- validation: current family 763 に対し、space 最大が約84かを実測。

### M-11a L2a integer-array engine

- 対象: `_endpoint_map()`, `_pair_deltas()`, `run_l2a()`。
- before: dict lookup/Pandas filter を permutation 内で反復する。
- after: compound ID を integer index へ一度写像し、`from_idx`, `to_idx`, flat `series_members`, offsets を作る。delta は `endpoint[to_idx]-endpoint[from_idx]` で一括算出する。
- signature:

```python
# before
_pair_deltas(pairs, values: dict[str, float], *, run_seed=None, iteration=None)

# after
prepare_l2a_arrays(pairs, compounds, series) -> L2AArrays
pair_deltas(arrays, endpoint_vector, permutation_indices=None) -> np.ndarray
```

- state: integer arrays、group offsets。candidate 0件なら permutation engine を起動せず空成果物を返す。
- estimate: 4.3。
- test: old reference exact delta、permutation seed、missing ID、empty candidates、入力行順非依存。

### M-11b L2a family

- 対象: L2a BH grouping。
- before: transformation をまたぐ広い family。
- after: `(L2a, transformation_class, transformation_id, question)`。
- artifact: family key。
- test: 同一 class の2 transformation が独立補正される。
- validation: current family 647 に対し最大約117かを実測。

### M-12a L4 distance kernel

- 対象: `candidate_distance_matrix()`, `score_l4_candidates()`。
- before: candidate-observation-feature の3次 broadcast を materialize する。
- after: squared Euclidean を `||x||^2 + ||y||^2 - 2XY^T` で計算し、rounding による負値を `maximum(value, 0)` で補正後 sqrt する。space は逐次処理し、全 space の巨大 distance matrix を同時保持しない。
- estimate: 4.4 の M-12 後式。
- test: broadcast reference と relative difference `<=1e-9`、zero/near-zero、chunk 境界、OOM guard。
- validation: M-12 未適用で candidate 10,000 fixture が 64 GiB guard により workload 前停止し、適用後は estimate が閾値内になること。

### M-12b L4 vectorized scoring

- 対象: `score_l4_candidates()`。
- before: candidate ごとに eligible filter、full sort、SciPy t-test を反復する。
- after:
  - eligible mask と lexical rank を loop 外で作る。
  - `argpartition` で K 近傍を bulk 選択する。
  - 境界 tie だけ distance、compound lexical rank で deterministic に解決する。
  - `t.ppf` は設定ごとに一度だけ計算する。
  - t statistic/p 値は mean/std/n から vectorized に算出する。
- state: neighbor index matrix、summary arrays。2M row guard は出力前に評価。
- test: scalar reference relative difference `<=1e-9`、p/Finding exact、tie、多数 candidate、K未満。
- validation: peak RSS、wall time、row count。

### M-13 D019 exclusion

- 対象: L4 runner の space 選択、evidence 出力。
- before: very_high-cost D019 を candidate re-description/score space に含め得る。
- after: D019 を L4 から除外し、使用した space ID を `space_ids_json` に保存する。
- estimate: `S4` と description cost は D019 除外後。candidate 当たり cost 上限は35。
- test: D019-only/混在 fixture、evidence の space list、cost calculation。
- validation: 既存 descriptor DB や他 Lens から D019 を削除しないこと。

### M-14 Runtime budgets/defaults

- 対象: `defaults.yaml`、Runtime guard。
- defaults:

```yaml
runtime:
  budgets:
    node_wall_seconds: 3600
    run_wall_seconds: 21600
    peak_memory_bytes: 68719476736
    family_size: 500
  progress:
    min_seconds: 5
    min_fraction: 0.01
    stall_multiplier: 20
    stall_min_seconds: 60
    stall_max_seconds: 600
  units_per_second:
    l5: 3650000
    l1b: 29800000
    l2a: 7230000
    l4: 31700
```

- L4 は family size gate 例外。`estimate/actual >=3` は warning。
- candidate cap は Q-001 の回答まで現行100を維持する。
- test: config validation、各 budget、run cumulative budget、3x warning。
- validation: production fixture の estimate が監査 report の測定値と整合。

### M-15 L4 cap 250,000（任意）

- 対象: `defaults.yaml` の L4 cap、scale guard test。
- 見解: **条件付き採用候補**。M-12/M-13、64 GiB preflight、2M row guard、1時間 node budgetを全て合格した後に限り、探索の豊富さを回復する選択肢として採用する価値がある。ただし R1 の必須修正と結合せず、別 commit/stage とする。
- before/after: `100 -> 250000` は Q-001 の明示回答後だけ行う。
- test: 249,999/250,000/250,001 境界、estimate stop、row guard。
- validation: 10k、50k、250k の段階測定。250k を直接本番投入しない。

### M-16 Peak-memory preflight

- 対象: M-1 estimator と Runtime guard。
- 必須計上:
  - L4: `candidate*N*8` distance、`candidate*max_features*8` candidate matrix。
  - L5: `context*feature*8*matrix_count`。
  - L1b: `(space*context*members)*k*8` neighbor index/value。
- 実装では4章の全 live array を加算し、Python/object overhead の安全係数1.25を最後に適用する。
- test: integer overflow を避ける Python int、大規模 synthetic metadata、閾値直上/直下。
- validation: actual peak RSS / estimate を記録し、過小評価があれば式を保守側へ改訂する。Runtime が閾値を自動緩和しない。

## 6. 実装 stage と停止点

1. R1-1: M-1/M-14/M-16。WorkEstimate と pre-launch guard。
2. R1-2: M-2。progress/heartbeat/stalled。
3. R1-3: M-3/M-4/M-10b/M-11b。統計 family 修正。
4. **ここで停止して中間報告する。** full production Run はまだ実施しない。
5. R1-4: M-6。
6. R1-5: M-5/M-10a/M-11a/M-12。
7. R1-6: M-13。
8. R1-7: M-7。
9. R1-8: M-8。
10. R1-9: M-9。
11. R1-10: M-15 を採用する場合だけ実施。

各 stage は、対象 unit test、契約 test、限定 integration fixture が全て成功してから次へ進む。統計契約を変える R1-3 と R1-4 の前後では、旧 Run の resume を禁止する。

## 7. テスト計画

### 7.1 既存テストの期待値変更

- `CONDUCTOR_modules/tests/unit/test_stage7_lenses.py::test_l5_detects_planted_same_axis_sign_reversal`
  - context pair 1件という前提を、各 focal context 対 axis complement へ変更する。
  - `condition_id`、entity、candidate/Finding 数、q 値の期待値を更新する。
- `CONDUCTOR_modules/tests/unit/test_stage7_lenses.py::test_l2a_excludes_pairs_outside_finite_endpoint_universe`
  - 現 fixture が単一 transformation なら数値期待値は不変だが、生成される `family_key` の契約は変更される。2 transformation fixture を追加する。
- `CONDUCTOR_modules/tests/integration/test_phase1_to_phase6_e2e.py::test_phase1_through_phase6_small_fixture`
  - 単一 space では q 値が偶然不変になり得るが、L1b/L2a/L5 の family key と evidence shape を新契約へ更新する。

現行テストには L1b の複数 space family 分離を直接検証するものがないため、新規 test が必要である。L2b/L7 の既存期待値は変更しない。

### 7.2 新規テストファイル

- `tests/unit/test_r1_work_contract.py`
- `tests/unit/test_r1_runtime_guard.py`
- `tests/unit/test_r1_progress.py`
- `tests/unit/test_r1_l5_context_complement.py`
- `tests/unit/test_r1_family_partitioning.py`
- `tests/unit/test_r1_feature_dedup.py`
- `tests/unit/test_r1_l1b_neighbors.py`
- `tests/unit/test_r1_l2a_arrays.py`
- `tests/unit/test_r1_l4_vectorization.py`
- `tests/integration/test_r1_runtime_preflight.py`
- `tests/performance/test_r1_worker_acceptance.py`（通常の unit suite からは除外）

### 7.3 数値・決定性の合格条件

- M-5/M-10a/M-12: reference との relative difference `<=1e-9`。
- p 値と Finding 集合: brief が exact を要求する項目は exact 一致。
- worker 1/2/64: Finding exact 一致。
- stable sort/argpartition tie: 入力行順、hash seed、worker 数に依存しない。
- fixed `run_seed` と同じ input/config/code hash で rerun 可能。

## 8. Artifact・状態・互換性

新規または変更する監査情報:

- `work_estimate.json`
- progress/heartbeat Runtime event
- runtime summary の latest progress/stalled/guard decision
- manifest metrics の estimate、actual、ratio warning
- family key
- `feature_representative_map.jsonl`
- calibration signature/hash
- L4 `space_ids_json`

schema version は 0.2.1 のままとし、artifact schema が任意 metrics を許す範囲で追加する。schema に列挙が必要なら schema と example を同じ stage で更新する。既存 Run state を in-place migration しない。

## 9. 実装工数見積り

単位は person-day。レビュー・限定 fixture を含むが、長時間の正式 production/calibration Run 待ち時間は含まない。

|項目|見積り|備考|
|---|---:|---|
|M-1|4–6|4 Lens estimator、wire contract、Runtime gate|
|M-2|3–4|Popen、drain、progress、state/summary|
|M-3|1–1.5|L5 comparison 再定義|
|M-4|0.5–1|L5 family と回帰 test|
|M-5|4–6|GEMM/permutation engine、数値同値|
|M-6|3–5|L1b 解釈確定後。科学的差分検証を含む|
|M-7|2–3|signature、参照比較、warning|
|M-8|1–2|運用準備・比較 report。計算待ちは除外|
|M-9|3–5|専有機での1/2/64測定と解析|
|M-10a|3–4|neighbor table、tie、同値検証|
|M-10b|0.5–1|family 分割|
|M-11a|2–3|integer array/permutation engine|
|M-11b|0.5–1|family 分割|
|M-12a/b|4–6|distance/scoring vectorization|
|M-13|1–2|space選択、cost/evidence|
|M-14|1–2|M-1 と重複する config/guard部分|
|M-15|0.5–1|採用時のみ。段階測定は別|
|M-16|1–2|M-1/M-12 と重複する memory model|

重複作業を統合した全体見積りは **29–44 person-day**。blocking 質問の回答によって、特に M-1/M-2/M-6/M-7/M-15 は変動する。

## 10. 初回レビューの出口条件

次を満たすまでコード実装へ進まない。

- blocking 質問への回答が得られている。
- WorkEstimate の全 Lens 適用範囲と L4 複合コスト式が確定している。
- L1b に対する M-6 の科学的意味が確定している。
- M-15 の cap default が確定している。
- stage R1-3 後に一旦停止することが合意されている。

