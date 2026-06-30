# RDKit Ligand Descriptor Generation Agent 実装設計仕様書

## 1. 目的

本仕様書は、Claude Code Agent が **RDKitを主エンジンとして Ligand-only descriptor / fingerprint を生成する Skill または Subagent** を迷わず実装できるようにするための設計仕様である。

対象は、社内で合成済み・活性評価済みの低分子化合物群である。入力は化合物IDおよびSMILESを含むCSVとするが、ID列名・SMILES列名は固定しない。Agentは列名と値の内容から自律的にID列・SMILES列を推定する。どうしても判定できない場合のみ、ユーザに確認する。

今回は **RDKitで生成可能なLigand-only特徴量のみを実装対象** とする。  
MOEで補完すべき特徴量は実装対象外とし、一覧表として整理する。

---

## 2. 前提

### 2.1 使用可能な環境

- Python
- RDKit version: `2026.03.3`
- MOE version: `2020.0901`
- 3D conformer生成関数は別途提供済み

3D conformer生成は本実装の中で新規実装しない。  
以下の関数が利用可能である前提とする。

```python
from gen_3d_conf import gen_3d_conformer
```

### 2.2 今回の主エンジン

- Main: RDKit
- MOE: RDKitで生成できない特徴量の補完候補としてリスト化のみ

### 2.3 入力

入力CSVは少なくとも以下を含む。

- 化合物ID列
- SMILES列

ただし列名は固定されない。

### 2.4 出力

特徴量の種類ごとにCSVファイルを分割して出力する。

出力ファイル名は必ず以下の形式とする。

```text
L01_<descriptor_set_name>.csv
L02_<descriptor_set_name>.csv
L03_<descriptor_set_name>.csv
...
```

各CSVには原則として以下の列を含める。

```text
compound_id, canonical_smiles, mol_parse_ok, descriptor_error, <features...>
```

descriptor計算に失敗した化合物については、特徴量値を欠損にし、別途エラーログに記録する。

---

## 3. 実装対象外

以下は今回の実装対象外とする。

- MOEを直接呼び出す処理
- 商用ツール連携
- Complex descriptor
- Protein–ligand interaction fingerprint
- docking pose descriptor
- xTB / QM descriptor
- ChemBERTa, MoLFormer, Uni-Mol等のML embedding
- 自社活性ラベルで学習するGNN descriptor
- 3D conformer生成アルゴリズム自体

ただし、RDKitで計算可能な3D descriptorについては、`gen_3d_conformer`で3D conformerを得る前提で実装対象とする。

---

## 4. 成果物

Claude Code Agent は以下のファイル群を作成すること。

```text
descriptor_agent/
├── README.md
├── SKILL.md
├── config/
│   └── descriptor_sets.yaml
├── src/
│   ├── __init__.py
│   ├── column_infer.py
│   ├── io_utils.py
│   ├── mol_utils.py
│   ├── desc_2d.py
│   ├── fp_morgan.py
│   ├── fp_keys.py
│   ├── scaffold_fragment.py
│   ├── desc_3d.py
│   ├── moe_coverage.py
│   └── run_descriptors.py
├── docs/
│   ├── implementation_notes.md
│   └── moe_coverage_table.md
├── tests/
│   ├── test_column_infer.py
│   ├── test_mol_utils.py
│   ├── test_descriptors_smoke.py
│   └── data/
│       └── sample_ligands.csv
└── outputs/
    └── .gitkeep
```

`outputs/` は実行時出力用ディレクトリであり、通常はGit管理対象外にしてよい。

---

## 5. Skill / Subagent 方針

### 5.1 推奨

本実装は **Skill** として作成することを推奨する。

理由:

- 明確なファイル入力・CSV出力タスクである
- Pythonファイル群をツールとして利用する形が自然
- Claude Codeが必要に応じてCLIを呼び出せばよい
- 自律判断はID/SMILES列推定と特徴量セット選択に限定できる

### 5.2 `SKILL.md` に書く内容

`SKILL.md` には以下を含める。

- Skill名
- 目的
- 使用条件
- 入力CSV要件
- 出力CSV命名規則
- 実行コマンド例
- ID列・SMILES列推定ルール
- descriptor set一覧
- 失敗時の対応
- MOE補完候補は実装対象外であること

