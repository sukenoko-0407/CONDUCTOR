# CONDUCTOR 0.2.1 実装詳細仕様書

Status: **設計回答反映済み。段階11の初回実装まで進行済み。正式較正・全体適合性確認待ち。**

作成日: 2026-09-17  
正本: [`CONDUCTOR_0.2.1_implementation_plan.md`](CONDUCTOR_0.2.1_implementation_plan.md)

## 0. この文書の扱い

本書は実装計画書を、ファイル配置、公開インターフェース、Artifact、型、擬似コード、失敗時挙動、並列化、テストへ落としたレビュー案である。

優先順位は次のとおりとする。

1. 実装計画書
2. `design/calibration_results.md`
3. 本書（2026-09-17 設計回答反映版）
4. その他の design 文書
5. 診断モジュール（較正値の再現と既知バグの参照実装）

[`CONDUCTOR_0.2.1_implementation_questions.md`](CONDUCTOR_0.2.1_implementation_questions.md) の18件は、2026-09-17 の設計回答を本書へ反映済みである。旧 `blocking` 14件を含め、確認事項由来の未確定placeholderはすべて解消した。実装計画書9章の既出5件は同書の指定時期に確認し、本書では既定案を保持する。

### 0.1 実装範囲

- 単一 Endpoint の L1b / L2a / L2b / L4 / L5 / L7
- L1a / L3 / L6 は診断値のみ。Finding を生成しない
- 複数 Endpoint レジストリと MPO 拡張用 schema。M1〜M3 の解析は実装しない
- Web UI、Web API、常駐 server、外部 API、3D binding-site、0.1.x Run 移行は実装しない
- 分子標準化は行わない。同一 compound ID・異構造は fail-fast

## 1. モジュールとファイル配置

### 1.1 リポジトリ配置

```text
.claude/skills/
├── cs-compute-description-*/       # 全18件: D001〜D016, D019, D020。D017/D018は予約
├── cs-fragment-engine/
├── cs-context-builder/
├── cs-stat-core/
│   ├── python/conductor_stat_core/ # lens Skill が local path dependency として使用
│   └── scripts/
├── cs-lens-l2/
├── cs-lens-l5/
├── cs-lens-l1b/
├── cs-lens-l4/
├── cs-lens-l7/
├── cs-scoring/
├── cs-deepdive/
│   └── resources/hammett_constants.tsv
├── cs-report/
└── cs-runtime/

CONDUCTOR_modules/
├── catalog/
│   ├── catalog.json
│   └── included_skills.json
├── config/
│   └── defaults.yaml
├── diagnosis/                       # 変更しない
├── schemas/
│   ├── artifact_manifest.schema.json
│   ├── context.schema.json
│   ├── deep_dive_node.schema.json
│   ├── endpoint_registry.schema.json
│   ├── execution_event.schema.json
│   ├── execution_request.schema.json
│   ├── finding.schema.json
│   ├── llm_request.schema.json
│   ├── llm_response.schema.json
│   ├── mpo_contract.schema.json
│   └── runtime_state.schema.json
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── regression/
│   ├── calibration/
│   └── fixtures/
└── tools/
    ├── description_database.py      # 保持
    ├── install_into_project.py      # 新 layout へ更新
    ├── verify_package_layout.py     # 再実装
    └── templates/                   # Skill 共通 wrapper の生成元
```

`schemas/` の各 `*.schema.json` には、同名の `*.example.json` を併設する。通常運用で利用者が事前に作成する必須 JSON は `endpoint_registry.json` だけであり、`endpoint_registry.example.json` を複製して実データに合わせる。`llm_request` / `llm_response` の例は offline provider の実装・疎通確認用、その他の例は Runtime 生成物の契約確認用とする。

各新規 Skill は最低限 `SKILL.md`、`capability.json`、`env/pixi.toml`、`env/pixi.lock`、`scripts/launch.py`、`scripts/run.py`、Skill 内 package、単体テストを持つ。実行は必ず `scripts/launch.py` を経由し、Pixi 環境・cache・一時領域を Skill の `env/` 配下へ閉じ込める。

`cs-stat-core` は import 可能な versioned package と CLI の両方を持つ。他の lens Skill は各自の Pixi lock に local path dependency を明記し、暗黙の `PYTHONPATH` や system Python へ依存しない。Skill 間のデータ受け渡しは Artifact のみとし、別 Skill の作業ディレクトリを直接変更しない。

### 1.2 Skill 責務

| Skill | 責務 | 主入力 | 主出力 |
|---|---|---|---|
| `cs-fragment-engine` | 3クラス fragmentation、canonical MMP DB、Cliff 抽出、fragment表、Similar core | compounds、Endpoint、構造空間 | `mmp.sqlite`, `fragment_observations.csv` |
| `cs-context-builder` | 距離、average-linkage、分位・骨格文脈、重複排除、翻訳 | Description、compounds、Endpoint | context catalog、membership、translation |
| `cs-stat-core` | block permutation、段階的 p 値、BH、block bootstrap、参加率 | statistic plan、Endpoint、blocks | null/test/bootstrap tables |
| `cs-lens-l2` | L2b と L2a | MMP DB、contexts、Endpoint | L2 candidate/result tables |
| `cs-lens-l5` | 同一分割軸内の相関符号矛盾 | contexts、Tier 1/2 features | L5 candidate/result tables |
| `cs-lens-l1b` | 条件付き局所平坦性 | distances、contexts、Endpoint | L1b candidate/result tables |
| `cs-lens-l4` | 未踏領域と到達可能性 | distances、L2 DB、Endpoint | L4 candidate/result tables |
| `cs-lens-l7` | 骨格×R基の転写性 | series、Endpoint | L7 candidate/result tables |
| `cs-scoring` | 5軸、足切り、重複統合、上位K | 全 lens candidate | `findings_scored.jsonl` |
| `cs-deepdive` | T01〜T10、予算、決定論状態判定、LLM分岐 | ranked Finding、全証拠表 | deep-dive tree/result |
| `cs-report` | entity graph、narrative、引用検証、表示 | Findings、trees、evidence | report、final findings |
| `cs-runtime` | DAG、State、Lease、single writer、監査、checkpoint | Run request、catalog | Runtime state/event/manifest |

## 2. 共通公開インターフェース

### 2.1 CLI

全 Skill の公開 CLI は次で統一する。

```text
python <skill>/scripts/launch.py \
  --request <execution_request.json> \
  --output-dir <attempt_directory> \
  [--workers N] [--overwrite]
```

- `--request`: 必須。UTF-8 JSON。schema validation 後に処理する
- `--output-dir`: 必須。既存非空 directory は `--overwrite` が無ければ拒否する
- `--workers`: 任意。0または省略で論理 CPU 数−1、最低1
- `--overwrite`: Runtime の新 attempt directory では通常使わない。人間が明示した再計算だけ
- Skill 固有引数は増やさず、versioned request の `parameters` に置く

stdout は成功・失敗を表す1個の JSON object のみ、進捗・warning・worker log は stderr の JSONL とする。stdout へ表や自然文を出さない。

成功時:

```json
{"status":"succeeded","manifest":"artifact_manifest.json","primary":"<relative path>"}
```

失敗時 exit code:

| code | 意味 |
|---:|---|
| 0 | 成功 |
| 2 | CLI / schema / config validation error |
| 3 | 入力データ契約違反 |
| 4 | 計算失敗、必要標本不足、dependency failure |
| 5 | Artifact / citation / audit 不整合 |
| 10 | Local LLM command未設定、または論理call失敗率が設定閾値超過 |

### 2.2 Execution Request

