#!/usr/bin/env python3
"""
Morphology Engine - Master Constitution Section 07 Compliant.
Parses and validates principal parts for verbs, nouns, and roots.
Strictly prohibits generating hallucinated or synthetic inflections.
"""
import sys

# Common German separable prefixes
SEPARABLE_PREFIXES = [
    'ab', 'an', 'auf', 'aus', 'bei', 'ein', 'fest', 'her', 'hin',
    'los', 'mit', 'nach', 'vor', 'weg', 'weiter', 'zu', 'zurück'
]

def parse_german_verb_morphology(infinitive: str, raw_forms: dict) -> dict:
    inf = infinitive.strip()
    
    # Detect separable verb prefix
    is_separable = False
    prefix = None
    for p in SEPARABLE_PREFIXES:
        if inf.startswith(p) and len(inf) > len(p) + 2:
            is_separable = True
            prefix = p
            break

    # Extract attested principal parts without inventing fake forms
    praesens_3sg = raw_forms.get('praesens_3sg')
    praeteritum = raw_forms.get('praeteritum')
    partizip_ii = raw_forms.get('partizip_ii')
    auxiliary = raw_forms.get('auxiliary', 'haben')

    # Sanitize auxiliary (must be haben or sein)
    if auxiliary not in ['haben', 'sein']:
        auxiliary = 'haben'

    return {
        'infinitive': inf,
        'is_separable': is_separable,
        'prefix': prefix,
        'praesens_3sg': praesens_3sg.strip() if praesens_3sg else None,
        'praeteritum': praeteritum.strip() if praeteritum else None,
        'partizip_ii': partizip_ii.strip() if partizip_ii else None,
        'auxiliary': auxiliary,
    }

def parse_german_noun_morphology(lemma: str, gender: str, raw_forms: dict) -> dict:
    genitive = raw_forms.get('genitive')
    plural = raw_forms.get('plural')

    clean_gender = gender.lower().strip() if gender else 'neutrum'
    if clean_gender not in ['masculin', 'feminin', 'neutrum']:
        clean_gender = 'neutrum'

    return {
        'lemma': lemma.strip(),
        'gender': clean_gender,
        'genitive': genitive.strip() if genitive else None,
        'plural': plural.strip() if plural else None,
    }

def validate_morphology_record(record: dict) -> bool:
    """Rejects empty or syntactically invalid morphology records."""
    if not record:
        return False
    if 'infinitive' in record and not record['infinitive']:
        return False
    if 'lemma' in record and not record['lemma']:
        return False
    return True