---

## 6. CLI仕様

### 6.1 基本コマンド

```bash
python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir outputs/descriptors \
  --config config/descriptor_sets.yaml
```

### 6.2 明示的にID列・SMILES列を指定する場合

```bash
python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir outputs/descriptors \
  --id-col CompoundID \
  --smiles-col SMILES
```

### 6.3 特定のdescriptor setのみ実行

```bash
python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir outputs/descriptors \
  --sets L01,L02,L04
```

### 6.4 3D descriptorを含む実行

```bash
python -m src.run_descriptors \
  --input path/to/input.csv \
  --output-dir outputs/descriptors \
  --sets L01,L14,L15,L16 \
  --enable-3d
```

### 6.5 dry-run

```bash
python -m src.run_descriptors \
  --input path/to/input.csv \
  --dry-run
```

dry-runでは以下を表示する。

- 推定ID列
- 推定SMILES列
- 入力行数
- valid SMILES数
- invalid SMILES数
- 実行予定descriptor set
- 出力予定ファイル名

---

## 7. 出力CSV仕様

### 7.1 共通列

全ての出力CSVは、先頭列として以下を持つ。

| 列名 | 内容 |
|---|---|
| compound_id | 入力CSVから抽出した化合物ID |
| canonical_smiles | RDKitで正規化したcanonical SMILES |
| mol_parse_ok | RDKit Mol化に成功したか |
| descriptor_error | そのdescriptor setで発生したエラー文字列。正常時は空欄 |

### 7.2 特徴量列名

特徴量列名は以下の規則に従う。

```text
<short_prefix>__<feature_name>
```

例:

```text
rdkit2d__MolWt
rdkit2d__TPSA
ecfp4_bit__bit_0000
ecfp4_cnt__bit_0123
maccs__bit_001
murcko__scaffold_smiles
rdkit3d__NPR1
```

### 7.3 欠損値

- descriptor計算不能: 空欄またはNaN
- bit fingerprint: 0/1
- count fingerprint: integer
- scaffold文字列: 空文字可

---

## 8. Descriptor set ID設計

以下のIDを固定する。

| ID | 出力ファイル名 | 内容 | 入力 | RDKit実装 |
|---|---|---|---|---|
| L01 | L01_rdkit_0d_1d_2d.csv | 古典的0D/1D/2D descriptor | SMILES | `Descriptors`, `rdMolDescriptors`, `Lipinski`, `Crippen`, `EState` |
| L02 | L02_ecfp4_bit.csv | ECFP4 bit fingerprint | SMILES | Morgan radius=2, bit vector |
| L03 | L03_ecfp4_count.csv | ECFP4 count fingerprint | SMILES | Morgan radius=2, count vector |
| L04 | L04_ecfp6_bit.csv | ECFP6 bit fingerprint | SMILES | Morgan radius=3, bit vector |
| L05 | L05_ecfp6_count.csv | ECFP6 count fingerprint | SMILES | Morgan radius=3, count vector |
| L06 | L06_fcfp4_bit.csv | FCFP4 bit fingerprint | SMILES | Morgan feature radius=2 |
| L07 | L07_fcfp4_count.csv | FCFP4 count fingerprint | SMILES | Morgan feature radius=2 count |
| L08 | L08_maccs_keys.csv | MACCS keys | SMILES | `MACCSkeys.GenMACCSKeys` |
| L09 | L09_atom_pair.csv | AtomPair fingerprint | SMILES | hashed atom pair fingerprint |
| L10 | L10_topological_torsion.csv | TopologicalTorsion fingerprint | SMILES | hashed topological torsion fingerprint |
| L11 | L11_rdkit_fragment_counts.csv | RDKit fragment count descriptors | SMILES | `rdkit.Chem.Fragments` |
| L12 | L12_scaffold.csv | Murcko scaffold / generic scaffold | SMILES | `MurckoScaffold` |
| L13 | L13_brics_recap.csv | BRICS / RECAP fragments | SMILES | `BRICS`, `Recap` |
| L14 | L14_rdkit_3d_descriptors.csv | RDKit 3D descriptors | 3D conformer | `Descriptors3D`, `rdMolDescriptors.Calc...` |
| L15 | L15_usr_usrcat.csv | USR / USRCAT | 3D conformer | `rdMolDescriptors.GetUSR`, `GetUSRCAT` |
| L16 | L16_shape_basic.csv | 基本3D shape descriptors | 3D conformer | PMI, NPR, radius of gyration, asphericity等 |

