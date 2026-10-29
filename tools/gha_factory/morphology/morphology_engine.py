from typing import Dict, Any, List, Tuple

VALID_GENDERS = {"der", "die", "das"}
VALID_AUXILIARIES = {"haben", "sein"}

def validate_morphological_entry(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates attested principal parts for verbs (praeteritum, partizip2, auxiliary)
    and grammatical gender for nouns before admission into production packs.
    """
    errors = []
    lemma = entry.get("lemma", "").strip()
    pos = entry.get("pos", "").lower().strip()

    if not lemma:
        return False, ["Missing or empty lemma"]

    if pos == "verb":
        for field in ["praeteritum", "partizip2", "auxiliary"]:
            if not entry.get(field):
                errors.append(f"Verb '{lemma}' missing mandatory principal part: '{field}'")
        
        aux = entry.get("auxiliary", "").lower().strip()
        if aux and aux not in VALID_AUXILIARIES:
            errors.append(f"Verb '{lemma}' has invalid auxiliary: '{aux}'. Allowed: {VALID_AUXILIARIES}")

    elif pos == "noun":
        gender = entry.get("gender", "").lower().strip()
        if not gender or gender not in VALID_GENDERS:
            errors.append(f"Noun '{lemma}' missing or invalid gender: '{gender}'. Allowed: {VALID_GENDERS}")

    return len(errors) == 0, errors
