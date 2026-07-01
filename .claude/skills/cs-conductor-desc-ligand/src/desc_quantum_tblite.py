from __future__ import annotations

import math

import numpy as np
from rdkit import Chem

from .desc_3d import get_3d_mol


BOHR_PER_ANGSTROM = 1.8897261246257702
HARTREE_TO_EV = 27.211386245988


def _extract_charge_stats(charges) -> dict:
    if charges is None:
        return {}
    arr = np.asarray(charges, dtype=float)
    return {
        "tblite__charge_min": float(np.min(arr)),
        "tblite__charge_max": float(np.max(arr)),
        "tblite__charge_mean": float(np.mean(arr)),
        "tblite__charge_std": float(np.std(arr)),
        "tblite__charge_positive_sum": float(np.sum(arr[arr > 0])),
        "tblite__charge_negative_sum": float(np.sum(arr[arr < 0])),
    }


def _frontier_from_orbitals(results) -> dict:
    energies = results.get("orbital-energies")
    occupations = results.get("orbital-occupations")
    if energies is None or occupations is None:
        return {}
    energies_ev = np.asarray(energies, dtype=float) * HARTREE_TO_EV
    occ = np.asarray(occupations, dtype=float)
    occupied = energies_ev[occ > 1.0e-8]
    unoccupied = energies_ev[occ <= 1.0e-8]
    if occupied.size == 0 or unoccupied.size == 0:
        return {}
    homo = float(np.max(occupied))
    lumo = float(np.min(unoccupied))
    gap = lumo - homo
    values = {
        "tblite__homo_ev": homo,
        "tblite__lumo_ev": lumo,
        "tblite__homo_lumo_gap_ev": gap,
        "tblite__chemical_potential_ev": 0.5 * (homo + lumo),
        "tblite__hardness_ev": gap,
    }
    if math.isfinite(gap) and abs(gap) > 1.0e-12:
        mu = values["tblite__chemical_potential_ev"]
        values["tblite__softness_ev_inv"] = 1.0 / gap
        values["tblite__electrophilicity_ev"] = (mu * mu) / (2.0 * gap)
    return values


def calc_tblite_xtb_singlepoint(mol, method: str = "GFN2-xTB", charge: float | None = None, uhf: int | None = None) -> dict:
    try:
        from tblite.interface import Calculator
    except ImportError as exc:
        raise RuntimeError(
            "tblite-python is required for L60 tblite_xtb_singlepoint. "
            "In this Windows environment, pip/uv source build may require a C/Fortran compiler; "
            "install a conda-forge environment with tblite-python if needed."
        ) from exc

    mol3d = get_3d_mol(mol)
    conformer = mol3d.GetConformer()
    numbers = np.array([atom.GetAtomicNum() for atom in mol3d.GetAtoms()], dtype=int)
    positions = np.array([list(conformer.GetAtomPosition(i)) for i in range(mol3d.GetNumAtoms())], dtype=float) * BOHR_PER_ANGSTROM
    total_charge = float(Chem.GetFormalCharge(mol3d) if charge is None else charge)
    calc = Calculator(method, numbers, positions, charge=total_charge, uhf=uhf)
    calc.set("verbosity", 0)
    results = calc.singlepoint()

    values = {
        "tblite__energy_hartree": float(results.get("energy")),
        "tblite__energy_ev": float(results.get("energy")) * HARTREE_TO_EV,
        "tblite__method_gfn2_xtb": int(method.upper() == "GFN2-XTB"),
    }
    dipole = results.get("dipole")
    if dipole is not None:
        dipole_arr = np.asarray(dipole, dtype=float)
        values["tblite__dipole_norm"] = float(np.linalg.norm(dipole_arr))
        for i, axis in enumerate(["x", "y", "z"]):
            if i < dipole_arr.size:
                values[f"tblite__dipole_{axis}"] = float(dipole_arr[i])
    values.update(_extract_charge_stats(results.get("charges")))
    values.update(_frontier_from_orbitals(results))
    return values