### 8.1 デフォルト実行対象

デフォルトでは以下を実行する。

```text
L01,L02,L03,L04,L05,L06,L07,L08,L09,L10,L11,L12,L13
```

3D descriptorは、`--enable-3d` が指定された場合のみ実行する。

```text
L14,L15,L16
```

---

## 9. `descriptor_sets.yaml` 仕様

`config/descriptor_sets.yaml` は以下の形式にする。

```yaml
global:
  n_bits_default: 2048
  id_column: null
  smiles_column: null
  include_invalid_rows: true
  canonicalize_smiles: true

sets:
  L01:
    name: rdkit_0d_1d_2d
    enabled_by_default: true
    output: L01_rdkit_0d_1d_2d.csv
    requires_3d: false

  L02:
    name: ecfp4_bit
    enabled_by_default: true
    output: L02_ecfp4_bit.csv
    requires_3d: false
    params:
      radius: 2
      n_bits: 2048
      use_features: false
      vector_type: bit

  L03:
    name: ecfp4_count
    enabled_by_default: true
    output: L03_ecfp4_count.csv
    requires_3d: false
    params:
      radius: 2
      n_bits: 2048
      use_features: false
      vector_type: count

  L04:
    name: ecfp6_bit
    enabled_by_default: true
    output: L04_ecfp6_bit.csv
    requires_3d: false
    params:
      radius: 3
      n_bits: 2048
      use_features: false
      vector_type: bit

  L05:
    name: ecfp6_count
    enabled_by_default: true
    output: L05_ecfp6_count.csv
    requires_3d: false
    params:
      radius: 3
      n_bits: 2048
      use_features: false
      vector_type: count

  L06:
    name: fcfp4_bit
    enabled_by_default: true
    output: L06_fcfp4_bit.csv
    requires_3d: false
    params:
      radius: 2
      n_bits: 2048
      use_features: true
      vector_type: bit

  L07:
    name: fcfp4_count
    enabled_by_default: true
    output: L07_fcfp4_count.csv
    requires_3d: false
    params:
      radius: 2
      n_bits: 2048
      use_features: true
      vector_type: count

  L08:
    name: maccs_keys
    enabled_by_default: true
    output: L08_maccs_keys.csv
    requires_3d: false

  L09:
    name: atom_pair
    enabled_by_default: true
    output: L09_atom_pair.csv
    requires_3d: false
    params:
      n_bits: 2048
      vector_type: count

  L10:
    name: topological_torsion
    enabled_by_default: true
    output: L10_topological_torsion.csv
    requires_3d: false
    params:
      n_bits: 2048
      vector_type: count

  L11:
    name: rdkit_fragment_counts
    enabled_by_default: true
    output: L11_rdkit_fragment_counts.csv
    requires_3d: false

  L12:
    name: scaffold
    enabled_by_default: true
    output: L12_scaffold.csv
    requires_3d: false

  L13:
    name: brics_recap
    enabled_by_default: true
    output: L13_brics_recap.csv
    requires_3d: false

  L14:
    name: rdkit_3d_descriptors
    enabled_by_default: false
    output: L14_rdkit_3d_descriptors.csv
    requires_3d: true

  L15:
    name: usr_usrcat
    enabled_by_default: false
    output: L15_usr_usrcat.csv
    requires_3d: true

  L16:
    name: shape_basic
    enabled_by_default: false
    output: L16_shape_basic.csv
    requires_3d: true
```

---

## 10. 各Pythonファイル仕様

### 10.1 `src/column_infer.py`

#### 目的

入力CSVの列名が固定されていないため、ID列とSMILES列を推定する。

#### 実装関数

```python
def infer_columns(df):
    """
    Return:
        {
            "id_col": str | None,
            "smiles_col": str | None,
            "confidence": {
                "id_col": float,
                "smiles_col": float
            },
            "messages": list[str]
        }
    """
```

