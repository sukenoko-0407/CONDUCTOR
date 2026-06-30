# MOE Coverage Table

This project implements ligand-only descriptors that RDKit can calculate directly. The categories below are not implemented here, but are reasonable MOE supplementation candidates.

| Feature category | Examples | RDKit support | MOE supplementation plan | Input |
|---|---|---:|---|---|
| Advanced 3D-QSAR field | CoMFA/CoMSIA-like fields, interaction fields | Partial/limited | Use MOE 3D-QSAR and field descriptor functions | aligned 3D conformers |
| Pharmacophore descriptor | pharmacophore hypotheses, feature distances | Partial | Use MOE pharmacophore functions | 3D conformers |
| pKa/logD/protomer | predicted pKa, logD, protomer state | Weak | Use MOE or another ionization-state predictor | SMILES/SDF |
| Conformational analysis | conformer ensemble energy, strain | Partial | Use MOE conformational search | 3D conformers |
| Alignment-based descriptor | alignment-dependent shape/field | Limited | Use MOE alignment/QSAR workflow | aligned 3D conformers |
| Electrostatic field | surface ESP, field values | Limited | Use MOE field descriptors | 3D conformers |
| Receptor-independent pharmacophore | feature triplets, pharmacophore fingerprints | Partial | Use MOE pharmacophore fingerprints | 3D conformers |
| Ligand interaction field | MIF-like descriptors | Limited | Use MOE field analysis | 3D conformers |

Input candidates include SMILES, 2D SDF, 3D SDF, aligned 3D conformers, conformer ensembles, docking-pose ligand conformations, and protein-ligand complex PDB files. Complex inputs are reference-only for this project.
