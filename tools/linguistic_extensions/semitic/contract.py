"""Attestation-only, language-scoped Semitic sidecar on morphology form schema v1.

No generated inflections, extrapolated roots, guessed genders or dialect transfer.
Only the search KEY is folded: original Unicode form and evidence remain intact.
"""
import json
from functools import lru_cache
import re
import unicodedata
from pathlib import Path

PROFILE_FILE = Path(__file__).with_name('profiles.json')
BASE_FORM_SCHEMA = Path(__file__).resolve().parents[3] / 'standards/morphology/form.schema.json'
AR_MARKS = set(range(0x0610, 0x061B)) | set(range(0x064B, 0x0660)) | {0x0670} | set(range(0x06D6, 0x06EE))
AR_FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي'})
MAX_LINE = 131072


class ContractError(ValueError):
    """Unverifiable form, mismatched language or unsupported interpretation."""


def strict_json(raw):
    """Reject duplicate keys and non-finite JSON numbers in source shards."""
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ContractError('duplicate JSON field: ' + key)
            obj[key] = value
        return obj
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite JSON')))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError('invalid JSON record') from exc


@lru_cache(maxsize=24)
def load_profile(root, language):
    """Profile membership is explicit; language-family/script similarities never grant access."""
    profiles = strict_json(PROFILE_FILE.read_bytes())['languages']
    if language not in profiles:
        raise ContractError('no reviewed Semitic language profile: ' + str(language))
    registry_path = Path(root) / 'catalog/language_registry.v1.json'
    registry = strict_json(registry_path.read_bytes())
    entries = [x for x in registry['languages'] if x.get('id') == language]
    if len(entries) != 1:
        raise ContractError('language absent or duplicated in canonical registry')
    entry, profile = entries[0], profiles[language]
    if entry.get('family') != profile['family'] or profile['script'] not in entry.get('scripts', []):
        raise ContractError('canonical registry identity/script mismatch')
    return profile


def _script_ok(value, language):
    if not isinstance(value, str) or not value or unicodedata.normalize('NFC', value) != value:
        return False
    letters = [ord(c) for c in value if unicodedata.category(c).startswith('L')]
    if not letters:
        return False
    if language == 'ar':
        return all(0x0600 <= n <= 0x06FF or 0x0750 <= n <= 0x077F or 0x08A0 <= n <= 0x08FF for n in letters)
    if language == 'am':
        return all(0x1200 <= n <= 0x137F or 0x2D80 <= n <= 0x2DDF or 0xAB00 <= n <= 0xAB2F for n in letters)
    return False


def normalize_retrieval(language, surface):
    if language not in ('ar', 'am') or not isinstance(surface, str) or not surface:
        raise ContractError('unknown language or empty search term')
    text = unicodedata.normalize('NFC', surface)
    if language == 'am':
        return text  # Ethiopic fidel is not Arabic; no hamza/haraka transformations.
    return ''.join(c for c in text if ord(c) not in AR_MARKS and c != '\u0640').translate(AR_FOLD)