```yaml
schema_version: '0.2.1'
identity:
  project: project_slug
  run_id: RUN-...
  phase_id: P03
  node_id: NODE-...
  attempt_id: ATT-...
  skill_name: cs-lens-l2
endpoint_id: EP_PRIMARY
config_path: /absolute/path/to/resolved_config.yaml
random_seed: 20260916
inputs:
  - role: endpoint_table
    path: /absolute/path/to/endpoints.csv
    sha256: ...
  - role: mmp_database
    path: /absolute/path/to/mmp.sqlite
    sha256: ...
parameters: {}
resources:
  workers: 31
  memory_mb: 64000
```

`inputs` は role ごとに必要数を capability catalog で宣言する。Runtime は存在、hash、producer manifest、schema version を検証してから node を lease する。Skill は request に無いファイルを探索して推測しない。

### 2.3 Artifact Manifest

全 node は最後に manifest を一時ファイルへ書き、fsync 後に atomic rename する。

```yaml
schema_version: '0.2.1'
producer: {run_id: ..., node_id: ..., attempt_id: ..., skill_name: ...}
status: succeeded
config_sha256: ...
input_artifacts:
  - {role: endpoint_table, path: ..., sha256: ...}
artifacts:
  - artifact_id: ART-...
    role: l2_candidates
    path: tables/l2_candidates.csv
    media_type: text/csv
    schema: l2_candidates@0.2.1
    rows: 151
    sha256: ...
metrics: {}
warnings: []
created_at: ...
```

相対 path は manifest directory から解決し、`..` による脱出を禁止する。各表は UTF-8、LF、RFC 4180 CSV とし、列順を schema で固定する。

## 3. 設定ファイル

確定パラメータは `CONDUCTOR_modules/config/defaults.yaml` に置き、コードに埋め込まない。Run準備時に defaults、project config、Run override の順で `load_resolved_config`によりdeep mergeし、未知 key を拒否した完全な`resolved_config.yaml`を作成する。各SkillとRuntimeへ渡す`config_path`は、この完全なfileを指すものとし、部分overlayを直接渡さない。既定値のまま運用する場合は`CONDUCTOR_modules/config/resolved_config.example.yaml`を複製し、machine固有の`llm.command`だけを置換してよい。Run開始時に同じ内容をRun rootへ保存し、そのhashを全Nodeで固定する。

```yaml
schema_version: '0.2.1'
measurement:
  sigma: 0.10
  sigma_diff: 0.14
  neutral_abs_delta_max: 0.28
  cliff_abs_delta_min: 0.42
  cliff_tanimoto_min: 0.75
  tolerance_variance_max: 0.02
contexts:
  neighbor_k: 10
  min_endpoint_n: 5
  jaccard_dedup_min: 0.90
  condition_depth: 1
  cluster_counts: [10, 20, 40]
  quantiles: [0.25, 0.50, 0.75]
  translation_auc_min: 0.70
statistics:
  screen_permutations: 100
  final_permutations: 1000
  screen_p_max: 0.05
  report_q_max: 0.05
  bootstrap_iterations: 200
  min_permutation_participation: 0.50
fragmentation:
  min_molecule_heavy_atoms: 6
  min_constant_heavy_atoms: 4
  max_variable_fraction: 0.60
  min_ring_variable_heavy_atoms: 3
  max_ring_attachments: 4
lenses:
  l1b: {lambda_min: 0.50}
  l2a: {min_transform_pairs: 3, min_pairs_in: 3, min_pairs_out: 3}
  l2b: {min_series_consistency: 2, min_series_variance: 3}
  l5: {min_abs_r: 0.30}
  l7: {min_common_r_groups: 5, min_abs_spearman_rho: 0.50}
scoring:
  statistical_strength_min: 0.50
  robustness_min: 0.70
  display_k: 10
deep_dive:
  max_depth: 3
  max_children: 3
  max_tests_per_finding: 15
  stop_after_consecutive_inconclusive: 2
  min_group_n: 3
  robustness_iterations: 500
llm:
  command: null
  timeout_seconds: 300
  schema_retries: 2
  max_failure_fraction: 0.20
runtime:
  random_seed: 20260916
  workers: 0
```

`measurement.sigma` は project 固有であることを config comment と manifest warning に明記する。別 project で defaults のまま実行しても自動変更せず、diagnosis 未実施 warning を出す。

## 4. 中心データ構造

### 4.1 Endpoint

```python
@dataclass(frozen=True)
class EndpointSpec:
    endpoint_id: str
    role: Literal['primary', 'secondary']
    kind: Literal['measured', 'derived']
    source_column: str | None
    transform: Literal['none', 'neg_log10', 'log10']
    higher_is_better: bool
    unit: str
    dependencies: tuple[str, ...]
```

1 Run は `endpoint_id` を1個だけ選ぶ。段階1で `oriented_value = transformed_value if higher_is_better else -transformed_value` を固定し、**全解析**の効果量、中央値、95パーセンタイル、最大値、frontier score を「大きいほど良い」oriented scale で計算する。raw、transformed、oriented を別列で保持し、表示時だけ元の単位と符号へ戻す。欠測は空文字として保存し補完しない。

### 4.2 Context

```python
@dataclass(frozen=True)
class ContextRecord:
    context_id: str
    context_type: Literal['cluster', 'quantile', 'scaffold', 'activity_diagnostic']
    axis_id: str
    source_space_id: str | None
    source_tier: int | None
    condition_depth: Literal[1]
    member_count: int
    endpoint_valid_count: int
    representative_context_id: str | None
    dedup_status: Literal['representative', 'near_duplicate']
    translation_status: Literal['native', 'translated', 'untranslatable', 'not_required']
    calibration_scope: bool
```

永続 ID のhash入力は RFC 8785 canonical JSONをUTF-8化し、SHA-256の先頭16桁を使う。contextは実装計画書の可読stemを保持し、末尾へhashを付ける（`CL|<space>|k<n>|c<index>|<16hex>`、`QT|<feature>|q<percentile>|<16hex>`、`SC|<16hex>`、`AD|<endpoint>|<16hex>`）。cluster indexは最小compound ID、次に全member IDのhashでclusterを安定sortしてから採番する。その他は `FRAG|<16hex>`、`PAIR|<16hex>`、`TR|<16hex>`、`FND|<16hex>`、`TEST|<16hex>` とする。

| ID | canonical hash入力 |
|---|---|
| cluster context | schema version、space ID、cluster count、sort済みmember compound IDs |
| quantile context | schema version、feature ID、percentile、finiteなcutoff value、sort済みmember compound IDs |
| scaffold context / scaffold entity | schema version、scaffold type、canonical scaffold key |
| activity diagnostic context | schema version、Endpoint ID、band定義、oriented scaleのcutoff values |
| fragmentation | schema version、compound ID、class、constant key、variable SMILES、attachment mapping |
| transformation | schema version、class、lexical方向のvariable from/to、attachment mapping |
| pair | schema version、transformation ID、constant key、方向付きcompound from/to |
| finding key | schema version、lens、sort済みEndpoint IDs、subject/condition/direction、sort済みtest question IDs |
| test | schema version、finding key、question、method、family key |

hash衝突を検出した場合は黙って延長せずRunをfailし、ID幅の変更をschema version変更として扱う。表示用 Finding IDだけは `finding_key` の lexical sort 後に Run 内で `F000001` から安定採番する。membership は compound ID の long table とし、配列位置を永続 ID にしない。

### 4.3 Fragment / Pair / Transformation

```python
TransformClass = Literal[
    'terminal_substitution',
    'linker_replacement',
    'ring_system_replacement',
]

@dataclass(frozen=True)
class FragmentationRecord:
    fragmentation_id: str
    compound_id: str
    transform_class: TransformClass
    constant_key: str
    variable_smiles: str
    cut_count: int
    attachment_mapping: tuple[int, ...]
    status: Literal['accepted', 'ambiguous', 'excluded']
    exclusion_reason: str | None

@dataclass(frozen=True)
class PairRecord:
    pair_id: str
    transform_class: TransformClass
    compound_from: str
    compound_to: str
    constant_key: str
    variable_from: str
    variable_to: str
    transformation_id: str
    endpoint_delta_oriented: float | None
```

