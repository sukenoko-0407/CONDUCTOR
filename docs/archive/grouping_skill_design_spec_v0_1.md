# Grouping Skill 設計仕様書 v0.1

## 0. 目的

本仕様書は、Claude Code上で動作する **Grouping Skill** を実装するための設計仕様である。

ここでいうGroupingとは、AI創薬SAR解析において、入力CSV中の化合物群を後続のLBDD/ML/SBDD/統合解釈で利用可能な比較単位へ整理する処理である。

本Skillは、以前の設計文書で `Context/Group整理Agent` と呼んでいた機能を、Claude Code用の **Skill** として単独実装するものである。

実装担当Agentは、本仕様書に従って以下を作成する。

```text
.claude/skills/grouping/SKILL.md
.claude/skills/grouping/scripts/*.py
.claude/skills/grouping/config/default_grouping_config.json
.claude/skills/grouping/schemas/*.json
.claude/skills/grouping/examples/*
```

---

## 1. Claude Code Skillとしての前提

### 1.1 Skillの配置

Project Skillとして以下に配置する。

```text
.claude/skills/grouping/SKILL.md
```

Claude Codeでは、Project Skillは `.claude/skills/<skill-name>/SKILL.md` として配置される。Skill本体は `SKILL.md` であり、補助スクリプトやテンプレートは同一Skillディレクトリ配下に置く。

推奨ディレクトリ構成:

```text
.claude/skills/grouping/
  SKILL.md
  README.md
  config/
    default_grouping_config.json
  schemas/
    group_registry.schema.json
    group_membership.schema.json
    group_relations.schema.json
    selected_groups.schema.json
    grouping_manifest.schema.json
  scripts/
    run_grouping.py
    detect_columns.py
    standardize_compounds.py
    build_human_groups.py
    build_murcko_groups.py
    build_mcs_groups.py
    build_similarity_groups.py
    build_meta_groups.py
    select_groups.py
    export_graph_packet.py
    grouping_io.py
    grouping_models.py
  examples/
    minimal_input.csv
    input_with_grouping_columns.csv
    grouping_config_example.json
    expected_outputs/
```

### 1.2 Skillの基本方針

`SKILL.md` は長大な実装詳細を書きすぎず、Claude Codeが迷わずに以下を実行できるナビゲーション文書とする。

```text
1. 入力CSVを確認する
2. Molecule ID列とSMILES列を推定する
3. ユーザ指定のGrouping列があるか確認する
4. Pythonスクリプトを実行する
5. 出力artifactを確認する
6. 不明点がある場合だけユーザに質問する
```

複雑な判定や計算は `scripts/` 配下のPythonに寄せる。

---

## 2. Skill名称

```text
Operation name: Grouping
Skill directory name: grouping
Explicit command: /grouping
```

---

## 3. 本Skillの責務

Grouping Skillは以下を行う。

```text
入力CSVの列推定
Molecule ID列の特定
SMILES列の特定
任意の活性列・Wet/Virtual列・Grouping列の検出
SMILES標準化と構造QA
特殊構造の検出・除外
人間指定Groupingの取り込み
Murcko scaffold group生成
Frequent MCS group生成
Structural similarity group生成
必要に応じたMeta-group生成
Group registry / membership / relation artifactの生成
Group graph可視化用packetの生成
後段解析に渡すselected groupsの生成
```

本Skillは以下を行わない。

```text
MMP解析
Activity Cliff解析
ML要因解析
SBDD/ProLIF/Pose解析
統合解釈
HTMLレポート生成
新規化合物提案
```

---

## 4. 入力CSVの前提

### 4.1 最小前提

入力CSVには少なくとも以下に相当する列が含まれる。

```text
Molecule ID
SMILES
```

ただし、列名は固定しない。

例:

```text
ID
Compound_ID
Molecule ID
MolID
Name
No
CID
Structure
SMILES
smiles
canonical_smiles
Mol
```

したがって、Skillは列名を固定前提にせず、自律的に推定する。

### 4.2 任意列

入力CSVには以下が含まれる可能性がある。