def validate_candidate(candidate, root, language, source_id, dataset_version, source_sha256):
    """Validate explicit claims against canonical v1 form fields and pinned evidence.

    Candidate envelope is a private sidecar contract; the nested 'record' remains
    exactly the v1 morphology form schema (no schema changes to PR #85).
    """
    profile = load_profile(root, language)
    if not isinstance(candidate, dict) or set(candidate) != {'record', 'evidence'}:
        raise ContractError('candidate must contain only record and evidence')
    record, evidence = candidate['record'], candidate['evidence']
    if not isinstance(record, dict) or not isinstance(evidence, dict):
        raise ContractError('malformed candidate')
    schema = strict_json((Path(root) / 'standards/morphology/form.schema.json').read_bytes())
    if not set(schema['required']).issubset(record) or not set(record).issubset(schema['properties']):
        raise ContractError('incompatible form schema v1 fields')
    required_strings = ['language_code', 'lemma_id', 'sense_id', 'lemma', 'form', 'source_id', 'evidence_version']
    if any(not isinstance(record.get(k), str) or not record[k] for k in required_strings):
        raise ContractError('missing string identity or provenance')
    if (record['language_code'] != language or record['source_id'] != source_id or
            record['evidence_version'] != dataset_version or
            not record['lemma_id'].startswith(language + ':') or
            not record['sense_id'].startswith(language + ':')):
        raise ContractError('form/lemma/source/version identity conflict')
    if any(not _script_ok(record[key], language) for key in ('lemma', 'form')):
        raise ContractError('script leakage or non-NFC spelling')
    if 'script' in record and record['script'] != profile['script']:
        raise ContractError('script label mismatched')
    if 'root' in record and not _script_ok(record['root'], language):
        raise ContractError('unattested or wrong-script root')
    if 'pattern' in record and not _script_ok(record['pattern'], language):
        raise ContractError('missing or wrong-script attested morphological template')
    features = record['features']
    if not isinstance(features, dict) or any(
            not isinstance(k, str) or k not in profile['feature_keys'] or
            not isinstance(v, str) or not v for k, v in features.items()):
        raise ContractError('unreviewed feature or empty feature value')
    if 'number' in features and features['number'] not in profile['numbers']:
        raise ContractError('language-specific number inventory violated')
    if 'grammatical_gender' in features and features['grammatical_gender'] not in ('masculine', 'feminine'):
        raise ContractError('invalid attested gender')
    processes = record.get('processes', [])
    if not isinstance(processes, list) or len(set(map(str, processes))) != len(processes) or not all(isinstance(p, str) and p for p in processes):
        raise ContractError('invalid processes')
    if 'broken_plural' in processes:
        if language != 'ar' or features.get('number') != 'plural' or not record.get('root') or not record.get('pattern'):
            raise ContractError('broken plural requires Arabic-specific attested root/template and plural')
    if ('root' in record) != ('pattern' in record):
        raise ContractError('root and pattern must be evidenced together')
    for key in ('components', 'segmentation'):
        if key in record and (not isinstance(record[key], list) or not all(isinstance(x, str) and x for x in record[key])):
            raise ContractError('invalid v1 list member')
    if 'morphemes' in record:
        if not isinstance(record['morphemes'], list):
            raise ContractError('invalid morpheme list')
        for m in record['morphemes']:
            if not isinstance(m, dict) or not {'surface', 'kind', 'position'}.issubset(m) or not set(m).issubset({'surface', 'kind', 'position', 'allomorph'}) or m['kind'] not in ('root','prefix','suffix','infix','clitic','stem','pattern','compound_member') or type(m['position']) is not int or m['position'] < 0 or not _script_ok(m['surface'], language):
                raise ContractError('invalid canonical morpheme')
            if 'allomorph' in m and not _script_ok(m['allomorph'], language):
                raise ContractError('invalid canonical morpheme allomorph')
    for key in ('vowel_harmony_class', 'orthographic_variant'):
        if key in record and not isinstance(record[key], str):
            raise ContractError('invalid canonical orthographic property')
    mandatory = {'source_locator', 'dataset_version', 'source_sha256', 'variety', 'part_of_speech', 'attested', 'claim_locators'}
    optional = {'dialect_tag', 'verb_stem'}
    if not mandatory.issubset(evidence) or not set(evidence).issubset(mandatory | optional):
        raise ContractError('missing or unknown evidence envelope fields')
    if (evidence['attested'] is not True or evidence['dataset_version'] != dataset_version or
            evidence['source_sha256'] != source_sha256 or
            not isinstance(evidence['source_locator'], str) or not evidence['source_locator'].strip() or
            len(evidence['source_locator']) > 1024):
        raise ContractError('source attestation is not immutable or not pinned')
    variety = evidence['variety']
    if variety not in profile['varieties']:
        raise ContractError('unverified language variety')
    tag = evidence.get('dialect_tag')
    if variety in ('dialect', 'regional'):
        if not isinstance(tag, str) or not re.fullmatch(language + r'-[A-Za-z0-9-]{2,35}', tag):
            raise ContractError('variety requires language-specific locale tag')
    elif tag is not None:
        raise ContractError('unneeded dialect tag')
    pos = evidence['part_of_speech']
    if pos not in ('noun', 'verb', 'other'):
        raise ContractError('unknown part of speech')
    if pos == 'verb':
        if not isinstance(evidence.get('verb_stem'), str) or not _script_ok(evidence['verb_stem'], language):
            raise ContractError('verb requires independently attested language-specific stem')
    elif 'verb_stem' in evidence:
        raise ContractError('nonverb cannot claim a verbal stem')
    claims = evidence['claim_locators']
    keys = {'form'} | {'features.' + k for k in features} | set(k for k in ('root','pattern') if k in record)
    keys.update('processes.' + p for p in processes)
    if pos == 'verb':
        keys.add('verb_stem')
    if not isinstance(claims, dict) or set(claims) != keys or any(
            not isinstance(value, str) or not value.strip() or len(value) > 1024
            for value in claims.values()):
        raise ContractError('every linguistic claim needs its own source locator')
    return candidate


def lookup(path, root, language, surface, limit=100):
    """Streaming exact-evidence retrieval; ambiguous folded forms stay ambiguous."""
    load_profile(root, language)
    key = normalize_retrieval(language, surface)
    exact_surface = unicodedata.normalize('NFC', surface)
    exact, folded, analyses = [], [], set()
    exact_keys = set()
    matched_count = 0
    with Path(path).open('rb') as stream:
        for line in stream:
            if len(line) > MAX_LINE:
                raise ContractError('oversize accepted line')
            if not line.strip():
                continue
            item = strict_json(line)
            record, evidence = item['record'], item['evidence']
            if record['language_code'] != language or normalize_retrieval(language, record['form']) != key:
                continue
            identity = (record['lemma_id'], record['sense_id'], json.dumps(record['features'], sort_keys=True),
                        record.get('root'), record.get('pattern'), evidence['variety'], evidence.get('dialect_tag'))
            analyses.add(identity)
            matched_count += 1
            if len(folded) < limit:
                folded.append(item)
            if record['form'] == exact_surface:
                # Track every analysis even when returned rows are truncated.
                exact_keys.add(identity)
                if len(exact) < limit:
                    exact.append(item)
    if not folded:
        return {'status': 'unknown', 'forms': [], 'normalization_ambiguous': False}
    selected = exact if exact else folded
    ambiguous = len(analyses) > 1
    return {'status': 'ambiguous' if len(exact_keys) > 1 or (not exact and ambiguous) else 'attested',
            'forms': selected, 'normalization_ambiguous': ambiguous, 'total_analyses': len(analyses),
            'truncated': matched_count > limit}
