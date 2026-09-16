"""設定の読み込み、入力 CSV の検証、分子の準備。"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")


@dataclasses.dataclass
class EndpointSpec:
    endpoint_id: str
    column: str
    role: str
    transform: str
    higher_is_better: bool


@dataclasses.dataclass
class Config:
    csv_path: str
    id_column: str
    smiles_column: str
    endpoints: list[EndpointSpec]
    descriptor_set: str
    neighbor_k: list[int]
    n_clusters_grid: list[int]
    max_cuts_per_molecule: int
    n_jobs: int
    output_dir: str
    aggregate_only: bool


def load_config(path: str) -> Config:
    import yaml  # selftest では不要なため遅延 import

    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    endpoints = [
        EndpointSpec(
            endpoint_id=e["endpoint_id"],
            column=e["column"],
            role=e.get("role", "secondary"),
            transform=e.get("transform", "none"),
            higher_is_better=bool(e.get("higher_is_better", True)),
        )
        for e in raw["endpoints"]
    ]

    analysis = raw.get("analysis", {})
    n_jobs = analysis.get("n_jobs")
    if not n_jobs:
        n_jobs = max(1, (os.cpu_count() or 2) - 1)

    return Config(
        csv_path=raw["input"]["csv_path"],
        id_column=raw["input"]["id_column"],
        smiles_column=raw["input"]["smiles_column"],
        endpoints=endpoints,
        descriptor_set=analysis.get("descriptor_set", "fast"),
        neighbor_k=list(analysis.get("neighbor_k", [5, 10, 20])),
        n_clusters_grid=list(analysis.get("n_clusters_grid", [10, 20, 40])),
        max_cuts_per_molecule=int(analysis.get("max_cuts_per_molecule", 2000)),
        n_jobs=int(n_jobs),
        output_dir=raw.get("output", {}).get("dir", "./diagnosis_output"),
        aggregate_only=bool(raw.get("output", {}).get("aggregate_only", True)),
    )


def _apply_transform(values: pd.Series, transform: str) -> np.ndarray:
    v = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if transform == "none":
        return v
    with np.errstate(divide="ignore", invalid="ignore"):
        if transform == "neg_log10":
            # nM 前提。非正値は欠測扱い。
            out = np.where(v > 0, -np.log10(v * 1e-9), np.nan)
        elif transform == "log10":
            out = np.where(v > 0, np.log10(v), np.nan)
        else:
            raise ValueError(f"unknown transform: {transform}")
    return out


@dataclasses.dataclass
class Dataset:
    """診断で使う正規化済みデータ。compound ID は索引としてのみ保持する。"""

    ids: list[str]
    smiles: list[str]
    mols: list[Any]
    endpoints: dict[str, np.ndarray]  # endpoint_id -> 変換済み値（欠測は NaN）
    specs: dict[str, EndpointSpec]
    input_issues: dict[str, Any]

    @property
    def n(self) -> int:
        return len(self.ids)


def load_dataset(cfg: Config) -> Dataset:
    df = pd.read_csv(cfg.csv_path)

    missing_cols = [
        c
        for c in [cfg.id_column, cfg.smiles_column] + [e.column for e in cfg.endpoints]
        if c not in df.columns
    ]
    if missing_cols:
        raise SystemExit(
            f"入力 CSV に次の列がありません: {missing_cols}\n"
            f"実在する列: {list(df.columns)}"
        )

    issues: dict[str, Any] = {"input_rows": int(len(df))}

    ids_raw = df[cfg.id_column].astype(str)
    issues["id_missing"] = int(ids_raw.isna().sum() + (ids_raw.str.strip() == "").sum())
    issues["id_duplicated"] = int(ids_raw.duplicated().sum())

    smiles_raw = df[cfg.smiles_column].astype(str)
    issues["smiles_blank"] = int((smiles_raw.str.strip() == "").sum())

    ids: list[str] = []
    smiles: list[str] = []
    mols: list[Any] = []
    keep_idx: list[int] = []
    parse_failed = 0

    # 同一 ID・異構造の検出（0.2.1 では fail-fast。診断では計数のみ）
    id_to_canonical: dict[str, str] = {}
    id_structure_conflicts = 0

    for i, (cid, smi) in enumerate(zip(ids_raw, smiles_raw)):
        mol = Chem.MolFromSmiles(smi) if smi and smi.strip() else None
        if mol is None:
            parse_failed += 1
            continue
        canonical = Chem.MolToSmiles(mol)
        prev = id_to_canonical.get(cid)
        if prev is not None and prev != canonical:
            id_structure_conflicts += 1
            continue
        id_to_canonical[cid] = canonical
        if prev is not None:
            # 同一 ID・同一構造の重複行はスキップ
            continue
        ids.append(cid)
        smiles.append(canonical)
        mols.append(mol)
        keep_idx.append(i)

    issues["smiles_parse_failed"] = parse_failed
    issues["same_id_different_structure"] = id_structure_conflicts
    issues["retained_compounds"] = len(ids)

    endpoints: dict[str, np.ndarray] = {}
    for spec in cfg.endpoints:
        transformed = _apply_transform(df[spec.column], spec.transform)
        endpoints[spec.endpoint_id] = transformed[keep_idx]

    return Dataset(
        ids=ids,
        smiles=smiles,
        mols=mols,
        endpoints=endpoints,
        specs={e.endpoint_id: e for e in cfg.endpoints},
        input_issues=issues,
    )


def make_synthetic_dataset(seed: int = 20260916) -> Dataset:
    """--selftest 用の合成データ。実データ無しで配線を検証する。

    3部品（置換基 R1 ― 中央フェニル ― 末端環 R2）で作り、
    末端置換・リンカー置換・環系置換の3クラスすべてが成立するようにしてある。
    活性には R1 主効果、R2 主効果、および R1×R2 交互作用を意図的に埋め込む。
    """
    rng = np.random.default_rng(seed)
    subs = [
        "C(F)(F)F", "S(C)(=O)=O", "OCCO", "N(C)C", "CCCC",
        "C(=O)OC", "OC(C)C", "CCN", "Cl", "C#N",
    ]
    rings = ["c1ccccc1", "c1ccncc1", "c1cccs1", "c1ccc2ccccc2c1", "C1CCCCC1"]

    ids, smiles, mols = [], [], []
    sub_idx, ring_idx = [], []
    for si, sub in enumerate(subs):
        for ri, ring in enumerate(rings):
            for variant in range(3):
                spacer = "C" * variant  # 同一 R1/R2 の近縁体を作る
                smi = f"{sub}{spacer}c1ccc(cc1)-{ring}"
                mol = Chem.MolFromSmiles(smi)
                if mol is None:
                    continue
                ids.append(f"SYN-{len(ids):04d}")
                smiles.append(Chem.MolToSmiles(mol))
                mols.append(mol)
                sub_idx.append(si)
                ring_idx.append(ri)

    m = len(ids)
    sub_effect = np.array([0.0, 0.4, -0.3, 0.2, 0.1, 0.0, -0.2, 0.3, 0.5, -0.1])
    ring_effect = np.array([0.0, 0.6, -0.4, 0.2, -0.5])
    # R1 × R2 の交互作用（L2 分散縮小 / L7 序列逆転を検出させるため）
    interaction = np.outer(
        np.array([0.5, -0.5, 0.3, -0.3, 0.0, 0.2, -0.2, 0.4, -0.4, 0.1]),
        np.array([1.0, -1.0, 0.5, -0.5, 0.0]),
    )
    primary = np.array(
        [
            6.0 + sub_effect[s] + ring_effect[r] + interaction[s, r]
            for s, r in zip(sub_idx, ring_idx)
        ]
    ) + rng.normal(0, 0.25, m)
    primary[rng.random(m) < 0.08] = np.nan

    secondary = primary + rng.normal(0, 0.5, m)
    secondary[primary < np.nanmedian(primary)] = np.nan  # 選択バイアスを意図的に作る

    specs = {
        "EP_PRIMARY": EndpointSpec("EP_PRIMARY", "p", "primary", "none", True),
        "EP_SECONDARY": EndpointSpec("EP_SECONDARY", "s", "secondary", "none", True),
    }
    return Dataset(
        ids=ids,
        smiles=smiles,
        mols=mols,
        endpoints={"EP_PRIMARY": primary, "EP_SECONDARY": secondary},
        specs=specs,
        input_issues={
            "input_rows": m,
            "id_missing": 0,
            "id_duplicated": 0,
            "smiles_blank": 0,
            "smiles_parse_failed": 0,
            "same_id_different_structure": 0,
            "retained_compounds": m,
        },
    )
