#!/usr/bin/env python3
"""Fail-closed offline redistribution admission gate. Never grants legal approval."""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SCHEMA = '1.0.0'
KINDS = {'dictionary', 'morphology', 'examples', 'font', 'pronunciation',
         'vector_art', 'visual_asset'}
LICENSES = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'}
OBLIGATIONS = {
    'CC-BY-SA-4.0': ('attribution', 'license_link', 'changes_disclosed',
                     'sharealike', 'no_additional_restrictions'),
    'GFDL-1.3-only': ('license_copy', 'copyright_notices', 'history',
                      'invariant_sections_checked', 'cover_texts_checked',
                      'transparent_copy_checked'),
}
HASH = re.compile(r'^[0-9a-f]{64}$')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def issue(out, code, label):
    out.append(f'{code}: {label}')


def text(value):
    return isinstance(value, str) and bool(value.strip())


def url_ok(value):
    if not text(value):
        return False
    try:
        u = urlsplit(value)
        forbidden = {'token', 'key', 'access_token', 'signature', 'auth', 'password'}
        return (u.scheme == 'https' and bool(u.hostname) and not u.username
                and not u.password and not (set(parse_qs(u.query)) & forbidden))
    except ValueError:
        return False


def valid_date(value):
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def artifact(root, relative, expected, out, label):
    """Verify local immutable evidence: never fetch unknown URLs or follow escapes."""
    if not text(relative) or not isinstance(expected, str) or not HASH.fullmatch(expected):
        issue(out, 'EVIDENCE', f'{label}: path and SHA-256 required')
        return False
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or '.git' in path.parts:
        issue(out, 'EVIDENCE', f'{label}: path outside approved repository')
        return False
    resolved_root = Path(root).resolve()
    resolved = (resolved_root / path).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        issue(out, 'EVIDENCE', f'{label}: missing or escaping local proof file')
        return False
    if sha256_file(resolved) != expected:
        issue(out, 'HASH_MISMATCH', f'{label}: artifact differs from recorded SHA-256')
        return False
    return True


def manual_review(value, out, label):
    if not isinstance(value, dict) or not text(value.get('reviewer')) or not url_ok(value.get('decision_url')):
        issue(out, 'MANUAL_REVIEW', f'{label}: reviewer and public decision evidence required')
        return False
    return True


