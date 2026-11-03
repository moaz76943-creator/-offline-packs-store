#!/usr/bin/env python3
"""
Cultural Policy & Content Filter - Master Constitution Section 08 & 11 Compliant.
Filters out vulgar, illicit, or culturally inappropriate senses and examples
using word-boundary regex and lexical tag inspection without false-positive blocks.
"""
import re
import sys

# Lexicographical tags indicating inappropriate educational content
PROHIBITED_TAGS = {
    'vulgar', 'offensive', 'slur', 'derogatory', 'obscene',
    'profanity', 'taboo', 'pejorative', 'insult'
}

# Explicit boundary-anchored patterns (avoids Scunthorpe substring bugs like 'pass', 'class')
PROHIBITED_PATTERNS = [
    re.compile(r'\b(?:schlampe|arschloch|hurensohn|fotze|scheiße)\b', re.IGNORECASE),
    re.compile(r'\b(?:قحبة|منيوك|شرموطة|كس|عرص)\b', re.IGNORECASE),
    re.compile(r'\b(?:bitch|asshole|whore|motherfucker|cunt)\b', re.IGNORECASE),
]

def is_content_admissible(entry: dict) -> tuple:
    # 1. Tag-based inspection from Wiktextract / Kaikki raw tags
    raw_tags = entry.get('tags', [])
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if str(t).lower() in PROHIBITED_TAGS:
                return False, f"FILTERED_BY_TAG: Lexicographical tag '{t}' is prohibited"

    # 2. Text inspection across term, glosses, and examples
    text_corpus = []
    if 'term' in entry:
        text_corpus.append(str(entry['term']))
    if 'senses' in entry:
        for s in entry['senses']:
            text_corpus.append(str(s))
    if 'source_sentence' in entry:
        text_corpus.append(str(entry['source_sentence']))
    if 'target_sentence' in entry:
        text_corpus.append(str(entry['target_sentence']))

    combined_text = " ".join(text_corpus)

    for pattern in PROHIBITED_PATTERNS:
        match = pattern.search(combined_text)
        if match:
            return False, f"FILTERED_BY_PATTERN: Matched prohibited term '{match.group(0)}'"

    return True, "CONTENT_APPROVED"

def filter_dataset(items: list) -> tuple:
    admitted = []
    quarantined = []
    for item in items:
        ok, reason = is_content_admissible(item)
        if ok:
            admitted.append(item)
        else:
            quarantined.append({'item': item, 'reason': reason})
    return admitted, quarantined

if __name__ == "__main__":
    sample = {"term": "Klasse", "senses": ["grade", "class (school)"]}
    ok, msg = is_content_admissible(sample)
    print(f"Sample test 'Klasse': {msg} (Must be approved)")
    assert ok, "False positive on 'Klasse'!"
