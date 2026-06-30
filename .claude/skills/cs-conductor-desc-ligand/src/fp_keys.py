from __future__ import annotations

from rdkit.Chem import MACCSkeys, rdFingerprintGenerator


def _dense_from_sparse(nonzero: dict[int, int], n_bits: int, prefix: str) -> dict:
    values = {f"{prefix}__bit_{i:04d}": 0 for i in range(n_bits)}
    for idx, count in nonzero.items():
        if 0 <= int(idx) < n_bits:
            values[f"{prefix}__bit_{int(idx):04d}"] = int(count)
    return values


def calc_maccs_keys(mol) -> dict:
    fp = MACCSkeys.GenMACCSKeys(mol)
    return {f"maccs__bit_{i:03d}": int(fp.GetBit(i)) for i in range(fp.GetNumBits())}


def calc_atom_pair_fp(mol, n_bits: int = 2048, vector_type: str = "count") -> dict:
    generator = rdFingerprintGenerator.GetAtomPairGenerator(fpSize=n_bits)
    if vector_type == "bit":
        fp = generator.GetFingerprint(mol)
        on_bits = set(fp.GetOnBits())
        return {f"atompair__bit_{i:04d}": int(i in on_bits) for i in range(n_bits)}
    fp = generator.GetCountFingerprint(mol)
    return _dense_from_sparse(fp.GetNonzeroElements(), n_bits, "atompair")


def calc_topological_torsion_fp(mol, n_bits: int = 2048, vector_type: str = "count") -> dict:
    generator = rdFingerprintGenerator.GetTopologicalTorsionGenerator(fpSize=n_bits)
    if vector_type == "bit":
        fp = generator.GetFingerprint(mol)
        on_bits = set(fp.GetOnBits())
        return {f"torsion__bit_{i:04d}": int(i in on_bits) for i in range(n_bits)}
    fp = generator.GetCountFingerprint(mol)
    return _dense_from_sparse(fp.GetNonzeroElements(), n_bits, "torsion")
