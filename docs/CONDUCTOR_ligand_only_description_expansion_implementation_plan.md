# CONDUCTOR Ligand-only Description Expansion Implementation Plan

この文書は、`cs-conductor-desc-ligand` Skill におけるLigand単体Descriptionの追加実装計画である。実装前の合意事項、追加するdescriptor/fingerprint/embedding候補、config方針、テスト方針を固定する。現時点では実装コードは変更しない。

## 1. スコープと目的

この文書の対象は、SMILESまたはLigand単体3D conformerから計算できるDescriptionに限定する。

対象:

- Ligand-only RDKit descriptor/fingerprint
- Ligand-only Mordred descriptor
- Ligand-only pharmacophore fingerprint
- Ligand-only foundation model embedding
- Ligand-only教師あり活性学習embedding
- Ligand-only量子化学descriptor

対象外:

- Protein-ligand complex descriptor
- protein pocket descriptor
- docking pose descriptor
- interaction fingerprint
- PLIF
- contact map
- protein-ligand graph
- protein配列・構造・pocket情報を必要とするembedding

Protein-ligand complex Descriptionは、別Skillとして設計・実装する。将来そのSkillを追加する場合も、Ligand-only Skillにcomplex前提の入力、依存関係、列仕様を混ぜない。

この文書でいう `Description` は、CONDUCTORの `descriptions/<input_csv_stem>/` に保存される化合物表現CSV全般を指す。個別の中身はdescriptor、fingerprint、embedding、量子化学descriptorを含む。

Ligand-only Desc Skillを、RDKit中心の古典的descriptor生成から、以下を扱える拡張可能なDescription生成Skillへ拡張する。

- RDKit descriptor/fingerprintの不足確認と追加
- Mordred 2D/3D descriptor
- 2D pharmacophore fingerprint表現
- OSS foundation model embedding
- 後日追加予定の教師あり活性学習embedding
- tblite/xTB系の量子化学descriptor

出力は従来通り `descriptions/<input_csv_stem>/` にCSVとして保存する。各CSVは `compound_id` 相当のID列、既知のmetadata列、数値特徴量列を持つ。

Ligand-only Descriptionは今後さらに追加される可能性があるため、L番号には余裕を残し、`category` と `metric_recommendation` をconfigで明示する。

## 1.1 実装ステータス

2026-07-01時点の実装状況:

- 実装済み: L14へのPBF追加
- 実装済み: RDKit ETKDGv3 + MMFF94s/UFF fallback conformer generator
- 実装済み: L17 Mordred 2D
- 実装済み: L18 Mordred 3D
- 実装済み: L19-L24 RDKit追加fingerprint / Pharm2D folded bit
- 実装済み: L25 Pharm2D TruncatedSVD
- 実装済み: L30-L49 pretrained embedding adapter registry
- 実装済み: Hugging Face local model adapter for compatible SMILES transformer models
- 実装済み: `config/model_registry.yaml`
- 実装済み: `--model-dir SET_ID=PATH` command-line override
- 実装済み: L60 tblite/xTB adapter code
- 環境未達: current Windows `.venv` では `tblite` buildにC/Fortran compilerが必要で導入未完了
- 未実装: GROVER, Uni-Mol, SMI-TED等のmodel-specific adapter本体

JAK smoke test:

- L17,L19,L20,L21,L22,L23,L24,L25はJAK 231化合物でCSV出力成功
- L25はraw 39972次元からactual 115次元へTruncatedSVD
- L18はJAK 231化合物でCSV出力成功、213次元、エラー0
- L30 ChemBERTa-100M-MLMはlocal weightでJAK 231化合物のCSV出力成功、768次元、エラー0
- L33はdry-runで選択確認済み。weight自動downloadは行わない
- L60はtblite未導入時に明示的な依存エラーを返すことを確認済み

## 2. 現行Ligand-only RDKit Descriptor確認結果

ローカル `.venv` のRDKitで確認した結果:

- RDKit version: `2026.03.3`
- 現行 `L01_rdkit_0d_1d_2d.csv`: 219次元
- RDKit公式 `Descriptors.CalcMolDescriptors`: 217次元
- `CalcMolDescriptors` に対する現行L01の不足: 0
- 現行L01に追加で入っている列: `FormalCharge`, `NumRings`
- 現行 `L11_rdkit_fragment_counts.csv`: 85次元
- RDKit `Descriptors3D` の現行未収載: `PBF`
- RDKit Gobbi 2D pharmacophore raw fingerprint: 39972次元
- Avalon fingerprint: 利用可能

判断:

- L01にはRDKit標準2D molecular descriptorの大きな抜けはない。
- L01へ新規descriptorを大量追加する必要はない。
- 3D descriptorでは `PBF` を `L14_rdkit_3d_descriptors.csv` に追加する。
- 追加RDKit表現はL01に混ぜず、専用CSVのfingerprint/embedding表現として扱う。

## 3. L番号計画

既存のL01-L16は維持する。L12/L13はGrouping Skill側で扱う設計のため復活させない。

| ID | name | category | default | expected dimension | note |
|---|---|---|---|---:|---|
| L17 | `mordred_2d` | `mordred_descriptor` | OFF | 1613 | Mordred 2D。単独CSV。 |
| L18 | `mordred_3d` | `mordred_descriptor` | OFF | variable | 3D conformer必須。 |
| L19 | `rdkit_path_fingerprint` | `rdkit_fingerprint` | OFF | 2048 | RDKit path-based fingerprint。 |
| L20 | `rdkit_pattern_fingerprint` | `rdkit_fingerprint` | OFF | 2048 | substructure screening寄り。 |
| L21 | `rdkit_layered_fingerprint` | `rdkit_fingerprint` | OFF | 2048 | 追加価値はあるが優先度はL19/L20より低い。 |
| L22 | `avalon_fingerprint` | `rdkit_fingerprint` | OFF | 2048 | RDKit buildで利用可能な場合のみ。 |
| L23 | `chiral_morgan_fingerprint` | `rdkit_fingerprint` | OFF | 2048 | 既存Morganにchiralityを加えたvariant。 |
| L24 | `gobbi_pharm2d_folded_bit` | `rdkit_fingerprint` | OFF | 2048 | 固定次元2D pharmacophore bit表現。 |
| L25 | `gobbi_pharm2d_svd` | `rdkit_reduced_fingerprint` | OFF | adaptive | dataset-specific SVD縮約表現。 |
| L30 | `chemberta_embedding` | `pretrained_embedding` | OFF | model-dependent | ChemBERTa family。 |
| L31 | `molformer_embedding` | `pretrained_embedding` | OFF | model-dependent | IBM MoLFormer。 |
| L32 | `grover_embedding` | `pretrained_embedding` | OFF | model-dependent | graph transformer。 |
| L33 | `unimol_embedding` | `pretrained_embedding` | OFF | model-dependent | 3D conformer必須。実装時に重点テスト。 |
| L34 | `smi_ted_embedding` | `pretrained_embedding` | OFF | model-dependent | IBM SMI-TED。 |
| L35 | `smi_ssed_embedding` | `pretrained_embedding` | OFF | model-dependent | IBM SMI-SSED。 |
| L36 | `selfies_ted_embedding` | `pretrained_embedding` | OFF | model-dependent | SELFIES入力。 |
| L37 | `megamolbart_embedding` | `pretrained_embedding` | OFF | model-dependent | NVIDIA/BioNeMo系。 |
| L38 | `chemformer_molbart_embedding` | `pretrained_embedding` | OFF | model-dependent | Chemformer/MolBART family。 |
| L39 | `cddd_embedding` | `pretrained_embedding` | OFF | 512 typical | CDDD/ONNX候補。 |
| L40 | `molbert_embedding` | `pretrained_embedding` | OFF | model-dependent | MolBERT family。 |
| L41 | `selformer_embedding` | `pretrained_embedding` | OFF | model-dependent | SELFIES transformer。 |
| L42 | `smiles_transformer_embedding` | `pretrained_embedding` | OFF | model-dependent | SMILES autoencoder transformer。 |
| L43 | `mol2vec_embedding` | `pretrained_embedding` | OFF | 300 typical | substructure Word2Vec系。 |
| L44 | `kpgt_embedding` | `pretrained_embedding` | OFF | model-dependent | knowledge-guided graph transformer。 |
| L45 | `mole_bert_embedding` | `pretrained_embedding` | OFF | model-dependent | graph pretraining。 |
| L46 | `molclr_embedding` | `pretrained_embedding` | OFF | model-dependent | contrastive GNN。 |
| L47 | `mole_embedding` | `pretrained_embedding` | OFF | model-dependent | Recursion MolE。 |
| L48 | `r_mat_embedding` | `pretrained_embedding` | OFF | model-dependent | relative molecule self-attention transformer。 |
| L49 | `multimodal_molecule_text_embedding` | `pretrained_embedding` | OFF | model-dependent | MolT5/KV-PLM/MoleculeSTM等。 |
| L60 | `tblite_xtb_singlepoint` | `quantum_chemistry` | OFF | small fixed set | tblite/xTB single point descriptor。 |

