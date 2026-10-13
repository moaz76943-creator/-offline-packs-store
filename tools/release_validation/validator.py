#!/usr/bin/env python3
"""Offline fail-closed public release audit; never compiles or publishes packs."""
import argparse
import base64
import hashlib
import json
import re
import sqlite3
import tempfile
import zlib
from pathlib import Path

LANGUAGES = ('de', 'ar', 'en', 'es', 'fr')
MEMBERS = {'content/content.json', 'content/content.sqlite', 'metadata/pack.json'}
CDN = 'https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/'
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_ENVELOPE = 8 * 1024 * 1024
MAX_MEMBER = 80 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
SEMVER = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
SHA = re.compile(r'^[0-9a-f]{64}$')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def confined(root, relative):
    """An exact, existing repository-local regular file, never a path traversal."""
    if not isinstance(relative, str) or '\\' in relative or relative.startswith('/'):
        raise ValueError('unsafe path')
    parts = Path(relative).parts
    if '..' in parts or '.' in parts or not parts:
        raise ValueError('unsafe path')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError('file missing or unsafe')
    return target


def bounded_gzip(blob):
    if len(blob) > MAX_ARCHIVE:
        raise ValueError('archive limit exceeded')
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    result = inflater.decompress(blob, MAX_ENVELOPE + 1)
    if len(result) > MAX_ENVELOPE or not inflater.eof or inflater.unused_data:
        raise ValueError('gzip envelope limit, truncation or trailing data')
    return result


