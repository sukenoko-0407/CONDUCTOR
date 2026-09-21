"""CONDUCTOR 0.2.1 report assembly and citation validation."""

from .html_report import render_html_report
from .report import CitationError, EvidenceRegistry, build_entity_components, validate_component_narrative, validate_component_response, validate_finding_tests

__all__ = ["CitationError", "EvidenceRegistry", "build_entity_components", "render_html_report", "validate_component_narrative", "validate_component_response", "validate_finding_tests"]
__version__ = "0.2.1"