```text
activity_type
activity_value
activity_unit
pIC50
IC50
is_virtual
human_series
human_scaffold
group
series
scaffold
project_group
r1_label
r2_label
r3_label
r4_label
registration_date
synthesis_date
assay_date
batch_id
```

ただし、これらは必須ではない。

---

## 5. CSV列推定の基本方針

### 5.1 自律推定を基本とする

Skillは、入力CSVを受け取ったら、まずPythonスクリプトで列候補を推定する。

主要スクリプト:

```text
scripts/detect_columns.py
```

このスクリプトは以下を出力する。

```text
detected_schema.json
column_detection_report.json
column_detection_warnings.json
```

### 5.2 ユーザに質問する条件

以下の場合のみ、Claude Codeはユーザに質問する。

```text
SMILES列候補が複数あり、どちらも高信頼で区別不能
SMILES列候補のRDKit valid率が低い
Molecule ID列候補が複数あり、どちらも同程度に妥当
Molecule ID列が見つからない
ユーザが「指定Groupingを使う」と言っているが該当列が不明
Grouping列候補が多数あり、意図が不明
CSV parseに失敗
```

質問は最小限にする。

例:

```text
SMILES列候補として `SMILES` と `Canonical_SMILES` が見つかりました。
どちらを使用しますか？
```

---

## 6. Molecule ID列の推定仕様

### 6.1 候補列名

以下の名前を高優先候補とする。

```text
compound_id
compoundid
compound id
molecule_id
moleculeid
molecule id
mol_id
molid
mol id
cid
id
name
compound
molecule
code
```

大文字小文字、空白、ハイフン、アンダースコアは正規化して比較する。

### 6.2 候補スコアリング

`detect_columns.py` は以下でスコアリングする。

```text
列名の一致度
欠損率の低さ
一意性の高さ
文字列らしさ
SMILESらしくないこと
数値連番のみではないこと
```

### 6.3 採択ルール

以下を満たす列をMolecule ID列として採用する。

```text
欠損率が低い
重複が少ない
列名スコアが高い
SMILES列候補ではない
```

ただし、数値連番しかない列でも、他に候補がなければID列として許容する。その場合はwarningを出す。

---

## 7. SMILES列の推定仕様

### 7.1 候補列名

以下の名前を高優先候補とする。

```text
smiles
canonical_smiles
canonical smiles
isomeric_smiles
isomeric smiles
structure
mol_smiles
molecule_smiles
```

### 7.2 RDKit valid率による判定

列名だけではなく、実際にRDKitでparseできる割合を用いる。

推奨判定:

```text
valid_smiles_ratio >= 0.85:
  high confidence

0.50 <= valid_smiles_ratio < 0.85:
  medium confidence

valid_smiles_ratio < 0.50:
  low confidence
```

### 7.3 採択ルール

以下を満たす列をSMILES列として採用する。

```text
列名スコアが高い
RDKit valid率が高い
空欄が少ない
Molecule ID列ではない
```

複数候補が同点の場合、ユーザに確認する。

---

## 8. ユーザ指定Groupingの扱い

### 8.1 基本方針

ユーザからGrouping指定がある可能性を前提とする。

例:

```text
Series列を使ってGroupingしてください。
human_seriesをグループとして使ってください。
Scaffold列とSubseries列をグルーピングに使ってください。
```

この場合、Claude Codeは指定列を優先して使用する。

### 8.2 ユーザ指定が明示されていない場合

Skillは入力CSV中にGrouping候補列があるかを推定する。

候補列名:

```text
group
grouping
series
subseries
scaffold
chemotype
core
core_id
cluster
class
family
human_series
human_scaffold
project_group
campaign
```

### 8.3 Grouping候補列の判定

以下を満たす列をGrouping候補とする。

```text
カテゴリカル列
ユニーク値数が多すぎない
欠損が少ない
Molecule ID列ではない
SMILES列ではない
活性値列ではない
```

目安:

```text
2 <= unique_value_count <= max(50, 0.5 * n_rows)
```