def inspect_archive(archive, language, version, expected_content_sha):
    """Check real decompression, required consumer members, SQLite integrity and FTS5."""
    if not SHA.fullmatch(expected_content_sha or ''):
        raise ValueError('missing valid content SHA-256')
    try:
        envelope = json.loads(bounded_gzip(archive))
    except (UnicodeDecodeError, json.JSONDecodeError, zlib.error) as exc:
        raise ValueError('invalid compressed envelope') from exc
    if not isinstance(envelope, dict) or envelope.get('packId') != language or envelope.get('version') != version:
        raise ValueError('envelope identity/version mismatch')
    files = envelope.get('files')
    if not isinstance(files, list) or len(files) != len(MEMBERS):
        raise ValueError('envelope required members missing')
    contents = {}
    used = 0
    for entry in files:
        if not isinstance(entry, dict) or entry.get('path') not in MEMBERS or entry['path'] in contents:
            raise ValueError('envelope member path invalid/duplicate')
        encoded = entry.get('contentBase64')
        if not isinstance(encoded, str) or len(encoded) > (MAX_MEMBER * 4 // 3 + 8):
            raise ValueError('member encoded length limit')
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError('invalid base64 member') from exc
        used += len(payload)
        if len(payload) > MAX_MEMBER or used > MAX_TOTAL:
            raise ValueError('decompressed member limit exceeded')
        contents[entry['path']] = payload
    if set(contents) != MEMBERS:
        raise ValueError('envelope required members missing')
    if digest(contents['content/content.sqlite']) != expected_content_sha:
        raise ValueError('content SHA-256 mismatch')
    try:
        metadata = json.loads(contents['metadata/pack.json'])
        document = json.loads(contents['content/content.json'])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON payload') from exc
    if not isinstance(document, dict) or not isinstance(metadata, dict):
        raise ValueError('non-object JSON payload')
    if metadata.get('packId') != language or metadata.get('version') != version:
        raise ValueError('metadata pack identity/version mismatch')
    with tempfile.TemporaryDirectory(prefix='public-pack-check-') as temp:
        db_path = Path(temp) / 'content.sqlite'
        db_path.write_bytes(contents['content/content.sqlite'])
        db_uri = db_path.as_uri() + '?mode=ro&immutable=1'
        try:
            with sqlite3.connect(db_uri, uri=True) as conn:
                conn.execute('PRAGMA trusted_schema=OFF')
                if conn.execute('PRAGMA user_version').fetchone()[0] != 2:
                    raise ValueError('SQLite user_version is not 2')
                if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity_check failed')
                if conn.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('SQLite foreign key check failed')
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                required = {'metadata', 'concepts', 'lexicon', 'senses', 'examples', 'lexicon_fts'}
                if not required.issubset(tables):
                    raise ValueError('SQLite v2 tables/FTS5 missing')
                counts = {k: conn.execute(f'SELECT count(*) FROM {k}').fetchone()[0]
                          for k in ('concepts', 'lexicon', 'senses', 'examples')}
                if min(counts['concepts'], counts['lexicon'], counts['senses']) < 1:
                    raise ValueError('placeholder or empty SQLite content')
                if conn.execute('SELECT count(*) FROM lexicon WHERE language_code != ?', (language,)).fetchone()[0]:
                    raise ValueError('cross-language lexicon contamination')
                sample = conn.execute('SELECT surface FROM lexicon WHERE length(trim(surface))>0 ORDER BY id LIMIT 1').fetchone()
                if not sample:
                    raise ValueError('no representative lexeme')
                tokens = re.findall(r'[^\W_]+', sample[0], re.UNICODE)
                if not tokens:
                    raise ValueError('FTS5 representative token missing')
                query = '"' + tokens[0].replace('"', '""') + '"'
                if not conn.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1', (query,)).fetchone():
                    raise ValueError('FTS5 MATCH query returned no entry')
                grammar = conn.execute('SELECT count(*) FROM grammar_rules').fetchone()[0] if 'grammar_rules' in tables else 0
        except sqlite3.DatabaseError as exc:
            raise ValueError('invalid SQLite v2 database or FTS5') from exc
    return {'concepts': counts['concepts'], 'lexemes': counts['lexicon'],
            'senses': counts['senses'], 'examples': counts['examples'],
            'grammar': grammar, 'fts_match': sample[0],
            'contentSha256': expected_content_sha}


def audit(root):
    root = Path(root).resolve()
    blocked = set()
    details = {}
    verified = []
    try:
        manifest, version = load(root/'manifest.json'), load(root/'version.json')
    except (OSError, ValueError, json.JSONDecodeError):
        return {'status':'BLOCKED_DEPENDENCY','blockers':['INVALID_INDEX_JSON'], 'verified_packs':[]}
    langs = manifest.get('languages')
    packs = manifest.get('packs')
    records = version.get('packs')
    if not isinstance(langs, list) or not isinstance(packs, list) or not isinstance(records, dict):
        return {'status':'BLOCKED_DEPENDENCY','blockers':['INVALID_INDEX_SCHEMA'], 'verified_packs':[]}
    ids = [x.get('code') for x in langs if isinstance(x, dict)]
    if len(ids) != len(set(ids)) or len(ids) != len(langs) or manifest.get('total_languages',len(langs)) != len(langs):
        blocked.add('LANGUAGE_REGISTRATION_INVALID')
    for code in LANGUAGES:
        if code not in ids:
            blocked.add('PILOT_LANGUAGE_UNREGISTERED')
    if manifest.get('intellectual_property_status') == 'PUBLIC_DOMAIN_ZERO_COPYRIGHT':
        blocked.add('UNSUPPORTED_BLANKET_COPYRIGHT_CLAIM')
    for lang in langs:
        if isinstance(lang, dict) and lang.get('is_active') and lang.get('pack_file') and not lang.get('pack_verified'):
            blocked.add('UNVERIFIED_LEGACY_ACTIVE')
        if isinstance(lang, dict) and lang.get('production_ready') and lang.get('code') not in [p.get('languageCode') for p in packs if isinstance(p,dict)]:
            blocked.add('FALSE_READY_LANGUAGE')
    # No source-specific approved artifacts means no production license clearance.
    try:
        ledger = load(root/'legal/ledger/sources.json')
        approved = [s for s in ledger['sources'] if s.get('status') == 'APPROVED_FOR_REDISTRIBUTION'
                    and s.get('retrieval', {}).get('sha256') and s.get('review',{}).get('reviewer')]
    except (OSError, ValueError, TypeError, KeyError):
        approved = []
    if not approved:
        blocked.add('APPROVED_LICENSE_SOURCES_MISSING')
    try:
        imported = load(root/'tools/sources/pilot5/blocked_sources.json')
    except (OSError, ValueError):
        imported = {}
    if imported.get('status') == 'BLOCKED_SOURCE' or not any((root/'tools/sources/pilot5').glob('*/lexical.json')):
        blocked.add('APPROVED_CORPUS_MISSING')
    if not (root/'catalog').is_dir():
        blocked.add('CANONICAL_REGISTRY_MISSING')
    if not (root/'tools/public_safety').is_dir():
        blocked.add('PUBLIC_SAFETY_GATE_MISSING')
    if not (root/'tools/pack_v2').is_dir():
        blocked.add('CANONICAL_COMPILER_MISSING')
    if not (root/'tools/release_validation/approved_consumer_fixture.json').is_file():
        blocked.add('APPROVED_CONSUMER_FIXTURE_MISSING')
    # Directory existence never constitutes an approval or a passed safety scan.
    try:
        evidence = load(root/'tools/release_validation/route_approvals.json')
        required_routes = ('02', '03', '05', '06', '07', '08', 'consumer')
        for route in required_routes:
            record = evidence['routes'][route]
            proof = confined(root, record['evidence_path'])
            if record.get('status') != 'APPROVED' or digest(proof.read_bytes()) != record.get('sha256'):
                raise ValueError('unapproved route evidence')
    except (OSError, ValueError, KeyError, TypeError):
        blocked.add('ROUTE_APPROVALS_MISSING_OR_INVALID')
    known = set()
    for p in packs:
        if not isinstance(p, dict):
            blocked.add('BAD_PACK_DESCRIPTOR'); continue
        lang, pack_id, ver = p.get('languageCode'), p.get('id'), p.get('version')
        path = p.get('artifact_path') or p.get('file') or p.get('pack_file')
        if lang not in LANGUAGES or pack_id in known or not isinstance(pack_id, str) or not SEMVER.fullmatch(ver or ''):
            blocked.add('INVALID_PACK_ID_OR_VERSION'); continue
        known.add(pack_id)
        if not isinstance(path,str) or not path.startswith('packs/pilot5/') or p.get('archiveUrl') != CDN+path:
            blocked.add('BAD_PACK_URL'); continue
        try:
            binary = confined(root, path).read_bytes()
            if p.get('sha256') != digest(binary) or p.get('archiveSizeBytes') != len(binary):
                raise ValueError('archive hash/size mismatch')
            inspected = inspect_archive(binary,lang,ver,p.get('contentSha256'))
            for name,col in [('conceptCount','concepts'),('lexemeCount','lexemes'),('senseCount','senses'),('exampleCount','examples'),('grammarCount','grammar')]:
                if name in p and p[name] != inspected[col]:
                    raise ValueError('pack count mismatch')
            verified.append({'id': pack_id, 'languageCode':lang, 'version':ver, 'artifact_path':path, **inspected})
        except (ValueError, OSError):
            blocked.add('PACK_CONTENT_NOT_VERIFIED')
    # Every version URL must address committed bytes in the same repository.
    for key,record in records.items():
        if not isinstance(record, dict):
            blocked.add('INVALID_VERSION_DESCRIPTOR');continue
        url=record.get('file_url')
        if not isinstance(url,str) or not url.startswith(CDN):
            blocked.add('INVALID_VERSION_URL');continue
        relative=url[len(CDN):]
        try:
            confined(root,relative)
        except (OSError,ValueError):
            blocked.add('VERSION_TARGET_MISSING')
        if relative.startswith('packs/pilot5/') and not any(p['artifact_path']==relative for p in verified):
            blocked.add('VERSION_WITHOUT_VERIFIED_PACK')
    if not packs:
        blocked.add('NO_VERIFIED_PRODUCTION_PACKS')
    if {p['languageCode'] for p in verified} != set(LANGUAGES):
        blocked.add('PILOT5_NOT_COMPLETE')
    for p in verified:
        if not any(isinstance(v,dict) and v.get('file_url') == CDN+p['artifact_path'] and v.get('version') == p['version'] for v in records.values()):
            blocked.add('PACK_VERSION_INDEX_MISMATCH')
    if len(verified) != len(packs):
        blocked.add('UNVERIFIED_PACK_DESCRIPTORS')
    if packs:
        # Route 05 independently enforces attribution, review and daily manifests.
        import subprocess
        import sys
        validator = root/'legal/ledger/admission.py'
        if not validator.is_file() or subprocess.run([sys.executable, str(validator), '--repo-root',str(root)], capture_output=True, timeout=30).returncode != 0:
            blocked.add('PUBLICATION_ADMISSION_NOT_PROVEN')
    details.update({'status':'VERIFIED_CANDIDATE' if not blocked else 'BLOCKED_DEPENDENCY',
                    'blockers': sorted(blocked),
                    'registered_languages':len(ids), 'published_pack_descriptors':len(packs),
                    'verified_packs':verified})
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, help='optional machine-readable evidence file')
    args=parser.parse_args()
    evidence=audit(args.repo_root)
    content=json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)+'\n'
    if args.output:
        target=args.output.resolve()
        if not target.is_relative_to(args.repo_root.resolve() / 'tools/release_validation'):
            parser.error('--output must remain inside tools/release_validation')
        target.parent.mkdir(parents=True, exist_ok=True)
        temp=target.with_suffix(target.suffix+'.tmp')
        temp.write_text(content, encoding='utf-8')
        temp.replace(target)
    print(content,end='')
    return 0 if evidence['status']=='VERIFIED_CANDIDATE' else 2


if __name__=='__main__':
    raise SystemExit(main())