pair は `variable_smiles` の lexical sort で小さい側を `from`、大きい側を `to` とし、`endpoint_delta_oriented = oriented_to - oriented_from` とする。同一 series・同一 fragment に複数 compound がある場合、Endpoint 平均を `FragmentObservation` 1件とし、元 compound IDs は配列 JSON として証拠表に残す。

### 4.4 Finding

Finding は JSON object 1件を1行にした `findings.jsonl` で保存し、各行を `finding.schema.json` で検証する。次を0.2.1の確定 schema とし、`entities` とその6配列は空配列の場合も省略不可とする。

```yaml
finding_id: F000042
finding_key: FND|0123456789abcdef
lens: L2b
endpoint_ids: [EP_PRIMARY]
claim:
  subject_type: fragment
  subject_id: FRAG-...
  condition_id: null
  condition_depth: 1
  effect_direction: positive
  effect_size: 0.62
  effect_unit: log_endpoint
  support_n: 7
tests:
  - test_id: TEST-...
    question: consistent_effect
    method: series_block_permutation
    statistic: 3.1
    p_value: 0.003
    q_value: 0.04
    null_iterations: 1000
falsification:
  type: label_permutation
  parameters: {}
  decision_rule: ...
triviality:
  confounders_tested: [MW, cLogP, TPSA, scaffold_class]
  raw_effect_size: 0.62
  adjusted_effect_size: 0.48
  verdict: notable
translation: {status: not_required}
entities:
  context_ids: []
  scaffold_ids: [SC-...]
  transformation_ids: []
  fragment_ids: [FRAG-...]
  compound_ids: [CPD-0231]
  feature_ids: []
citations:
  - citation_id: CIT-...
    table_ref: phase3/l2b_evidence.csv#row_id=L2B-...
scores:
  statistical_strength: null
  robustness: null
  non_triviality: null
  actionability: null
  frontier_relevance: null
  composite: null
  rank: null
state:
  pipeline: candidate
  deep_dive: not_dived
labels: []
merged_into: null
narrative: null
```

`entities` は統合キーなので全 Finding で必須。数値は JSON number、非有限値は禁止。複数 test の q 値を1つの Finding にまとめる場合も、test ごとの raw record を失わない。

## 5. Run directory と中間成果物

```text
results/CONDUCTOR/<project>/<run_id>/
├── run_request.json
├── resolved_config.yaml
├── run_manifest.json
├── state/runtime.sqlite
├── logs/events.jsonl
├── phase1/
├── phase2/
├── phase3/
├── phase4/
├── phase5/
└── phase6/
```

### 5.1 Phase 1

| Artifact | 形式 | 主な列・内容 |
|---|---|---|
| `compounds.csv` | CSV | `row_id,compound_id,input_smiles,canonical_smiles,structure_sha256,mol_parse_ok` |
| `endpoint_registry.json` | JSON | `EndpointSpec[]` と selected endpoint |
| `endpoints.csv` | CSV | `row_id,compound_id,endpoint_id,raw_value,value,oriented_value,is_measured` |
| `endpoint_missingness.csv` | CSV | measured/unmeasured比較、n、効果量、p、q、判定 |
| `feature_spaces.json` | JSON | space ID、Tier、structurality、metric、version、path |
| `descriptions/<Dxxx>.*` | 既存 Skill 契約 | Description Database から hit/miss 統合後の表 |
| `distance/<space>.npy` | NumPy | float32、対称、対角0。metadata JSONとsha256を併設 |

Description Database は既存 `description_database.py` の cache plan、同一 ID・異構造 fail-fast、audit invalidate を保持する。Description Skill の生出力を変更せず、Pipeline planはtracked canonical entry pointである`CONDUCTOR_modules/tools/description_node.py`をPhase 1 Description Nodeの`launch_path`として指定する。このNodeだけが`description_adapter.py`を介して18 Skillを実行し、`feature_spaces.json`と`distance/`を生成する。Claude CodeがRun root内へ同等scriptを即席生成したり、18 SkillをRuntime外から直接起動してはならない。

### 5.2 Fragment engine

| Artifact | 形式 | 内容 |
|---|---|---|
| `mmp.sqlite` | SQLite | 下記の immutable canonical DB |
| `fragment_observations.csv` | CSV | `row_id,series_key,fragment_id,fragment_smiles,compound_ids_json,n_compounds,endpoint_mean` |
| `fragmentation_exclusions.csv` | CSV | ambiguous、N≥5、サイズ違反、parse失敗を理由付きで全件 |
| `cliff_candidates.csv` | CSV | space、pair、similarity、delta、extraction status、transformation ID |

`mmp.sqlite` table:

- `metadata(key PRIMARY KEY, value_json)`
- `fragmentations(fragmentation_id PRIMARY KEY, compound_id, class, constant_key, variable_smiles, cut_count, attachment_mapping_json, status, exclusion_reason)`
- `pairs(pair_id PRIMARY KEY, class, compound_from, compound_to, constant_key, variable_from, variable_to, transformation_id)`
- `transformations(transformation_id PRIMARY KEY, class, variable_from, variable_to, pair_count)`
- `similar_core_map(map_id PRIMARY KEY, core_a, core_b, similarity_class, tanimoto, mcs_coverage, attachment_mapping_json, status)`
- index: `(class, constant_key)`, `(transformation_id)`, `(compound_from)`, `(compound_to)`

DB は build 完了後 read-only とし、`metadata.complete=true` と全 table count/hash を最後の単一 transaction で書く。Endpoint delta は構造 DB と分離した view Artifact へ置き、Endpoint 変更時に canonical DB を再構築しない。

### 5.3 Phase 2

| Artifact | 形式 | 主な列 |
|---|---|---|
| `contexts.csv` | CSV | ContextRecord 全列、`calibration_scope` |
| `context_membership.csv` | CSV | `row_id,context_id,compound_id,is_member`。true 行だけを保存 |
| `context_dedup.csv` | CSV | `context_id,representative_context_id,jaccard,component_id` |
| `translations.csv` | CSV | `context_id,status,auc,folds,feature_ids_json,coefficients_json,description` |
| `context_metrics.json` | JSON | 種類別件数、重複率、翻訳不能率、AUC分布 |

### 5.4 Phase 3〜6

| Phase | Artifact | 形式 |
|---|---|---|
| 3 | `<lens>_screen.csv`, `<lens>_tests.csv`, `<lens>_evidence.csv` | CSV |
| 3 | `permutation_participation.csv`, `diagnostic_metrics.json` | CSV / JSON |
| 4 | `findings_candidates.jsonl`, `findings_scored.jsonl`, `ranking.csv`, `merge_map.csv` | JSONL / CSV |
| 5 | `deep_dive_tree.json`, `deep_dive_tests.csv`, `llm_calls.jsonl` | JSON / CSV / JSONL |
| 6 | `findings_final.jsonl`, `entity_components.csv`, `citation_audit.csv`, `report.md` | JSONL / CSV / Markdown |

CSV の先頭列は必ず永続的な `row_id` とする。引用は物理行番号ではなく `relative_path#row_id=<id>` を正本とし、validator は file hash と row_id 一意性も検証する。人間向けに物理行番号を付記してよいが参照キーにはしない。

## 6. 統計基盤

### 6.1 block permutation

```python
def permute_within_blocks(values, block_labels, rng):
    out = values.copy()
    groups = group finite values by non-null block label
    eligible = 0
    for group in groups:
        if len(group) > 1:
            out[group] = values[rng.permutation(group)]
            eligible += len(group)
    participation = eligible / count_finite(values)
    return out, participation
```

- null block、欠測、singleton は値を保持する
- candidate と反復番号から seed を `SHA-256(run_seed|candidate_key|iteration)` で導出する
- worker数・task順に関係なく同じ反復列を得る
- participation を反復ごとと candidate集計で保存する
- 50%未満は warning と `needs_design_review=true`。計算は完了させるが自動報告へ進めない