ただし、全行ユニークに近い列はGrouping列としない。

### 8.4 複数Grouping列

複数列を同時に使ってよい。

例:

```text
human_series
human_scaffold
subseries
```

各列は別々のHuman-defined Groupとして登録する。

複数列の組み合わせGroupは、デフォルトでは作らない。必要な場合はconfigで明示する。

```json
{
  "human_grouping": {
    "combine_columns": [
      ["human_series", "human_scaffold"]
    ]
  }
}
```

### 8.5 多重所属

1つのセルに複数Groupが含まれる可能性を許容する。

例:

```text
Series_A;Series_B
CoreX|R2_campaign
```

分割delimiter候補:

```text
;
|
,
```

ただし、CSV delimiterと衝突しないよう慎重に処理する。

---

## 9. Groupingの種類

本Skillは以下のGroup Builderを持つ。

```text
human_group_builder
murcko_group_builder
mcs_group_builder
similarity_group_builder
meta_group_builder
auto_rgroup_group_builder  # experimental / default OFF
```

### 9.1 Human Group

入力CSVまたはhuman_contextsファイル由来のGroup。

例:

```text
Series_A
CoreX_closeup
R2_campaign
```

### 9.2 Murcko Group

RDKitのBemis-Murcko scaffoldに基づくreference group。優先度は中〜低。

### 9.3 MCS Group

Wet化合物または全化合物に対するFrequent MCS coreに基づくgroup。

デフォルトではWet-only mining。

```json
{
  "mcs_group_builder": {
    "enabled": true,
    "include_virtual_in_mcs_mining": false,
    "min_mcs_heavy_atoms": 8,
    "min_mcs_fraction_of_smaller_molecule": 0.4,
    "min_unique_wet_compounds": 5,
    "min_pair_count": 3
  }
}
```

### 9.4 Similarity Group

Morgan fingerprint + Tanimoto similarityに基づく構造類似group。

初期実装では以下を推奨。

```text
Morgan radius=2
nBits=2048
Tanimoto similarity
threshold graph clustering or Butina clustering
```

### 9.5 Meta Group

類似・重複するGroupを破壊的に統合せず、上位Groupとして追加する。

例:

```text
Human Series A と MCS_CORE_014 が大きく重なる
MCS_CORE_014 と MCS_CORE_021 のcoreが類似
```

この場合、元Groupは保持し、Meta Groupを追加する。

### 9.6 Auto R-group-like Group

自動R-group風のgroup生成。

品質懸念があるため、default OFF。

```json
{
  "auto_rgroup_group_builder": {
    "enabled": false,
    "status": "experimental"
  }
}
```

---

## 10. Wet / Virtualの扱い

### 10.1 is_virtual列がある場合

`is_virtual` または類似列を検出し、以下へ正規化する。

```text
is_virtual = true / false
```

許容値例:

```text
true/false
1/0
yes/no
wet/virtual
measured/predicted
experimental/virtual
```

### 10.2 is_virtual列がない場合

すべてWet相当として扱う。

warningを出す。

```text
is_virtual column not found. All compounds are treated as Wet for grouping.
```

### 10.3 MCS mining

デフォルト:

```text
Wet-only MCS mining
```

ただし、configでVirtualを含める。

```json
{
  "mcs_group_builder": {
    "include_virtual_in_mcs_mining": true
  }
}
```

---

## 11. Activity列の扱い

Grouping Skillは活性解析を行わない。

ただし、以下のために活性列を検出してよい。

```text
group summary
selected groups prioritization
warnings
future downstream compatibility
```

検出対象:

```text
pIC50
IC50
activity_value
activity_type
activity_unit
```

IC50/pIC50正規化機能は持ってよいが、Grouping定義そのものには原則使わない。

活性情報を使うのはGroup prioritizationまでとする。

---

## 12. 出力Artifact

出力ディレクトリはデフォルトで以下。

```text
outputs/grouping/
```

主要出力:

```text
compounds_master.csv
excluded_compounds.csv
group_registry.json
group_membership.csv
group_relations.json
selected_groups.json
group_summary.json
group_graph_packet.json
grouping_warnings.json
grouping_manifest.json
detected_schema.json
column_detection_report.json
```

