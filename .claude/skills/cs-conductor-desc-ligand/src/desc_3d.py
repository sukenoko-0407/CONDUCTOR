from __future__ import annotations

from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Descriptors3D, rdMolDescriptors


def get_3d_mol(mol):
    """Generate or load an RDKit Mol with a 3D conformer."""
    try:
        from .gen_3d_conf import gen_3d_conformer
    except ImportError as exc:
        try:
            from gen_3d_conf import gen_3d_conformer
        except ImportError:
            raise RuntimeError("src.gen_3d_conf.gen_3d_conformer is required for 3D descriptors.") from exc

    result = gen_3d_conformer(mol)
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, Chem.Mol):
        mol3d = result
    elif isinstance(result, (str, Path)):
        supplier = Chem.SDMolSupplier(str(result), removeHs=False)
        mol3d = next((m for m in supplier if m is not None), None)
    else:
        raise RuntimeError(f"Unsupported gen_3d_conformer return type: {type(result)!r}")

    if mol3d is None or mol3d.GetNumConformers() == 0:
        raise RuntimeError("3D conformer generation did not return a molecule with conformers.")
    return mol3d


def calc_rdkit_3d_descriptors(mol3d) -> dict:
    names = [
        "Asphericity",
        "Eccentricity",
        "InertialShapeFactor",
        "NPR1",
        "NPR2",
        "PMI1",
        "PMI2",
        "PMI3",
        "PBF",
        "RadiusOfGyration",
        "SpherocityIndex",
    ]
    result = {}
    for name in names:
        func = getattr(Descriptors3D, name)
        result[f"rdkit3d__{name}"] = func(mol3d)
    return result


def calc_usr_usrcat(mol3d) -> dict:
    result = {}
    for i, value in enumerate(rdMolDescriptors.GetUSR(mol3d)):
        result[f"usr__dim_{i:02d}"] = value
    for i, value in enumerate(rdMolDescriptors.GetUSRCAT(mol3d)):
        result[f"usrcat__dim_{i:02d}"] = value
    return result


def calc_shape_basic(mol3d) -> dict:
    funcs = {
        "PMI1": rdMolDescriptors.CalcPMI1,
        "PMI2": rdMolDescriptors.CalcPMI2,
        "PMI3": rdMolDescriptors.CalcPMI3,
        "NPR1": rdMolDescriptors.CalcNPR1,
        "NPR2": rdMolDescriptors.CalcNPR2,
        "RadiusOfGyration": rdMolDescriptors.CalcRadiusOfGyration,
        "Asphericity": rdMolDescriptors.CalcAsphericity,
        "Eccentricity": rdMolDescriptors.CalcEccentricity,
        "InertialShapeFactor": rdMolDescriptors.CalcInertialShapeFactor,
        "SpherocityIndex": rdMolDescriptors.CalcSpherocityIndex,
    }
    return {f"shape3d__{name}": func(mol3d) for name, func in funcs.items()}