解析別 block:

| Lens | block |
|---|---|
| L2a / L2b | `series_key` |
| L1b / L5 | Murcko scaffold ID |
| L4 | Murcko scaffold ID |
| L7 | 系列内 R基 label |

L1b は context membership と距離行列を固定し、Endpointだけを Murcko骨格内で並べ替えて λ を再計算する。同サイズランダム subset は作らない。L2b は series（同一 constant key）内で Endpoint を並べ替える。診断互換 mode は任意の補助機能であり、実装・合否判定の必須条件ではない。

### 6.2 段階的 p 値

```text
observed statistic を1回計算
B=100 の帰無で p100 = (1 + extreme_count) / 101
p100 > 0.05 なら screened_out（BHなし）
生存候補だけ、同じ seed stream の先頭100を含む合計 B=1000 まで延長
p1000 = (1 + extreme_count) / 1001
lens family ごとに BH q を計算
```

極端性は test ごとに `two_sided_abs`、`upper`、`lower` を明示し、暗黙に推測しない。B=100 の結果も監査用に保存する。途中再開は完了反復数と extreme count から行う。

### 6.3 BH

入力 p 値の stable sort は `(p_value, candidate_key, test_id)`。逆順累積最小で q を算出し `[0,1]` へ clip する。NaN test は族から除外し、除外理由を candidate に残す。重複文脈は BH 前に代表だけへ縮約する。

族:

- L1b: representative context × Tier 1/2 space
- L2a: class別の eligible transformation × representative context
- L2b: terminal fragment と ring fragment を別 family
- L5: 同一 axis 内 context pair × Tier 1/2 feature
- L7: common R≥5 の series pair
- L4: candidate region

### 6.4 block bootstrap

Murcko scaffold を復元抽出し、選ばれた scaffold に属する全 compound をまとめて複製する。複製 block には bootstrap instance ID を付けて同一 compound ID の衝突を避ける。B=200。各反復で元 test と同じ効果方向・`p≤0.05` が保たれた割合を robustness とする。化合物単位 bootstrap は実装しない。

## 7. 各段階のアルゴリズム

### 7.1 段階1: データモデル、Endpoint、欠測診断

```text
load dataset and Endpoint registry
validate unique non-empty compound_id
parse SMILES and calculate canonical SMILES
if one compound_id maps to multiple canonical structures: fail Run
write compounds.csv and endpoint_registry.json
for each registered Endpoint:
    transform values; invalid domain is a data error
    do not impute missing values
    compare measured vs unmeasured groups on every other Endpoint
    write missingness tests and selection_biased decision
validate all JSON/CSV contracts
```

対象 Endpoint の測定済み群と未測定群について、他の各 Endpoint を用いた Mann-Whitney U 両側検定を行う。両群とも n≥5 の比較だけを対象とし、対象 Endpointごとの族で BH補正する。1件でも q≤0.05 なら `selection_biased` とし、rank-biserial correlationを効果量として保存する。解析対象 Endpoint が `selection_biased` でも除外せず、全 Finding に label を伝播する。

MPO schema は `endpoint_ids: array`、derived dependency、Endpoint別 score map を表現するが、0.2.1 validator は解析 Finding の配列長を1に制限する。

### 7.2 段階2: 表現生成

```text
for each retained Description capability:
    prepare_cache_plan()
    send only misses to the Description Skill
    validate its manifest and result
    finalize_cached_output()
    register Tier, structurality, metric and calculation_version
for each space:
    compute or reuse one distance matrix
    store float32 .npy + metadata
```

Tier / structurality は `feature_spaces.json` のデータとして持つ。最低限の対応:

- Tier 1: RDKit 2D、RDKit fragment counts
- Tier 2: MACCS、Mordred 2D/3D、RDKit 3D、shape、USR/USRCAT、xTB
- Tier 3: Morgan、atom-pair、torsion、path/pattern/layered、Avalon、Gobbi Pharm2D、ChemBERTa
- structural: 部分構造 fingerprint 群（Morgan、MACCS、atom-pair、torsion、path/pattern/layered、Avalon）
- non-structural: descriptor、3D、xTB、Gobbi Pharm2D、ChemBERTa、fragment counts

0.2.1 の Description capability 母集団は現存18件（D001〜D016、D019、D020）に固定する。D017/D018 は予約番号であり、空実装や復元対象にはしない。catalogには実在する18件だけを登録する。

0.2.1 identityを保持するRuntimeと、0.1.xの厳格な`round_id=RNDdddd`、`node_id=Ndddddd`、`attempt_id=ATTdddd`を要求するDescription Skillの間には、共通の決定論的identity bridgeを置く。0.2.1 identityを旧Skillへ直接渡してはならない。cache miss subset CSVはNode出力先の外側に作った`TemporaryDirectory`へ置き、Skillが要求する空のoutput directoryを汚染しない。Nodeの距離Artifactは常にNode root直下の`distance/`へ置く。

Description Databaseへの登録はcapability別の契約とする。既定は全featureが有限値であることを要求する。D015/D016 Mordredだけは、構造上定義されない希少元素関連featureをnullのまま保持できる`allow_partial`とし、1行あたりfeatureの50%以上かつ1件以上が有限であることを要求する。全feature非有限、計算error、conformer生成失敗は登録しない。登録契約の変更はcalculation signatureへ含め、D015/D016の`calculation_version`を更新する。距離計算では観測集合全体で一度も有限にならない列を除外し、残る欠測だけを観測中央値で補完する。

### 7.3 段階3: 統計基盤

実装順は pure function の unit test → synthetic block test → staged permutation → BH → bootstrap とする。lens コードより先に calibration harness を作る。

統計 API:

```python
def empirical_p_value(
    observed: float,
    null_statistics: NDArray[float],
    alternative: Literal['two_sided_abs', 'upper', 'lower'],
) -> float: ...

def benjamini_hochberg(records: Sequence[TestRecord]) -> list[TestRecord]: ...

def block_bootstrap_indices(
    block_labels: Sequence[str | None], iterations: int, seed: int
) -> Iterator[BootstrapSample]: ...
```

`TestRecord` は candidate key、family key、statistic、alternative、p、q、B、seed derivation、participation、status を持つ。

### 7.4 段階4: Fragment engine

#### 3クラス fragmentation

```text
for each valid molecule with heavy_atoms >= 6:
    terminal:
        cut each acyclic single bond once
        smaller side is variable; other side is constant
    linker:
        cut pairs of acyclic single bonds
        exactly one fragment with 2 dummies is variable
        two 1-dummy fragments are constants
    ring:
        merge fused/spiro rings into ring systems
        cut every exocyclic bond of one ring system
        identify variable by intersection with original ring atom indices
        never identify by dummy count
    normalize every dummy isotope/map for key comparison
    apply heavy atom and variable fraction rules
    record both accepted and excluded cases
```

canonical key:

```text
1-cut: canonical constant SMILES
2/N-cut: canonical constant component SMILES sorted lexically and joined by ' | '
```

環 N=3/4 では dummy に元結合の attachment index を付け、constant側 fragmentの canonical rankと分子自己同型から全対応を列挙する。全対応が同じ canonical transformation keyになる場合だけ対称等価として採用し、それ以外は `ambiguous_mapping` で除外する。`min_constant_heavy_atoms=4` は合計ではなく**各** constant fragmentへ個別適用する。N≥5 は除外件数を記録する。変換3クラスは table、統計 family、Finding、表示を混ぜない。

#### Pair と fragment table

```text
group accepted fragmentations by (class, constant_key)
deduplicate duplicate (compound_id, variable_smiles)
for each unordered member pair with different variable:
    orient by lexical variable SMILES
    create stable pair and transformation keys
for each series with >=2 distinct variables:
    group same variable's compounds
    endpoint_mean = mean(finite Endpoint values)
    emit one FragmentObservation
```

