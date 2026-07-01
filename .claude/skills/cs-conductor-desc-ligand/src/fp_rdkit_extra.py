from __future__ import annotations

from rdkit.Chem import LayeredFingerprint, PatternFingerprint, RDKFingerprint, rdFingerprintGenerator


def _bitvect_to_dense(fp, n_bits: int, prefix: str) -> dict:
    on_bits = set(fp.GetOnBits())
    return {f"{prefix}__bit_{i:04d}": int(i in on_bits) for i in range(n_bits)}


def calc_rdkit_path_fingerprint(mol, n_bits: int = 2048) -> dict:
    fp = RDKFingerprint(mol, fpSize=n_bits)
    return _bitvect_to_dense(fp, n_bits, "rdkitfp")


def calc_rdkit_pattern_fingerprint(mol, n_bits: int = 2048) -> dict:
    fp = PatternFingerprint(mol, fpSize=n_bits)
    return _bitvect_to_dense(fp, n_bits, "patternfp")


def calc_rdkit_layered_fingerprint(mol, n_bits: int = 2048) -> dict:
    fp = LayeredFingerprint(mol, fpSize=n_bits)
    return _bitvect_to_dense(fp, n_bits, "layeredfp")


def calc_avalon_fingerprint(mol, n_bits: int = 2048, vector_type: str = "bit") -> dict:
    try:
        from rdkit.Avalon import pyAvalonTools
    except ImportError as exc:
        raise RuntimeError("RDKit Avalon support is required for L22 avalon_fingerprint.") from exc

    if vector_type == "count":
        fp = pyAvalonTools.GetAvalonCountFP(mol, nBits=n_bits)
        values = {f"avalon__bit_{i:04d}": 0 for i in range(n_bits)}
        for idx, count in fp.GetNonzeroElements().items():
            if 0 <= int(idx) < n_bits:
                values[f"avalon__bit_{int(idx):04d}"] = int(count)
        return values
    fp = pyAvalonTools.GetAvalonFP(mol, n_bits)
    return _bitvect_to_dense(fp, n_bits, "avalon")


def calc_chiral_morgan_fingerprint(mol, radius: int = 2, n_bits: int = 2048) -> dict:
    generator = rdFingerprintGenerator.GetMorganGenerator(
        radius=radius,
        fpSize=n_bits,
        includeChirality=True,
        useBondTypes=True,
    )
    fp = generator.GetFingerprint(mol)
    return _bitvect_to_dense(fp, n_bits, f"chiral_morgan_r{radius}")
