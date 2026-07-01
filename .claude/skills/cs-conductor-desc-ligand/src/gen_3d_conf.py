from __future__ import annotations

import argparse
import math
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem


def _embed_conformers(mol: Chem.Mol, num_confs: int, random_seed: int, prune_rms_thresh: float) -> list[int]:
    params = AllChem.ETKDGv3()
    params.randomSeed = int(random_seed)
    params.pruneRmsThresh = float(prune_rms_thresh)
    params.useSmallRingTorsions = True
    params.useMacrocycleTorsions = True
    conf_ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=int(num_confs), params=params))
    if conf_ids:
        return conf_ids

    params.useRandomCoords = True
    return list(AllChem.EmbedMultipleConfs(mol, numConfs=int(num_confs), params=params))


def _optimize_mmff(mol: Chem.Mol, max_iters: int, variant: str) -> tuple[str, list[tuple[int, float]]]:
    if not AllChem.MMFFHasAllMoleculeParams(mol):
        return "", []
    results = AllChem.MMFFOptimizeMoleculeConfs(
        mol,
        numThreads=0,
        maxIters=int(max_iters),
        mmffVariant=variant,
    )
    return variant, [(int(not_converged), float(energy)) for not_converged, energy in results]


def _optimize_uff(mol: Chem.Mol, max_iters: int) -> tuple[str, list[tuple[int, float]]]:
    if not AllChem.UFFHasAllMoleculeParams(mol):
        return "", []
    results = AllChem.UFFOptimizeMoleculeConfs(
        mol,
        numThreads=0,
        maxIters=int(max_iters),
    )
    return "UFF", [(int(not_converged), float(energy)) for not_converged, energy in results]


def _select_lowest_energy_conformer(
    mol: Chem.Mol,
    conf_ids: list[int],
    energies: list[tuple[int, float]],
    method: str,
) -> Chem.Mol:
    scored: list[tuple[float, int, int]] = []
    for conf_id, (not_converged, energy) in zip(conf_ids, energies):
        if math.isfinite(energy):
            scored.append((energy, int(conf_id), int(not_converged)))
    if not scored:
        raise RuntimeError(f"{method} minimization did not produce finite conformer energies.")

    energy, conf_id, not_converged = min(scored, key=lambda item: item[0])
    selected = Chem.Mol(mol)
    selected.RemoveAllConformers()
    conformer = Chem.Conformer(mol.GetConformer(conf_id))
    conformer.SetId(0)
    selected.AddConformer(conformer, assignId=True)
    selected.SetProp("_ConformerMethod", method)
    selected.SetDoubleProp("_ConformerEnergy", float(energy))
    selected.SetIntProp("_ConformerConverged", 0 if not_converged else 1)
    return selected


def gen_3d_conformer(
    mol: Chem.Mol,
    num_confs: int = 20,
    random_seed: int = 61453,
    prune_rms_thresh: float = 0.5,
    max_iters: int = 200,
    mmff_variant: str = "MMFF94s",
    fallback_to_uff: bool = True,
) -> Chem.Mol:
    """Generate low-cost RDKit 3D conformers and return the lowest-energy minimized conformer.

    The returned molecule has explicit hydrogens and exactly one conformer.
    """
    if mol is None:
        raise ValueError("mol must not be None.")
    if num_confs < 1:
        raise ValueError("num_confs must be >= 1.")

    work = Chem.AddHs(Chem.Mol(mol))
    conf_ids = _embed_conformers(work, num_confs, random_seed, prune_rms_thresh)
    if not conf_ids:
        raise RuntimeError("RDKit ETKDG conformer embedding failed.")

    method, energies = _optimize_mmff(work, max_iters, mmff_variant)
    if not energies and fallback_to_uff:
        method, energies = _optimize_uff(work, max_iters)
    if not energies:
        raise RuntimeError("Neither MMFF nor UFF parameters are available for this molecule.")

    return _select_lowest_energy_conformer(work, conf_ids, energies, method)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one low-energy RDKit 3D conformer from a SMILES string.")
    parser.add_argument("--smiles", required=True, help="Input SMILES.")
    parser.add_argument("--output-sdf", default=None, help="Optional output SDF path.")
    parser.add_argument("--num-confs", type=int, default=20)
    parser.add_argument("--random-seed", type=int, default=61453)
    parser.add_argument("--max-iters", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mol = Chem.MolFromSmiles(args.smiles)
    if mol is None:
        raise ValueError("Invalid input SMILES.")
    mol3d = gen_3d_conformer(
        mol,
        num_confs=args.num_confs,
        random_seed=args.random_seed,
        max_iters=args.max_iters,
    )
    print(
        {
            "method": mol3d.GetProp("_ConformerMethod"),
            "energy": mol3d.GetDoubleProp("_ConformerEnergy"),
            "converged": bool(mol3d.GetIntProp("_ConformerConverged")),
            "num_atoms": mol3d.GetNumAtoms(),
            "num_conformers": mol3d.GetNumConformers(),
        }
    )
    if args.output_sdf:
        output = Path(args.output_sdf)
        output.parent.mkdir(parents=True, exist_ok=True)
        writer = Chem.SDWriter(str(output))
        writer.write(mol3d)
        writer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
