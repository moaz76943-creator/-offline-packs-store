"""Source-reviewed relations are distinct from Unicode canonical equivalence."""
import hashlib

from .processor import (ScriptContractError, approved_sources, validate_text)

KINDS = frozenset(('lexical_equivalent', 'transliteration',
                   'related_form', 'ambiguous_orthography'))
EVIDENCE_FIELDS = frozenset(('language_code', 'source_id', 'source_sha256',
                             'left_utf8_sha256', 'right_utf8_sha256',
                             'relation_kind', 'evidence_version'))


def classify_relation(code, left, right, *, evidence=None, ledger=None):
    """Return explicit source-backed relation, or conservative unknown.

    NFC equality supports *Unicode* equivalence only, not same sense/lemma.
    Source review must pin both ORIGINAL UTF-8 strings and the approved source.
    """
    a = validate_text(code, left)
    b = validate_text(code, right)
    if a['search_key'] == b['search_key']:
        if evidence is not None:
            raise ScriptContractError('redundant/conflicting relation evidence')
        return {'status': 'canonical_unicode_equivalent', 'lexical_claim': False}
    if evidence is None:
        return {'status': 'unresolved', 'relation_kind': 'unknown',
                'lexical_claim': False}
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_FIELDS:
        raise ScriptContractError('noncanonical relation evidence')
    source = approved_sources(ledger).get(evidence['source_id']) if ledger is not None else None
    if (source is None or code not in source['languages'] or
            evidence['language_code'] != code or
            evidence['source_sha256'] != source['sha256'] or
            evidence['left_utf8_sha256'] != a['original_utf8_sha256'] or
            evidence['right_utf8_sha256'] != b['original_utf8_sha256'] or
            evidence['relation_kind'] not in KINDS or
            not isinstance(evidence['evidence_version'], str) or
            not evidence['evidence_version'].strip()):
        raise ScriptContractError('missing, fabricated or wrong-language relation evidence')
    return {'status': 'attested_relation_only',
            'relation_kind': evidence['relation_kind'],
            'lexical_claim': evidence['relation_kind'] == 'lexical_equivalent',
            'source_id': evidence['source_id'],
            'evidence_version': evidence['evidence_version']}