互換性のため、必要に応じて以下の別名も出力する。

```text
context_registry.json       # alias of group_registry.json
context_membership.csv      # alias of group_membership.csv
context_relations.json      # alias of group_relations.json
selected_contexts.json      # alias of selected_groups.json
```

後続ドキュメントでは `Context` と呼ぶことがあるが、Skill実装上の操作名称は `Grouping` とする。

---

## 13. group_registry.json Schema概要

各Groupの定義を保持する。

例:

```json
{
  "group_id": "GRP_MCS_001",
  "group_label": "MCS_CORE_001",
  "group_type": "frequent_mcs_core",
  "group_source": "mcs_group_builder",
  "source_column": null,
  "activity_blind": true,
  "definition": {
    "method": "mcs",
    "mcs_smarts": "...",
    "parameters": {
      "min_mcs_heavy_atoms": 8
    }
  },
  "compound_count": 24,
  "wet_count": 22,
  "virtual_count": 2,
  "quality": {
    "status": "passed",
    "exploratory": false
  }
}
```

---

## 14. group_membership.csv Schema概要

どの化合物がどのGroupに属するかを保持する。

```csv
group_id,compound_id,membership_source,membership_reason
GRP_HUM_001,Cpd001,human_column,human_series=Series_A
GRP_MCS_001,Cpd001,mcs,contains_MCS_CORE_001
GRP_MURCKO_003,Cpd001,murcko,scaffold_hash=...
```

1化合物が複数Groupに属してよい。

---

## 15. group_relations.json Schema概要

Group同士の関係を保持する。

関係タイプ:

```text
overlaps_with
subset_of
similar_core_to
derived_from
meta_group_of
same_source_as
```

例:

```json
{
  "relation_id": "REL_0001",
  "source_group_id": "GRP_HUM_001",
  "target_group_id": "GRP_MCS_001",
  "relation_type": "overlaps_with",
  "metrics": {
    "jaccard_overlap": 0.72,
    "shared_compound_count": 18
  }
}
```

---

## 16. selected_groups.json Schema概要

後段解析に優先的に渡すGroupを保持する。

```json
{
  "selected_group_id": "GRP_MCS_001",
  "selection_reason": [
    "sufficient_wet_count",
    "high_interpretability",
    "high_local_sar_signal_score"
  ],
  "priority": "high",
  "enabled_for_downstream": true
}
```

Selectionは単一スコアでなく、複数軸で行う。

---

## 17. Group ID命名規則

内部IDはASCII固定。

```text
GRP_HSER_001      # human_series
GRP_HSCF_001      # human_scaffold
GRP_HUM_001       # human_context / user-defined group
GRP_MCS_001       # MCS group
GRP_MURCKO_001    # Murcko group
GRP_SIM_001       # Similarity group
GRP_META_001      # Meta group
GRP_ARG_001       # Auto R-group-like group
```

ラベルは別に保持する。

```text
group_label = "Series A"
```

---

## 18. Python Scripts 詳細

### 18.1 run_grouping.py

全体実行のentry point。

CLI:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/run_grouping.py \
  --input data/input.csv \
  --outdir outputs/grouping \
  --config ${CLAUDE_SKILL_DIR}/config/default_grouping_config.json
