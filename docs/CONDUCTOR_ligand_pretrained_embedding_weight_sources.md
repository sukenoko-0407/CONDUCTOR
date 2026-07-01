# CONDUCTOR Ligand Pretrained Embedding Weight Sources

Last updated: 2026-07-02

This document summarizes which ligand-only pretrained embedding sets can be executed by the current `cs-conductor-desc-ligand` Skill, what the user must prepare, where model weights are available, and where execution risk remains.

## 1. Current Execution Classes

| Class | Meaning | User work required |
|---|---|---|
| Direct Hugging Face | The Skill can call `AutoTokenizer`/`AutoModel` directly from a local `model_dir`. | Download the model repo under `embed_model/<model_name>` and set `model_dir`. |
| Built-in specialized loader | The Skill has a dedicated loader, but extra packages and local files are required. | Install the required package, place weights, and set `model_dir` plus optional params. |
| Custom adapter | The Skill core is ready, but model-specific loading code must be provided next to the weights. | Place `conductor_embedding_adapter.py` or `adapter.py` in `model_dir`. |
| External command | The Skill core is ready, but the official repo/CLI should generate the embeddings. | Prepare the external model environment and set `params.command` with `{input_csv}` and `{output_csv}`. |
| Not reached | Included in the plan, but not yet ready enough to call through the Skill. | Requires additional implementation or source clarification. |

## 2. Models Ready After Weight Preparation

### 2.1 Direct Hugging Face or Built-in Loader

| Set | Model family | Loader | Weight-only readiness | Current status | Risk after weight placement |
|---|---|---|---|---|---|
| L30 | ChemBERTa family | `huggingface_transformers` | Yes | ChemBERTa-100M, 5M, 10M tested on JAK. | Low. |
| L31 | MoLFormer / MoLFormer-XL | `huggingface_transformers_trust_remote_code` | Yes, if local HF repo is complete. | Not yet tested with local weight. | Low to medium. `trust_remote_code` and model-specific pooling can be brittle. |
| L33 | Uni-Mol / Uni-Mol2 | `unimol_local` | Mostly, but requires `unimol_tools`. | Loader implemented; package missing in current `.venv`. | Medium to high on Windows because of package/dependency and 3D handling. |
| L34 | SMI-TED | `huggingface_transformers_trust_remote_code` | Yes for HF root model; official inference folders may need custom handling. | Not yet tested locally. | Medium. Large checkpoint and custom model code are likely failure points. |
| L35 | SMI-SSED | `huggingface_transformers_trust_remote_code` | Yes for HF root model; Mamba dependencies may be required. | Not yet tested locally. | Medium to high. Mamba/state-space dependencies may not work cleanly on Windows CPU. |
| L36 | SELFIES-TED | `huggingface_transformers` | Yes, if complete HF repo is local. | SELFIES conversion tested; full model not downloaded. | Medium. Very large model and memory use. |
| L43 | Mol2vec | `mol2vec_local` | Yes, if a compatible Word2Vec model file is supplied. | Loader implemented; `mol2vec`/`gensim` missing in current `.venv`. | Medium. `gensim`/SciPy compatibility and model-file naming are common issues. |

### 2.2 Custom Adapter or External Command

These sets can now be executed through the Skill without changing the Skill core, but the user must provide a model-specific adapter or command.

| Set | Model family | Loader | User must provide | Risk after weight placement |
|---|---|---|---|---|
| L32 | GROVER | `external_command` | GROVER environment plus a command that reads `{input_csv}` and writes `{output_csv}`. | High. Older dependencies, graph featurization, and command output alignment are fragile. |
| L37 | MegaMolBART | `local_custom` | Adapter around NVIDIA/BioNeMo/NeMo inference. | High. Heavy NeMo/BioNeMo stack and checkpoint format. |
| L38 | Chemformer / MolBART | `local_custom` | Adapter around Chemformer/AiZynthModels checkpoint loading. | Medium to high. Project versions and checkpoint migration matter. |
| L39 | CDDD | `local_custom` | Adapter around CDDD or CDDD-ONNX. | High for original CDDD because it depends on TensorFlow 1.x/Python 3.6-era tooling. |
| L40 | MolBERT | `local_custom` | Adapter around MolBERT Lightning checkpoint. | High. Official implementation targets older Python/RDKit/PyTorch stack. |
| L41 | SELFormer | `local_custom` | Adapter around SELFormer SELFIES model. | Medium to high. SELFIES/tokenizer/model directory layout must match. |
| L42 | SMILES Transformer | `local_custom` | Adapter around official SMILES Transformer checkpoint. | Medium. Official code is older PyTorch but simpler than graph models. |
| L44 | KPGT / LiGhT | `local_custom` | Adapter around KPGT feature extraction. | High. Requires graph preprocessing, descriptor/fingerprint auxiliary inputs, and older environment. |
| L45 | Mole-BERT | `local_custom` | Adapter around a user-provided or user-trained Mole-BERT checkpoint. | High. Public pretrained checkpoint source was not confirmed. |
| L46 | MolCLR | `local_custom` | Adapter around GIN/GCN pretrained models. | Medium to high. PyG/torch-scatter stack is the main risk. |
| L47 | MolE | `local_custom` | Adapter around `mole_predict.encode` plus checkpoint. | High until public checkpoint source is confirmed. |
| L48 | MAT / R-MAT | `local_custom` | Adapter around MAT/R-MAT or HuggingMolecules. | Medium to high. Official MAT and HuggingMolecules checkpoint APIs differ. |
| L49 | MolT5 / 3D-MolT5 / molecule-text models | `local_custom` | Adapter for molecule-side encoder output. | Medium to high. Seq2Seq models often expose decoder/generation outputs rather than direct molecular embeddings. |

