# CONDUCTOR 0.2.1 実装詳細仕様書

Status: **レビュー待ち。実装未着手。**  
作成日: 2026-09-17  
正本: [`CONDUCTOR_0.2.1_implementation_plan.md`](CONDUCTOR_0.2.1_implementation_plan.md)

## 0. この文書の扱い

本書は実装計画書を、ファイル配置、公開インターフェース、Artifact、型、擬似コード、失敗時挙動、並列化、テストへ落としたレビュー案である。

優先順位は次のとおりとする。

1. 実装計画書
2. `design/calibration_results.md`
3. 本書（レビュー承認後）
4. その他の design 文書
5. 診断モジュール（較正値の再現と既知バグの参照実装）

[`CONDUCTOR_0.2.1_implementation_questions.md`](CONDUCTOR_0.2.1_implementation_questions.md) の `blocking` は、本書内で `TBD(Q-xxx)` と記す。承認前にコードを書かない。実装計画書9章の5件は同書の時期に確認し、本書では既定案だけを保持する。

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
├── cs-compute-description-*/       # 現存 D001〜D016, D019, D020 を保持。Q-002
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
| 10 | Local LLM provider の恒久失敗 |

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

確定パラメータは `CONDUCTOR_modules/config/defaults.yaml` に置き、コードに埋め込まない。Runtime は defaults、project config、Run override の順に deep merge し、未知 key を拒否して `resolved_config.yaml` を Run に保存する。

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

1 Run は `endpoint_id` を1個だけ選ぶ。内部統計には `oriented_value = value if higher_is_better else -value` を使う案を採るが、Q-012 の承認が必要。raw、transformed、oriented を別列で保持し、表示は transformed scale を使う。欠測は空文字として保存し補完しない。

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
```

ID は実装計画書の `CL|...`、`QT|...`、`SC|...` を使う。hash と安定採番は Q-003 で確定する。membership は compound ID の long table とし、配列位置を永続 ID にしない。

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

canonical 方向は Q-008 で確定するまで `TBD`。同一 series・同一 fragment に複数 compound がある場合、Endpoint 平均を `FragmentObservation` 1件とし、元 compound IDs は配列 JSON として証拠表に残す。

### 4.4 Finding

Finding は JSON object 1件を1行にした `findings.jsonl` で保存し、各行を `finding.schema.json` で検証する。提案 schema は次の形とするが Q-003 承認前は固定しない。

```yaml
finding_id: F000042
finding_key: sha256:...
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

Description Database は既存 `description_database.py` の cache plan、同一 ID・異構造 fail-fast、audit invalidate を保持する。Description Skill の生出力を変更せず、Phase 1 adapter が `feature_spaces.json` へ登録する。

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

L1b の追加ランダム subset、L2b の較正互換は Q-004/Q-005 で確定する。

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

欠測診断の具体判定は Q-015 の案を interface の背後へ隔離する。解析対象 Endpoint が `selection_biased` でも除外せず、全 Finding に label を伝播する。

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

Q-002 が解決するまで capability 母集団を固定しない。

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

環 N=3/4 mapping と N-cut constant size は Q-007。N≥5 は除外件数を記録する。変換3クラスは table、統計 family、Finding、表示を混ぜない。

#### Pair と fragment table

```text
group accepted fragmentations by (class, constant_key)
deduplicate duplicate (compound_id, variable_smiles)
for each unordered member pair with different variable:
    orient by approved canonical rule
    create stable pair and transformation keys
for each series with >=2 distinct variables:
    group same variable's compounds
    endpoint_mean = mean(finite Endpoint values)
    emit one FragmentObservation
```

MMP canonical DB と Similar core の移植元は Q-001。Similarity class は `exact / radius2 / radius1 / mcs_mapped`。mapping 不成立・coverage不足・ambiguous は除外理由を残す。

#### Cliff 起点

structural space だけを対象に、Tanimoto≥0.75 かつ `|oriented delta|≥0.42` の pair を列挙し、3クラス変換抽出を試す。抽出成功した transformation は網羅列挙集合へ union する。Cliff pair 自身は Finding にしない。非構造空間は λ の診断だけで Cliff pair を列挙しない。

### 7.5 段階5: 文脈構築

#### クラスタ

```text
for each Description space in parallel:
    load or compute distance matrix once
    for k in [10, 20, 40]:
        average-linkage agglomerative clustering(precomputed distance)
        emit CL|space_id|k<k>|c<stable_cluster_index>
```

cluster index は、各 cluster の最小 compound ID、次に全 member ID の hash で安定ソートしてから採番する。fingerprint は `1-Tanimoto`、descriptor は全欠損・定数列を除外、列中央値補完、z標準化後の Euclidean。別 clustering 手法を追加しない。

#### 分位・骨格・活性域

- Tier 1 feature ごとに raw feature scale の q25/q50/q75 以下を `QT|feature|qNN` とする。以上側を別 context にしない
- Murcko/MCS/BRICS/RECAP context を構造依存 Artifact として作る。Endpoint valid n≥5 は Run ごとの eligibility 列で判定する
- 活性域は診断行だけに使い、L1b/L2/L5 の condition に渡さない
- 270件受け入れの scope は Q-006

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

