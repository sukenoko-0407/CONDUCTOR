from __future__ import annotations

import itertools
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_io import write_csv, write_json
from grouping_models import assign_group_ids, registry_entry, stable_hash

try:
    from rdkit import Chem  # type: ignore
    from rdkit import RDLogger  # type: ignore
    from rdkit.Chem import rdFMCS  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    rdFMCS = None
    RDKIT_AVAILABLE = False


MolRow = tuple[str, Any, int, bool]

MCS_CANDIDATE_COLUMNS = [
    "mcs_candidate_id",
    "rank",
    "mcs_smarts",
    "pair_count",
    "heavy_atom_count",
    "sample_compound_support_count",
    "sample_wet_support_count",
    "selected_by_top_n",
    "selected_by_pair_count",
    "selected_by_heavy_atom_count",
    "selected_final",
    "full_compound_count",
    "full_wet_count",
    "full_virtual_count",
    "representative_pair_1",
    "representative_pair_2",
]

MCS_SWEEP_COLUMNS = [
    "top_n",
    "min_pair_count",
    "min_heavy_atoms",
    "selection_mode",
    "selected_core_count",
    "full_membership_count",
    "median_group_size",
    "max_group_size",
    "singleton_group_count",
]


def _valid_mol_rows(compounds: pd.DataFrame) -> list[MolRow]:
    rows: list[MolRow] = []
    for _, row in compounds.sort_values("compound_id").iterrows():
        mol = Chem.MolFromSmiles(str(row.get("canonical_smiles", "")))
        if mol is None:
            continue
        rows.append(
            (
                str(row["compound_id"]),
                mol,
                int(mol.GetNumHeavyAtoms()),
                bool(row.get("is_virtual", False)) if "is_virtual" in compounds.columns else False,
            )
        )
    return rows


def _sample_mol_rows(mol_rows: list[MolRow], cfg: dict[str, Any]) -> tuple[list[MolRow], dict[str, Any]]:
    max_sample = int(cfg.get("max_mcs_sample_compounds", cfg.get("max_sample_compounds", 1000)))
    seed = int(cfg.get("random_seed", 42))
    strategy = str(cfg.get("sampling_strategy", "random_wet_first"))
    rng = random.Random(seed)

    if len(mol_rows) <= max_sample:
        sampled = list(mol_rows)
        rng.shuffle(sampled)
    elif strategy == "random_wet_first":
        wet = [row for row in mol_rows if not row[3]]
        virtual = [row for row in mol_rows if row[3]]
        rng.shuffle(wet)
        rng.shuffle(virtual)
        sampled = (wet + virtual)[:max_sample]
    else:
        sampled = list(mol_rows)
        rng.shuffle(sampled)
        sampled = sampled[:max_sample]

    sampled = sorted(sampled, key=lambda row: row[0])
    metadata = {
        "strategy": strategy,
        "random_seed": seed,
        "max_mcs_sample_compounds": max_sample,
        "max_mcs_pair_count": int(cfg.get("max_mcs_pair_count", 1000)),
        "valid_compound_count": len(mol_rows),
        "sampled_compound_count": len(sampled),
        "sampled_wet_count": sum(1 for row in sampled if not row[3]),
        "sampled_virtual_count": sum(1 for row in sampled if row[3]),
        "all_pair_count": len(sampled) * (len(sampled) - 1) // 2,
    }
    return sampled, metadata


def _find_mcs_for_pair(left: MolRow, right: MolRow, cfg: dict[str, Any]) -> tuple[str, int] | None:
    timeout = int(cfg.get("timeout_seconds_per_pair", 5))
    _, mol_a, atoms_a, _ = left
    _, mol_b, atoms_b, _ = right
    min_fraction = float(cfg.get("min_mcs_fraction_of_smaller_molecule", 0.4))
    try:
        result = rdFMCS.FindMCS(
            [mol_a, mol_b],
            timeout=timeout,
            ringMatchesRingOnly=bool(cfg.get("ringMatchesRingOnly", True)),
            completeRingsOnly=bool(cfg.get("completeRingsOnly", True)),
            matchValences=bool(cfg.get("matchValences", True)),
        )
    except Exception:
        return None
    if result.canceled or not result.smartsString:
        return None
    heavy_atoms = int(result.numAtoms)
    if heavy_atoms / max(1, min(atoms_a, atoms_b)) < min_fraction:
        return None
    return result.smartsString, heavy_atoms