MMP canonical DB と Attachment制約付き Similar coreは、Stage 0退避直前の commit `470d312d250ba55b5a564ced8211882b32164a97` にある `mmp_0111_model.py`、`mmp_engine.py`、`mmp_0111_evidence.py` から必要な純粋関数だけを移植する。旧 Runtime、Target起点処理、報告処理は移植しない。実装時の監査記録へ元 commit、元 path、移植関数、移植先、差分理由を残す。Similarity class は `exact / radius2 / radius1 / mcs_mapped`。mapping 不成立・coverage不足・ambiguous は除外理由を残す。

#### Cliff 起点

structural space だけを対象に、Tanimoto≥0.75 かつ `|oriented delta|≥0.42` の pair を列挙し、3クラス変換抽出を試す。抽出成功した transformation は網羅列挙集合へ union する。Cliff pair 自身は Finding にしない。非構造空間は λ の診断だけで Cliff pair を列挙しない。

### 7.5 段階5: 文脈構築

#### クラスタ

```text
for each Description space in parallel:
    load or compute distance matrix once
    for k in [10, 20, 40]:
        average-linkage agglomerative clustering(precomputed distance)
        stable-sort clusters and emit CL|<space_id>|k<k>|c<index>|<sha16>
```

fingerprint は `1-Tanimoto`、descriptor は全欠損・定数列を除外、列中央値補完、z標準化後の Euclidean。別 clustering 手法を追加しない。

#### 分位・骨格・活性域

- Tier 1 feature ごとに raw feature scale の q25/q50/q75 以下を `QT|<feature>|q<percentile>|<16hex>` とする。以上側を別contextにしない
- Murcko/MCS/BRICS/RECAP context を構造依存 Artifact として作る。MCS は generic Murcko topology が同一の化合物群ごとに atom/bond `CompareAny`、`ringMatchesRingOnly=true`、`completeRingsOnly=true` で群内 MCS を計算し、その SMARTS を監査可能な class key とする。Endpoint valid n≥5 は Run ごとの eligibility 列で判定する
- 活性域は診断行だけに使い、L1b/L2/L5 の condition に渡さない
- 全contextに `calibration_scope` を持たせ、診断互換の cluster + Tier 1分位 + Murckoだけを `true` とする。270±20%はこのsubsetだけへ適用し、全context数は別指標として報告する

#### 重複排除

```text
build graph where edge(A,B) iff Jaccard(A,B) >= 0.9
for each connected component:
    representative = maximum member_count, then lexical context_id
    retain every context row
    mark non-representatives and reference representative
only representatives enter BH families and Finding generation
```

#### 翻訳

Tier 3 cluster について、Tier 1 features だけを説明変数とする L2 正則化 logistic regression を3-fold stratified CVで評価する。fold 内で欠測補完・標準化を fit し、leakage を防ぐ。AUC<0.70 は `untranslatable`。AUC≥0.70 は全データで再fitし、係数と方向を保存する。標準化係数が非ゼロの特徴を絶対値降順、同値はfeature ID順で並べ、上位3件を符号付き固定テンプレートで記述する。Phase 2ではLLMを使わず、言い換えはPhase 6の narrativeだけで許可する。

### 7.6 段階6: L2b

L2b でいう series は同一 `(transform_class, constant_key)` であり、Phase 2 context とは区別する。

```text
for each eligible series s:
    collapse duplicate fragment observations to one endpoint mean
    require at least 2 finite fragment observations
    series_mean = mean(observation endpoint means)
    for each fragment F in s:
        residual(F,s) = endpoint_mean(F,s) - series_mean

for each fragment F:
    residuals = one residual per series
    m = number of series
    if m < 2: exclude
    test consistent effect when m >= 2:
        t = mean(residuals) / (sample_sd(residuals) / sqrt(m))
        if sample_sd == 0: p=1
    test series variance when m >= 3:
        v = sample variance(residuals)
    null:
        permute Endpoint within each series
        recompute collapse, means, residuals and statistic
```

問い1は両側、問い2は上側。terminal と ring を別 family とし、混ぜない。fragment が2 seriesなら問い1のみ、3以上なら両方。各問いは独立 test record とし、同一 fragment の両方が通過した場合は1 Finding内に2 testsを持たせる。

段階6完了後、必ず停止する。本番の系列内検定で `L2b enrichment > 1.5` を確認し、`series_count`、pair数、context数、参加率、候補数、診断値との差分原因を報告する。診断互換 mode は任意であり、2.07 / 2.31 / 2.54 との厳密一致を要求しない。基準未達または明示承認前は段階7へ進まない。Phase 2 contextで系列を層別する解析は、系列を一意に写像できる場合の任意追加解析とする。

### 7.7 段階7: 残りの lens

#### L5

axis ID ごとに context pair を作る。同一 clustering の cluster間、同一 feature の quantile間など、異なる axis は比較しない。各文脈で Tier 1/2 feature と Endpoint の Pearson r を計算し、双方 `|r|≥0.3` かつ逆符号を候補とする。観測 statistic は Fisher z 差とし、p値は EndpointのMurcko骨格内並べ替えから経験的に求める。包含を含む文脈の重なりを許容し、共有化合物数を証拠表へ記録する。Global r も証拠として保存する。

#### L1b

Tier 1/2 space と representative context の各組について、context内各化合物を同じ context内の k=10 最近傍から予測し、

```text
lambda = 1 - mean((observed - neighbor_prediction)^2) / global_endpoint_variance
```

を求める。対象化合物自身を近傍・λ計算に含めない。有効 n<5、global variance≤0、近傍不足は候補外。`lambda≥0.5` は診断ゲートとする。有意性は、context membershipと距離行列を固定したままEndpointだけをMurcko骨格内で並べ替える帰無分布から求める。同サイズランダムsubsetは生成しない。L1a は全空間の min λ を診断表へ出すだけで Finding を作らない。

#### L2a

3 pair以上の transformation だけを対象に、representative contextごとの中央値シフトと分散縮小を独立 test とする。両端がcontext Cに属するpairだけを `in_C`、両端が非所属のpairだけを `out_C` とし、跨ぐpairは除外する。deltaはlexicalなvariable SMILES方向で固定する。シフト統計量は `median(delta_in)-median(delta_out)` の両側検定、分散統計量は `Var(in_C)/Var(all)` の下側片側検定とし、系列内Endpoint並べ替えごとにpairを再生成する。少なくとも `n_in≥3` と `n_out≥3` を満たさない候補は検定しない。許容性は `|median delta|<0.28` かつ分散≤0.02で labelする。

#### L7

同一系列・同一 R基の重複 compound をEndpoint平均へ集約し、共通 R基5個以上の series pairだけを列挙する。Spearman ρ は系列BのR基labelを並べ替え、系列平均差は各共通R基の対応を保ったまま骨格A/B labelを交換し、それぞれ両側経験p値を求めて同じL7族でBH補正する。系列平均差へR基label並べ替えを適用すると統計量が不変になるため、主効果には対応付きlabel交換を使う。ρの `q≤0.05` を共通の有意性条件とし、`ρ≤-0.5` は序列逆転、`ρ≥0.5` かつ主効果 `q≤0.05` は上位互換、`ρ≥0.5` かつ主効果 `q>0.05` は独立最適化として採択する。それ以外はFindingにしない。

#### L4

候補生成と領域評価は二段に分離する。第一段で one-step 候補を `l4_candidate_compounds.csv` に固定し、第二段で Phase 1 の `feature_spaces.json` に記録された Skill と `parameters` を使って、候補そのものについて全 Tier 1/2 Description を再実行する。`candidate_feature_spaces.json` に候補 payload を登録し、観測化合物に fit した特徴列、欠測補完値、標準化値をそのまま使って候補―観測化合物間距離を計算する。候補 Description の欠落・行失敗・ID不一致は fail-closed とし、到達元化合物の近傍を proxy にしてはならない。