Tier 3 cluster について、Tier 1 features だけを説明変数とする L2 正則化 logistic regression を3-fold stratified CVで評価する。fold 内で欠測補完・標準化を fit し、leakage を防ぐ。AUC<0.70 は `untranslatable`。AUC≥0.70 は全データで再fitし、係数と方向を保存する。説明文は Q-018 の承認までは固定テンプレート案とする。

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
    test context variance when m >= 3:
        v = sample variance(residuals)
    null:
        permute Endpoint within each series
        recompute collapse, means, residuals and statistic
```

問い1は両側、問い2は上側。terminal と ring を別 family とし、混ぜない。fragment が2 seriesなら問い1のみ、3以上なら両方。各問いは独立 test record とし、同一 fragment の両方が通過した場合は1 Finding内に2 testsを持たせる案とする。

段階6完了後、必ず停止する。本番系列内検定に加え、Q-005 で承認された互換 mode で enrichment 2.07 / 2.31 / 2.54 の±30%を確認し、pair数、context数、参加率、候補数、差分原因を報告する。未達なら段階7へ進まない。

### 7.7 段階7: 残りの lens

#### L5

axis ID ごとに context pair を作る。同一 clustering の cluster間、同一 feature の quantile間など、異なる axis は比較しない。各文脈で Tier 1/2 feature と Endpoint の Pearson r を計算し、双方 `|r|≥0.3` かつ逆符号を候補とする。観測 statistic は Fisher z 差。本番 p 値は Q-009 の決定に従う。Global r を証拠として保存する。

#### L1b

Tier 1/2 space と representative context の各組について、context内各化合物を同じ context内の k=10 最近傍から予測し、

```text
lambda = 1 - mean((observed - neighbor_prediction)^2) / global_endpoint_variance
```

を求める。対象化合物自身を近傍・λ計算に含めない。有効 n<5、global variance≤0、近傍不足は候補外。`lambda≥0.5` は診断ゲートであり、有意性は Q-004 の帰無分布から求める。L1a は全空間の min λ を診断表へ出すだけで Finding を作らない。

#### L2a

3 pair以上の transformation だけを対象に、representative contextごとの平均シフトと分散縮小を独立 test とする。文脈内外の pair定義、delta方向、statistic は Q-008。少なくとも `n_in≥3` と `n_out≥3` を満たさない候補は検定しない。許容性は `|median delta|<0.28` かつ分散≤0.02で labelする。

#### L7

同一 R基の重複 compound を平均へ集約し、共通 R基5個以上の series pairだけを列挙する。`|Spearman ρ|≥0.5` を効果ゲートとする。p値・主効果・3 Finding型は Q-011。帰無では系列内 R基 label を並べ替える。

#### L4

L2 canonical transformation DB が完成してから最後に実装する。最低条件は平坦な近傍、到達経路1本以上、未観測構造、RDKit sanitize成功。領域生成、信頼下限、密度、path長は Q-010。仕様確定前に placeholder candidate generator を本番へ入れない。

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
    oriented scale on Q-012 approval
composite:
    non_triviality * actionability * frontier_relevance
```

`n_candidates_in_lens` は最終 B=1000 と BH を完了した候補数とする。q tie は平均順位ではなく stable ordinal rank案とし、レビューで確認する。`E_adj` は Q-013。

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

