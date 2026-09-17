---
name: cs-lens-l7
description: Run the CONDUCTOR 0.2.1 L7 series-pair lens for scaffold-dependent or transferable substituent rankings. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR L7 lens

Invoke `scripts/launch.py` with terminal fragment observations and the selected Endpoint. Collapse duplicate compounds for one series/R-group to one mean and compare only series pairs with at least five common R groups.

Use R-group label permutation for Spearman transferability and paired scaffold-label permutation for the scaffold mean effect. Apply BH to both questions in one L7 family. Emit only ranking reversal, scaffold superiority, or independent-optimization Findings under the fixed rho and q rules.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.7.
