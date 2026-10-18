#!/usr/bin/env python3
"""Offline source-specific rights evidence preflight; NEVER grants pack release.

Reads the canonical legal/ledger/sources.json schema without changing it.
No network access, source download, source admission, or automatic legal advice.
"""
import argparse
import hashlib
import ipaddress
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SUPPORTED = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'}
MEDIA = {'font', 'pronunciation', 'vector_art', 'visual_asset'}
KINDS = MEDIA | {'dictionary', 'morphology', 'examples'}
HEX = re.compile(r'^[0-9a-f]{64}$')
NC = re.compile(r'\bcc\s*[- ]?by\s*[- ]?nc\b|attribution\s*[- ]?noncommercial|\bnon[- ]commercial\b', re.I)
ND = re.compile(r'\bcc\s*[- ]?by\s*[- ]?nd\b|\bno[- ]derivatives\b', re.I)
NOTICE_LABELS = {
    'CC-BY-SA-4.0': re.compile(r'\bcc\s*[- ]?by\s*[- ]?sa\s*[- ]?4\.0\b|attribution\s*[- ]?share\s*[- ]?alike\s*4\.0', re.I),
    'GFDL-1.3-only': re.compile(r'\bgfdl\b|gnu free documentation license', re.I),
    'CC0-1.0': re.compile(r'\bcc0\b|creative commons zero', re.I),
}
MAX_NOTICE_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024


def finding(out, code, severity, detail):
    out.append({'code': code, 'severity': severity, 'detail': detail})


def safe_url(value):
    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value):
        return False
    try:
        u = urlsplit(value)
        host = u.hostname
        if u.scheme != 'https' or not host or u.username or u.password or u.port not in (None, 443):
            return False
        if host.lower() in {'localhost'} or host.lower().endswith(('.local', '.internal')):
            return False
        if host.startswith('[') or '\\' in value or '%00' in value.lower():
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        secret_names = {'token', 'key', 'access_token', 'signature', 'auth', 'password', 'api_key'}
        return not (set(k.lower() for k in parse_qs(u.query)) & secret_names)
    except (ValueError, TypeError):
        return False


def evidence(root, relative, expected, label, out, *, notice=False):
    """Hash actual bytes, reject traversal and symlinks; never read remote URLs."""
    prefix = 'NOTICE' if notice else 'ARTIFACT'
    if not isinstance(relative, str) or not relative or not isinstance(expected, str) or not HEX.fullmatch(expected):
        finding(out, prefix + '_MISSING', 'REVIEW_REQUIRED', label + ': local proof path and SHA256 required')
        return None
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative or '.git' in path.parts:
        finding(out, 'UNSAFE_PATH', 'BLOCKED', label + ': unsafe relative path')
        return None
    root = Path(root).resolve()
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            finding(out, 'UNSAFE_PATH', 'BLOCKED', label + ': symbolic link in evidence path')
            return None
    resolved = cursor.resolve()
    if not resolved.is_relative_to(root):
        finding(out, 'UNSAFE_PATH', 'BLOCKED', label + ': path escapes evidence root')
        return None
    if not resolved.is_file():
        finding(out, prefix + '_MISSING', 'REVIEW_REQUIRED', label + ': actual source bytes unavailable')
        return None
    size = resolved.stat().st_size
    if size > (MAX_NOTICE_BYTES if notice else MAX_ARTIFACT_BYTES):
        finding(out, prefix + '_TOO_LARGE', 'REVIEW_REQUIRED', label + ': exceeds bounded audit limit')
        return None
    digest = hashlib.sha256()
    with resolved.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        finding(out, prefix + '_HASH_MISMATCH', 'BLOCKED', label + ': original bytes differ from declared SHA256')
        return None
    return resolved.read_bytes() if notice else True