#### SMILES列推定ルール

以下を総合してスコアリングする。

1. 列名スコア
   - 高スコア: `smiles`, `smi`, `canonical_smiles`, `structure`, `mol_smiles`
   - 中スコア: `mol`, `molecule`, `compound`, `structure_string`

2. 値スコア
   - RDKit `Chem.MolFromSmiles(value)` が成功する比率
   - 有効SMILES率が最も高い列を優先
   - 有効率が一定以下ならSMILES列不明とする

3. 除外条件
   - 数値列
   - ほぼ全て欠損の列
   - 極端に短い値ばかりの列
   - IDらしい値のみの列

#### ID列推定ルール

以下を総合してスコアリングする。

1. 列名スコア
   - 高スコア: `id`, `compound_id`, `cmpd_id`, `mol_id`, `molecule_id`, `name`, `compound_name`
   - 中スコア: `code`, `registry`, `sample_id`

2. 値スコア
   - 一意性が高い
   - 欠損が少ない
   - SMILESとしては解釈されない
   - 文字列または整数IDとして自然

3. fallback
   - ID列が見つからない場合は `row_000001` のようなIDを生成
   - ただしログに警告を出す

#### ユーザ確認条件

以下の場合はAgentがユーザに確認してよい。

- SMILES列候補が複数あり、有効SMILES率がほぼ同等
- 有効SMILES率が50%未満
- ID列候補が複数あり、どれも同程度
- 指定列が存在しない

---

### 10.2 `src/io_utils.py`

#### 目的

CSV入出力、ログ保存、出力ディレクトリ作成、エラーレポート生成を行う。

#### 実装関数

```python
def read_input_csv(path: str):
    pass

def ensure_output_dir(path: str) -> None:
    pass

def write_descriptor_csv(df, output_path: str) -> None:
    pass

def write_run_metadata(metadata: dict, output_dir: str) -> None:
    pass

def write_error_report(errors: list[dict], output_dir: str) -> None:
    pass
```

#### 生成するメタデータ

`run_metadata.json` を出力する。

含める項目:

- input file path
- output directory
- datetime
- RDKit version
- selected descriptor sets
- inferred id column
- inferred smiles column
- number of rows
- number of valid molecules
- number of invalid molecules
- number of failed descriptors by set
- command line arguments

---

### 10.3 `src/mol_utils.py`

#### 目的

SMILESからRDKit Molを生成し、canonical SMILESを作成する。

#### 実装関数

```python
def smiles_to_mol(smiles: str):
    """
    Return:
        mol, error_message
    """
```

```python
def canonicalize_smiles(mol) -> str:
    pass
```

```python
def prepare_molecule_table(df, id_col: str, smiles_col: str):
    """
    Return DataFrame with:
        compound_id
        input_smiles
        canonical_smiles
        mol_parse_ok
        mol
        mol_error
    """
```

#### 方針

- `Chem.MolFromSmiles` を使う
- sanitizeに失敗した場合はエラーを記録
- invalid SMILES行も出力CSVに残す
- canonical SMILESはRDKit標準で生成
- salt処理や標準化は今回は過度に行わない
- 必要なら将来的にMolStandardizeを追加可能にする

---

### 10.4 `src/desc_2d.py`

#### 目的

古典的0D/1D/2D descriptorを生成する。

#### 対応ID

- L01
- L11の一部

#### 実装関数

```python
def calc_rdkit_2d_descriptors(mol) -> dict:
    pass

def calc_rdkit_fragment_counts(mol) -> dict:
    pass
```

#### L01に含める推奨descriptor

RDKitの `Descriptors.descList` を基本とする。

追加で明示的に含めるべきもの:

- MolWt
- ExactMolWt
- HeavyAtomMolWt
- NumValenceElectrons
- NumRadicalElectrons
- MolLogP
- MolMR
- TPSA
- LabuteASA
- NumHAcceptors
- NumHDonors
- NumRotatableBonds
- NumHeavyAtoms
- FractionCSP3
- RingCount
- NumAromaticRings
- NumAliphaticRings
- NumSaturatedRings
- NumHeteroatoms
- FormalCharge
- BertzCT
- BalabanJ
- Kappa1
- Kappa2
- Kappa3
- Chi descriptors
- EState descriptors
- BCUT2D descriptors