状態規則は実装計画書9-1をそのまま pure function にする。LLMに状態を返させない。T01〜T10 executable contract は Q-014、LLM provider は Q-016、EWG/EDG は Q-017。プロジェクト SMARTS が無くても機械分割軸で動作する。

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
```

同じ `(node_id, input_hashes, config_hash, code_version)` の成功 Artifact は再利用可能。lease token と attempt ID が一致しない late event は監査ログへ隔離し正本状態を変更しない。Phase boundary/checkpoint は実装計画書9章の既出確認事項として別レビューする。

## 8. エラー処理

| 状況 | 挙動 |
|---|---|
| request/config/schema不正 | node開始前に fail、出力Artifactなし |
| 同一 compound ID・異構造 | Run fail-fast。自動修正しない |
| invalid SMILES | compounds表に失敗を記録。対象化合物を構造計算から除外し、件数をwarning。全件無効ならfail |
| Endpoint transform domain不正 | 対象値とcompound IDを示してRun fail |
| Description 1件失敗 | そのspaceをfailedとしてPhase 1 fail。黙ってspace数を減らさない |
| fragmentation個別失敗 | exclusion tableへ理由付きで続行。class全体0件ならPhase 3依存nodeをnot-applicableではなくfail |
| candidate標本不足 | candidate status=`not_testable`で続行。p/qを捏造しない |
| statistic非有限・分散0 | 文書指定の境界処理（L2b p=1等）または`not_testable`。例外を握り潰さない |
| permutation参加率<50% | 結果を保存し `needs_design_review`。自動報告へ進めない |
| worker失敗 | task keyとtracebackを記録。同じseedで1回再試行後node fail |
| SQLite/CSV atomic commit失敗 | node fail。部分Artifactを正本manifestへ載せない |
| Local LLM schema違反 | Q-016の回数だけ再試行。fallback文章を生成しない |
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
- translation fold leakage防止、AUC境界0.70
- 各 lens statistic と境界条件
- score clip、E_raw=0、lower-is-better方向
- duplicate Finding merge、tie-break
- deep-dive budget、状態、連続INCONCLUSIVE、REFUTED停止
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
- planted L2b consistent effect とcontext varianceを検出し、null dataでFPR確認
- planted L5 sign flip、L1b flat subset、L7 reversed ranking
- L1a/L3/L6がFindingを生成しないこと
- Phase 1→6 small fixture end-to-end、Runtime resume、worker数1/N一致
- LLMはfixture commandを使い、schema違反・timeout・引用幻覚を再現

### 10.4 較正再現

| 項目 | 期待 | test gate |
|---|---:|---|
| L2b enrichment | 2.07 / 2.31 / 2.54 | ±30%、段階6停止点。Q-005 protocol |
| L5 enrichment | 2.19 / 1.82 / 1.81 | ±30% |
| L1b enrichment | 1.45 / 1.43 / 1.29 | ±30% |
| TERM/RING/LINK pair | 9,548 / 1,579 / 436 | ±10%、Q-007差分併記 |
| context count | 270 | ±20%、Q-006 scope |
| translation AUC median | 0.96 | ≥0.90 |
| L5 block null | 約148 against observed 325 | 全体null約3と取り違えない |

較正dataはrepositoryへ持ち込まず、pathを環境変数/Run requestで与える。test outputはaggregate onlyとしcompound IDや構造をCI logへ出さない。

## 11. 段階別完了条件

| 段階 | 完了条件 |
|---|---|
| 0 | 指定資産をArchiveへ退避、ignore、保持対象確認 |
| 1 | schemas/catalog/Endpoint契約、contract tests green |
| 2 | 全承認Descriptionのcache hit/miss統合、距離Artifact |
| 3 | stat-core unit/regression、L5 50倍過大評価検知fixture |
| 4 | 3クラス synthetic tests、canonical DB、pair count calibration |
| 5 | context/dedup/translation、270 scopeとAUC calibration |
| 6 | L2b、本番＋互換enrichment報告後に停止 |
| 7 | L5→L1b→L2a→L7→L4、lens別 tests |
| 8 | score/merge/K判定、全候補保持 |
| 9 | T01〜T10、budget/state/citation付きsummary |
| 10 | entity graph、引用検証、全lens calibration |
| 11 | Runtime lease/resume/audit、installer/verifier |

## 12. 実装見積もり

レビュー・較正data実行待ちを除く、1名相当の実装/テスト工数。blocking仕様が確定し、既存Description資産がそのまま動く前提。

| 段階 | 見積もり（人日） | 主な変動要因 |
|---|---:|---|
| 0 仕分け | 0.5（完了） | — |
| 1 モデル・契約 | 4〜6 | Q-003、MPO schema粒度 |
| 2 表現生成 | 4〜7 | Q-002、既存Skillの互換修正 |
| 3 統計基盤 | 6〜9 | Q-004、決定性・並列化 |
| 4 Fragment engine | 9〜14 | Q-001/Q-007、Similar core移植 |
| 5 文脈構築 | 7〜10 | Q-006、全Description距離 |
| 6 L2b＋停止検証 | 6〜9 | Q-005、較正差分調査 |
| 7 残りlens | 18〜28 | Q-008〜Q-011、特にL4 |
| 8 scoring | 5〜8 | Q-012/Q-013 |
| 9 deep dive | 10〜16 | Q-014/Q-016/Q-017、Local LLM統合 |
| 10 統合・報告 | 6〜9 | 引用validator、narrative再試行 |
| 11 Runtime | 9〜14 | Phase境界レビュー、resume/lease |
| 全体統合・installer・較正 | 7〜11 | 実data実行時間と差分原因 |
| **合計** | **90〜141人日** | 約18〜28週（1名相当） |

段階6までの最初の停止点は **36.5〜55.5人日**。多コア計算資源はwall-clockを短縮するが、実装・レビュー工数には含めない。Q-010のL4を別releaseへ送る場合は全体から概ね6〜10人日減るが、現仕様では0.2.1対象なので除外しない。

## 13. レビューで確認する順序

1. Q-001〜Q-003（資産と段階1契約）
2. Q-004/Q-005（統計正当性と段階6停止判定）
3. Q-006/Q-007（受け入れ件数のscope）
4. Q-008〜Q-014（残りlens、scoring、deep dive）
5. non-blocking 4件と実装計画書9章の既出5件

承認後も実装順は実装計画書5章から変更しない。段階6で報告し、明示承認を得るまで段階7へ進まない。
