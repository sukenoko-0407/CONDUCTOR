from __future__ import annotations


def get_moe_coverage_table() -> list[dict]:
    return [
        {
            "feature_category": "Advanced 3D-QSAR field",
            "examples": "CoMFA/CoMSIA-like fields, interaction fields",
            "rdkit_support": "limited",
            "moe_plan": "Use MOE 3D-QSAR or field descriptor tools.",
            "input": "aligned 3D conformers",
        },
        {
            "feature_category": "Pharmacophore descriptor",
            "examples": "pharmacophore hypotheses, feature distances",
            "rdkit_support": "partial",
            "moe_plan": "Use MOE pharmacophore tools.",
            "input": "3D conformers",
        },
        {
            "feature_category": "pKa/logD/protomer",
            "examples": "predicted pKa, logD, protomer state",
            "rdkit_support": "weak",
            "moe_plan": "Use MOE or ChemAxon-style prediction.",
            "input": "SMILES or SDF",
        },
        {
            "feature_category": "Conformational analysis",
            "examples": "ensemble energy, strain, conformer statistics",
            "rdkit_support": "partial",
            "moe_plan": "Use MOE conformational search.",
            "input": "3D conformers or conformer ensemble",
        },
        {
            "feature_category": "Alignment-based shape/field",
            "examples": "alignment-dependent shape and field descriptors",
            "rdkit_support": "limited",
            "moe_plan": "Use MOE alignment and QSAR workflows.",
            "input": "aligned 3D conformers",
        },
        {
            "feature_category": "Electrostatic field",
            "examples": "surface ESP and field values",
            "rdkit_support": "limited",
            "moe_plan": "Use MOE field descriptors.",
            "input": "3D conformers",
        },
        {
            "feature_category": "Ligand interaction field",
            "examples": "MIF-like ligand descriptors",
            "rdkit_support": "limited",
            "moe_plan": "Use MOE field analysis.",
            "input": "3D conformers",
        },
    ]