L50-L59は、追加のLigand-only pretrained model候補に予約する。L番号は実装時点の採用順に応じて微調整してよいが、既存L01-L25とL60は不用意に変更しない。

## 4. Ligand-only RDKit追加方針

### 4.1 L14へのPBF追加

RDKit `Descriptors3D` には `PBF` が存在するが、現行L14には入っていない。L14に `rdkit3d__PBF` を追加する。

### 4.2 L19-L23 fingerprint

RDKit追加fingerprintはすべて単独CSVとする。既存L02-L10と同じく、ID/metadata列 + bit/count列で出力する。

推奨metric:

- bit fingerprint: Tanimoto/Jaccard
- count fingerprint: generalized Tanimotoまたはcosine

## 5. 2D Pharmacophore方針

RDKit Gobbi Pharm2Dは、pharmacophore特徴の組み合わせと2Dトポロジカル距離関係をbitで表現する。raw次元は39972であり、そのままCSVに出すには高次元すぎる。

そのため、2つの表現を分けて実装する。

### 5.1 L24: folded bit表現

主表現として `L24_gobbi_pharm2d_folded_bit.csv` を作る。

仕様:

- raw 39972次元 sparse bit fingerprintを内部生成する。
- stable hashまたはdeterministic foldingで2048次元へ折りたたむ。
- 出力は0/1 bit列。
- 列名は `pharm2d_folded__bit_0000` 形式。
- `n_bits` はconfigで1024/2048/4096などに変更可能にする。
- Python組み込み `hash()` は実行ごとに変わり得るため使わない。
- 推奨metricはTanimoto/Jaccard。

利点:

- サンプル数に依存しない。
- 別データセット間でも同じ列定義を維持できる。
- ECFP等と同様にfingerprintとして扱いやすい。

制約:

- foldingによるcollisionは発生する。
- ただしhashed fingerprintでは一般的なトレードオフであり、raw 39972次元をそのまま扱うより実用的である。

### 5.2 L25: adaptive SVD表現

補助表現として `L25_gobbi_pharm2d_svd.csv` を作る。

仕様:

- raw 39972次元 sparse bit fingerprintから `TruncatedSVD` で連続値ベクトルを作る。
- 通常PCAではなく、sparse入力を扱いやすい `TruncatedSVD` を使う。
- 出力列名は `pharm2d_svd__dim_0000` 形式。
- 推奨metricはcosineまたはeuclidean。

次元数:

```text
actual_dim = min(
  target_dim,
  floor(n_valid_compounds / 2),
  n_valid_compounds - 1,
  raw_dim
)
```

既定値:

- `target_dim: 1024`
- `min_dim: 32`
- `max_dim: 1024`
- `random_seed: 61453`

注意:

- SVD/PCAの実次元数はサンプル数に依存する。
- `n_valid_compounds - 1` まで使うと低分散ノイズまで拾いやすいため、既定では `floor(n_valid_compounds / 2)` を上限にする。
- JAKサンプルが231化合物なら、既定では最大115次元程度になる。
- L25はdataset-specificな座標系であり、別入力CSV間の軸は直接比較できない。

## 6. Mordred追加方針

Mordredは2D/3D descriptorを大量に生成できるため、RDKit L01とは分ける。

- `L17_mordred_2d.csv`
- `L18_mordred_3d.csv`

方針:

- L17は2D descriptorとして単独CSV。
- L18は3D conformer必須、`--enable-3d`対象。
- Mordredの非数値、欠損、エラーは `descriptor_error` に集約し、下流は数値列のみを使う。
- Mordred依存関係は `mordredcommunity` を使用する。現行 `.venv` には導入済み。