候補Descriptionの前にscale contractを適用する。全one-step候補を、(1)異なる到達経路数、(2)利用した変換の観測pair数合計、(3)到達元化合物数の降順、(4)candidate IDの昇順でstable sortし、`lenses.l4.candidate_cap`件だけを残す。既定は100件とする。除外候補は`reason=scale_cap`としてgeneration auditへ残す。さらに`選択候補数 × Tier 1/2 space数`と、Description cost classを`low=1, medium=4, high=16, very_high=64`で重み付けしたcost unitsを事前計算する。このcost unitsはwall-clock時間ではなく、lowとvery_highを同じ1行として扱わないための相対的なschedule guardである。予定行数が`lenses.l4.max_candidate_description_rows`（既定900）、またはcost unitsが`lenses.l4.max_candidate_description_cost_units`（既定10,000）を超える場合は、Description Skillを1件も起動せず`needs_design_review`で停止する。候補capまたはコスト上限をRun中に自動拡大してはならない。

L2 canonical transformation DB が完成してから最後に実装する。既存化合物へ実績のあるL2変換を1本だけ適用して得られる、未観測かつRDKit sanitize済みの構造を候補とする。各Tier 1/2空間のk=10近傍を領域とし、期待値は近傍平均の片側95%下限、密度ギャップは `1 - min(n_region/min_context_size, 1)`（`min_context_size = contexts.min_endpoint_n`）、到達可能性はvalidation済み1-stepなら1とする。候補不足またはenrichmentが1.0付近でも閾値を調整せず、そのまま降格判断用に報告する。

L3/L6 は診断 module と同等の集計を `diagnostic_metrics.json` へ出してよいが、candidate table と Finding factory を持たせない。

### 7.8 段階8: スコアリング

```text
statistical_strength:
    within each lens, stable rank by ascending q then finding_key
    1 - (rank - 1) / n_candidates_in_lens
robustness:
    Murcko block bootstrap B=200 survival ratio
gate:
    statistical_strength >= 0.5 and robustness >= 0.7
non_triviality:
    clip(E_adj / E_raw, 0, 1), E_raw=0 => 0
actionability:
    exact enum 1.0 / 0.6 / 0.2
frontier_relevance:
    oriented scale
composite:
    non_triviality * actionability * frontier_relevance
```

`n_candidates_in_lens` は最終 B=1000 と BH を完了した候補数とする。q tie は平均順位ではなく `(q, finding_key)` の stable ordinal rankとする。`E_adj` は各レンズの最小観測単位でMW、cLogP、TPSA、骨格dummyを簡潔な線形モデルで残差化し、同じ効果統計を再計算する。L1b/L5は化合物残差、L2aはpairの交絡差、L2bは系列内残差、L7は系列内residualized Endpoint、L4は到達元と生成物の予測交絡差を使う。

scoring Node は `feature_spaces` の D001 payload を必須入力とし、L4 Finding が存在するときは `candidate_feature_spaces` も入力する。D001 の `rdkit2d__MolWt`、`rdkit2d__MolLogP`、`rdkit2d__TPSA` と入力構造から機械生成した Murcko scaffold class を交絡表とする。各 Lens の `score_observations` は同じ効果統計を再計算できる compound、pair、series、neighbor、context/feature の識別情報を保持する。情報不足時に説明率による縮約へ戻してはならず fail-closed とする。

重複判定:

```text
if count(shared entities) >= 2 and subject_type equal:
    keep higher composite
    tie-break: lower q, then lexical finding_key
    loser.merged_into = winner.finding_id
```

loser を削除しない。初期 θ で K=10 を満たせなければ Runtime を `needs_design_review` で止め、θを自動的に下げない。

### 7.9 段階9: 深堀

LLM は親 Finding と実行可能 template schema を受け、最大3個の `{template_id, parameters}` を返す。0個を許容する。同一 ancestor path で同じ template+canonical parameters を再実行しない。

```text
queue root node depth=0
while queue and budget < 15:
    LLM selects 0..3 templates
    for selection:
        budget += 1 even if precondition/min-n fails
        deterministic executor returns test result
        deterministic judge assigns state
        REFUTED: stop branch
        SURVIVED or WEAKENED and depth < 3: enqueue
        two consecutive INCONCLUSIVE on branch: stop branch
summarize tree with citations
```

全テンプレートを次のシグネチャで実装する。

```python
def execute(
    parent_finding: Finding,
    parameter_object: Mapping[str, JSONValue],
    artifact_registry: ArtifactRegistry,
) -> DeepDiveTestResult: ...
```

`DeepDiveTestResult` は最低限 `template_id`、canonical parameter hash、`execution_status`（`completed|not_testable|failed`）、family key、primary/comparator の n、親/子効果量、効果方向、nullableなp/q、補助統計、判定入力、引用可能 row ID、理由を持つ。全統計はoriented scaleを使い、親レンズと同じ最小観測単位、block、欠測規則を再利用する。群の最小nは、特記がなければ `max(3, 親レンズの最小n)` とする。同一template呼出しで生成した比較を `(parent_finding_id, template_id, axis_id)` 族としてBH補正する。axisを持たないtemplateは `axis_id=global` とする。

| ID | 必須 parameter / 実行契約 | 判定へ渡す主出力 |
|---|---|---|
| T01 | `axis_id`, `level`。各levelを「該当/非該当」の独立二値分割として親レンズの効果と検定を両群で再実行。両群が最小n以上 | 両群の n/effect/p/q、効果比、包含関係 |
| T02 | `axis_id`。順序値が3水準以上、各水準n≥3。最小観測単位の効果proxyと軸順位のSpearman ρを親block内の並べ替えで両側検定 | ρ、p/q、水準別nと中央値 |
| T03 | `context_ids`（1〜3件）。executorがmembership Jaccard降順で提示した親以外の代表contextから選び、親レンズ検定を再実行 | context別n/effect/p/q、Jaccard、共有n |
| T04 | `target_ids`（1〜3件）。L2はSimilarity classと構造類似度、L5は共通compound上の特徴相関でexecutorが提示した対象から選び、親レンズ検定を再実行 | 対象別similarity、n/effect/p/q |
| T05 | `iterations`（既定500）。親と同じblock bootstrapで効果符号を再評価 | 符号一致率、その95%区間、中央値効果。p/qはnull |
| T06 | `context_id`, `transformation_id`。context内の未適用化合物へ既知変換を1-step適用し、未観測・sanitize・重複を検証 | 候補数、元compound、生成構造、validation理由。p/qはnull |
| T07 | `confounders`。MW、cLogP、TPSA、骨格dummyを個別および一括で残差化し親統計を再実行 | raw/adjusted effect、説明割合、p/q |
| T08 | `unit_type`。最小観測単位を1件ずつ除外し、効果変化最大の行を特定してその除外結果を再検定 | 最大影響row、effect変化、除外後p/q |
| T09 | `sample_n`, `iterations`（既定1000）。親のeligible母集団から同数をblock制約付きで抽出し効果量を再計算 | 観測効果の経験p/q、null分位、参加率 |
| T10 | `counterexample_rule`。親方向と逆の最小観測単位を明示列挙し、方向一致/不一致の二項統計を両側検定 | 反例row、反例率、符号統計、p/q |

T09は観測効果の絶対値以上となるnull反復数に+1/+1を適用し、T10は一致/不一致を帰無確率0.5の正確二項両側検定とする。T03/T04/T07/T08は再実行した親レンズのp値を使用する。

T01 は必須実装とし、骨格クラス、置換基heavy atom数、極性（cLogP/TPSA）、水素結合能（HBD/HBA）、環の有無、立体化学、電子効果、正規化attachment位置を機械算出軸として登録する。連続軸は親標本の有限値中央値で二値化し、category軸は各level対その他とする。プロジェクト固有SMARTSは任意追加軸であり、各patternを非排他的な二値flagとして扱い、包含関係を保存する。

