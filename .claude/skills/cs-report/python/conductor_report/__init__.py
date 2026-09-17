"""CONDUCTOR 0.2.1 report assembly and citation validation."""

from .report import CitationError, EvidenceRegistry, build_entity_components, validate_component_narrative, validate_finding_tests

__all__ = ["CitationError", "EvidenceRegistry", "build_entity_components", "validate_component_narrative", "validate_finding_tests"]
__version__ = "0.2.1"
