# A008 MMP transformation evidence

Version 0.1.11 replaces Type-I/II/III with two modes: `target` analyzes explicit Run compound IDs, while `database` builds a Target-independent canonical MMP database.

The standard Runtime supplies analysis-unit Top1 plus Global Top1 to `target`. Human On-demand requests use the same mode and name their own Targets. A compatible canonical database is reused read-only; otherwise `target` invokes the same builder once.

The database retains a fixed structural direction and signed delta. Target reports always place Target (or the Target-matched side) at the arrow end and retain a signed Target-oriented delta. Positive values support the Target Endpoint; negative values are improvement clues. This changes the reading, not the intrinsic quality of the evidence. Direct and Transferred evidence remain separate provenance classes.

Both 1-cut and 2-cut are generated and kept separate. 2-cut structural classes are Target-independent. Similar-core transfer uses attachment topology, Core similarity, attachment-aware MCS, and Environment class. Proposed structures are labelled Virtual unless they match an observed Run compound.

Target reports are offline, PC-wide Interactive HTML workspaces with a compact relationship map and click-driven detail drawer. A009 receives only versioned static-map paths through `mmp_report_index.json`.

The following defaults remain provisional until sample-data human checkpoints are approved: 2-cut size thresholds, standard cut SMARTS, similar-core thresholds, and maximum embedded evidence rows.

See [references/mmp_contract.md](references/mmp_contract.md) and the repository 0.1.11 specification/implementation plan.
