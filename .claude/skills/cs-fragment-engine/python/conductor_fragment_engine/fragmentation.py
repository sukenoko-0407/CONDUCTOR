"""Deterministic three-class fragmentation for CONDUCTOR 0.2.1."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations, product
from typing import Iterable, Literal

from rdkit import Chem

from .chemistry import attachment_neutral_structure, heavy_atom_count


TransformClass = Literal[
    "terminal_substitution",
    "linker_replacement",
    "ring_system_replacement",
]


@dataclass(frozen=True)
class FragmentationRecord:
    compound_id: str
    transform_class: TransformClass
    constant_key: str
    variable_smiles: str
    cut_count: int
    attachment_mapping: tuple[int, ...]
    mapping_status: str
    variable_variants: tuple[str, ...]
    status: Literal["accepted", "ambiguous", "excluded"]
    exclusion_reason: str | None


@dataclass(frozen=True)
class FragmentationConfig:
    min_molecule_heavy_atoms: int = 6
    min_constant_heavy_atoms: int = 4
    max_variable_fraction: float = 0.60
    min_ring_variable_heavy_atoms: int = 3
    max_ring_attachments: int = 4


def _canonical_fragment(molecule: Chem.Mol, labels: dict[int, int]) -> str:
    copy = Chem.Mol(molecule)
    for atom in copy.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
            atom.SetIsotope(labels.get(atom.GetIsotope(), atom.GetIsotope()))
        else:
            atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(copy, canonical=True, isomericSmiles=True)


def _original_indices(molecule: Chem.Mol) -> frozenset[int]:
    return frozenset(
        atom.GetAtomMapNum() - 1
        for atom in molecule.GetAtoms()
        if atom.GetAtomicNum() != 0 and atom.GetAtomMapNum() > 0
    )


def _dummy_tags(molecule: Chem.Mol) -> tuple[int, ...]:
    return tuple(
        sorted(atom.GetIsotope() for atom in molecule.GetAtoms() if atom.GetAtomicNum() == 0)
    )


def _cut_fragments(molecule: Chem.Mol, bond_indices: tuple[int, ...]) -> list[Chem.Mol]:
    tagged = Chem.Mol(molecule)
    for atom in tagged.GetAtoms():
        atom.SetAtomMapNum(atom.GetIdx() + 1)
    labels = [(offset + 1, offset + 1) for offset in range(len(bond_indices))]
    cut = Chem.FragmentOnBonds(
        tagged,
        list(bond_indices),
        addDummies=True,
        dummyLabels=labels,
    )
    return list(Chem.GetMolFrags(cut, asMols=True, sanitizeFrags=True))


def _acyclic_single_bonds(molecule: Chem.Mol) -> list[int]:
    return [
        bond.GetIdx()
        for bond in molecule.GetBonds()
        if bond.GetBondType() == Chem.BondType.SINGLE and not bond.IsInRing()
    ]


def _ring_systems(molecule: Chem.Mol) -> list[frozenset[int]]:
    systems = [set(ring) for ring in molecule.GetRingInfo().AtomRings()]
    changed = True
    while changed:
        changed = False
        merged: list[set[int]] = []
        while systems:
            current = systems.pop()
            overlaps = [other for other in systems if current.intersection(other)]
            if overlaps:
                for other in overlaps:
                    current.update(other)
                    systems.remove(other)
                changed = True
            merged.append(current)
        systems = merged
    return sorted((frozenset(system) for system in systems), key=lambda item: tuple(sorted(item)))


def _label_variants(
    variable: Chem.Mol,
    constants: list[Chem.Mol],
) -> tuple[str, tuple[str, ...], str]:
    """Return one constant key, every symmetry-valid variable key, and status.

    Constants are ordered by their attachment-neutral canonical structures.  Only
    constants with the same neutral key may exchange attachment labels.  This
    enumerates at most 4! mappings and defers pair-level ambiguity detection to
    the database builder, where both sides of a transformation are available.
    """

    entries: list[tuple[str, int, Chem.Mol]] = []
    for constant in constants:
        tags = _dummy_tags(constant)
        if len(tags) != 1:
            raise ValueError("constant_attachment_multiplicity")
        entries.append((attachment_neutral_structure(Chem.MolToSmiles(constant)), tags[0], constant))
    entries.sort(key=lambda item: (item[0], item[1]))

    groups: list[list[tuple[str, int, Chem.Mol]]] = []
    for entry in entries:
        if not groups or groups[-1][0][0] != entry[0]:
            groups.append([entry])
        else:
            groups[-1].append(entry)

    group_orders = [list(permutations(group)) for group in groups]
    variants: set[str] = set()
    constant_keys: set[str] = set()
    for choices in product(*group_orders):
        ordered = [entry for group in choices for entry in group]
        mapping = {entry[1]: label for label, entry in enumerate(ordered, start=1)}
        constant_parts = sorted(_canonical_fragment(entry[2], mapping) for entry in ordered)
        constant_keys.add(" | ".join(constant_parts))
        variants.add(_canonical_fragment(variable, mapping))
    if len(constant_keys) != 1:
        raise ValueError("ambiguous_constant_mapping")
    ordered_variants = tuple(sorted(variants))
    status = "unique" if len(ordered_variants) == 1 else "symmetry_candidate"
    return next(iter(constant_keys)), ordered_variants, status


def _record(
    compound_id: str,
    transform_class: TransformClass,
    variable: Chem.Mol,
    constants: list[Chem.Mol],
    molecule_heavies: int,
    config: FragmentationConfig,
) -> FragmentationRecord:
    cut_count = len(constants)
    try:
        constant_key, variants, mapping_status = _label_variants(variable, constants)
    except ValueError as exc:
        return FragmentationRecord(
            compound_id,
            transform_class,
            "",
            "",
            cut_count,
            tuple(range(1, cut_count + 1)),
            "ambiguous",
            (),
            "ambiguous",
            str(exc),
        )
    variable_heavies = sum(atom.GetAtomicNum() > 1 for atom in variable.GetAtoms())
    constant_heavies = [sum(atom.GetAtomicNum() > 1 for atom in item.GetAtoms()) for item in constants]
    reason: str | None = None
    if any(value < config.min_constant_heavy_atoms for value in constant_heavies):
        reason = "constant_too_small"
    elif variable_heavies / molecule_heavies > config.max_variable_fraction:
        reason = "variable_fraction_exceeded"
    elif transform_class == "ring_system_replacement" and variable_heavies < config.min_ring_variable_heavy_atoms:
        reason = "ring_variable_too_small"
    return FragmentationRecord(
        compound_id,
        transform_class,
        constant_key,
        variants[0],
        cut_count,
        tuple(range(1, cut_count + 1)),
        mapping_status,
        variants,
        "excluded" if reason else "accepted",
        reason,
    )


def _terminal_records(
    compound_id: str,
    molecule: Chem.Mol,
    molecule_heavies: int,
    config: FragmentationConfig,
) -> Iterable[FragmentationRecord]:
    for bond_index in _acyclic_single_bonds(molecule):
        fragments = _cut_fragments(molecule, (bond_index,))
        if len(fragments) != 2:
            continue
        ordered = sorted(
            fragments,
            key=lambda item: (
                sum(atom.GetAtomicNum() > 1 for atom in item.GetAtoms()),
                attachment_neutral_structure(Chem.MolToSmiles(item)),
            ),
        )
        variable, constant = ordered[0], ordered[1]
        yield _record(
            compound_id,
            "terminal_substitution",
            variable,
            [constant],
            molecule_heavies,
            config,
        )


def _linker_records(
    compound_id: str,
    molecule: Chem.Mol,
    molecule_heavies: int,
    config: FragmentationConfig,
) -> Iterable[FragmentationRecord]:
    for bond_indices in combinations(_acyclic_single_bonds(molecule), 2):
        fragments = _cut_fragments(molecule, bond_indices)
        variables = [fragment for fragment in fragments if len(_dummy_tags(fragment)) == 2]
        constants = [fragment for fragment in fragments if len(_dummy_tags(fragment)) == 1]
        if len(variables) != 1 or len(constants) != 2 or len(fragments) != 3:
            continue
        yield _record(
            compound_id,
            "linker_replacement",
            variables[0],
            constants,
            molecule_heavies,
            config,
        )


def _ring_records(
    compound_id: str,
    molecule: Chem.Mol,
    molecule_heavies: int,
    config: FragmentationConfig,
) -> Iterable[FragmentationRecord]:
    for ring_atoms in _ring_systems(molecule):
        exocyclic = sorted(
            bond.GetIdx()
            for bond in molecule.GetBonds()
            if (bond.GetBeginAtomIdx() in ring_atoms) != (bond.GetEndAtomIdx() in ring_atoms)
        )
        if not exocyclic:
            continue
        if len(exocyclic) > config.max_ring_attachments:
            yield FragmentationRecord(
                compound_id,
                "ring_system_replacement",
                "",
                "",
                len(exocyclic),
                tuple(range(1, len(exocyclic) + 1)),
                "excluded",
                (),
                "excluded",
                "ring_attachment_count_exceeded",
            )
            continue
        fragments = _cut_fragments(molecule, tuple(exocyclic))
        # Original atom indices, rather than dummy counts, identify the ring side.
        variables = [fragment for fragment in fragments if ring_atoms.issubset(_original_indices(fragment))]
        if len(variables) != 1:
            yield FragmentationRecord(
                compound_id,
                "ring_system_replacement",
                "",
                "",
                len(exocyclic),
                tuple(range(1, len(exocyclic) + 1)),
                "ambiguous",
                (),
                "ambiguous",
                "ring_component_not_unique",
            )
            continue
        variable = variables[0]
        constants = [fragment for fragment in fragments if fragment is not variable]
        if len(constants) != len(exocyclic):
            yield FragmentationRecord(
                compound_id,
                "ring_system_replacement",
                "",
                "",
                len(exocyclic),
                tuple(range(1, len(exocyclic) + 1)),
                "ambiguous",
                (),
                "ambiguous",
                "ring_constant_attachment_multiplicity",
            )
            continue
        yield _record(
            compound_id,
            "ring_system_replacement",
            variable,
            constants,
            molecule_heavies,
            config,
        )


def fragment_compound(
    compound_id: str,
    smiles: str,
    config: FragmentationConfig | None = None,
) -> list[FragmentationRecord]:
    config = config or FragmentationConfig()
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return [
            FragmentationRecord(
                compound_id,
                "terminal_substitution",
                "",
                "",
                0,
                (),
                "excluded",
                (),
                "excluded",
                "parse_failed",
            )
        ]
    molecule_heavies = molecule.GetNumHeavyAtoms()
    if molecule_heavies < config.min_molecule_heavy_atoms:
        return [
            FragmentationRecord(
                compound_id,
                "terminal_substitution",
                "",
                "",
                0,
                (),
                "excluded",
                (),
                "excluded",
                "molecule_too_small",
            )
        ]
    records = list(_terminal_records(compound_id, molecule, molecule_heavies, config))
    records.extend(_linker_records(compound_id, molecule, molecule_heavies, config))
    records.extend(_ring_records(compound_id, molecule, molecule_heavies, config))
    unique: dict[tuple[object, ...], FragmentationRecord] = {}
    for record in records:
        key = (
            record.transform_class,
            record.constant_key,
            record.variable_smiles,
            record.cut_count,
            record.status,
            record.exclusion_reason,
        )
        unique.setdefault(key, record)
    return [unique[key] for key in sorted(unique, key=lambda item: tuple(str(value) for value in item))]


def pair_variable_mapping(
    left: FragmentationRecord,
    right: FragmentationRecord,
) -> tuple[str, str] | None:
    """Resolve a pair only if all symmetry mappings yield one transform key."""

    possibilities = {
        tuple(sorted((left_variant, right_variant)))
        for left_variant in left.variable_variants
        for right_variant in right.variable_variants
        if left_variant != right_variant
    }
    return next(iter(possibilities)) if len(possibilities) == 1 else None
