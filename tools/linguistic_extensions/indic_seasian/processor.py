"""Fail-closed orthography and evidence processing for 18 canonical languages.

No text-to-morphology inference, dictionary segmentation, transliteration, or
production licensing is asserted. All operations use bounded, local input.
"""
import hashlib
import json
from pathlib import Path
import re
import unicodedata as ud


class ScriptContractError(ValueError):
    """Unregistered language, unsafe text, script mismatch or absent evidence."""


# Codes, identities, and scripts are checked against the PUBLIC canonical registry
# at runtime. Neither a common script nor a family grants shared lexical data.
LANGUAGE_SCRIPTS = {
    'hi': ('Deva',), 'mr': ('Deva',), 'ne': ('Deva',),
    'bn': ('Beng',), 'as': ('Beng',), 'pa': ('Guru', 'Arab'),
    'gu': ('Gujr',), 'or': ('Orya',), 'ta': ('Taml',),
    'te': ('Telu',), 'kn': ('Knda',), 'ml': ('Mlym',),
    'si': ('Sinh',), 'ur': ('Arab',), 'th': ('Thai',),
    'lo': ('Laoo',), 'km': ('Khmr',), 'my': ('Mymr',),
}
REQUIRES_DICTIONARY = frozenset({'th', 'lo', 'km', 'my'})
# Unicode ranges; these classify characters, NOT lexemes or languages.
SCRIPT_RANGES = {
    'Deva': ((0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF)),
    'Beng': ((0x0980, 0x09FF),), 'Guru': ((0x0A00, 0x0A7F),),
    'Gujr': ((0x0A80, 0x0AFF),), 'Orya': ((0x0B00, 0x0B7F),),
    'Taml': ((0x0B80, 0x0BFF),), 'Telu': ((0x0C00, 0x0C7F),),
    'Knda': ((0x0C80, 0x0CFF),), 'Mlym': ((0x0D00, 0x0D7F),),
    'Sinh': ((0x0D80, 0x0DFF),), 'Thai': ((0x0E00, 0x0E7F),),
    'Laoo': ((0x0E80, 0x0EFF),), 'Khmr': ((0x1780, 0x17FF), (0x19E0, 0x19FF)),
    'Mymr': ((0x1000, 0x109F), (0xA9E0, 0xA9FF), (0xAA60, 0xAA7F)),
    'Arab': ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
             (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
}
VIRAMAS = frozenset(chr(c) for c in (
    0x094D, 0x09CD, 0x0A4D, 0x0ACD, 0x0B4D, 0x0BCD, 0x0C4D,
    0x0CCD, 0x0D4D, 0x0DCA, 0x17D2, 0x1039, 0x103A,
))
JOINERS = frozenset(('\u200c', '\u200d'))
# Distinct families have disjoint PER-LANGUAGE eligibility, not attestation.
INDO_ARYAN = frozenset({'hi', 'mr', 'ne', 'bn', 'as', 'pa', 'gu', 'or', 'si', 'ur'})
DRAVIDIAN = frozenset({'ta', 'te', 'kn', 'ml'})
FEATURES = {
    'indo_aryan': frozenset(('grammatical_gender', 'case', 'number', 'agreement',
                            'person', 'tense', 'aspect', 'mood', 'honorifics',
                            'postposition', 'verb_form')),
    'dravidian': frozenset(('case', 'number', 'agreement', 'person', 'tense',
                           'aspect', 'mood', 'honorifics', 'suffix', 'verb_form')),
    'thai_lao': frozenset(('classifiers', 'tone', 'honorifics', 'particle')),
    'khmer_myanmar': frozenset(('classifiers', 'particle', 'honorifics')),
}
FIELDS = frozenset(('language_code', 'lemma_id', 'sense_id', 'lemma', 'form',
                    'features', 'source_id', 'evidence_version', 'script'))
REQUIRED = FIELDS - {'script'}
HEX_SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_TEXT = 2048


def profile(code, registry):
    """Verify the frozen script mapping against an independently read registry."""
    if code not in LANGUAGE_SCRIPTS:
        raise ScriptContractError('language is outside this extension')
    entries = registry.get('languages') if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        raise ScriptContractError('invalid canonical registry')
    matches = [item for item in entries if isinstance(item, dict) and item.get('id') == code]
    if len(matches) != 1 or tuple(matches[0].get('scripts', ())) != LANGUAGE_SCRIPTS[code]:
        raise ScriptContractError('canonical language/script drift')
    item = matches[0]
    group = ('indo_aryan' if code in INDO_ARYAN else 'dravidian' if code in DRAVIDIAN
             else 'thai_lao' if code in ('th', 'lo') else 'khmer_myanmar')
    return {'language': code, 'family': item.get('family'),
            'scripts': list(LANGUAGE_SCRIPTS[code]),
            'boundary_strategy': 'requires_attested_words' if code in REQUIRES_DICTIONARY
                                 else 'whitespace_hints_only',
            'morphology': 'evidence_required_no_generated_forms',
            'candidate_feature_keys': sorted(FEATURES[group]),
            'lexeme_count': 0}  # profile metadata never claims a corpus


def _script(ch):
    point = ord(ch)
    for script, blocks in SCRIPT_RANGES.items():
        if any(a <= point <= b for a, b in blocks):
            return script
    return None


def validate_text(code, text, *, script=None):
    """Preserve exact original UTF-8; joiners require local script context."""
    if code not in LANGUAGE_SCRIPTS or not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        raise ScriptContractError('invalid language or text length')
    allowed = LANGUAGE_SCRIPTS[code]
    if script is not None and script not in allowed:
        raise ScriptContractError('unregistered language script')
    observed = set()
    for i, ch in enumerate(text):
        cat = ud.category(ch)
        if ch in JOINERS:
            # An unrelated virama ELSEWHERE in the string never authorizes a
            # detached joiner. Urdu/Shahmukhi medial ZWNJ has a separate rule.
            if not (0 < i < len(text) - 1):
                raise ScriptContractError('dangling Unicode joiner')
            before, after = text[i - 1], text[i + 1]
            if before in JOINERS or after in JOINERS:
                raise ScriptContractError('adjacent Unicode joiners')
            if (code in ('ur', 'pa') and ch == '\u200c' and
                    _script(before) == 'Arab' and _script(after) == 'Arab'):
                continue
            if before not in VIRAMAS or _script(after) not in allowed:
                raise ScriptContractError('joiner lacks adjacent virama and script base')
            continue
        if cat in ('Cc', 'Cs', 'Co', 'Cn', 'Cf'):
            raise ScriptContractError('unsafe or unassigned Unicode code point')
        found = _script(ch)
        if found:
            if found not in allowed or (script and found != script):
                raise ScriptContractError('script mismatch')
            observed.add(found)
        elif cat.startswith('L') or cat.startswith('M'):
            raise ScriptContractError('unrecognized letter or detached script mark')
    if not observed:
        raise ScriptContractError('no language script characters')
    if len(observed) != 1:
        raise ScriptContractError('mixed orthographies require separate records')
    raw = text.encode('utf-8', errors='strict')
    return {'original': text, 'original_utf8_sha256': hashlib.sha256(raw).hexdigest(),
            'utf8_length': len(raw), 'script': next(iter(observed)),
            'search_key': ud.normalize('NFC', text), 'search_transform': 'NFC_only',
            'lexical_equivalence': 'not_asserted'}


def orthographic_units(code, text):
    """Bounded script-aware akshara-like units; NOT full Unicode UAX #29.

    Combining vowel signs stay attached; virama may join a following base.
    For Thai/Lao/Khmer/Myanmar these are display units, NOT words.
    Complex grapheme sequences outside the covered rules need ICU/UAX29 QA.
    """
    validate_text(code, text)
    units = []
    for ch in text:
        mark = ud.category(ch).startswith('M')
        prev = units[-1] if units else ''
        join = bool(prev and (prev.endswith(tuple(VIRAMAS)) or
                             (prev.endswith('\u200d') and any(v in prev for v in VIRAMAS))))
        if prev and (mark or ch in JOINERS or (join and ch.isalpha())):
            units[-1] += ch
        else:
            units.append(ch)
    return tuple(units)


def search_relation(code, left, right):
    """Only canonical Unicode normalization is evidence-free equivalence."""
    a = validate_text(code, left)
    b = validate_text(code, right)
    if a['search_key'] == b['search_key']:
        return 'unicode_canonical_equivalent'
    return 'undetermined_not_transliteration_or_lexical_equivalence'


SEGMENT_FIELDS = frozenset(('language_code', 'source_id', 'source_sha256',
                            'text_sha256', 'tokens'))
REVIEW_TYPES = ('morphology', 'segmentation', 'orthographic_relation')


def evidence_digest(record):
    """Canonical content digest; metadata alone does not license a new record."""
    if not isinstance(record, dict):
        raise ScriptContractError('evidence must be a JSON object')
    try:
        data = json.dumps(record, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ScriptContractError('noncanonical evidence') from exc
    if len(data) > 65536:
        raise ScriptContractError('oversized evidence')
    return hashlib.sha256(data).hexdigest()


def words(code, text, *, attested=None, ledger=None):
    """No dictionary tokens unless independently reviewed bytes were pinned."""
    validate_text(code, text)
    if attested is not None:
        if not isinstance(attested, dict) or set(attested) != SEGMENT_FIELDS:
            raise ScriptContractError('noncanonical segmentation evidence')
        source = approved_sources(ledger).get(attested.get('source_id'))
        if (not source or code not in source['languages'] or
                attested.get('language_code') != code or
                attested.get('source_sha256') != source['sha256'] or
                attested.get('text_sha256') != hashlib.sha256(text.encode('utf-8')).hexdigest()):
            raise ScriptContractError('unapproved or mismatched segmentation evidence')
        tokens = attested.get('tokens')
        if (not isinstance(tokens, list) or not tokens or len(tokens) > MAX_TEXT or
                any(not isinstance(part, str) or not part for part in tokens) or
                ''.join(tokens) != text):
            raise ScriptContractError('segmentation does not reconstruct original UTF-8')
        if evidence_digest(attested) not in source['reviewed_records']['segmentation']:
            raise ScriptContractError('segmentation boundary was not independently reviewed')
        return {'status': 'attested', 'tokens': tokens, 'strategy': 'reviewed_evidence_only'}
    if code in REQUIRES_DICTIONARY:
        return {'status': 'requires_attested_segmentation', 'tokens': [],
                'strategy': 'language_specific_dictionary_or_lexical_evidence'}
    return {'status': 'orthographic_hints_only',
            'tokens': re.findall(r'\S+', text), 'strategy': 'whitespace_not_verified_words'}


def approved_sources(ledger):
    """Require independently provisioned release/rights state and per-record hashes.

    The trusted source ledger is an externally reviewed input, not a reviewer
    signature checker. An arbitrary caller-supplied ledger is NOT proof of
    rights and must never be used as production approval authority.
    """
    sources = ledger.get('sources') if isinstance(ledger, dict) else None
    if not isinstance(sources, list):
        raise ScriptContractError('missing public source ledger')
    accepted, seen_ids = {}, set()
    for item in sources:
        if not isinstance(item, dict):
            raise ScriptContractError('invalid source ledger entry')
        source_id = item.get('id')
        if not isinstance(source_id, str) or not source_id.strip() or source_id in seen_ids:
            raise ScriptContractError('invalid or duplicate source identifier')
        seen_ids.add(source_id)
        if item.get('release_approved') is not True:
            continue
        langs = item.get('languages')
        forms = item.get('reviewed_records')
        if (not isinstance(source_id, str) or not source_id.strip() or
                source_id in accepted or
                not isinstance(langs, list) or not 1 <= len(langs) <= len(LANGUAGE_SCRIPTS) or
                any(not isinstance(lang, str) or lang not in LANGUAGE_SCRIPTS for lang in langs) or
                len(set(langs)) != len(langs) or
                not isinstance(item.get('sha256'), str) or not HEX_SHA.fullmatch(item['sha256']) or
                item.get('rights_status') != 'APPROVED' or
                not isinstance(item.get('reviewed_by'), str) or not item['reviewed_by'].strip() or
                not isinstance(item.get('rights_evidence_sha256'), str) or
                not HEX_SHA.fullmatch(item['rights_evidence_sha256']) or
                not isinstance(forms, dict) or set(forms) != set(REVIEW_TYPES)):
            raise ScriptContractError('incomplete or contradictory source approval')
        reviewed = {}
        for kind in REVIEW_TYPES:
            hashes = forms[kind]
            if (not isinstance(hashes, list) or len(hashes) > 2000 or
                    any(not isinstance(h, str) or not HEX_SHA.fullmatch(h) for h in hashes) or
                    len(set(hashes)) != len(hashes)):
                raise ScriptContractError('invalid reviewed record hashes')
            reviewed[kind] = frozenset(hashes)
        accepted[source_id] = {'languages': frozenset(langs),
                               'sha256': item['sha256'], 'reviewed_records': reviewed}
    return accepted


def validate_attestation(record, code, registry, ledger):
    """Validate a supplied exact form, never infer any missing morphology."""
    p = profile(code, registry)
    if not isinstance(record, dict) or not REQUIRED <= record.keys() or record.keys() - FIELDS:
        raise ScriptContractError('noncanonical form envelope')
    if record['language_code'] != code:
        raise ScriptContractError('cross-language attestation')
    for key in ('lemma_id', 'sense_id', 'source_id', 'evidence_version'):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ScriptContractError('invalid evidence identifiers')
    if not record['lemma_id'].startswith(code + ':') or not record['sense_id'].startswith(code + ':'):
        raise ScriptContractError('non-scoped lexical identity')
    allowed = approved_sources(ledger)
    if code not in allowed.get(record['source_id'], {}).get('languages', frozenset()):
        raise ScriptContractError('source not approved for this language')
    lemma = validate_text(code, record['lemma'], script=record.get('script'))
    form = validate_text(code, record['form'], script=record.get('script'))
    if lemma['script'] != form['script']:
        raise ScriptContractError('form/lemma orthography mismatch')
    features = record['features']
    if not isinstance(features, dict) or not features or len(features) > 16:
        raise ScriptContractError('missing or excessive morphological evidence')
    for key, value in features.items():
        if key not in p['candidate_feature_keys'] or not isinstance(value, str) or not value.strip() or len(value) > 80:
            raise ScriptContractError('unsupported or fabricated feature claim')
    if evidence_digest(record) not in allowed[record['source_id']]['reviewed_records']['morphology']:
        raise ScriptContractError('morphological record was not independently reviewed')
    return {'status': 'attested_only', 'language': code, 'lemma_id': record['lemma_id'],
            'sense_id': record['sense_id'], 'form': record['form'],
            'features': dict(features), 'source_id': record['source_id'],
            'evidence_version': record['evidence_version'], 'script': form['script']}


def audit_jsonl(path, code, registry, ledger, *, max_records=2000, max_bytes=4_000_000):
    """Bounded read-only per-language worker, with SHA and actual coverage."""
    profile(code, registry)
    if (type(max_records) is not int or not 1 <= max_records <= 2000 or
            type(max_bytes) is not int or not 1 <= max_bytes <= 4_000_000):
        raise ScriptContractError('unsafe audit budget')
    target = Path(path)
    if not target.is_file() or target.is_symlink() or target.stat().st_size > max_bytes:
        raise ScriptContractError('unsafe or oversized input')
    lexemes, forms, digest = set(), set(), hashlib.sha256()
    with target.open('rb') as handle:
        for number, raw in enumerate(handle, 1):
            if number > max_records or len(raw) > 65536:
                raise ScriptContractError('worker record budget exceeded')
            digest.update(raw)
            try:
                record = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
            except (ValueError, UnicodeError) as exc:
                raise ScriptContractError('malformed or duplicate-key JSONL') from exc
            accepted = validate_attestation(record, code, registry, ledger)
            lexemes.add((accepted['lemma_id'], accepted['sense_id']))
            fingerprint = (accepted['lemma_id'], accepted['sense_id'], accepted['form'],
                           tuple(sorted(accepted['features'].items())))
            if fingerprint in forms:
                raise ScriptContractError('duplicate attested form')
            forms.add(fingerprint)
    if not forms:
        raise ScriptContractError('empty input is not a verified corpus')
    return {'language': code, 'input_sha256': digest.hexdigest(),
            'verified_lexemes': len(lexemes), 'verified_forms': len(forms),
            'coverage': 'attested_input_only', 'status': 'PASS_EVIDENCE_QA'}


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', required=True, choices=sorted(LANGUAGE_SCRIPTS))
    parser.add_argument('--registry', default='catalog/language_registry.v1.json')
    parser.add_argument('--ledger', default='legal/ledger/sources.json')
    parser.add_argument('--input-jsonl', help='Approved exact attestation records; never generated')
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding='utf-8'))
    ledger = json.loads(Path(args.ledger).read_text(encoding='utf-8'))
    result = (audit_jsonl(args.input_jsonl, args.language, registry, ledger)
              if args.input_jsonl else profile(args.language, registry))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