## 7. 3D Conformer作成Script

本格的なconformer生成コードは別途準備予定だが、当面のテスト用に低計算コストのRDKit scriptを用意する。この初期版は `src/gen_3d_conf.py` として実装済みである。

既存 `desc_3d.py` は `src.gen_3d_conf.gen_3d_conformer` を優先して呼ぶ。従来互換のため、外部 `gen_3d_conf.py` もfallbackとして許容する。

推奨仕様:

- RDKit ETKDGv3で複数conformer生成。
- default `num_confs: 20`。
- `random_seed: 61453`。
- MMFF94sでminimization。
- MMFF parameterが使えない場合のみUFF fallback。
- energy最小conformerを1つ採用。
- 戻り値はconformer付き `Chem.Mol`。
- 失敗時は例外を投げ、既存の `descriptor_error` / `errors.csv` に流す。

実装済み初期版:

- `src/gen_3d_conf.py`
- `gen_3d_conformer(mol, num_confs=20, random_seed=61453, prune_rms_thresh=0.5, max_iters=200, mmff_variant="MMFF94s", fallback_to_uff=True)`
- CLI smoke test: `python -m src.gen_3d_conf --smiles "CCO" --num-confs 5`

## 8. Ligand-only事前学習Embedding候補

Categoryは `pretrained_embedding` とする。後日追加予定のChemprop等の活性label学習済みembeddingは `supervised_task_embedding` として明確に分ける。

### 8.1 採用確定候補

| ID | model | input | priority | note |
|---|---|---|---|---|
| L30 | ChemBERTa / ChemBERTa family | SMILES | high | Hugging Face/Transformersで扱いやすい。 |
| L31 | MolFormer | SMILES | high | IBM MoLFormer。SMILES transformer embedding。 |
| L32 | GROVER | graph | high | graph transformer。依存関係はやや重い。 |
| L33 | Uni-Mol / Uni-Mol2 | 3D conformer | high | 3D molecular foundation model。癖があるため実装時に重点テスト。 |

この4系統は採用する。ただし、weight downloadは実装時に行わない。後日ユーザが指定するlocal `model_dir` を読むadapterとして実装する。Uni-Molは依存関係と入力3D構造の癖が強いため、weightを同梱しない範囲でloader・前処理・小規模疎通テストまで行う。

### 8.2 候補インベントリ

網羅性を優先し、候補となり得るLigand-only pretrained embedding modelをまず広く保持する。明らかに古い、生成専用、weight入手性が低い、または性能・再現性に懸念があるものは、初期実装対象からは外しても候補表には残す。

#### 8.2.1 SMILES/SELFIES sequence model

| provisional ID | model family | input | initial status | note |
|---|---|---|---|---|
| L30 | ChemBERTa / ChemBERTa-2 / ChemBERTa-3 | SMILES | implement | BERT/RoBERTa系。Hugging Face系adapterで開始しやすい。 |
| L31 | MolFormer / MoLFormer-XL | SMILES | implement | IBMのSMILES transformer。 |
| L34 | SMI-TED | SMILES | strong candidate | IBMのSMILES encoder-decoder foundation model。 |
| L35 | SMI-SSED | SMILES | strong candidate | IBMのMamba系SMILES model。 |
| L36 | SELFIES-TED | SELFIES | strong candidate | SELFIES入力のencoder-decoder。 |
| L37 | MegaMolBART | SMILES | candidate | NVIDIA/BioNeMo系。embedding取得は有用だが環境が重い。 |
| L38 | Chemformer / MolBART | SMILES | candidate | BART系denoising model。 |
| L39 | CDDD / CDDD-ONNX | SMILES | candidate | 連続data-driven descriptor。ONNX版を優先検討。 |
| L40 | MolBERT | SMILES/substructure | candidate | ChemBERTaと近いが代表モデルとして保持。 |
| L41 | SELFormer | SELFIES | candidate | SELFIES transformer。 |
| L42 | SMILES Transformer | SMILES | candidate | autoencoder transformer。やや古いが代表例。 |
| L43 | Mol2vec | substructure tokens | candidate | Word2Vec系。foundation modelではないが軽量embeddingとして保持。 |
| L49 | MolT5 | SMILES + text | optional | molecule-text model。Ligand-only embeddingだけ使う場合に候補。 |
| L49 | 3D-MolT5 | SMILES/3D/text | optional | 3D/テキスト混合。Ligand-only範囲で使える部分のみ候補。 |
| L49 | KV-PLM | SMILES + biomedical text | optional | molecule-text系。SAL用途では優先度低め。 |
| L50 | MolecularTransformerEmbeddings | SMILES/IUPAC | optional | PubChem SMILES/IUPAC翻訳系embedding。 |
| L51 | GP-MoLFormer | SMILES | optional | 生成寄りのMoLFormer派生。embedding用途は要確認。 |
| L52 | MolGPT / SMILES GPT系 | SMILES | archive candidate | 生成寄り。embedding抽出は可能だが初期優先度は低い。 |
| L53 | SMILES RNN/LSTM autoencoder系 | SMILES | archive candidate | 古いRNN/LSTM系。代表として記録するが初期実装対象外。 |