def evaluate(ledger, manifest, dailies, root):
    """Return sorted admission blockers; empty only for explicitly reviewed evidence."""
    out = []
    if not isinstance(ledger, dict) or ledger.get('schema_version') != SCHEMA:
        return ['SCHEMA_VERSION: unsupported provenance ledger version']
    if not isinstance(ledger.get('sources'), list):
        return ['SCHEMA: sources must be a list']
    sources = {}
    for source in ledger['sources']:
        if not isinstance(source, dict):
            issue(out, 'SCHEMA', 'source must be object')
            continue
        sid = source.get('source_id')
        label = str(sid)
        if not text(sid):
            issue(out, 'SCHEMA', 'missing source_id')
            continue
        if sid in sources:
            issue(out, 'DUPLICATE', f'{sid}: repeated source ID')
        sources[sid] = source
        if source.get('kind') not in KINDS:
            issue(out, 'SCHEMA', f'{label}: invalid kind')
        for key in ('origin_url',):
            if not url_ok(source.get(key)):
                issue(out, 'EVIDENCE', f'{label}: exact HTTPS {key} required')
        if not text(source.get('publisher')) or not text(source.get('dataset_version')):
            issue(out, 'EVIDENCE', f'{label}: publisher and exact dataset version required')
        retrieval = source.get('retrieval') or {}
        if not isinstance(retrieval, dict):
            retrieval = {}
        if not text(retrieval.get('identity')) or not url_ok(retrieval.get('url')) or not valid_date(retrieval.get('date')):
            issue(out, 'EVIDENCE', f'{label}: retrieval identity, HTTPS URL and date required')
        artifact(root, retrieval.get('artifact_path'), retrieval.get('sha256'), out, f'{label} source')
        license_info = source.get('license') or {}
        if not isinstance(license_info, dict):
            license_info = {}
        lid = license_info.get('id')
        if lid not in LICENSES:
            issue(out, 'BLOCKED_LICENSE', f'{label}: unknown or unsupported license')
        if not url_ok(license_info.get('evidence_url')):
            issue(out, 'EVIDENCE', f'{label}: source-specific license URL required')
        else:
            url = license_info['evidence_url']
            if ('creativecommons.org/licenses/' in url or
                'creativecommons.org/publicdomain/zero/' in url or
                'gnu.org/licenses/fdl-' in url):
                issue(out, 'EVIDENCE', f'{label}: generic license terms are not source-specific proof')
        artifact(root, license_info.get('evidence_path'), license_info.get('evidence_sha256'), out, f'{label} license proof')
        if lid == 'PUBLIC-DOMAIN':
            pd = license_info.get('public_domain_proof') or {}
            if not isinstance(pd, dict) or not all(text(pd.get(k)) for k in ('jurisdiction', 'legal_basis', 'work_date')):
                issue(out, 'PD_PROOF', f'{label}: jurisdiction, legal basis and work date required')
        if source.get('kind') == 'vector_art':
            if not url_ok(license_info.get('artwork_evidence_url')):
                issue(out, 'ARTWORK_LICENSE', f'{label}: distinct artwork license evidence required')
            artwork_errors = []
            artifact(root, license_info.get('artwork_evidence_path'),
                     license_info.get('artwork_evidence_sha256'), artwork_errors,
                     f'{label} vector artwork rights proof')
            if artwork_errors:
                issue(out, 'ARTWORK_LICENSE', f'{label}: missing or altered vector artwork evidence')
        if source.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
            issue(out, 'REVIEW_REQUIRED' if source.get('status') == 'REVIEW_REQUIRED' else 'BLOCKED_LICENSE',
                  f'{label}: source not manually approved')
        else:
            manual_review(source.get('review'), out, f'{label} source')
        if not isinstance(source.get('alterations'), list) or not source['alterations']:
            issue(out, 'EVIDENCE', f'{label}: alteration history required (including none)')

    candidates = {}
    for daily in dailies:
        if not isinstance(daily, dict) or daily.get('schema_version') != SCHEMA or not valid_date(daily.get('date')):
            issue(out, 'SCHEMA_VERSION', 'daily content manifest has invalid schema/date')
            continue
        items = daily.get('release_candidates')
        if not isinstance(items, list):
            issue(out, 'SCHEMA', 'daily release_candidates must be list')
            continue
        for entry in items:
            if not isinstance(entry, dict):
                issue(out, 'SCHEMA', 'release candidate must be object')
                continue
            cid = entry.get('asset_id')
            label = str(cid)
            if not text(cid):
                issue(out, 'SCHEMA', 'missing asset_id')
                continue
            if cid in candidates:
                issue(out, 'DUPLICATE', f'{cid}: duplicate candidate across daily manifests')
            candidates[cid] = entry
            if entry.get('kind') not in KINDS:
                issue(out, 'SCHEMA', f'{cid}: unknown candidate kind')
            artifact(root, entry.get('artifact_path'), entry.get('sha256'), out, f'{cid} release asset')
            refs = entry.get('source_refs')
            if not isinstance(refs, list) or not refs:
                issue(out, 'SOURCE_PROVENANCE', f'{cid}: source_refs missing')
                refs = []
            resolved = []
            for ref in refs:
                if not isinstance(ref, dict) or ref.get('source_id') not in sources:
                    issue(out, 'SOURCE_PROVENANCE', f'{cid}: unknown source reference')
                    continue
                src = sources[ref['source_id']]
                resolved.append(src)
                if entry.get('kind') != src.get('kind'):
                    issue(out, 'SOURCE_PROVENANCE', f'{cid}: source kind does not match asset kind')
                if ref.get('dataset_version') != src.get('dataset_version'):
                    issue(out, 'VERSION_MISMATCH', f"{cid}: {ref['source_id']} dataset version changed")
                if ref.get('artifact_sha256') != (src.get('retrieval') or {}).get('sha256'):
                    issue(out, 'HASH_MISMATCH', f"{cid}: {ref['source_id']} source snapshot changed")
            ids = {r['source_id'] for r in resolved}
            if not text(entry.get('compiler_license_id')):
                issue(out, 'COMPILER_LICENSE', f'{cid}: separate compiler license required')
            output_license = entry.get('output_license_id')
            if output_license not in LICENSES:
                issue(out, 'BLOCKED_LICENSE', f'{cid}: unsupported output license')
            copyleft = {s['license']['id'] for s in resolved if s.get('license', {}).get('id') in OBLIGATIONS}
            if len(copyleft) > 1:
                issue(out, 'LICENSE_CONFLICT', f'{cid}: GFDL and CC BY-SA cannot be assumed interchangeable')
            for src in resolved:
                lid = src.get('license', {}).get('id')
                if lid in OBLIGATIONS and output_license != lid:
                    issue(out, 'LICENSE_CONFLICT', f"{cid}: {src['source_id']} cannot be relicensed to {output_license}")
                if lid == 'CC0-1.0' and output_license == 'PUBLIC-DOMAIN':
                    issue(out, 'LICENSE_CONFLICT', f'{cid}: CC0 is not a blanket public-domain claim')
            if not copyleft and resolved and output_license == 'PUBLIC-DOMAIN' and any(
                s.get('license', {}).get('id') != 'PUBLIC-DOMAIN' for s in resolved):
                issue(out, 'LICENSE_CONFLICT', f'{cid}: public-domain label contradicts original rights')
            notices = entry.get('notices') or {}
            if not isinstance(notices, dict):
                notices = {}
            for src in resolved:
                sid = src['source_id']
                rel = notices.get(sid)
                if not text(rel):
                    issue(out, 'NOTICE', f'{cid}: missing attribution/rights notice for {sid}')
                    continue
                try:
                    path = (Path(root).resolve() / rel).resolve()
                    if Path(rel).is_absolute() or not path.is_relative_to(Path(root).resolve()):
                        raise ValueError('bad path')
                    content = path.read_text(encoding='utf-8')
                    if not all(term in content for term in (sid, src['publisher'],
                             src['license']['id'], src['origin_url'])):
                        raise ValueError('notice incomplete')
                except (OSError, UnicodeError, ValueError):
                    issue(out, 'NOTICE', f'{cid}: incomplete/missing notice for {sid}')
            compliance = entry.get('compliance') or {}
            for lid in copyleft:
                for requirement in OBLIGATIONS[lid]:
                    if not isinstance(compliance, dict) or compliance.get(requirement) is not True:
                        issue(out, 'OBLIGATION', f'{cid}: {lid} requires {requirement}')
            if 'GFDL-1.3-only' in copyleft:
                rel = entry.get('gfdl_license_copy_path')
                try:
                    path = (Path(root).resolve() / rel).resolve()
                    if Path(rel).is_absolute() or not path.is_relative_to(Path(root).resolve()):
                        raise ValueError('invalid')
                    if 'GNU Free Documentation License' not in path.read_text(encoding='utf-8'):
                        raise ValueError('license not found')
                except (TypeError, OSError, UnicodeError, ValueError):
                    issue(out, 'NOTICE', f'{cid}: GFDL license text copy absent')
            mode = entry.get('provenance_mode')
            if mode == 'per_record':
                records = entry.get('record_sources')
                if not isinstance(records, list) or not records:
                    issue(out, 'RECORD_PROVENANCE', f'{cid}: missing per-record mappings')
                else:
                    record_ids = set()
                    for record in records:
                        if not isinstance(record, dict) or not text(record.get('record_id')) or not isinstance(record.get('source_ids'), list) or not record['source_ids'] or not set(record['source_ids']).issubset(ids) or record['record_id'] in record_ids:
                            issue(out, 'RECORD_PROVENANCE', f'{cid}: incomplete record-source mapping')
                        else:
                            record_ids.add(record['record_id'])
            elif mode != 'source_set' or not text(entry.get('record_provenance_reason')):
                issue(out, 'RECORD_PROVENANCE', f'{cid}: per_record or justified source_set required')
            manual_review(entry.get('review'), out, f'{cid} candidate')

    if not isinstance(manifest, dict):
        issue(out, 'SCHEMA', 'public manifest must be object')
        return sorted(set(out))
    if manifest.get('intellectual_property_status') == 'PUBLIC_DOMAIN_ZERO_COPYRIGHT':
        issue(out, 'BLOCKED_LICENSE', 'public manifest asserts unsupported blanket PUBLIC_DOMAIN_ZERO_COPYRIGHT')
    published = []
    if not isinstance(manifest.get('languages', []), list) or not isinstance(manifest.get('packs', []), list):
        issue(out, 'SCHEMA', 'public manifest languages/packs must be arrays')
        return sorted(set(out))
    for language in manifest.get('languages', []):
        if isinstance(language, dict) and language.get('is_active') and text(language.get('pack_file')):
            published.append('packs/' + language['pack_file'])
    for pack in manifest.get('packs', []):
        if isinstance(pack, dict):
            for key in ('file', 'pack_file', 'artifact_path'):
                if text(pack.get(key)):
                    published.append(pack[key]); break
    admitted_paths = {e.get('artifact_path') for e in candidates.values()}
    for path in published:
        if path not in admitted_paths:
            issue(out, 'UNVERIFIED_RELEASE', f'{path}: published without approved source and daily candidate')
    return sorted(set(out))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--daily-dir', type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    ledger_path = args.ledger or root / 'legal/ledger/sources.json'
    manifest_path = args.manifest or root / 'manifest.json'
    daily_dir = args.daily_dir or root / 'legal/ledger/daily'
    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        dailies = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(daily_dir.glob('*.json'))]
    except (OSError, ValueError) as exc:
        print(f'EVIDENCE: cannot read admission inputs: {exc.__class__.__name__}', file=sys.stderr)
        return 2
    errors = evaluate(ledger, manifest, dailies, root)
    for e in errors:
        print('BLOCK ' + e)
    if errors:
        print(f'NO-GO: {len(errors)} distinct blockers')
        return 1
    print('EVIDENCE GATE PASS: human rights approval still required; no legal warranty')
    return 0


if __name__ == '__main__':
    sys.exit(main())