電子効果は版管理した `resources/hammett_constants.tsv` を使い、attachment位置がmeta/paraへ一意に対応するときだけHammett値を採用する。Hammett σは正をEWG、負をEDG、0をneutralとする。それ以外はGasteiger fragment chargeを用い、較正データの中央値/MADで標準化して `z≥0.5` をEWG、`z≤-0.5` をEDG、`|z|<0.5` をneutralとする。xTB電荷は検証列にのみ保存し区分へ使わない。TSVのversion、出典、license、sha256をmanifestへ記録する。

状態規則は実装計画書9-1を pure function にし、LLMに状態を返させない。原則として q≤0.05かつ親と同符号なら `SURVIVED`、逆符号なら `REFUTED`、T01で部分集合だけが有意かつ補集合が非有意または親効果の50%未満なら `WEAKENED`、それ以外を `INCONCLUSIVE` とする。T05は95% percentile区間が0をまたがず親方向なら `SURVIVED`、逆方向なら `REFUTED`、それ以外を `INCONCLUSIVE` とする。T06は検証済み候補が1件以上なら `SURVIVED`、0件なら `INCONCLUSIVE` とし、`REFUTED`/`WEAKENED` を返さない。T01〜T10は全て0.2.1の完了条件であり、`not_available` 実装は禁止する。

LLM providerは `llm.command` に設定したローカルコマンドとJSONL stdin/stdoutで通信する。schema違反・timeout・process失敗は同一論理callを最大2回再試行し、全再試行失敗後は当該Findingをnarrativeなしで保持してRunを続行する。`failed_logical_calls / attempted_logical_calls > llm.max_failure_fraction`（既定0.20）の場合だけPhaseを失敗させる。未設定commandはLLMを必要とするPhaseの設定エラーとする。fallback文章は生成しない。

参照実装は、Ubuntu CPU機上で動作する`CONDUCTOR_modules/local_llm_provider/provider.py`と、別GPU機上の承認済み`vllm serve` OpenAI互換APIの組合せとする。providerは推論engineを内包せず、固定した`/v1/chat/completions` endpointへ接続する。接続先hostnameをallowlistし、非loopback HTTP、URL埋込みcredential、redirect、proxyを既定で拒否する。今回の信頼済み社内networkに限り、固定した`approved_host`に対して`allow_plaintext_http: true`を明示することでHTTPを許可し、認証なしの場合は`authentication: "none"`および`api_key_env: null`とする。認証を使用する構成ではAPI keyを環境変数からだけ取得する。model運用値に基づき固定・記録したsampling parameter、固定seed、`chat_template_kwargs.enable_thinking=false`、`llm_response.schema.json`を用いたJSON Schema structured outputを指定する。vLLM xgrammarが未対応の`uniqueItems`は生成用schemaからだけ除外し、同じ一意性をproviderの事後検証で強制する。greedy decodingやbit単位のLLM出力再現性は要求しない。vLLM版、served model名、model/deployment revision、量子化、prompt版とhash、provider config hashの宣言値をprovider stderrへ出し、呼出側は成功callのstderrもattempt logへ保持する。開発機の擬似OpenAI互換server testはJSONL/HTTP契約だけを検証し、実modelの3タスクprobeを代替しない。全てのDescription計算、統計検定、template実行、状態判定、引用検証はCPU機上で行い、GPU serverへ委譲しない。

### 7.10 段階10: 統合と報告

```text
extract every typed entity from reportable Findings
build undirected graph: edge if at least one entity is shared
compute connected components deterministically
for each component:
    pass only Findings and citeable rows to Local LLM
    request one paragraph with explicit citation IDs
validate narrative and Finding numeric claims
if any validation fails: fail Phase 6, keep invalid draft for diagnosis
```

引用検証:

1. narrative の数値 token を locale非依存 parser で抽出し、参照 row の数値集合と相対誤差1%以内で照合
2. compound ID / pair ID が Run registry に存在
3. table path が Run 内にあり、manifest hash一致、row_idが一意に存在
4. test p/q/statistic が test table と一致
5. narrative の citation marker が全て citations array に存在し、未使用 citation も warning

自動修正しない。不一致には narrative ID、token、citation ID、table_ref、expected/actual を含める。

### 7.11 段階11: Runtime

Runtime は SQLite WAL の single writer。worker は State DB を直接更新せず、attempt directory に execution event を atomic writeし、Runtime coordinatorだけが transactionで取り込む。

node状態:

```text
pending -> leased -> running -> succeeded
                         |-> failed
                         |-> needs_design_review
leased/running --lease expiry--> retryable
failed --explicit audited administrative requeue--> retryable
```

同じ `(node_id, input_hashes, config_hash, code_version)` の成功 Artifact は再利用可能。lease token と attempt ID が一致しない late event は監査ログへ隔離し正本状態を変更しない。Phase boundary/checkpoint は実装計画書9章の既出確認事項として別レビューする。

`failed`からの再キューは一般的なstate編集ではない。修正済みSkill名、対象node ID、操作者、理由を明示し、対象が実際に`failed`である場合だけ、専用のadministrative requeueで`retryable`へ遷移させる。入力、config、計算契約が不変で、Pixi launcher解決等の実行環境だけを是正した場合に限定する。`succeeded`、`needs_design_review`、`leased`、`running`、`pending`、既に`retryable`のNodeには適用しない。旧attempt ID、理由、操作者をRuntime SQLiteのeventへ記録し、attempt/leaseをclearしてから同じRunの通常coordinatorで再開する。計算契約を変更した場合は新しいRunを作成する。

Runtimeに明示された`resources.workers`はNode単位の論理CPU上限である。coordinatorは解決した値を子processの`--workers`、`CONDUCTOR_AVAILABLE_CPU_CORES`、`CONDUCTOR_NODE_CPU_CORES`だけでなく、attemptごとに解決したExecution Requestの`resources.workers`にも同じ値で記録する。明示値がOS affinityで利用可能なCPU数を超える場合はNode起動前に拒否する。

## 8. エラー処理

| 状況 | 挙動 |
|---|---|
| request/config/schema不正 | node開始前に fail、出力Artifactなし |
| 同一 compound ID・異構造 | Run fail-fast。自動修正しない |
| invalid SMILES | compounds表に失敗を記録。対象化合物を構造計算から除外し、件数をwarning。全件無効ならfail |
| Endpoint transform domain不正 | 対象値とcompound IDを示してRun fail |
| Description 1件失敗 | そのspaceをfailedとしてPhase 1 fail。黙ってspace数を減らさない |
| L4候補再記述がコスト上限超過 | Skill起動前に`needs_design_review`。候補capを自動拡大せず、生成件数・選択件数・予定Description行数・cost class別行数・cost unitsを保存 |
| fragmentation個別失敗 | exclusion tableへ理由付きで続行。class全体0件ならPhase 3依存nodeをnot-applicableではなくfail |
| candidate標本不足 | candidate status=`not_testable`で続行。p/qを捏造しない |
| statistic非有限・分散0 | 文書指定の境界処理（L2b p=1等）または`not_testable`。例外を握り潰さない |
| permutation参加率<50% | 結果を保存し `needs_design_review`。自動報告へ進めない |
| worker失敗 | task keyとtracebackを記録。同じseedで1回再試行後node fail |
| SQLite/CSV atomic commit失敗 | node fail。部分Artifactを正本manifestへ載せない |
| Local LLM schema違反・timeout・process失敗 | 同一論理callを最大2回再試行。失敗Findingはnarrativeなしで続行し、論理call失敗率が `llm.max_failure_fraction`（既定20%）を超えた場合だけPhase fail。fallback文章は生成しない |
| citation不一致 | Phase 6 fail。draftを保持し自動修正しない |
| K未達 | scoring結果を保持し `needs_design_review`。θを変更しない |

skip と failure を区別する。仕様上の最小 n 不足は候補単位の `not_testable`、必要入力やalgorithmの失敗はnode failureとする。

