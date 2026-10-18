"""Evidence-gated proficiency classification and comparative mapping."""
from .engine import ProficiencyCatalog, ValidationError, validate_curricula

__all__ = ["ProficiencyCatalog", "ValidationError", "validate_curricula"]
