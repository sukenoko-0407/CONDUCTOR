---
name: cs-lens-l1b
description: Run the CONDUCTOR 0.2.1 L1b conditional-flatness lens over Tier 1/2 distance spaces and fixed representative contexts. Use only inside an explicit CONDUCTOR Run.
---

# CONDUCTOR L1b lens

Invoke `scripts/launch.py` with compounds, Endpoint, context catalog/membership, and the feature-space registry containing distance artifacts.

For each Tier 1/2 space and eligible representative context, predict every member from its ten nearest *other* context members. Reject contexts that cannot supply all ten neighbors. Keep context membership and the distance matrix fixed while permuting Endpoint values inside Murcko blocks. L1a is diagnostic only and must never generate a Finding.

The governing contract is `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, section 7.7.
