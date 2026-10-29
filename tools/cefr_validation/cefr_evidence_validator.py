import os
from typing import Dict, Any, List, Tuple

VALID_CEFR_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}

def is_safe_sandbox_path(base_dir: str, target_path: str) -> bool:
    """
    Prevents path traversal attacks (CWE-22) by ensuring target path
    is strictly resolved within the base directory sandbox.
    """
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, target_path))
    return target.startswith(base + os.sep) or target == base

def validate_cefr_evidence_entry(entry: Dict[str, Any], base_dir: str = ".") -> Tuple[bool, List[str]]:
    errors = []
    level = entry.get("cefr_level", "").upper().strip()

    if not level or level not in VALID_CEFR_LEVELS:
        errors.append(f"Invalid CEFR level: '{level}'. Allowed: {VALID_CEFR_LEVELS}")

    evidence_file = entry.get("evidence_file", "").strip()
    if evidence_file:
        if not is_safe_sandbox_path(base_dir, evidence_file):
            errors.append(f"Path traversal detected in evidence_file: '{evidence_file}'")

    corpus_citation = entry.get("corpus_citation", "").strip()
    if not corpus_citation:
        errors.append("Missing required corpus citation evidence")

    return len(errors) == 0, errors
