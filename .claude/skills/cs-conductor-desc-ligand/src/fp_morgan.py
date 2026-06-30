from __future__ import annotations

from rdkit.Chem import rdFingerprintGenerator


def _sparse_to_dense(nonzero: dict[int, int], n_bits: int, prefix: str) -> dict:
    values = {f"{prefix}__bit_{i:04d}": 0 for i in range(n_bits)}
    for idx, count in nonzero.items():
        if 0 <= int(idx) < n_bits:
            values[f"{prefix}__bit_{int(idx):04d}"] = int(count)
    return values


def calc_morgan_fingerprint(
    mol,
    radius: int,
    n_bits: int,
    use_features: bool,
    vector_type: str,
    prefix: str,
) -> dict:
    atom_invariants = rdFingerprintGenerator.GetMorganFeatureAtomInvGen() if use_features else None
    generator = rdFingerprintGenerator.GetMorganGenerator(
        radius=radius,
        fpSize=n_bits,
        includeChirality=False,
        useBondTypes=True,
        atomInvariantsGenerator=atom_invariants,
    )
    if vector_type == "bit":
        fp = generator.GetFingerprint(mol)
        on_bits = set(fp.GetOnBits())
        return {f"{prefix}__bit_{i:04d}": int(i in on_bits) for i in range(n_bits)}
    if vector_type == "count":
        fp = generator.GetCountFingerprint(mol)
        return _sparse_to_dense(fp.GetNonzeroElements(), n_bits, prefix)
    raise ValueError(f"Unsupported Morgan vector_type: {vector_type}")