def _support_counts(query: Any, rows: list[MolRow]) -> tuple[set[str], set[str], set[str]]:
    members: set[str] = set()
    wet: set[str] = set()
    virtual: set[str] = set()
    for compound_id, mol, _, is_virtual in rows:
        try:
            matched = bool(mol.HasSubstructMatch(query))
        except Exception:
            matched = False
        if not matched:
            continue
        members.add(compound_id)
        if is_virtual:
            virtual.add(compound_id)
        else:
            wet.add(compound_id)
    return members, wet, virtual


def _selection_flag(rank: int, pair_count: int, heavy_atoms: int, cfg: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
    top_n = int(cfg.get("candidate_top_n", cfg.get("mcs_candidate_top_n", 50)))
    min_pair_count = int(cfg.get("candidate_min_pair_count", cfg.get("min_pair_count", 10)))
    min_heavy_atoms = int(cfg.get("min_mcs_heavy_atoms", 8))
    mode = str(cfg.get("selection_mode", "intersection"))

    by_top_n = rank <= top_n
    by_pair_count = pair_count >= min_pair_count
    by_heavy_atoms = heavy_atoms >= min_heavy_atoms

    if mode == "union":
        final = by_top_n or by_pair_count or by_heavy_atoms
    elif mode == "top_n_only":
        final = by_top_n
    elif mode == "count_cutoff_only":
        final = by_pair_count
    elif mode == "heavy_atom_cutoff_only":
        final = by_heavy_atoms
    else:
        final = by_top_n and by_pair_count and by_heavy_atoms
    return by_top_n, by_pair_count, by_heavy_atoms, final


def _candidate_rows(
    candidates: dict[str, dict[str, Any]],
    sample_rows: list[MolRow],
    all_rows: list[MolRow],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates.values(),
        key=lambda row: (-int(row["pair_count"]), -int(row["heavy_atom_count"]), str(row["mcs_smarts"])),
    )
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ordered, start=1):
        smarts = str(candidate["mcs_smarts"])
        query = Chem.MolFromSmarts(smarts)
        if query is None:
            continue
        sample_members, sample_wet, _ = _support_counts(query, sample_rows)
        full_members, full_wet, full_virtual = _support_counts(query, all_rows)
        by_top_n, by_pair_count, by_heavy_atoms, selected = _selection_flag(
            rank,
            int(candidate["pair_count"]),
            int(candidate["heavy_atom_count"]),
            cfg,
        )
        representative_pairs = sorted(candidate["representative_pairs"])[:2]
        rows.append(
            {
                "mcs_candidate_id": f"MCS_CAND_{rank:04d}",
                "rank": rank,
                "mcs_smarts": smarts,
                "pair_count": int(candidate["pair_count"]),
                "heavy_atom_count": int(candidate["heavy_atom_count"]),
                "sample_compound_support_count": len(sample_members),
                "sample_wet_support_count": len(sample_wet),
                "selected_by_top_n": by_top_n,
                "selected_by_pair_count": by_pair_count,
                "selected_by_heavy_atom_count": by_heavy_atoms,
                "selected_final": selected,
                "full_compound_count": len(full_members),
                "full_wet_count": len(full_wet),
                "full_virtual_count": len(full_virtual),
                "full_compound_ids": sorted(full_members),
                "representative_pair_1": "|".join(representative_pairs[0]) if len(representative_pairs) >= 1 else "",
                "representative_pair_2": "|".join(representative_pairs[1]) if len(representative_pairs) >= 2 else "",
            }
        )
    return rows


