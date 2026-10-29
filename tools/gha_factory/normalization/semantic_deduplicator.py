#!/usr/bin/env python3
"""
Semantic Sense Deduplicator - Master Constitution Section 08 Compliant.
Guarantees distinct semantic senses are never overwritten or lost during
multi-source merging, while eliminating exact duplicate glosses.
"""
import re
import sys
import unicodedata

def compute_sense_fingerprint(gloss: str) -> str:
    """Computes a normalized fingerprint of a sense definition."""
    nfc = unicodedata.normalize('NFC', gloss.strip().lower())
    # Remove punctuation and redundant spaces
    cleaned = re.sub(r'[^\w\s]', '', nfc)
    return " ".join(cleaned.split())

def deduplicate_lexical_records(records: list) -> list:
    """
    Groups entries by (term, pos).
    Deduplicates identical senses while strictly preserving distinct semantic concepts.
    """
    # Key: (term, pos) -> dict of {sense_fingerprint: sense_entry}
    grouped = {}

    for entry in records:
        term = unicodedata.normalize('NFC', entry.get('term', '').strip())
        pos = str(entry.get('pos', 'unknown')).strip().lower()
        if not term:
            continue

        group_key = (term, pos)
        if group_key not in grouped:
            grouped[group_key] = {
                'term': term,
                'pos': pos,
                'gender': entry.get('gender'),
                'senses_map': {}, # fingerprint -> list of sources/examples
            }

        target_group = grouped[group_key]
        if not target_group['gender'] and entry.get('gender'):
            target_group['gender'] = entry.get('gender')

        # Process each sense in the entry
        raw_senses = entry.get('senses', [])
        source_id = entry.get('source_id', 'unknown')

        for s in raw_senses:
            gloss = str(s).strip()
            fp = compute_sense_fingerprint(gloss)
            if not fp:
                continue

            if fp not in target_group['senses_map']:
                target_group['senses_map'][fp] = {
                    'gloss': gloss,
                    'sources': set([source_id]),
                }
            else:
                target_group['senses_map'][fp]['sources'].add(source_id)

    # Flatten back to list with multiple distinct senses preserved
    result = []
    for (term, pos), g in grouped.items():
        distinct_senses = [item['gloss'] for item in g['senses_map'].values()]
        all_sources = sorted(list(set().union(*[item['sources'] for item in g['senses_map'].values()])))

        result.append({
            'term': term,
            'pos': pos,
            'gender': g['gender'],
            'distinct_senses_count': len(distinct_senses),
            'senses': distinct_senses,
            'sources': all_sources,
        })

    return result

if __name__ == "__main__":
    test_input = [
        {"term": "Bank", "pos": "noun", "senses": ["bench to sit on"], "source_id": "kaikki"},
        {"term": "Bank", "pos": "noun", "senses": ["financial institution"], "source_id": "wiktionary"},
        {"term": "Bank", "pos": "noun", "senses": ["bench to sit on."], "source_id": "tatoeba"}
    ]
    out = deduplicate_lexical_records(test_input)
    print(f"Test 'Bank': Expected 2 distinct senses, got {len(out[0]['senses'])}")
    assert len(out[0]['senses']) == 2, "Failed to preserve distinct senses!"
