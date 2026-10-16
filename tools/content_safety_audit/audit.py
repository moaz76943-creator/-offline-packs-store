"""Offline advisory candidate screening; does NOT authorize release or remove sources.

Usage: python3 -m tools.content_safety_audit.audit --input candidates.jsonl
Only anonymized decisions/counts are printed; raw source/target material is never logged.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

DEFAULT_POLICY = Path(__file__).with_name('policy.json')
DECISIONS = ('ALLOW', 'HUMAN_REVIEW', 'REJECT')
SENSITIVE_KEYS = frozenset(('learner_id', 'user_id', 'device_id', 'email', 'password',
                            'access_token', 'token', 'srs', 'srs_history', 'review_history',
                            'progress_history', 'personal_data', 'session_token'))
SENSITIVE_PATH = re.compile(r'(?:^|[/_.-])(srs|learner|learners|user_data|userdata|'
                            r'progress_history|review_history|private_key|credentials)(?:[/_.-]|$)',
                            re.IGNORECASE)
LANGUAGE_CODE = re.compile(r'^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$')
SAFE_ID = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
PERMISSIONS_TO_REVIEW = frozenset((
    'android.permission.RECORD_AUDIO', 'android.permission.CAMERA',
    'android.permission.READ_CONTACTS', 'android.permission.READ_SMS',
    'android.permission.READ_EXTERNAL_STORAGE', 'android.permission.WRITE_EXTERNAL_STORAGE',
    'android.permission.ACCESS_FINE_LOCATION', 'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.BLUETOOTH_CONNECT', 'android.permission.BLUETOOTH_SCAN',
    'android.permission.READ_PHONE_STATE'))


def load_policy(path=DEFAULT_POLICY):
    source = Path(path)
    if source.stat().st_size > 32768 or source.is_symlink():
        raise ValueError('unsafe policy source')
    policy = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(policy, dict) or policy.get('schema_version') != '1.0.0':
        raise ValueError('unsupported content policy schema')
    if not isinstance(policy.get('lexical_review_terms'), dict) or not isinstance(policy.get('owner_excluded_senses'), list):
        raise ValueError('missing lexical policy entries')
    for k in ('image_reject_tags', 'image_review_tags', 'audio_reject_tags'):
        if not isinstance(policy.get(k), list) or not all(isinstance(x, str) for x in policy[k]):
            raise ValueError('invalid media policy entries')
    for locale, terms in policy['lexical_review_terms'].items():
        if not LANGUAGE_CODE.fullmatch(locale) or not isinstance(terms, list) or not all(isinstance(t, str) and t for t in terms):
            raise ValueError('invalid per-language lexical policy')
    if not all(isinstance(x, str) and x for x in policy['owner_excluded_senses']):
        raise ValueError('invalid excluded senses')
    return policy


def _contains_private_keys(value, depth=0):
    if depth > 6:
        return True  # not safe to infer absence of personal metadata
    if isinstance(value, dict):
        if any(str(k).casefold() in SENSITIVE_KEYS for k in value):
            return True
        return any(_contains_private_keys(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_contains_private_keys(v, depth + 1) for v in value[:100]) or len(value) > 100
    return False


def _terms_appear(s, terms):
    """Word-boundary check, never substring-filter compound words or strip accents."""
    folded = unicodedata.normalize('NFC', s).casefold()
    return any(re.search(r'(?<!\w)' + re.escape(unicodedata.normalize('NFC', term).casefold()) + r'(?!\w)', folded)
               for term in terms)


def _codes_for_text(value, locale, policy):
    if not isinstance(value, str):
        return ['NON_TEXT_VALUE'] if value is not None else []
    if not isinstance(locale, str):
        return ['INVALID_LANGUAGE_CODE']
    base = locale.lower().split('-')[0]
    if base not in policy['lexical_review_terms']:
        return ['LANGUAGE_SCREENING_NOT_CONFIGURED']
    if _terms_appear(value, policy['lexical_review_terms'].get(base, [])):
        return ['AMBIGUOUS_EXCLUDED_TERM']
    return []


def review_item(item, policy):
    """One anonymous deterministic decision. No raw content or IDs echoed.

    ALLOW means only that this lightweight candidate QA saw no trigger;
    it never means rights verification, publication approval or media inspection.
    """
    reasons = []
    if not isinstance(item, dict):
        return _result('REJECT', ['MALFORMED_RECORD'], 'EVIDENCE_REQUIRED')
    if _contains_private_keys(item):
        return _result('REJECT', ['LEARNER_DATA_IN_CANDIDATE'], 'EVIDENCE_REQUIRED')
    if not SAFE_ID.fullmatch(item.get('item_id', '') if isinstance(item.get('item_id'), str) else ''):
        reasons.append('MALFORMED_ITEM_ID')
    src = item.get('source_language')
    tgt = item.get('target_language')
    if not all(isinstance(x, str) and LANGUAGE_CODE.fullmatch(x) for x in (src, tgt)):
        reasons.append('MISSING_LANGUAGE_PAIR')
    media_type = item.get('media_type')
    if media_type not in ('text', 'image', 'audio'):
        reasons.append('UNKNOWN_MEDIA_TYPE')
    sense = item.get('sense_id')
    if isinstance(sense, str) and sense in policy['owner_excluded_senses']:
        return _result('REJECT', ['OWNER_EXCLUDED_SENSE'], 'EVIDENCE_REQUIRED')
    if media_type == 'text':
        reasons.extend(_codes_for_text(item.get('source_text'), src, policy))
        reasons.extend(_codes_for_text(item.get('target_text'), tgt, policy))
        if not isinstance(item.get('source_text'), str) or not item['source_text'].strip():
            reasons.append('NO_SOURCE_TEXT')
        for field, locale in (('definition', src), ('notes', src)):
            if field in item:
                reasons.extend(_codes_for_text(item[field], locale, policy))
        for field, default_locale in (('examples', src), ('translations', tgt)):
            values = item.get(field, [])
            if not isinstance(values, list) or len(values) > 50:
                reasons.append('INVALID_MULTILINGUAL_COLLECTION')
                continue
            for value in values:
                if isinstance(value, str):
                    reasons.extend(_codes_for_text(value, default_locale, policy))
                elif isinstance(value, dict):
                    lang = value.get('language')
                    if not isinstance(lang, str) or not LANGUAGE_CODE.fullmatch(lang):
                        reasons.append('MISSING_EXAMPLE_LANGUAGE')
                    reasons.extend(_codes_for_text(value.get('text'), lang, policy))
                else:
                    reasons.append('INVALID_MULTILINGUAL_ENTRY')
    elif media_type in ('image', 'audio'):
        tags = item.get('tags', [])
        if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
            reasons.append('INVALID_MEDIA_TAGS')
            tags = []
        observed = {tag.casefold() for tag in tags}
        rejecting = policy['image_reject_tags'] if media_type == 'image' else policy['audio_reject_tags']
        if observed.intersection(t.casefold() for t in rejecting):
            return _result('REJECT', ['EXPLICIT_MEDIA_RISK_TAG'], 'EVIDENCE_REQUIRED')
        if media_type == 'image' and observed.intersection(t.casefold() for t in policy['image_review_tags']):
            reasons.append('IMAGE_VISUAL_REVIEW_REQUIRED')
        if media_type == 'audio':
            reasons.extend(_codes_for_text(item.get('transcript'), src, policy))
        reasons.append('MEDIA_NOT_INSPECTED')  # tags/transcripts cannot verify pixels/waveform
    elif media_type not in ('text', 'image', 'audio'):
        pass
    # No PII, content, evidence blob, or source path is included in the report.
    codes = list(dict.fromkeys(reasons))
    return _result('HUMAN_REVIEW' if codes else 'ALLOW', codes, 'EVIDENCE_REQUIRED')


def _result(decision, codes, rights):
    return {'decision': decision, 'reason_codes': codes,
            'rights_status': rights, 'publication_approved': False,
            'inspection_level': 'metadata_and_text_only'}


def audit_candidates(records, policy):
    counts = {decision: 0 for decision in DECISIONS}
    results = []
    for idx, item in enumerate(records, 1):
        result = review_item(item, policy)
        counts[result['decision']] += 1
        results.append({'record_number': idx, **result})
    return {'schema_version': '1.0.0', 'counts': counts, 'total': sum(counts.values()),
            'decisions': results, 'publication_approved': False,
            'rights_verification': 'NOT_PERFORMED', 'media_byte_inspection': 'NOT_PERFORMED'}


def scan_jsonl(path, policy):
    max_line = min(policy.get('max_jsonl_line_bytes', 131072), 131072)
    max_records = min(policy.get('max_records', 10000), 10000)
    if not isinstance(max_line, int) or max_line < 128 or not isinstance(max_records, int) or max_records < 1:
        raise ValueError('invalid input limits')
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('unsafe/missing candidate source')
    def bounded():
        with path.open('rb') as stream:
            for index in range(1, max_records + 2):
                line = stream.readline(max_line + 1)
                if not line:
                    return
                if index > max_records:
                    raise ValueError('candidate count exceeds bound')
                if len(line) > max_line:
                    yield {'media_type': 'invalid', 'item_id': 'invalid', 'source_language': 'xx', 'target_language': 'yy', 'source_text': ''}
                    # Don't continue parsing after overflowing a line to avoid treating tail as record.
                    raise ValueError('oversized candidate line')
                try:
                    yield json.loads(line.decode('utf-8'))
                except (UnicodeError, ValueError):
                    yield None
    return audit_candidates(bounded(), policy)


def privacy_inventory(paths):
    """Path-only screening. No filenames or file bytes included in report."""
    count = 0
    total = 0
    for p in paths:
        total += 1
        if not isinstance(p, str) or SENSITIVE_PATH.search(p.replace('\\', '/')):
            count += 1
    return {'status': 'HUMAN_REVIEW' if count else 'UNKNOWN', 'flagged_count': count,
            'paths_scanned': total, 'file_contents_verified': False,
            'reason_codes': ['SENSITIVE_PUBLIC_PATH_INDICATORS'] if count else ['PATH_ONLY_CANNOT_PROVE_PRIVACY']}


def manifest_audit(xml_text):
    """Read-only permission inventory; permission usage must be reviewed in app context."""
    try:
        root = ET.fromstring(xml_text)
        perms = {p.attrib.get('{http://schemas.android.com/apk/res/android}name', '')
                 for p in root if p.tag in ('uses-permission', 'uses-permission-sdk-23')}
    except (ET.ParseError, TypeError):
        return {'status': 'UNKNOWN', 'permissions_to_review': [], 'reason_codes': ['MANIFEST_NOT_VERIFIED']}
    flagged = sorted(perms & PERMISSIONS_TO_REVIEW)
    return {'status': 'HUMAN_REVIEW' if flagged else 'ALLOW',
            'permissions_to_review': flagged, 'permissions_present_count': len(perms),
            'reason_codes': ['FEATURE_OWNER_REVIEW_REQUIRED'] if flagged else [],
            'manifest_modified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='bounded candidate JSONL; no network access')
    parser.add_argument('--policy', default=str(DEFAULT_POLICY), help='offline editable policy')
    parser.add_argument('--paths-json', help='optional JSON array of public repository paths (metadata only)')
    parser.add_argument('--manifest', help='optional local AndroidManifest.xml read-only input')
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        report = scan_jsonl(args.input, policy)
        report['privacy_qa'] = {'status': 'UNKNOWN', 'reason_codes': ['NO_PUBLIC_FILE_INVENTORY_PROVIDED']}
        if args.paths_json:
            p = Path(args.paths_json)
            if p.is_symlink() or p.stat().st_size > 1024 * 1024:
                raise ValueError('unsafe path inventory')
            paths = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(paths, list) or len(paths) > 200000:
                raise ValueError('invalid path inventory')
            report['privacy_qa'] = privacy_inventory(paths)
        report['android_qa'] = {'status': 'UNKNOWN', 'reason_codes': ['ANDROID_MANIFEST_NOT_PROVIDED']}
        if args.manifest:
            p = Path(args.manifest)
            if p.is_symlink() or p.stat().st_size > 1024 * 1024:
                raise ValueError('unsafe manifest')
            report['android_qa'] = manifest_audit(p.read_text(encoding='utf-8'))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report['counts']['REJECT'] == 0 and report['counts']['HUMAN_REVIEW'] == 0 else 1
    except (OSError, ValueError, TypeError) as exc:
        # Exception messages may contain private paths/bytes: never echo them.
        print(json.dumps({'error': 'AUDIT_INCOMPLETE', 'publication_approved': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
