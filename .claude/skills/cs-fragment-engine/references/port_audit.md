# MMP pure-function port audit

- Source commit: `470d312d250ba55b5a564ced8211882b32164a97`
- Source paths:
  - `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/mmp_0111_model.py`
  - `.claude/skills/cs-analysis-matched-molecular-pairs/scripts/mmp_engine.py`
- Destination: `python/conductor_fragment_engine/chemistry.py`
- Ported: attachment-neutral canonicalization, heavy-atom counting, attachment topology/environment signatures, attachment-aware Tanimoto/MCS mapping.
- Excluded: Runtime integration, Target-specific evidence, HTML/report generation, native mmpdb process control, and 0.1.x schema/database writers.
- Adaptation: stable IDs use the 0.2.1 canonical JSON implementation from `conductor-stat-core`; mappings return typed diagnostics consumed by the new immutable database builder.