def audit_source(source, root):
    out = []
    if not isinstance(source, dict):
        return {'source_id': '<invalid>', 'decision': 'BLOCKED', 'findings': [
            {'code': 'INVALID_SOURCE', 'severity': 'BLOCKED', 'detail': 'source entry is not an object'}]}
    sid = source.get('source_id')
    if not isinstance(sid, str) or not sid.strip():
        finding(out, 'SOURCE_ID_MISSING', 'UNKNOWN', 'source has no identity')
    sid = sid if isinstance(sid, str) and sid.strip() else '<missing>'
    if not isinstance(source.get('kind'), str) or source.get('kind') not in KINDS:
        finding(out, 'KIND_UNKNOWN', 'UNKNOWN', 'source media/text kind not recognized')
    for key in ('origin_url',):
        if not safe_url(source.get(key)):
            finding(out, 'UNSAFE_URL', 'BLOCKED', key + ' must be a safe HTTPS origin')
    for key in ('publisher', 'dataset_version'):
        if not isinstance(source.get(key), str) or not source[key].strip():
            finding(out, 'PROVENANCE_MISSING', 'UNKNOWN', key + ' is missing')
    retrieval = source.get('retrieval')
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    if not safe_url(retrieval.get('url')):
        finding(out, 'UNSAFE_URL', 'BLOCKED', 'retrieval URL is not acceptable HTTPS')
    else:
        path = urlsplit(retrieval['url']).path.lower()
        if any(x in path for x in ('latest', '/current/', 'raw-wiktextract-data.jsonl.gz')):
            finding(out, 'MUTABLE_SOURCE_URL', 'REVIEW_REQUIRED', 'retrieval URL is mutable; retain immutable snapshot')
    if not isinstance(retrieval.get('identity'), str) or not retrieval['identity'].strip():
        finding(out, 'SNAPSHOT_ID_MISSING', 'REVIEW_REQUIRED', 'immutable retrieval identity not recorded')
    try:
        if date.fromisoformat(retrieval['date']).isoformat() != retrieval['date']:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        finding(out, 'RETRIEVAL_DATE_MISSING', 'REVIEW_REQUIRED', 'exact retrieval date required')
    evidence(root, retrieval.get('artifact_path'), retrieval.get('sha256'), sid + ' source', out)

    lic = source.get('license')
    lic = lic if isinstance(lic, dict) else {}
    lid = lic.get('id')
    if not isinstance(lid, str) or lid not in SUPPORTED:
        if isinstance(lid, str) and (NC.search(lid) or ND.search(lid)):
            finding(out, 'RESTRICTED_LICENSE', 'BLOCKED', 'NC/ND license is not approved for commercial corpus')
        else:
            finding(out, 'LICENSE_UNKNOWN', 'UNKNOWN', 'unsupported or undocumented license; never assume CC0')
    if not safe_url(lic.get('evidence_url')):
        finding(out, 'UNSAFE_URL', 'BLOCKED', 'source-specific license evidence URL required')
    elif urlsplit(lic['evidence_url']).hostname in {'creativecommons.org', 'www.gnu.org', 'gnu.org'}:
        finding(out, 'GENERIC_LICENSE_ONLY', 'REVIEW_REQUIRED', 'license terms URL is not a source-specific notice')
    notice = evidence(root, lic.get('evidence_path'), lic.get('evidence_sha256'), sid + ' notice', out, notice=True)
    if isinstance(notice, bytes):
        content = notice.decode('utf-8', 'replace')
        if NC.search(content) or ND.search(content):
            finding(out, 'NONCOMMERCIAL_RESTRICTION', 'BLOCKED', 'notice contains NC/ND restrictions; manual assessment needed')
        recognized = {key for key, pattern in NOTICE_LABELS.items() if pattern.search(content)}
        if not recognized:
            finding(out, 'NOTICE_LICENSE_UNDETERMINED', 'REVIEW_REQUIRED', 'original notice does not establish selected license')
        elif lid in SUPPORTED and lid not in recognized and lid != 'PUBLIC-DOMAIN':
            finding(out, 'NOTICE_LICENSE_CONFLICT', 'BLOCKED', 'declared license contradicts observed source notice')
        elif lid == 'PUBLIC-DOMAIN':
            finding(out, 'PUBLIC_DOMAIN_PROOF_REVIEW', 'REVIEW_REQUIRED', 'license notice text cannot by itself prove public domain')
        elif len(recognized) > 1:
            finding(out, 'MULTI_LICENSE_REVIEW', 'REVIEW_REQUIRED', 'dual/multiple licensing requires independent route selection')
    if lid == 'PUBLIC-DOMAIN':
        pd = lic.get('public_domain_proof')
        if not isinstance(pd, dict) or not all(isinstance(pd.get(k), str) and pd[k].strip() for k in ('jurisdiction', 'legal_basis', 'work_date')):
            finding(out, 'PUBLIC_DOMAIN_PROOF_MISSING', 'REVIEW_REQUIRED', 'jurisdiction, legal basis and work date required')
    if isinstance(source.get('kind'), str) and source.get('kind') in MEDIA:
        finding(out, 'MEDIA_RIGHTS_REVIEW', 'REVIEW_REQUIRED', 'independently verify rights for each font, image, artwork or audio item')
    if not isinstance(source.get('alterations'), list) or not source['alterations']:
        finding(out, 'ALTERATIONS_MISSING', 'REVIEW_REQUIRED', 'original versus modified provenance not documented')
    status = source.get('status')
    if status == 'BLOCKED_LICENSE':
        finding(out, 'NOT_APPROVED', 'BLOCKED', 'canonical ledger explicitly blocks source')
    elif status != 'APPROVED_FOR_REDISTRIBUTION':
        finding(out, 'NOT_APPROVED', 'REVIEW_REQUIRED', 'canonical source owner has not approved this source')
    review = source.get('review')
    if not isinstance(review, dict) or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip() or not safe_url(review.get('decision_url')):
        finding(out, 'MANUAL_REVIEW_MISSING', 'REVIEW_REQUIRED', 'independent reviewer and verifiable decision URL needed')
    severities = {i['severity'] for i in out}
    decision = next((x for x in ('BLOCKED', 'UNKNOWN', 'REVIEW_REQUIRED') if x in severities), 'APPROVED')
    return {'source_id': sid, 'kind': source.get('kind'), 'decision': decision,
            'findings': sorted(out, key=lambda a: (a['code'], a['detail']))}