def _parameter_sweep_rows(candidate_rows: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    sweep = cfg.get("parameter_sweep", {}) or {}
    if not bool(sweep.get("enabled", True)):
        return []

    top_values = [int(value) for value in sweep.get("top_n_values", [10, 20, 50, 100, 200])]
    pair_values = [int(value) for value in sweep.get("min_pair_count_values", [3, 5, 10, 20, 50, 100])]
    atom_values = [int(value) for value in sweep.get("min_heavy_atoms_values", [6, 8, 10, 12, 15, 20])]
    mode = str(cfg.get("selection_mode", "intersection"))
    rows: list[dict[str, Any]] = []

    for top_n, min_pair_count, min_atoms in itertools.product(top_values, pair_values, atom_values):
        selected: list[dict[str, Any]] = []
        for row in candidate_rows:
            by_top = int(row["rank"]) <= top_n
            by_pair = int(row["pair_count"]) >= min_pair_count
            by_atom = int(row["heavy_atom_count"]) >= min_atoms
            if mode == "union":
                final = by_top or by_pair or by_atom
            elif mode == "top_n_only":
                final = by_top
            elif mode == "count_cutoff_only":
                final = by_pair
            elif mode == "heavy_atom_cutoff_only":
                final = by_atom
            else:
                final = by_top and by_pair and by_atom
            if final:
                selected.append(row)

        sizes = [int(row["full_compound_count"]) for row in selected]
        rows.append(
            {
                "top_n": top_n,
                "min_pair_count": min_pair_count,
                "min_heavy_atoms": min_atoms,
                "selection_mode": mode,
                "selected_core_count": len(selected),
                "full_membership_count": sum(sizes),
                "median_group_size": float(pd.Series(sizes).median()) if sizes else 0.0,
                "max_group_size": max(sizes) if sizes else 0,
                "singleton_group_count": sum(1 for size in sizes if size == 1),
            }
        )
    return rows


def _write_figures(candidate_rows: list[dict[str, Any]], sweep_rows: list[dict[str, Any]], outdir: Path, cfg: dict[str, Any]) -> list[str]:
    if not bool(cfg.get("write_mcs_figures", True)):
        return []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return [f"matplotlib is not available; skipped MCS figures: {exc}"]

    figure_dir = outdir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    def save_hist(values: list[int], title: str, xlabel: str, filename: str) -> None:
        plt.figure(figsize=(7, 4))
        if values:
            plt.hist(values, bins=min(40, max(5, len(set(values)))))
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel("candidate core count")
        plt.tight_layout()
        plt.savefig(figure_dir / filename, dpi=160)
        plt.close()

    save_hist([int(row["pair_count"]) for row in candidate_rows], "MCS Pair Count Distribution", "pair_count", "mcs_pair_count_distribution.png")
    save_hist([int(row["heavy_atom_count"]) for row in candidate_rows], "MCS Heavy Atom Count Distribution", "heavy_atom_count", "mcs_heavy_atom_distribution.png")

    sweep_df = pd.DataFrame(sweep_rows)
    if sweep_df.empty:
        return warnings

    default_pair = int(cfg.get("candidate_min_pair_count", cfg.get("min_pair_count", 10)))
    default_atoms = int(cfg.get("min_mcs_heavy_atoms", 8))
    default_top = int(cfg.get("candidate_top_n", 50))

    top_df = sweep_df[(sweep_df["min_pair_count"] == default_pair) & (sweep_df["min_heavy_atoms"] == default_atoms)]
    if not top_df.empty:
        plt.figure(figsize=(7, 4))
        plt.plot(top_df["top_n"], top_df["selected_core_count"], marker="o", label="selected_core_count")
        plt.plot(top_df["top_n"], top_df["full_membership_count"], marker="s", label="full_membership_count")
        plt.xlabel("TopN")
        plt.ylabel("count")
        plt.title("MCS TopN Sensitivity")
        plt.legend()
        plt.tight_layout()
        plt.savefig(figure_dir / "mcs_topn_sensitivity.png", dpi=160)
        plt.close()

    pair_df = sweep_df[(sweep_df["top_n"] == default_top) & (sweep_df["min_heavy_atoms"] == default_atoms)]
    if not pair_df.empty:
        plt.figure(figsize=(7, 4))
        plt.plot(pair_df["min_pair_count"], pair_df["selected_core_count"], marker="o", label="selected_core_count")
        plt.plot(pair_df["min_pair_count"], pair_df["full_membership_count"], marker="s", label="full_membership_count")
        plt.xlabel("min_pair_count K")
        plt.ylabel("count")
        plt.title("MCS Pair Count Cutoff Sensitivity")
        plt.legend()
        plt.tight_layout()
        plt.savefig(figure_dir / "mcs_pair_count_cutoff_sensitivity.png", dpi=160)
        plt.close()

    atom_df = sweep_df[(sweep_df["top_n"] == default_top) & (sweep_df["min_pair_count"] == default_pair)]
    if not atom_df.empty:
        plt.figure(figsize=(7, 4))
        plt.plot(atom_df["min_heavy_atoms"], atom_df["selected_core_count"], marker="o", label="selected_core_count")
        plt.plot(atom_df["min_heavy_atoms"], atom_df["full_membership_count"], marker="s", label="full_membership_count")
        plt.xlabel("min_heavy_atoms H")
        plt.ylabel("count")
        plt.title("MCS Heavy Atom Cutoff Sensitivity")
        plt.legend()
        plt.tight_layout()
        plt.savefig(figure_dir / "mcs_heavy_atom_cutoff_sensitivity.png", dpi=160)
        plt.close()

    heat_df = sweep_df[sweep_df["top_n"] == default_top]
    if not heat_df.empty:
        pivot = heat_df.pivot_table(index="min_heavy_atoms", columns="min_pair_count", values="selected_core_count", aggfunc="max", fill_value=0)
        plt.figure(figsize=(8, 5))
        plt.imshow(pivot.values, aspect="auto", origin="lower")
        plt.colorbar(label="selected_core_count")
        plt.xticks(range(len(pivot.columns)), [str(item) for item in pivot.columns])
        plt.yticks(range(len(pivot.index)), [str(item) for item in pivot.index])
        plt.xlabel("min_pair_count K")
        plt.ylabel("min_heavy_atoms H")
        plt.title(f"MCS Parameter Heatmap (TopN={default_top})")
        plt.tight_layout()
        plt.savefig(figure_dir / "mcs_parameter_heatmap.png", dpi=160)
        plt.close()

    return warnings


def _write_diagnostics(
    candidate_rows: list[dict[str, Any]],
    sweep_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    outdir: Path | None,
    cfg: dict[str, Any],
) -> list[str]:
    if outdir is None or not bool(cfg.get("write_mcs_diagnostics", True)):
        return []
    serializable_candidates = []
    for row in candidate_rows:
        copied = dict(row)
        copied.pop("full_compound_ids", None)
        serializable_candidates.append(copied)
    write_csv(outdir / "mcs_candidate_cores.csv", serializable_candidates, MCS_CANDIDATE_COLUMNS)
    write_csv(outdir / "mcs_parameter_sweep.csv", sweep_rows, MCS_SWEEP_COLUMNS)
    write_json(outdir / "mcs_sampling_metadata.json", metadata)
    return _write_figures(candidate_rows, sweep_rows, outdir, cfg)


def build_mcs_groups(
    compounds: pd.DataFrame,
    config: dict[str, Any],
    outdir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not RDKIT_AVAILABLE:
        return [], [], ["RDKit is not installed; MCS groups were skipped."]

    cfg = config or {}
    warnings: list[str] = []
    all_rows = _valid_mol_rows(compounds)
    sample_rows, metadata = _sample_mol_rows(all_rows, cfg)
    if len(sample_rows) < 2:
        warnings.append("Fewer than two valid sampled compounds; MCS groups were skipped.")
        _write_diagnostics([], [], metadata, Path(outdir) if outdir else None, cfg)
        return [], [], warnings

    pairs = list(itertools.combinations(sample_rows, 2))
    max_pairs = int(cfg.get("max_mcs_pair_count", len(pairs)))
    if max_pairs > 0 and len(pairs) > max_pairs:
        rng = random.Random(int(cfg.get("random_seed", 42)))
        rng.shuffle(pairs)
        pairs = sorted(pairs[:max_pairs], key=lambda pair: (pair[0][0], pair[1][0]))
        warnings.append(f"MCS pair mining was capped at max_mcs_pair_count={max_pairs} out of {metadata['all_pair_count']} possible sampled pairs.")
    metadata["evaluated_pair_count"] = len(pairs)

    candidates: dict[str, dict[str, Any]] = {}
    for left, right in pairs:
        result = _find_mcs_for_pair(left, right, cfg)
        if result is None:
            continue
        smarts, heavy_atoms = result
        candidate = candidates.setdefault(
            smarts,
            {
                "mcs_smarts": smarts,
                "pair_count": 0,
                "heavy_atom_count": heavy_atoms,
                "representative_pairs": set(),
            },
        )
        candidate["pair_count"] += 1
        candidate["heavy_atom_count"] = max(int(candidate["heavy_atom_count"]), heavy_atoms)
        if len(candidate["representative_pairs"]) < 10:
            candidate["representative_pairs"].add(tuple(sorted((left[0], right[0]))))

    candidate_rows = _candidate_rows(candidates, sample_rows, all_rows, cfg)
    selected_candidates = [row for row in candidate_rows if bool(row["selected_final"])]
    sweep_rows = _parameter_sweep_rows(candidate_rows, cfg)
    warnings.extend(_write_diagnostics(candidate_rows, sweep_rows, metadata, Path(outdir) if outdir else None, cfg))

    pending: list[dict[str, Any]] = []
    for row in selected_candidates:
        compound_ids = list(row["full_compound_ids"])
        if not compound_ids:
            continue
        pending.append(
            {
                "group_label": f"MCS_CORE_{stable_hash(row['mcs_smarts'], 8)}",
                "mcs_smarts": row["mcs_smarts"],
                "compound_ids": sorted(compound_ids),
                "pair_count": int(row["pair_count"]),
                "heavy_atoms": int(row["heavy_atom_count"]),
                "sample_compound_support_count": int(row["sample_compound_support_count"]),
                "sample_wet_support_count": int(row["sample_wet_support_count"]),
                "rank": int(row["rank"]),
                "selection_flags": {
                    "selected_by_top_n": bool(row["selected_by_top_n"]),
                    "selected_by_pair_count": bool(row["selected_by_pair_count"]),
                    "selected_by_heavy_atom_count": bool(row["selected_by_heavy_atom_count"]),
                    "selection_mode": str(cfg.get("selection_mode", "intersection")),
                },
                "sort_key": f"{int(row['rank']):04d}:{row['mcs_smarts']}",
            }
        )

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    for item in assign_group_ids(pending, "MCS"):
        group_id = item["group_id"]
        registry.append(
            registry_entry(
                group_id=group_id,
                label=item["group_label"],
                group_type="frequent_mcs_core",
                source="mcs_group_builder",
                source_column=None,
                definition={
                    "method": "sampled_frequent_mcs",
                    "mcs_smarts": item["mcs_smarts"],
                    "parameters": {
                        "max_mcs_sample_compounds": int(cfg.get("max_mcs_sample_compounds", 1000)),
                        "max_mcs_pair_count": int(cfg.get("max_mcs_pair_count", 1000)),
                        "sampling_strategy": str(cfg.get("sampling_strategy", "random_wet_first")),
                        "random_seed": int(cfg.get("random_seed", 42)),
                        "candidate_top_n": int(cfg.get("candidate_top_n", 50)),
                        "candidate_min_pair_count": int(cfg.get("candidate_min_pair_count", cfg.get("min_pair_count", 10))),
                        "min_mcs_heavy_atoms": int(cfg.get("min_mcs_heavy_atoms", 8)),
                        "selection_mode": str(cfg.get("selection_mode", "intersection")),
                        "min_mcs_fraction_of_smaller_molecule": float(cfg.get("min_mcs_fraction_of_smaller_molecule", 0.4)),
                        "timeout_seconds_per_pair": int(cfg.get("timeout_seconds_per_pair", 5)),
                    },
                    "sampling_metadata": metadata,
                    "rank": item["rank"],
                    "pair_count": item["pair_count"],
                    "heavy_atoms": item["heavy_atoms"],
                    "sample_compound_support_count": item["sample_compound_support_count"],
                    "sample_wet_support_count": item["sample_wet_support_count"],
                    "selection_flags": item["selection_flags"],
                },
                compounds=compounds,
                compound_ids=item["compound_ids"],
            )
        )
        for compound_id in item["compound_ids"]:
            membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": "mcs",
                    "membership_reason": f"contains_{item['group_label']}",
                }
            )

    return registry, membership, warnings