#### 注意

RDKit versionによりdescriptor名が変わる可能性があるため、実行時に実際のdescriptor名を取得し、列として出力する。

---

### 10.5 `src/fp_morgan.py`

#### 目的

Morgan系fingerprintを生成する。

#### 対応ID

- L02 ECFP4 bit
- L03 ECFP4 count
- L04 ECFP6 bit
- L05 ECFP6 count
- L06 FCFP4 bit
- L07 FCFP4 count

#### 実装方針

RDKit 2026.03.3では可能な限り新しいGenerator APIを使う。

推奨:

```python
from rdkit.Chem import rdFingerprintGenerator

generator = rdFingerprintGenerator.GetMorganGenerator(
    radius=radius,
    fpSize=n_bits,
    includeChirality=False,
    useBondTypes=True,
    useFeatures=use_features,
)
```

bit vector:

```python
fp = generator.GetFingerprint(mol)
```

count vector:

```python
fp = generator.GetCountFingerprint(mol)
```

#### 実装関数

```python
def calc_morgan_fingerprint(
    mol,
    radius: int,
    n_bits: int,
    use_features: bool,
    vector_type: str,
    prefix: str,
) -> dict:
    pass
```

#### 列名

```text
ecfp4_bit__bit_0000
ecfp4_bit__bit_0001
...
ecfp4_cnt__bit_0000
...
fcfp4_bit__bit_0000
...
```

#### vector_type

- `bit`: 0/1
- `count`: integer count

---

### 10.6 `src/fp_keys.py`

#### 目的

Morgan以外のfingerprintを生成する。

#### 対応ID

- L08 MACCS keys
- L09 AtomPair
- L10 TopologicalTorsion

#### 実装関数

```python
def calc_maccs_keys(mol) -> dict:
    pass

def calc_atom_pair_fp(mol, n_bits: int = 2048, vector_type: str = "count") -> dict:
    pass

def calc_topological_torsion_fp(mol, n_bits: int = 2048, vector_type: str = "count") -> dict:
    pass
```

#### MACCS

RDKitのMACCSは通常167 bitsである。  
bit 0を含むかどうかは実装に依存しうるため、列名は実際のbit indexに合わせる。

#### AtomPair

推奨はhashed count vector。  
高次元になりすぎないよう `n_bits=2048` をdefaultにする。

#### TopologicalTorsion

推奨はhashed count vector。  
`n_bits=2048` をdefaultにする。

---

### 10.7 `src/scaffold_fragment.py`

#### 目的

Scaffold / fragment系表現を生成する。

#### 対応ID

- L12 scaffold
- L13 BRICS / RECAP

#### 実装関数

```python
def calc_murcko_scaffold(mol) -> dict:
    pass

def calc_brics_fragments(mol) -> dict:
    pass

def calc_recap_fragments(mol) -> dict:
    pass
```

#### L12 出力列

| 列名 | 内容 |
|---|---|
| scaffold__murcko_smiles | Bemis–Murcko scaffold SMILES |
| scaffold__generic_murcko_smiles | Generic Murcko scaffold SMILES |
| scaffold__has_scaffold | scaffoldが取得できたか |
| scaffold__num_scaffold_atoms | scaffold atom count |
| scaffold__num_scaffold_heavy_atoms | scaffold heavy atom count |

#### L13 出力列

BRICS/RECAPは可変長fragmentを直接横持ちにしにくいため、以下のように出す。

| 列名 | 内容 |
|---|---|
| brics_recap__brics_fragments | `;` 区切りfragment SMILES |
| brics_recap__num_brics_fragments | fragment数 |
| brics_recap__recap_fragments | `;` 区切りfragment SMILES |
| brics_recap__num_recap_fragments | fragment数 |

将来的にfragment vocabularyを作成してone-hot化する拡張は可能とするが、今回は必須ではない。

---

### 10.8 `src/desc_3d.py`

#### 目的

`gen_3d_conformer` により3D conformerを取得し、RDKit 3D descriptorを計算する。

#### 対応ID

- L14 RDKit 3D descriptors
- L15 USR / USRCAT
- L16 basic shape descriptors

#### 前提