#### 8.2.2 Graph / GNN / graph transformer model

| provisional ID | model family | input | initial status | note |
|---|---|---|---|---|
| L32 | GROVER | graph | implement | 採用確定。graph transformer。 |
| L44 | KPGT / LiGhT | graph | strong candidate | knowledge-guided graph transformer。 |
| L45 | Mole-BERT | graph | candidate | molecular graph pretraining代表。 |
| L46 | MolCLR / iMolCLR | graph | candidate | contrastive GNN。 |
| L47 | MolE | graph | candidate if weights available | Recursionのfoundation model。weight入手性を確認する。 |
| L48 | MAT / R-MAT | graph | candidate | relative molecule self-attention transformer。 |
| L54 | Pretrain-GNN / AttrMasking / ContextPred | graph | archive candidate | 重要な古典的GNN pretraining。初期実装優先度は低い。 |
| L55 | GraphCL | graph | archive candidate | graph contrastive learning代表。molecule特化adapterは要確認。 |
| L56 | GEM / GeoGNN | graph + geometry | candidate but heavy | Paddle系依存の可能性。ベンチマークによっては重い。 |
| L57 | GraphMVP | graph + 3D pretraining | candidate but heavy | 2D/3D対応。実装負荷が高く、初期対象からは外す可能性あり。 |
| L58 | MHG-GED | molecular graph / grammar | optional | IBM materials系。Ligand-only embeddingとして利用可能なら候補。 |

#### 8.2.3 3D molecular foundation model

| provisional ID | model family | input | initial status | note |
|---|---|---|---|---|
| L33 | Uni-Mol / Uni-Mol2 | 3D conformer | implement and smoke-test | 採用確定。依存関係と3D入力の癖があるため重点確認。 |
| L57 | GraphMVP | graph + 3D | candidate but heavy | 3D pretraining由来。 |
| L56 | GEM / GeoGNN | geometry graph | candidate but heavy | 3D/geometry依存。 |
| L59 | 3D-EMGP / InfoMax3D / related 3D SSL | 3D conformer | optional | 代表的3D SSL系として保持。安定weightと実装可否を確認してから採用。 |

#### 8.2.4 初期実装対象の考え方

初期実装は、候補の全weightを動かすことではなく、local weight pathを受け取って安定にembedding抽出できるadapterを用意することである。

Tier 1:

- ChemBERTa
- MolFormer
- GROVER
- Uni-Mol

Tier 2:

- SMI-TED
- SMI-SSED
- SELFIES-TED
- MegaMolBART
- Chemformer/MolBART
- CDDD
- KPGT
- MolE
- Mole-BERT
- MolCLR
- MAT/R-MAT

Tier 3:

- Mol2vec
- SMILES Transformer
- SELFormer
- MolBERT
- MolT5 / 3D-MolT5
- KV-PLM / MoleculeSTM
- GraphMVP
- GEM / GeoGNN
- GraphCL / Pretrain-GNN
- SMILES RNN/LSTM/GPT系

Tier 3は候補として保持するが、初期実装の必須対象ではない。古いRNN/LSTM系は、代表モデル名とgeneric adapter方針を残すに留める。

