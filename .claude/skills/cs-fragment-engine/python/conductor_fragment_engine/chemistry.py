"""Pure chemistry helpers ported from the approved 0.1.11 MMP source.

Source commit: 470d312d250ba55b5a564ced8211882b32164a97
Source files: mmp_0111_model.py and mmp_engine.py
Ported functions: attachment_neutral_structure, heavy_atom_count,
attachment_topology_unlabeled, environment_signature, core_similarity_mapping.
The old Runtime, Target-specific evidence, and report code are intentionally absent.
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdFMCS


_CORE_FP_GENERATOR = AllChem.GetMorganGenerator(radius=2, fpSize=2048)


def attachment_neutral_structure(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    molecule = Chem.MolFromSmiles(text)
    if molecule is None:
        molecule = Chem.MolFromSmarts(text)
    if molecule is None:
        return text
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
            atom.SetIsotope(0)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def heavy_atom_count(value: Any) -> int:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return 0
    return sum(atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms())


def attachment_topology_unlabeled(value: Any) -> str:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return ""
    sites: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0:
            continue
        neighbors = list(dummy.GetNeighbors())
        if not neighbors:
            sites.append("unbound")
            continue
        neighbor = neighbors[0]
        bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
        sites.append(
            ":".join(
                [
                    str(neighbor.GetAtomicNum()),
                    "ar" if neighbor.GetIsAromatic() else "al",
                    "ring" if neighbor.IsInRing() else "chain",
                    str(bond.GetBondType()) if bond is not None else "none",
                ]
            )
        )
    return "|".join(sorted(sites))


def environment_signature(value: Any, radius: int) -> str:
    molecule = Chem.MolFromSmiles(str(value)) if value is not None else None
    if molecule is None:
        molecule = Chem.MolFromSmarts(str(value)) if value is not None else None
    if molecule is None:
        return ""
    sites: list[str] = []
    for dummy in molecule.GetAtoms():
        if dummy.GetAtomicNum() != 0 or not dummy.GetNeighbors():
            continue
        frontier = {dummy.GetNeighbors()[0].GetIdx()}
        visited = {dummy.GetIdx()}
        layers: list[str] = []
        for _ in range(radius + 1):
            atoms: list[str] = []
            next_frontier: set[int] = set()
            for atom_index in sorted(frontier):
                if atom_index in visited:
                    continue
                visited.add(atom_index)
                atom = molecule.GetAtomWithIdx(atom_index)
                atoms.append(
                    ":".join(
                        [
                            str(atom.GetAtomicNum()),
                            str(atom.GetFormalCharge()),
                            "ar" if atom.GetIsAromatic() else "al",
                            "ring" if atom.IsInRing() else "chain",
                            str(atom.GetTotalDegree()),
                        ]
                    )
                )
                next_frontier.update(neighbor.GetIdx() for neighbor in atom.GetNeighbors())
            layers.append(",".join(sorted(atoms)))
            frontier = next_frontier - visited
        sites.append("/".join(layers))
    return "|".join(sorted(sites))


def core_similarity_mapping(
    left: str,
    right: str,
    *,
    minimum_tanimoto: float = 0.0,
) -> dict[str, Any]:
    left_original = Chem.MolFromSmiles(left)
    right_original = Chem.MolFromSmiles(right)
    if left_original is None or right_original is None:
        return {"core_tanimoto": 0.0, "mcs_coverage": 0.0, "mapping_status": "failed"}
    if attachment_topology_unlabeled(left) != attachment_topology_unlabeled(right):
        return {"core_tanimoto": 0.0, "mcs_coverage": 0.0, "mapping_status": "failed"}
    left_mol, right_mol = Chem.Mol(left_original), Chem.Mol(right_original)
    for molecule in (left_mol, right_mol):
        for atom in molecule.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(0)
                atom.SetIsotope(0)
    left_fp = _CORE_FP_GENERATOR.GetFingerprint(left_mol)
    right_fp = _CORE_FP_GENERATOR.GetFingerprint(right_mol)
    similarity = float(DataStructs.TanimotoSimilarity(left_fp, right_fp))
    if similarity < minimum_tanimoto:
        return {
            "core_tanimoto": similarity,
            "mcs_coverage": 0.0,
            "mapping_status": "prefilter_rejected",
        }
    for query_mol, target_mol in ((left_mol, right_mol), (right_mol, left_mol)):
        matches = target_mol.GetSubstructMatches(query_mol, uniquify=True, maxMatches=64)
        query_dummies = [atom.GetIdx() for atom in query_mol.GetAtoms() if atom.GetAtomicNum() == 0]
        valid = [
            match
            for match in matches
            if all(target_mol.GetAtomWithIdx(match[index]).GetAtomicNum() == 0 for index in query_dummies)
        ]
        if len(valid) == 1:
            coverage = min(
                heavy_atom_count(left) / max(1, heavy_atom_count(right)),
                heavy_atom_count(right) / max(1, heavy_atom_count(left)),
            )
            return {
                "core_tanimoto": similarity,
                "mcs_coverage": float(coverage),
                "mapping_status": "unique",
                "mcs_smarts": Chem.MolToSmarts(query_mol),
                "mapping_method": "attachment_substructure",
            }
    result = rdFMCS.FindMCS(
        [left_mol, right_mol],
        timeout=3,
        ringMatchesRingOnly=True,
        completeRingsOnly=True,
        atomCompare=rdFMCS.AtomCompare.CompareElements,
        bondCompare=rdFMCS.BondCompare.CompareOrder,
    )
    if result.canceled or not result.smartsString:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    query = Chem.MolFromSmarts(result.smartsString)
    if query is None:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    query_dummies = [atom.GetIdx() for atom in query.GetAtoms() if atom.GetAtomicNum() == 0]
    expected = sum(atom.GetAtomicNum() == 0 for atom in left_mol.GetAtoms())
    if len(query_dummies) < expected:
        return {"core_tanimoto": similarity, "mcs_coverage": 0.0, "mapping_status": "failed"}
    mcs_heavies = sum(atom.GetAtomicNum() > 1 for atom in query.GetAtoms())
    coverage = min(mcs_heavies / max(1, heavy_atom_count(left)), mcs_heavies / max(1, heavy_atom_count(right)))
    left_matches = left_mol.GetSubstructMatches(query, uniquify=True, maxMatches=64)
    right_matches = right_mol.GetSubstructMatches(query, uniquify=True, maxMatches=64)
    mappings: set[tuple[tuple[int, int], ...]] = set()
    for left_match in left_matches:
        for right_match in right_matches:
            mapping: list[tuple[int, int]] = []
            valid = True
            for query_index in query_dummies:
                left_index, right_index = left_match[query_index], right_match[query_index]
                if left_mol.GetAtomWithIdx(left_index).GetAtomicNum() != 0 or right_mol.GetAtomWithIdx(right_index).GetAtomicNum() != 0:
                    valid = False
                    break
                mapping.append((left_index, right_index))
            if valid:
                mappings.add(tuple(sorted(mapping)))
    if len(mappings) == 1:
        status = "unique"
    elif mappings:
        def signatures(molecule: Chem.Mol) -> set[tuple[Any, ...]]:
            values: set[tuple[Any, ...]] = set()
            for dummy in molecule.GetAtoms():
                if dummy.GetAtomicNum() != 0 or not dummy.GetNeighbors():
                    continue
                neighbor = dummy.GetNeighbors()[0]
                bond = molecule.GetBondBetweenAtoms(dummy.GetIdx(), neighbor.GetIdx())
                values.add((neighbor.GetAtomicNum(), neighbor.GetFormalCharge(), neighbor.GetIsAromatic(), neighbor.IsInRing(), str(bond.GetBondType())))
            return values
        status = "symmetry_equivalent" if len(signatures(left_mol)) == 1 and len(signatures(right_mol)) == 1 else "ambiguous"
    else:
        status = "ambiguous"
    return {
        "core_tanimoto": similarity,
        "mcs_coverage": float(coverage),
        "mapping_status": status,
        "mcs_smarts": result.smartsString,
        "mapping_method": "fmcs",
    }