```python
from gen_3d_conf import gen_3d_conformer
```

`gen_3d_conformer` の返り値の仕様は実装時に確認する。  
想定は以下のいずれか。

1. 3D conformerを持つRDKit Molを返す
2. SDF pathを返す
3. Molとメタデータを返す

Agentは実際の関数仕様に合わせて薄いadapterを作ること。

#### 実装関数

```python
def get_3d_mol(mol):
    """
    Use gen_3d_conformer and return RDKit Mol with at least one conformer.
    """
```

```python
def calc_rdkit_3d_descriptors(mol3d) -> dict:
    pass

def calc_usr_usrcat(mol3d) -> dict:
    pass

def calc_shape_basic(mol3d) -> dict:
    pass
```

#### L14 推奨descriptor

RDKitで利用可能な3D descriptorを含める。

例:

- Asphericity
- Eccentricity
- InertialShapeFactor
- NPR1
- NPR2
- PMI1
- PMI2
- PMI3
- RadiusOfGyration
- SpherocityIndex

#### L15

- USR 12 dimensions
- USRCAT dimensions

列名例:

```text
usr__dim_00
usr__dim_01
...
usrcat__dim_00
...
```

#### 注意

- 3D生成失敗時はdescriptor_errorに記録
- 3D descriptorは `--enable-3d` 指定時のみ実行
- 3D conformer生成に時間がかかるため、キャッシュ機構を将来拡張可能にする

---

### 10.9 `src/moe_coverage.py`

#### 目的

RDKitでカバーしないがMOEで補完しうる特徴量候補を表として返す。

#### 実装関数

```python
def get_moe_coverage_table() -> list[dict]:
    pass
```

---

### 10.10 `src/run_descriptors.py`

#### 目的

CLIエントリポイント。  
全体のワークフローを制御する。

#### 処理フロー

1. CLI引数をparse
2. config yamlを読み込む
3. 入力CSVを読み込む
4. ID列・SMILES列を決定
   - CLI指定があれば優先
   - なければ自動推定
5. SMILESをRDKit Molに変換
6. canonical SMILESを生成
7. descriptor setを決定
8. 各descriptor setを計算
9. setごとにCSV出力
10. error reportを出力
11. run metadataを出力

#### 引数

```text
--input
--output-dir
--config
--id-col
--smiles-col
--sets
--enable-3d
--dry-run
--n-bits
--include-invalid-rows
--overwrite
```

---

## 11. エラー処理仕様

### 11.1 invalid SMILES

- Mol化に失敗しても行を落とさない
- `mol_parse_ok=False`
- `canonical_smiles`は空欄
- descriptor列はNaN
- `descriptor_error`にエラー内容を入れる

### 11.2 descriptor計算失敗

- そのdescriptor setだけNaN
- 他のdescriptor setは継続
- `errors.csv`に記録

### 11.3 出力ファイル既存

デフォルトは上書きしない。  
`--overwrite` がある場合のみ上書きする。

### 11.4 3D生成失敗

- L14/L15/L16のみ失敗扱い
- 2D descriptorには影響させない

---

## 12. エラーレポート仕様

`errors.csv` を出力する。

列:

| 列名 | 内容 |
|---|---|
| compound_id | 化合物ID |
| input_smiles | 入力SMILES |
| canonical_smiles | canonical SMILES |
| descriptor_set | L01など |
| error_type | mol_parse_error / descriptor_error / conformer_error |
| error_message | 詳細 |
| traceback | 必要に応じて |

---

## 13. run metadata仕様

`run_metadata.json` を出力する。

例:

```json
{
  "input": "data/input.csv",
  "output_dir": "outputs/descriptors",
  "rdkit_version": "2026.03.3",
  "datetime": "2026-06-29T00:00:00",
  "id_col": "compound_id",
  "smiles_col": "smiles",
  "n_rows": 1000,
  "n_valid_mols": 998,
  "n_invalid_mols": 2,
  "descriptor_sets": ["L01", "L02", "L03"],
  "outputs": {
    "L01": "L01_rdkit_0d_1d_2d.csv",
    "L02": "L02_ecfp4_bit.csv"
  },
  "errors": {
    "L01": 0,
    "L02": 0
  }
}
```

