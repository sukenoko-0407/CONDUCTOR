---
name: cs-fragment-engine
description: Build the CONDUCTOR 0.2.1 canonical three-class fragmentation database, fragment observations, similar-core mappings, and structural cliff audit artifacts from validated Phase 1 compounds and one Endpoint. Use only inside an explicit CONDUCTOR Run.
allowed-tools: Read, Write, Bash
---

# CONDUCTOR fragment engine

Invoke `scripts/launch.py` with a versioned Execution Request containing exactly one `compounds` input and one `endpoint_table` input. The public operation is `parameters.operation: build_database`.

Enumerate terminal substitution, linker replacement, and ring-system replacement independently. Identify ring variables from original ring atom indices, enforce the constant-size rule on each constant component, retain every exclusion reason, and never merge the three transform classes.

Pair direction is the lexical order of mapped variable SMILES. Collapse duplicate compounds with the same series and fragment to one finite Endpoint mean while preserving their compound IDs. Keep Endpoint values outside `mmp.sqlite`; the canonical database is endpoint-independent and read-only after its completion transaction.

Attachment-aware similarity helpers are the audited pure-function port described in `references/port_audit.md`. No legacy Runtime, target-specific evidence, or reporting behavior may be introduced.

The governing contracts are in `CONDUCTOR_modules/docs/CONDUCTOR_0.2.1_implementation_detail_spec.md`, sections 4.3, 5.2, and 7.4.