## 3. User Workflow

### 3.1 Direct Hugging Face sets

1. Download the model repo under:

```text
C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\embed_model\<model_name>
```

2. Add the path to `.claude/skills/cs-conductor-desc-ligand/config/model_registry.yaml`:

```yaml
models:
  L31:
    model_dir: C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\embed_model\MoLFormer-XL-both-10pct
```

3. Run the Skill:

```powershell
cd C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\CONDUCTOR\.claude\skills\cs-conductor-desc-ligand
..\..\..\.venv\Scripts\python.exe -m src.run_descriptors --input ..\..\..\chemble_jak2.csv --sets L31 --overwrite
```

One-off override:

```powershell
..\..\..\.venv\Scripts\python.exe -m src.run_descriptors --input ..\..\..\chemble_jak2.csv --sets L31 --model-dir L31=C:\path\to\model --overwrite
```

### 3.2 Local custom adapter sets

Put this file in `model_dir`:

```text
conductor_embedding_adapter.py
```

It must expose one of:

```python
def embed_smiles(smiles, model_dir, params):
    return vectors, metadata

def embed_molecules(records, model_dir, params):
    return vectors, metadata
```

`vectors` must be a 2D vector-like object with one row per valid molecule. `metadata` is optional but recommended.

### 3.3 External command sets

Set `params.command` in `model_registry.yaml`:

```yaml
models:
  L32:
    model_dir: C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\embed_model\GROVER
    params:
      command:
        - python
        - C:\path\to\grover_embed.py
        - --input
        - "{input_csv}"
        - --output
        - "{output_csv}"
        - --checkpoint_dir
        - "{model_dir}"
```

The command receives a CSV with `compound_id,canonical_smiles` and must write a CSV with `compound_id` plus numeric embedding columns.

## 4. Weight Sources

Sizes are from Hugging Face Hub metadata or HTTP HEAD checks when available. Google Drive, Box, NGC, and some figshare pages may require manual browser download.