---

## 14. README.md 要件

READMEには以下を含める。

1. このSkillの目的
2. 対象descriptor set
3. 入力CSV仕様
4. ID/SMILES列自動推定
5. 出力CSV仕様
6. 実行例
7. 3D descriptorの扱い
8. MOE補完候補
9. 注意事項
10. トラブルシューティング

---

## 15. `docs/moe_coverage_table.md` 要件

今回RDKitでは実装しないが、MOEで補完候補となる特徴量を整理する。

| 特徴量カテゴリ | 具体例 | RDKit対応 | MOE補完方針 | Input |
|---|---|---:|---|---|
| 高度な3D-QSAR field | CoMFA/CoMSIA類似 field, interaction field | 一部不可 | MOE 3D-QSAR/field系機能で補完 | aligned 3D conformers |
| Pharmacophore descriptor | pharmacophore hypothesis, feature distance | 一部可 | MOE pharmacophore機能 | 3D conformers |
| pKa/logD系 | predicted pKa, logD, protomer state | RDKit単独では弱い | MOEまたはChemAxon等で補完 | SMILES/SDF |
| conformational analysis | conformer ensemble energy, strain | RDKitでも一部可 | MOE conformational searchで補完 | 3D conformers |
| 3D alignment-based descriptor | alignment-dependent shape/field | RDKit単独では限定的 | MOE alignment/QSARで補完 | aligned 3D conformers |
| electrostatic field | surface ESP, field values | RDKit単独では限定的 | MOE field descriptor | 3D conformers |
| receptor-independent pharmacophore | feature triplets, pharmacophore fingerprints | RDKit一部可 | MOE pharmacophore fingerprints | 3D conformers |
| ligand interaction field | MIF-like descriptors | RDKit単独では限定的 | MOE field analysis | 3D conformers |

Input候補:

- SMILES
- 2D SDF
- 3D SDF
- aligned 3D conformers
- conformer ensemble
- docking pose ligand conformation
- protein–ligand complex PDB

ただし今回の実装対象はLigand-only RDKit descriptorであるため、Complex inputは参考としてのみ記載する。

---

## 16. テスト仕様

### 16.1 sample input

`tests/data/sample_ligands.csv` を作る。

内容例:

```csv
compound_id,SMILES,activity
CMPD_001,CCO,5.1
CMPD_002,c1ccccc1,6.2
CMPD_003,CC(=O)Oc1ccccc1C(=O)O,7.0
CMPD_BAD,not_a_smiles,
```

### 16.2 テスト項目

| テスト | 内容 |
|---|---|
| `test_column_infer.py` | ID列・SMILES列が推定できる |
| `test_mol_utils.py` | valid/invalid SMILES処理 |
| `test_descriptors_smoke.py` | L01〜L13が落ちずに出力される |
| 3D smoke test | `--enable-3d`時のみ。`gen_3d_conformer`が利用可能な環境で実行 |
| output naming test | L01, L02形式で出力される |
| invalid row test | invalid SMILESが出力CSVに残る |
| metadata test | run_metadata.jsonが出力される |
| errors test | errors.csvが出力される |

### 16.3 Acceptance criteria

最低限、以下を満たすこと。

- sample CSVでCLIが成功する
- L01〜L13のCSVが生成される
- 出力ファイル名が仕様通り
- 各CSVに `compound_id`, `canonical_smiles`, `mol_parse_ok`, `descriptor_error` が含まれる
- invalid SMILES行が保持される
- errors.csvが生成される
- run_metadata.jsonが生成される
- RDKit versionがmetadataに記録される
- `--id-col`, `--smiles-col` 指定時に自動推定を上書きできる
- `--sets` で指定セットのみ生成できる
- `--enable-3d`なしではL14〜L16を実行しない

---

## 17. 実装上の重要注意点

### 17.1 RDKit API

RDKit 2026.03.3ではMorgan fingerprintについて、可能な限り `rdFingerprintGenerator` を使う。  
古いAPIを使う場合でも動作確認を行うこと。

### 17.2 高次元fingerprint

ECFP等は2048 bitをdefaultにする。  
configで変更可能にする。

### 17.3 Count vector