## 9. 並列化と決定性

| 単位 | 実装 |
|---|---|
| Description × compound batch | Skillごとのprocess。D019等の排他的高コスト設定をcatalogに宣言 |
| distance / context | spaceごとのprocess。距離行列をk間で共有 |
| fragmentation | compound chunk。worker shardをcoordinatorがstable merge |
| permutation | candidate chunk × iteration range。seedはtask順から独立 |
| lens | candidate key chunk。family BHだけcoordinatorで逐次 |
| scoring | Finding chunk。rank/mergeだけ逐次 |
| deep dive | Finding間並列、Finding内queue逐次 |
| report | component narrativeは並列可、最終検証とreport assemblyは逐次 |

Windowsを含むため multiprocessing は `spawn` を前提とし、module import時にpoolを作らない。RDKit objectをprocess間で渡さず、canonical SMILESまたはserialized binaryを渡す。NumPy distance matrixはread-only memory mapで共有する。

出力順は常に stable key sort。workerは共通CSV/SQLiteへ書かず個別 shardへ書き、coordinatorが検証・mergeする。これによりworker数1とNでbyte-identicalな決定論Artifact（timestamp等監査metadataを除く）を要求する。

## 10. テスト仕様

### 10.1 単体

- `permute_within_blocks`: 欠測、null label、singleton保持、block内multiset不変、参加率
- p値の+1/+1、alternative3種、B=0拒否
- BH: known vector、tie、NaN除外、family分離
- block bootstrap: scaffold一括再抽出、化合物単位になっていないこと
- λ: 対象自身の除外、zero variance、近傍不足
- fragmentation 3クラス、dummy label正規化、constant key順序
- 環末端でring側/remaining側がdummy数同一でも原子indexで正しく判定
- N=1/2/3/4/N≥5、ambiguous mapping、全size境界
- same series/same fragment複数compoundの1観測化
- context ID、distance、dedup connected component代表選択
- RFC 8785 hash入力、ID再現性、意図的な短縮hash衝突のfail-fast
- translation fold leakage防止、AUC境界0.70
- 各 lens statistic と境界条件
- L1b帰無でmembership/distance固定かつ同サイズsubsetを作らないこと、L2a crossing pair除外
- score clip、E_raw=0、lower-is-better方向
- duplicate Finding merge、tie-break
- T01の全機械軸、T01〜T10 parameter schema、deep-dive budget、T05/T06特殊状態、連続INCONCLUSIVE、REFUTED停止
- citation numeric tolerance、missing row、hash不一致

### 10.2 契約

- 全 JSON schema のvalid/invalid fixture
- 各 Skill request role、manifest、stdout 1 JSON契約
- Finding必須5要素、entities必須、Endpoint配列長1
- Artifact path traversal拒否、sha256照合、CSV column順
- catalogとfilesystemの双方向一致、全 SkillのPixi manifest/lock存在
- `install_into_project.py` dry-run、非上書き、obsolete検出

### 10.3 回帰・統合

- `make_synthetic_dataset()` で terminal/linker/ring の全クラス成立
- planted L2b consistent effect とseries varianceを検出し、null dataでFPR確認
- planted L5 sign flip、L1b flat subset、L7 reversed ranking
- L1a/L3/L6がFindingを生成しないこと
- Phase 1→6 small fixture end-to-end、Runtime resume、worker数1/N一致
- LLMはfixture commandを使い、schema違反・timeout・引用幻覚を再現。論理call失敗率20%以下/超過の境界と、引用不一致が1件でPhase failする別経路を確認

### 10.4 較正再現

| 項目 | 期待 | test gate |
|---|---:|---|
| L2b enrichment | >1.5 | 本番series内帰無で判定。段階6停止点 |
| L5 enrichment | >1.5 | 本番Murcko block帰無で判定 |
| L1b enrichment | 1.1〜1.8 | 本番Murcko block帰無で判定 |
| L3 / L6 enrichment | 0.85〜1.15 | 診断値を計算した場合だけ確認。Findingは作らない |
| TERM/RING/LINK pair | 9,548 / 1,579 / 436 | ±10%。RINGは各constant fragmentへのsize制約で減りうるため差分を併記 |
| `calibration_scope` context count | 270 | ±20%。全context数は別指標として併記 |
| translation AUC median | 0.96 | ≥0.90 |
| L5 block null | 約148 against observed 325 | 診断用参照値。全体null約3と取り違えず、block nullの方が明確に大きいことを確認 |

較正dataはrepositoryへ持ち込まず、pathを環境変数/Run requestで与える。test outputはaggregate onlyとしcompound IDや構造をCI logへ出さない。

## 11. 段階別完了条件

| 段階 | 完了条件 |
|---|---|
| 0 | 指定資産をArchiveへ退避、ignore、保持対象確認 |
| 1 | schemas/catalog/Endpoint契約、contract tests green |
| 2 | Description全18件のcache hit/miss統合、距離Artifact |
| 3 | stat-core unit/regression、L5 50倍過大評価検知fixture |
| 4 | 3クラス synthetic tests、canonical DB、pair count calibration |
| 5 | context/dedup/translation、`calibration_scope`件数とAUC calibration |
| 6 | L2b本番enrichment >1.5と診断差分の報告後に停止 |
| 7 | L5→L1b→L2a→L7→L4、lens別 tests |
| 8 | score/merge/K判定、全候補保持 |
| 9 | T01〜T10、budget/state/citation付きsummary |
| 10 | entity graph、引用検証、全lens calibration |
| 11 | Runtime lease/resume/audit、installer/verifier |

## 12. 実装見積もり

詳細仕様レビュー・較正data実行待ちを除く、1名相当の実装/テスト工数。確認事項18件の回答を反映済みで、既存Description資産がそのまま動く前提。

| 段階 | 見積もり（人日） | 主な変動要因 |
|---|---:|---|
| 0 仕分け | 0.5（完了） | — |
| 1 モデル・契約 | 4〜6 | Finding/MPO schema粒度 |
| 2 表現生成 | 4〜7 | 既存18 Skillの互換修正 |
| 3 統計基盤 | 6〜9 | block帰無、決定性・並列化 |
| 4 Fragment engine | 9〜14 | N-cut対応、Similar core移植 |
| 5 文脈構築 | 7〜10 | 全Description距離、translation |
| 6 L2b＋停止検証 | 6〜9 | 本番較正差分調査 |
| 7 残りlens | 18〜28 | L2a/L5/L1b/L7、特にL4 |
| 8 scoring | 5〜8 | レンズ別残差化 |
| 9 deep dive | 10〜16 | T01〜T10、Local LLM統合 |
| 10 統合・報告 | 6〜9 | 引用validator、narrative再試行 |
| 11 Runtime | 9〜14 | Phase境界レビュー、resume/lease |
| 全体統合・installer・較正 | 7〜11 | 実data実行時間と差分原因 |
| **合計** | **90〜141人日** | 約18〜28週（1名相当） |

段階6までの最初の停止点は **36.5〜55.5人日**。多コア計算資源はwall-clockを短縮するが、実装・レビュー工数には含めない。L4を含むT01〜T10の全項目が0.2.1対象であり、完了条件から除外しない。

## 13. 回答反映状況と残るレビュー点

Q-001〜Q-018は全件反映済みであり、実装開始を妨げる未回答事項はない。再レビューでは、回答そのものを再審議するのではなく、次の実装者決定が設計意図に沿うかを確認する。

1. SHA-256先頭16桁を使う永続IDのcanonical入力定義
2. T01〜T10の最小n、統計量、BH family、特殊判定（特にT05/T06/T09/T10）
3. Local LLM論理call失敗率の既定値20%
4. Hammett TSVの出典・license・version管理方法

実装順は実装計画書5章から変更しない。段階6でL2b本番enrichmentと差分を報告し、明示承認を得るまで段階7へ進まない。実装計画書9章の既出5件は、指定された時期に別途確認する。