### 8.3 Adapter契約とWeight管理

この段階ではweight downloadは行わない。実装時はconfigに明示されたlocal pathだけを読む。

原則:

- 実装コードはネットワークからweightを自動取得しない。
- Hugging Face系も `local_files_only` 相当の挙動を基本にする。
- `trust_remote_code` が必要なmodelはconfigで明示する。
- `model_dir` が未指定または存在しない場合は、明確なエラーメッセージを返す。
- defaultではpretrained embedding系setは実行しない。
- `--sets L30,L31` のように明示指定された場合だけ実行する。
- local model pathは `config/model_registry.yaml` に書くか、`--model-dir L30=C:\path\to\model` で一時上書きする。
- 出力CSVにはmodel名、checkpoint path、pooling、tokenizer、入力正規化方法をmetadata列またはrun metadataとして残す。

```yaml
model_registry:
  chemberta:
    category: pretrained_embedding
    model_dir: null
    loader: huggingface_transformers
    pooling: mean_last_hidden_state
  molformer:
    category: pretrained_embedding
    model_dir: null
    loader: huggingface_transformers_trust_remote_code
    pooling: cls_or_mean
  unimol:
    category: pretrained_embedding
    model_dir: null
    loader: unimol_local
    requires_3d: true
  smi_ted:
    category: pretrained_embedding
    model_dir: null
    loader: local_custom
    pooling: model_default
  generic_smiles_transformer:
    category: pretrained_embedding
    model_dir: null
    loader: generic_torch_sequence
    pooling: cls_or_mean
```

各embedding CSVには以下を入れる。

- `compound_id`
- `canonical_smiles`
- `mol_parse_ok`
- `descriptor_error`
- `model_name`
- `model_version`
- `model_dir`
- `pooling`
- numeric embedding columns

## 9. Ligand-only Supervised Task Embedding予定

後日、Chemprop等でLigandと活性labelを使ってモデルを学習し、中間層embeddingを取り出すcategoryを追加する。

Category:

- `supervised_task_embedding`

これは、事前学習済みfoundation modelからの汎用embeddingとは意味が異なる。Property labelを見て学習するため、Analysis Phase1/2で比較する際は、事前学習embeddingとは分けて解釈する。

Protein-ligand complexを使った教師ありembeddingはこのcategoryには含めない。complex情報を使う場合は、別Skill側のcategoryとして設計する。

## 10. Ligand-only量子化学Descriptor

Categoryは `quantum_chemistry` とする。DFTは計算コストのため対象外。最初は `tblite` を使う。

現行 `.venv` の依存状態:

- 導入済み: `mordredcommunity`
- 導入済み: `torch`
- 導入済み: `transformers`
- 導入済み: `safetensors`
- 未導入: `tblite`

追加候補:

| ID | name | backend | default | note |
|---|---|---|---|---|
| L60 | `tblite_xtb_singlepoint` | tblite | OFF | GFN2-xTB相当のsingle point descriptor。 |

出力候補:

- total energy
- HOMO
- LUMO
- HOMO-LUMO gap
- dipole moment
- charge min/max/mean/std
- positive charge sum
- negative charge sum
- electronic chemical potential
- hardness
- softness
- electrophilicity index
- method
- convergence/status

テスト方針:

- `tblite` が利用可能なPython環境で実行する。現行Windows `.venv` ではsource buildが失敗したため、conda-forgeの `tblite-python` 環境を推奨する。
- ethanol/benzene等の小分子でsmoke testする。
- JAKサンプルでsubset testする。
- 可能ならJAK全件で実行し、失敗行を `descriptor_error` に残す。
- tblite descriptorは、`tblite-python` が利用可能な環境でTEST必須対象とする。

## 11. Config設計

既存 `descriptor_sets.yaml` を拡張し、追加カテゴリを明確化する。

推奨category:

- `rdkit_descriptor`
- `rdkit_fingerprint`
- `rdkit_reduced_fingerprint`
- `mordred_descriptor`
- `pretrained_embedding`
- `supervised_task_embedding`
- `quantum_chemistry`

各setに持たせる項目:

- `name`
- `category`
- `enabled_by_default`
- `output`
- `requires_3d`
- `requires_model_dir`
- `requires_external_backend`
- `runtime_tier`
- `metric_recommendation`
- `params`