def audit_ledger(ledger, root):
    if not isinstance(ledger, dict) or ledger.get('schema_version') != '1.0.0' or not isinstance(ledger.get('sources'), list):
        return {'status': 'BLOCKED', 'release_ready': False, 'sources': [],
                'counts': {k: 0 for k in ('APPROVED', 'REVIEW_REQUIRED', 'BLOCKED', 'UNKNOWN')},
                'error': 'invalid canonical source ledger schema'}
    results = [audit_source(s, root) for s in ledger['sources']]
    counts = {k: sum(x['decision'] == k for x in results) for k in ('APPROVED', 'REVIEW_REQUIRED', 'BLOCKED', 'UNKNOWN')}
    ids = [r['source_id'] for r in results]
    duplicate = len(ids) != len(set(ids))
    status = ('BLOCKED' if duplicate or counts['BLOCKED'] else
              'UNKNOWN' if not results or counts['UNKNOWN'] else
              'REVIEW_REQUIRED' if counts['REVIEW_REQUIRED'] else 'APPROVED')
    return {'status': status, 'release_ready': False, 'sources': results,
            'counts': counts, 'error': 'duplicate source IDs' if duplicate else None,
            'notice': 'Source audit only. Canonical admission, legal review, release QA and pack gates are separate.'}


def to_markdown(report):
    lines = ['# Source rights evidence audit', '', f"Source preflight: **{report['status']}**",
             '', '**Release ready: NO** — this report cannot authorize packs.', '',
             '| Source | Type | Decision | Findings |', '|---|---|---|---|']
    for row in report['sources']:
        label = str(row['source_id']).replace('|', '\\|').replace('\n', ' ')
        codes = ', '.join(f['code'] for f in row['findings']) or 'none'
        lines.append(f"| {label} | {row['kind']} | {row['decision']} | {codes} |")
    if not report['sources']:
        lines.append('| (none registered) | — | UNKNOWN | NO_APPROVED_SOURCES |')
    if report.get('error'):
        lines.extend(['', 'Registry error: ' + report['error']])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--ledger', type=Path, default=Path('legal/ledger/sources.json'))
    parser.add_argument('--json-report', type=Path)
    parser.add_argument('--markdown-report', type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        report = audit_ledger(ledger, root)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        report = {'status': 'UNKNOWN', 'release_ready': False, 'sources': [],
                  'counts': {k: 0 for k in ('APPROVED', 'REVIEW_REQUIRED', 'BLOCKED', 'UNKNOWN')},
                  'error': 'cannot read source registry: ' + type(exc).__name__}
    json_text = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + '\n'
    if args.json_report:
        args.json_report.write_text(json_text, encoding='utf-8')
    else:
        print(json_text, end='')
    if args.markdown_report:
        args.markdown_report.write_text(to_markdown(report), encoding='utf-8')
    return 0 if report['status'] == 'APPROVED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
