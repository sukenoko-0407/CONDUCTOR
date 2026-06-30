from __future__ import annotations

import math

from rdkit import Chem
from rdkit.Chem import Descriptors, Fragments, rdMolDescriptors


def _clean_value(value):
    try:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
    except TypeError:
        pass
    return value


def calc_rdkit_2d_descriptors(mol) -> dict:
    result = {}
    for name, func in Descriptors.descList:
        try:
            result[f"rdkit2d__{name}"] = _clean_value(func(mol))
        except Exception:
            result[f"rdkit2d__{name}"] = None

    extras = {
        "LabuteASA": rdMolDescriptors.CalcLabuteASA,
        "TPSA": rdMolDescriptors.CalcTPSA,
        "FractionCSP3": rdMolDescriptors.CalcFractionCSP3,
        "NumRings": rdMolDescriptors.CalcNumRings,
        "NumAromaticRings": rdMolDescriptors.CalcNumAromaticRings,
        "NumAliphaticRings": rdMolDescriptors.CalcNumAliphaticRings,
        "NumSaturatedRings": rdMolDescriptors.CalcNumSaturatedRings,
        "NumHeteroatoms": rdMolDescriptors.CalcNumHeteroatoms,
        "FormalCharge": Chem.GetFormalCharge,
    }
    for name, func in extras.items():
        key = f"rdkit2d__{name}"
        if key not in result:
            try:
                result[key] = _clean_value(func(mol))
            except Exception:
                result[key] = None
    return result


def calc_rdkit_fragment_counts(mol) -> dict:
    result = {}
    for name in sorted(dir(Fragments)):
        if not name.startswith("fr_"):
            continue
        func = getattr(Fragments, name)
        if not callable(func):
            continue
        try:
            result[f"rdfrag__{name}"] = func(mol)
        except Exception:
            result[f"rdfrag__{name}"] = None
    return result