| Set | Model | Source URL | Approx. weight size | Notes |
|---|---|---|---:|---|
| L30 | ChemBERTa-100M-MLM | https://huggingface.co/DeepChem/ChemBERTa-100M-MLM | 351.5 MB | Already present locally and tested. |
| L30 | ChemBERTa-5M-MLM | https://huggingface.co/DeepChem/ChemBERTa-5M-MLM | 13.1 MB | Downloaded to `embed_model\ChemBERTa-5M-MLM`; JAK test OK. |
| L30 | ChemBERTa-10M-MLM | https://huggingface.co/DeepChem/ChemBERTa-10M-MLM | 13.1 MB | Downloaded to `embed_model\ChemBERTa-10M-MLM`; JAK test OK. |
| L31 | MoLFormer-XL-both-10pct | https://huggingface.co/ibm-research/MoLFormer-XL-both-10pct | 178.6 MB | Direct HF loader with `trust_remote_code`. |
| L32 | GROVER base/large | https://github.com/tencent-ailab/grover | Not checked | README links to Google Drive and OneDrive. Use `external_command`. |
| L33 | Uni-Mol models | https://huggingface.co/dptech/Uni-Mol-Models | 181.7-309.4 MB per listed checkpoint | `unimol_tools` docs point to this HF repo. |
| L34 | SMI-TED | https://huggingface.co/ibm-research/materials.smi-ted | ~1.15 GB | HF model card lists `.pt` and `safetensors` weights. |
| L35 | SMI-SSED | https://huggingface.co/ibm-research/materials.smi_ssed | ~1.35 GB | HF model card lists `.pt` and `.bin` weights. |
| L36 | SELFIES-TED | https://huggingface.co/ibm-research/materials.selfies-ted | 1.37 GB model; optimizer file is larger | Download only model/tokenizer files, not optimizer, for inference. |
| L37 | MegaMolBART | https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/models/megamolbart | Not checked | Also see https://github.com/NVIDIA/MegaMolBART. Heavy NeMo/BioNeMo stack. |
| L38 | Chemformer / MolBART | https://github.com/MolecularAI/Chemformer | Not checked | README links public models on Box. Updated project points to AiZynthModels. |
| L39 | CDDD | https://github.com/jrwnter/cddd | Not checked | README links `default_model.zip` on Google Drive. |
| L40 | MolBERT | https://github.com/BenevolentAI/MolBERT | 967 MB | Direct figshare file: https://ndownloader.figshare.com/files/25611290 |
| L41 | SELFormer | https://github.com/HUBioDataLab/SELFormer | Not checked | README links pretrained models on Google Drive. |
| L42 | SMILES Transformer | https://github.com/DSPsleeporg/smiles-transformer | Not checked | README links pretrained model on Google Drive. |
| L43 | Mol2vec | https://github.com/samoturk/mol2vec | Not checked | Need compatible Word2Vec model file plus `mol2vec`/`gensim`. |
| L44 | KPGT / LiGhT | https://github.com/lihan97/kpgt | Not checked | README links pretrained base model on figshare. |
| L46 | MolCLR | https://github.com/yuyangw/MolCLR | Included in repo path, size not checked | README says pretrained GCN/GIN models are in `ckpt/pretrained_gcn` and `ckpt/pretrained_gin`. |
| L47 | MolE | https://github.com/recursionpharma/mole_public | Public checkpoint not confirmed | Zenodo record found for code only: https://zenodo.org/records/13891642 |
| L48 | MAT / R-MAT | MAT: https://github.com/ardigen/MAT ; R-MAT/HuggingMolecules: https://github.com/gmum/huggingmolecules | Not checked | MAT README links Google Drive; HuggingMolecules includes MAT/GROVER/R-MAT APIs. |
| L49 | MolT5 | https://github.com/blender-nlp/MolT5 | 293.6 MB small, 944.5 MB base, 2.99 GB large | HF checkpoints include `laituan245/molt5-small`, `base`, `large`. |
| L49 | 3D-MolT5 | https://huggingface.co/collections/QizhiPei/3d-molt5 | ~973.6 MB for base | Requires 3D/molecule-text adapter design. |

## 5. Downloaded And Tested Small Weights

The following small-ish weights were downloaded under `C:\Users\kimot\OneDrive\TAKAHIRO\coding_workspace\embed_model` and tested with JAK using L30:

| Local folder | Source | Output | Shape | Errors |
|---|---|---|---|---:|
| `ChemBERTa-5M-MLM` | `DeepChem/ChemBERTa-5M-MLM` | `descriptions/chemble_jak2_chemberta_5m/L30_chemberta_embedding.csv` | 231 x 388, 384 embedding dims | 0 |
| `ChemBERTa-10M-MLM` | `DeepChem/ChemBERTa-10M-MLM` | `descriptions/chemble_jak2_chemberta_10m/L30_chemberta_embedding.csv` | 231 x 388, 384 embedding dims | 0 |

No other planned pretrained embedding weight was clearly around 10 MB. Most direct model checkpoints are 178 MB to several GB, or are hosted on Google Drive/Box/NGC with manual download steps.

## 6. Main Failure Points

- Checkpoint format mismatch: official checkpoints may be `.ckpt`, `.pt`, custom PyTorch state dicts, or full framework folders rather than Hugging Face model dirs.
- Dependency pinning: older models often require Python 3.6/3.7, old PyTorch, TensorFlow 1.x, PyTorch Geometric, or CUDA-specific packages.
- Windows compatibility: Uni-Mol, PyG-based graph models, Mamba/state-space models, and TensorFlow 1.x-era packages may fail on Windows CPU environments.
- Tokenization mismatch: SMILES/SELFIES models often require exact vocabulary files and preprocessing.
- Output alignment: custom/external adapters must preserve one embedding row per valid `compound_id`.
- Memory/runtime: 1GB+ sequence models may run slowly or fail on CPU-only inference.

## 7. Models In The Plan But Not Fully Reached

These are in the broader plan, but are not yet at the "provide weight and run through Skill" stage:

| Model group | Reason |
|---|---|
| Mole-BERT (L45) | Official repo does not provide an obvious pretrained checkpoint in README; it documents training and fine-tuning paths. |
| MolE (L47) | Public code is available, but a direct public pretrained checkpoint source was not confirmed. |
| GraphMVP | Kept as Tier 3 candidate; not implemented in config. |
| GEM / GeoGNN | Kept as Tier 3 candidate; not implemented in config. |
| GraphCL / Pretrain-GNN | Kept as Tier 3 candidate; not implemented in config. |
| SMILES RNN/LSTM/GPT family | Kept as archive candidates; not implemented because stronger transformer/foundation alternatives are prioritized. |
| Additional L50-L59 ligand-only pretrained candidates | Reserved range; not assigned to concrete implemented sets yet. |
