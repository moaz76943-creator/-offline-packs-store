import json
import os
from typing import Dict, Any, List, Tuple

REQUIRED_WORD_FIELDS = ["lemma", "pos", "cefr_level", "meaning_ar"]

def validate_canonical_fixture(fixture_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates that test suites execute against immutable, canonical fixtures
    with zero missing mandatory linguistic fields.
    """
    errors = []
    if "fixture_id" not in fixture_data:
        errors.append("Missing 'fixture_id' attribute in canonical fixture")

    words = fixture_data.get("words")
    if not isinstance(words, list) or len(words) == 0:
        return False, ["Fixture 'words' list is missing or empty"]

    for idx, word_entry in enumerate(words):
        for field in REQUIRED_WORD_FIELDS:
            val = word_entry.get(field)
            if val is None or val == "":
                errors.append(f"Word #{idx} ('{word_entry.get('lemma', 'unknown')}') missing required field: '{field}'")

    return len(errors) == 0, errors

def load_and_verify_fixture(fixture_path: str) -> Dict[str, Any]:
    if not os.path.exists(fixture_path):
        raise FileNotFoundError(f"Canonical fixture not found at {fixture_path}")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    valid, errors = validate_canonical_fixture(data)
    if not valid:
        raise ValueError(f"Corrupted canonical fixture: {errors}")
    return data