```

オプション:

```text
--id-column
--smiles-column
--grouping-columns
--activity-column
--is-virtual-column
--include-virtual-in-mcs
--skip-mcs
--skip-similarity
--write-context-aliases
```

### 18.2 detect_columns.py

列推定を行う。

出力:

```text
detected_schema.json
column_detection_report.json
column_detection_warnings.json
```

### 18.3 standardize_compounds.py

SMILES標準化、特殊構造除外、canonical SMILES生成を行う。

### 18.4 build_human_groups.py

CSV列またはhuman_contextsファイル由来のGroupを生成する。

### 18.5 build_murcko_groups.py

Murcko scaffold groupを生成する。

### 18.6 build_mcs_groups.py

Frequent MCS groupを生成する。

MCSは計算負荷が高いため、timeoutとcacheを必須にする。

### 18.7 build_similarity_groups.py

Morgan fingerprint / Tanimotoに基づくSimilarity groupを生成する。

### 18.8 build_meta_groups.py

Group同士の重複・類似性からMeta group候補を生成する。

### 18.9 select_groups.py

後段解析へ渡すselected groupsを選ぶ。

### 18.10 export_graph_packet.py

HTMLレポートや可視化用のgraph packetを生成する。

---

## 19. Config仕様

デフォルトConfig:

```json
{
  "column_detection": {
    "ask_user_when_ambiguous": true,
    "min_smiles_valid_ratio": 0.85
  },
  "input_columns": {
    "id_column": null,
    "smiles_column": null,
    "is_virtual_column": null,
    "activity_column": null,
    "grouping_columns": []
  },
  "group_builders": {
    "human_group_builder": {
      "enabled": true
    },
    "murcko_group_builder": {
      "enabled": true,
      "priority": "reference"
    },
    "mcs_group_builder": {
      "enabled": true,
      "include_virtual_in_mcs_mining": false,
      "min_mcs_heavy_atoms": 8,
      "min_mcs_fraction_of_smaller_molecule": 0.4,
      "min_unique_wet_compounds": 5,
      "min_pair_count": 3,
      "timeout_seconds_per_pair": 5
    },
    "similarity_group_builder": {
      "enabled": true,
      "fingerprint": "morgan",
      "radius": 2,
      "n_bits": 2048,
      "similarity_threshold": 0.7
    },
    "meta_group_builder": {
      "enabled": true,
      "max_meta_groups": 20
    },
    "auto_rgroup_group_builder": {
      "enabled": false,
      "status": "experimental"
    }
  },
  "outputs": {
    "write_context_aliases": true,
    "write_graph_packet": true
  }
}
```

---

## 20. SKILL.md実装内容

実装担当Agentは以下の内容で `SKILL.md` を作ること。

### 20.1 Frontmatter

```yaml
---
name: grouping
description: Detect molecule ID and SMILES columns from SAR CSV files, ingest optional user-defined grouping columns, and generate grouping artifacts such as group_registry, membership, relations, selected groups, and graph packets for downstream SAR analysis.
allowed-tools: Read Write Bash Grep Glob
---
```

`description` は自動起動に使われるため、必ず具体的に書く。

### 20.2 本文に含めるべき指示

`SKILL.md` 本文には以下を入れる。

```text
When to use
Inputs
Outputs
Column detection rules
Ask-user policy
Execution command
Validation checklist
Do-not-do list
```

### 20.3 SKILL.mdの要約実行手順

```text
1. Locate the input CSV.
2. Run detect_columns.py unless columns are explicitly specified.
3. If ID or SMILES columns are ambiguous, ask the user.
4. Check whether user-defined grouping was requested.
5. If requested, identify the grouping column(s); ask only if ambiguous.
6. Run run_grouping.py with detected or user-specified columns.
7. Verify required artifacts exist.
8. Summarize generated groups and warnings.
```

---

## 21. Ask-user Policy

ユーザに質問してよいのは以下に限定する。

```text
ID列が不明
SMILES列が不明
複数の高信頼SMILES列がある
ユーザ指定Grouping列が不明
CSV parseに失敗
RDKit valid率が極端に低い
```

それ以外は、warningを出して処理を継続する。

---

## 22. Output Summary

Skill実行後、Claude Codeはユーザに以下を短く報告する。

```text
input CSV
detected molecule ID column
detected SMILES column
detected grouping columns
number of compounds
number of excluded compounds
number of generated groups by type
output directory
major warnings
```

例:

```text
Grouping completed.
Molecule ID column: Compound_ID
SMILES column: SMILES
User grouping columns: human_series, scaffold_class
Compounds processed: 184
Groups generated: human=6, murcko=14, mcs=22, similarity=9, meta=3
Outputs: outputs/grouping/
Warnings: 3 compounds excluded due to invalid SMILES.
```

---

## 23. Acceptance Criteria

実装完了条件:

```text
Minimal CSV with arbitrary ID/SMILES column names can be processed.
SMILES column is inferred using RDKit valid ratio.
Molecule ID column is inferred with uniqueness and name heuristics.
User-defined grouping columns can be detected or specified.
Human groups are correctly written to group_registry and group_membership.
Murcko groups are generated.
MCS groups are generated with threshold and timeout.
Similarity groups are generated.
Group relations are generated.
Selected groups are generated.
Context alias outputs are written when enabled.
All required outputs pass schema validation.
Skill can be invoked as /grouping.
SKILL.md references scripts using ${CLAUDE_SKILL_DIR}.
```

---

## 24. Tests to Implement

### 24.1 Minimal input test

Input:

```text
ID,SMILES
Cpd001,CCO
Cpd002,c1ccccc1
```

Expected:

```text
ID detected as Molecule ID
SMILES detected as SMILES
compounds_master.csv generated
group artifacts generated
```

### 24.2 Arbitrary column names test

Input:

```text
Molecule Code,Structure String
A001,CCO
A002,c1ccccc1
```

Expected:

```text
Molecule Code detected as ID
Structure String detected as SMILES if RDKit valid ratio high
```

### 24.3 Grouping column test

Input:

```text
compound_id,smiles,Series,Scaffold
Cpd001,CCO,A,S1
Cpd002,CCN,A,S1
Cpd003,c1ccccc1,B,S2
```

Expected:

```text
Series and Scaffold detected as grouping candidates
human groups generated
```

### 24.4 Ambiguous SMILES test

Two SMILES-like columns.

Expected:

```text
detected_schema marks ambiguity
Skill asks user
```

### 24.5 Invalid SMILES test

Expected:

```text
invalid rows excluded or flagged
excluded_compounds.csv written
warnings written
```

### 24.6 Virtual flag test

Expected:

```text
is_virtual normalized
MCS mining default Wet-only
```

---

## 25. Implementation Notes

### 25.1 Python dependency assumptions

Required:

```text
python >= 3.10
pandas
numpy
rdkit
networkx
scikit-learn
```

Optional:

```text
tqdm
pydantic
jsonschema
```

### 25.2 Performance constraints

MCS can be expensive.

Implement:

```text
pairwise timeout
cache
max pair count warning
Wet-only default
configurable include_virtual flag
```

### 25.3 Determinism

Where possible, output should be deterministic.

```text
sort group IDs
sort compound IDs
fixed random_state for clustering
record config and versions in manifest
```

---

## 26. Manifest

`grouping_manifest.json` must record:

```json
{
  "skill_name": "grouping",
  "skill_version": "0.1.0",
  "input_file": "data/input.csv",
  "detected_columns": {
    "id_column": "Compound_ID",
    "smiles_column": "SMILES"
  },
  "config_file": "default_grouping_config.json",
  "outputs": [
    "group_registry.json",
    "group_membership.csv"
  ],
  "warnings": [],
  "created_at": "ISO-8601 timestamp"
}
```

---

## 27. Do-not-do List

Grouping Skill must not:

```text
make SAR conclusions
generate hypotheses
run LBDD operators such as MMP or Activity Cliff
train ML models
interpret activity mechanisms
generate HTML reports
modify the input CSV in place
discard ambiguous rows without recording them
ask the user unnecessary questions
```

---

## 28. Summary for Implementation Agent

Build a Claude Code Project Skill named `grouping`.

The Skill must:

```text
autonomously infer Molecule ID and SMILES columns
ingest optional user-defined grouping columns
ask the user only when ambiguity cannot be resolved
run Python scripts bundled in the Skill directory
generate group registry, membership, relations, selected groups, graph packet, warnings, and manifest
support both group_* artifact names and context_* compatibility aliases
remain independent from LBDD, ML, SBDD, and Integrated Interpretation agents
```

The implementation should prioritize robustness, deterministic artifacts, and clear warning behavior over aggressive over-inference.