重いものはdefault OFF:

- Mordred 3D
- Gobbi Pharm2D SVD
- pretrained embedding
- supervised task embedding
- quantum chemistry

現時点では、追加setはすべてdefault OFFにする。既存L01-L11のdefault挙動を変えないためである。ユーザが必要なsetを `--sets` で明示する。

## 12. 実装順

Phase A: RDKit/Mordred基盤

1. RDKit audit scriptを固定化する。
2. L14に `PBF` を追加する。
3. 低計算コストRDKit conformer scriptを追加する。
4. L17 Mordred 2Dを追加する。
5. L18 Mordred 3Dを追加する。

Phase B: RDKit追加fingerprint

6. L19-L23 RDKit追加fingerprintを実装する。
7. L24 Gobbi Pharm2D folded bitを実装する。
8. L25 Gobbi Pharm2D SVDを実装する。
9. Config schemaを拡張する。

Phase C: 量子化学

10. L60 tblite xTB descriptorを実装する。
11. `tblite-python` が利用可能な環境でtblite smoke test、JAK subset test、可能ならJAK全件testを行う。

Phase D: foundation model embedding

12. L30 ChemBERTa adapterを実装する。
13. L31 MolFormer adapterを実装する。
14. L33 Uni-Mol adapterを実装し、Uni-Molのみ重点的に疎通テストする。
15. L32 GROVER adapterを実装する。
16. 追加候補モデルを優先度順にadapter化する。

## 13. 実装時の検証基準

必須:

- 既存L01-L16の出力互換性を壊さない。
- ID欠損・ID重複・Invalid SMILESの既存扱いを維持する。
- 各CSVは `compound_id`, `canonical_smiles`, `mol_parse_ok`, `descriptor_error` を持つ。
- Ligand-only Skillにprotein構造、pocket、pose、complex interaction前提の入力仕様を追加しない。
- 外部依存が未導入の場合は、曖昧なImportErrorではなく、どのsetに何が必要かを明示する。
- `--sets` で個別setを実行できる。
- 重いsetは明示指定なしに走らない。
- `run_metadata.json` にdescriptor set、依存version、次元数、configを記録する。
- 将来のLigand-only Description追加に備え、既存L番号・既存出力ファイル名を不用意に変更しない。

JAKテスト:

- RDKit追加fingerprintはJAK全件で実行する。
- Mordred 2DはJAK全件で実行する。
- Mordred 3Dはconformer生成込みでJAK subsetから確認する。
- tbliteは `tblite-python` が利用可能な環境でJAK subset以上を確認する。
- foundation model embeddingはweight downloadをしないため、model_dir未指定時のskip/error動作を確認する。Uni-Molは可能な範囲でloader疎通まで確認する。

## 14. 参考情報

- RDKit Descriptors: https://www.rdkit.org/docs/source/rdkit.Chem.Descriptors.html
- Mordred paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC5801138/
- MolFormer: https://github.com/IBM/molformer
- Uni-Mol: https://github.com/deepmodeling/Uni-Mol
- GROVER: https://github.com/tencent-ailab/grover
- ChemBERTa: https://github.com/seyonechithrananda/bert-loves-chemistry
- ChemBERTa-3: https://github.com/deepforestsci/chemberta3
- SMI-TED: https://huggingface.co/ibm-research/materials.smi-ted
- MegaMolBART: https://github.com/NVIDIA/MegaMolBART
- MolBART: https://github.com/MolecularAI/MolBART
- CDDD: https://github.com/jrwnter/cddd
- Mol2vec: https://github.com/samoturk/mol2vec
- SMILES Transformer: https://github.com/DSPsleeporg/smiles-transformer
- SELFormer: https://github.com/HUBioDataLab/SELFormer
- MolCLR: https://github.com/yuyangw/MolCLR
- KPGT: https://github.com/lihan97/kpgt
- GraphMVP: https://github.com/chao1224/graphmvp
- Mole-BERT: https://github.com/junxia97/Mole-BERT
- tblite: https://github.com/tblite/tblite
- xtb-python note recommending tblite: https://github.com/grimme-lab/xtb-python
- Chemprop: https://github.com/chemprop/chemprop
