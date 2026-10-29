import re
from typing import Dict, Any, List, Tuple

BANNED_SEMANTIC_TAGS = {
    "vulgar", "offensive", "slur", "derogatory",
    "hate speech", "obscene", "profanity", "pejorative"
}

def is_content_culturally_compliant(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Enforces cultural policy safety on raw lexical entries.
    Flags words tagged with vulgarity, profanity, or containing derogatory slurs.
    """
    violations = []

    # 1. فحص وسوم المعنى (Sense Tags)
    tags = entry.get("tags", [])
    for tag in tags:
        t_clean = str(tag).lower().strip()
        if t_clean in BANNED_SEMANTIC_TAGS:
            violations.append(f"Prohibited cultural policy tag: '{tag}'")

    # 2. فحص نصوص الشرح والترجمة بالحدود اللفظية الكاملة (Word Boundaries)
    glosses = entry.get("glosses", [])
    for gloss in glosses:
        for banned in BANNED_SEMANTIC_TAGS:
            pattern = r'\b' + re.escape(banned) + r'\b'
            if re.search(pattern, str(gloss), re.IGNORECASE):
                violations.append(f"Prohibited offensive term in gloss: '{banned}'")

    return len(violations) == 0, violations
