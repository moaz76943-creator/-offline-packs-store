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

    # Extract attested principal parts without inventing fake forms
    praesens_3sg = raw_forms.get('praesens_3sg')
    praeteritum = raw_forms.get('praeteritum')
    partizip_ii = raw_forms.get('partizip_ii')
    auxiliary = raw_forms.get('auxiliary')

    # Sanitize auxiliary (must be haben or sein)
    if auxiliary not in ['haben', 'sein']:
        auxiliary = None

    # Spelling alone is insufficient: antworten is not an an- separable verb.
    # Prefer the longest prefix supported by an attested detached finite form
    # or the corresponding prefix+ge participle.
    prefix = None
    for candidate in sorted(SEPARABLE_PREFIXES, key=len, reverse=True):
        if inf.startswith(candidate) and (
            any(isinstance(form, str) and form.strip().endswith(' ' + candidate)
                for form in (praesens_3sg, praeteritum)) or
            (isinstance(partizip_ii, str) and partizip_ii.strip().startswith(candidate + 'ge'))
        ):
            prefix = candidate
            break
    is_separable = bool(prefix) if any((praesens_3sg, praeteritum, partizip_ii)) else None

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

    clean_gender = gender.lower().strip() if isinstance(gender, str) else None
    if clean_gender not in ['masculin', 'feminin', 'neutrum']:
        clean_gender = None

    return {
        'lemma': lemma.strip(),
        'gender': clean_gender,
        'genitive': genitive.strip() if genitive else None,
        'plural': plural.strip() if plural else None,
    }

def validate_morphology_record(record: dict) -> bool:
    """Rejects empty or syntactically invalid morphology records."""
    if not isinstance(record, dict) or not record:
        return False
    if ('infinitive' in record) == ('lemma' in record):
        return False
    verb = 'infinitive' in record
    identifier = record['infinitive' if verb else 'lemma']
    if not isinstance(identifier, str) or not identifier.strip():
        return False
    if verb:
        if record.get('auxiliary') not in ('haben', 'sein'):
            return False
        if record.get('is_separable') not in (None, True, False):
            return False
        fields = ('praesens_3sg', 'praeteritum', 'partizip_ii', 'prefix')
    else:
        if record.get('gender') not in ('masculin', 'feminin', 'neutrum'):
            return False
        fields = ('plural', 'genitive')
    if any(value is not None and (not isinstance(value, str) or not value.strip())
           for value in (record.get(field) for field in fields)):
        return False
    return True
