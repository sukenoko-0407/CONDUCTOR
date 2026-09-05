# Internal claim-source ledger

This file supports `report-source.md` and is not an implementation specification.

| Claim | Primary source | Use |
|---|---|---|
| mmpdb separates rules from radius-specific rule environments and stores property-change distributions | https://github.com/rdkit/mmpdb | Evidence key and context design |
| Chemical context can separate otherwise hidden positive and negative MMP trends | https://pubmed.ncbi.nlm.nih.gov/20873842/ | Context conflict warning |
| Direction-first analysis and chemically specific MMP subsets are informative | https://pubmed.ncbi.nlm.nih.gov/28967750/ | Favorable/N before magnitude |
| Experimental uncertainty changes interpretation of MMP significance | https://pubmed.ncbi.nlm.nih.gov/24738976/ | Noise caveat |
| High-level transform results should drill into plots and raw structures | https://github.com/Merck/matcher | Report navigation |
| SAR matrices expose core/substituent combinations and missing analogs | https://pmc.ncbi.nlm.nih.gov/articles/PMC4215758/ | Conditional matrix |
| Matched molecular series networks support SAR transfer and reduce reliance on isolated pairs | https://pubmed.ncbi.nlm.nih.gov/30108724/ | Conditional network |
| Nonadditivity can encode real structural changes or assay artifacts and violates additive MMP assumptions | https://pubmed.ncbi.nlm.nih.gov/25760829/ | Future nonadditivity detector |
| Nonadditivity can be analyzed using pairs of matched pairs | https://pubmed.ncbi.nlm.nih.gov/31508950/ | 2x2 cycle proposal |
| Matched-pair differences can be more robust to inter-assay variability, while curation still matters | https://pmc.ncbi.nlm.nih.gov/articles/PMC11748845/ | Assay curation caveat |
| 3D MMP visualization can project changed moieties and pharmacophore differences into binding sites | https://pubmed.ncbi.nlm.nih.gov/25244105/ | Optional 3D view only with evidence |
| Recurrent transformations can become prospective medicinal chemistry design moves | https://pubs.acs.org/doi/10.1021/acs.jcim.0c01143 | Future playbook, separate from observed evidence |
| A color-coded R-group replacement matrix can drill down to complete structures and activity changes | https://cas-biofinder.zendesk.com/hc/en-us/articles/37303631485965-March-2025-Matched-Molecular-Pair-Analysis-MMPA | Conditional interactive matrix |
| Observed and model-predicted property deltas can be compared on matched pairs | https://pmc.ncbi.nlm.nih.gov/articles/PMC4272757/ | Future A005 × A008 model audit |