count fingerprintでは0/1ではなく整数値を出す。  
列名はbit vectorと同じく `bit_0000` 形式でよい。

### 17.4 Fragment list

BRICS/RECAPは可変長なので、最初は文字列リストとして出力する。  
one-hot化は将来拡張とする。

### 17.5 ID重複

ID列に重複があっても処理は継続する。  
ただしmetadataに重複数を記録し、警告する。

### 17.6 SMILES標準化

今回は過度な標準化を行わない。  
理由は、社内化合物IDと構造の対応を不用意に変えるリスクを避けるため。

将来拡張として以下を追加可能:

- salt stripping
- largest fragment chooser
- charge neutralization
- tautomer canonicalization
- stereochemistry standardization

---

## 18. Agentへの実装指示

Claude Code Agentは以下の順番で実装すること。

1. フォルダ構成を作成
2. `config/descriptor_sets.yaml` を作成
3. `src/column_infer.py` を実装
4. `src/mol_utils.py` を実装
5. `src/io_utils.py` を実装
6. `src/desc_2d.py` を実装
7. `src/fp_morgan.py` を実装
8. `src/fp_keys.py` を実装
9. `src/scaffold_fragment.py` を実装
10. `src/desc_3d.py` を実装
11. `src/moe_coverage.py` を実装
12. `src/run_descriptors.py` を実装
13. `README.md` を作成
14. `SKILL.md` を作成
15. `docs/moe_coverage_table.md` を作成
16. sample CSVとテストを作成
17. smoke testを実行
18. 実行ログと出力例をREADMEに追記

---

## 19. 実行例

### 19.1 dry-run

```bash
python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/sample \
  --dry-run
```

### 19.2 default descriptors

```bash
python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/sample \
  --overwrite
```

### 19.3 only ECFP descriptors

```bash
python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/sample_ecfp \
  --sets L02,L03,L04,L05 \
  --overwrite
```

### 19.4 with 3D descriptors

```bash
python -m src.run_descriptors \
  --input tests/data/sample_ligands.csv \
  --output-dir outputs/sample_3d \
  --sets L14,L15,L16 \
  --enable-3d \
  --overwrite
```

---

## 20. 完了条件

本実装は以下を満たしたら完了とする。

1. `descriptor_agent/` 以下に仕様通りのファイルが存在する
2. sample CSVでL01〜L13が生成される
3. 3D関数が利用可能な環境ではL14〜L16も生成できる
4. 出力CSVの命名が `Lxx_*.csv` 形式で統一されている
5. エラー行を落とさず、errors.csvに記録できる
6. ID列・SMILES列の自動推定が機能する
7. 明示指定で列推定を上書きできる
8. `README.md` を読めばユーザが実行できる
9. `SKILL.md` を読めばClaude CodeがSkillとして利用できる
10. MOE補完候補が `docs/moe_coverage_table.md` に整理されている

---

## 21. 非目標

以下は今回実装しない。

- 活性値を使ったQSARモデル構築
- SHAP解析
- feature selection
- Applicability Domain解析
- Complex descriptor生成
- docking pose解析
- MOE自動実行
- ML embedding生成
- Chemprop/AttentiveFP等の学習
- descriptorの統合・標準化・欠損補完

これらは後続Agentまたは別Skillで扱う。

---

## 22. 将来拡張案

将来的には以下を別SkillまたはSubagentとして追加する。

1. MOE descriptor generation Skill
2. Protein–ligand complex descriptor Skill
3. ProLIF/PLIP/Arpeggio interaction fingerprint Skill
4. ChemBERTa/MoLFormer/Uni-Mol embedding Skill
5. Chemprop activity-trained representation Skill
6. Descriptor merge and preprocessing Skill
7. QSAR interpretation Skill
8. SAR report generation Skill

---

## 23. まとめ

本Agent/Skillは、RDKitで計算可能なLigand-only descriptorを、種類別CSVとして安定に生成するための基盤である。  
特徴量ID `L01`, `L02`, `L03`, ... を固定し、出力ファイル名と対応づけることで、後続のQSAR・SAR解釈・AD解析Agentが迷わず利用できるようにする。

今回の主眼は予測モデルではなく、**後続解釈に耐えるdescriptor生成の再現性・分割性・追跡性**である。
