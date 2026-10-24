#!/usr/bin/env python3
"""Fail-closed, local SQLite v2 release candidate staging; never publishes."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MEMBERS = ('content/content.json', 'content/content.sqlite', 'metadata/pack.json')
TABLES = ('metadata', 'schema_migrations', 'concepts', 'lexicon', 'senses',
          'translations', 'examples', 'lexical_relations', 'grammar', 'lexicon_fts')
INDEXES = ('idx_lexicon_order', 'idx_lexicon_surface', 'idx_senses_lexeme',
           'idx_examples_sense', 'idx_translations_directed')
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_ENVELOPE = 120 * 1024 * 1024
MAX_SQLITE = 80 * 1024 * 1024
HASH = re.compile(r'^[0-9a-f]{64}$')
SIGN_DOMAIN = b'DEUTSCH-SQLITE-V2-RC\x00'


class ReleaseError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def safe_file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ReleaseError('unsafe source path')
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts:
        raise ReleaseError('unsafe source path')
    dest = (root / p).resolve()
    if not dest.is_relative_to(root.resolve()) or not dest.is_file():
        raise ReleaseError('source artifact absent/unsafe')
    return dest


def bounded_gzip(blob):
    if not blob or len(blob) > MAX_ARCHIVE:
        raise ReleaseError('archive size limit')
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = dec.decompress(blob, MAX_ENVELOPE + 1)
        if len(raw) > MAX_ENVELOPE or not dec.eof or dec.unused_data or dec.unconsumed_tail:
            raise ReleaseError('archive truncated, trailing or expansion limit')
    except zlib.error as exc:
        raise ReleaseError('corrupted gzip') from exc
    return raw


def _json(raw, label):
    # All candidate, manifest and rights metadata must have one unambiguous
    # interpretation. json.loads otherwise silently keeps the last duplicate
    # property and accepts non-standard NaN/Infinity numeric constants.
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('duplicate JSON property')
            obj[key] = value
        return obj

    def finite_only(value):
        raise ValueError('non-finite JSON constant')

    try:
        item = json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=finite_only)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ReleaseError('invalid ' + label) from exc
    if not isinstance(item, dict):
        raise ReleaseError(label + ' must be object')
    return item


def _members(envelope):
    entries = envelope.get('files')
    if not isinstance(entries, list) or len(entries) != len(MEMBERS):
        raise ReleaseError('three mandatory envelope members required')
    contents = {}
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('path') not in MEMBERS or entry['path'] in contents:
            raise ReleaseError('invalid/duplicate envelope member')
        data = entry.get('contentBase64')
        limit = MAX_SQLITE if entry['path'].endswith('.sqlite') else 20 * 1024 * 1024
        if not isinstance(data, str) or len(data) > (limit * 4 // 3 + 8):
            raise ReleaseError('member encoded size limit')
        try:
            b = base64.b64decode(data, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ReleaseError('corrupt member base64') from exc
        if len(b) > limit:
            raise ReleaseError('member decompression size limit')
        total += len(b)
        if total > MAX_ENVELOPE:
            raise ReleaseError('total member size limit')
        contents[entry['path']] = b
    if set(contents) != set(MEMBERS):
        raise ReleaseError('mandatory envelope missing')
    return contents


def _check_sqlite(contents, language, counts):
    with tempfile.TemporaryDirectory(prefix='rc-sqlite-') as td:
        path = Path(td) / 'verify.sqlite'
        path.write_bytes(contents['content/content.sqlite'])
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
                db.execute('PRAGMA trusted_schema=OFF')
                if db.execute('PRAGMA user_version').fetchone()[0] != 2:
                    raise ReleaseError('SQLite user_version mismatch')
                if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise ReleaseError('SQLite integrity_check failed')
                if db.execute('PRAGMA foreign_key_check').fetchone():
                    raise ReleaseError('SQLite foreign_key_check failed')
                schema = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                indexes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                if not set(TABLES).issubset(schema) or not set(INDEXES).issubset(indexes):
                    raise ReleaseError('required SQLite tables/indexes absent')
                meta = dict(db.execute('SELECT key,value FROM metadata'))
                if meta.get('language_code') != language or meta.get('mapping_version') != '2.0.0' or meta.get('contract_version') != '1.0.0':
                    raise ReleaseError('SQLite language/schema contract mismatch')
                real = {t: db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in counts}
                if real != counts or real.get('lexicon', 0) < 1 or real.get('senses', 0) < 1:
                    raise ReleaseError('empty/incorrect actual lexical counts')
                if db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0] != real['lexicon']:
                    raise ReleaseError('FTS5 row count mismatch')
                if not db.execute('SELECT 1 FROM lexicon WHERE language_code=? LIMIT 1', (language,)).fetchone():
                    raise ReleaseError('target language has no lexemes')
                samples = db.execute("SELECT id,surface,direction FROM lexicon WHERE language_code=? AND trim(surface)<>'' ORDER BY id LIMIT 5", (language,)).fetchall()
                if not samples:
                    raise ReleaseError('no representative Unicode lexical records')
                fts_tests = 0
                for lexeme_id, surface, direction in samples:
                    if not surface or '\x00' in surface or not surface.encode('utf-8'):
                        raise ReleaseError('invalid Unicode surface')
                    if language == 'ar' and direction != 'rtl':
                        raise ReleaseError('Arabic lexeme must have RTL direction')
                    quoted = '"' + surface.replace('"', '""') + '"'
                    hit = db.execute('''SELECT 1 FROM lexicon_fts JOIN lexicon l ON l.rowid=lexicon_fts.rowid
                        WHERE lexicon_fts MATCH ? AND l.id=? LIMIT 1''', (quoted, lexeme_id)).fetchone()
                    if not hit:
                        raise ReleaseError('real FTS5 representative MATCH failed')
                    fts_tests += 1
                    for n in (1, 2):
                        prefix = surface[:n]
                        if not db.execute('SELECT 1 FROM lexicon WHERE id=? AND substr(surface,1,?)=?',
                                          (lexeme_id, len(prefix), prefix)).fetchone():
                            raise ReleaseError('short-query Unicode fallback failed')
                target_count = db.execute('SELECT COUNT(*) FROM lexicon WHERE language_code=?', (language,)).fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ReleaseError('SQLite or FTS5 validation failed') from exc
    return fts_tests, target_count


def inspect_archive(archive, language, *, allow_fixture=False):
    raw = bounded_gzip(archive)
    env = _json(raw, 'envelope')
    if (env.get('packId') != language or env.get('schemaVersion') != '2.0.0'
            or env.get('contractVersion') != '1.0.0' or env.get('format') != 'json-gzip-v1'
            or env.get('version') != '1.0.0'):
        raise ReleaseError('wrong language or stale/incompatible package version')
    contents = _members(env)
    info = _json(contents['content/content.json'], 'content info')
    meta = _json(contents['metadata/pack.json'], 'pack metadata')
    counts = info.get('tableCounts')
    sqlhash = digest(contents['content/content.sqlite'])
    if (meta.get('languageCode') != language or meta.get('packId') != language
            or info.get('languageCode') != language or meta.get('schemaVersion') != '2.0.0'
            or info.get('schemaVersion') != '2.0.0' or meta.get('version') != '1.0.0'
            or meta.get('contentSha256') != sqlhash or info.get('sqliteSha256') != sqlhash
            or meta.get('contentMetadataSha256') != digest(contents['content/content.json'])
            or not isinstance(counts, dict) or set(counts) != set(('lexicon','concepts','senses','translations','examples','lexical_relations','grammar'))
            or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values())
            or meta.get('contentRows') != counts['lexicon']
            or meta.get('fixtureOnly') != info.get('fixtureOnly')):
        raise ReleaseError('metadata/schema/hash/count mismatch')
    fixture = info['fixtureOnly']
    if not isinstance(fixture, bool) or (fixture and not allow_fixture):
        raise ReleaseError('synthetic fixture forbidden for production candidate')
    sources = info.get('sourceIds')
    if (not isinstance(sources, list) or not sources or meta.get('sourceIds') != sources
            or any(not isinstance(s, str) or not s.strip() for s in sources)
            or len(set(sources)) != len(sources)):
        raise ReleaseError('missing, duplicate or mismatched source provenance IDs')
    fts_tests, target_count = _check_sqlite(contents, language, counts)
    # Reuse the canonical consumer/producer contract, without modifying Route 07.
    from tools.pack_v2.pipeline import check_envelope
    check_envelope(raw, language)
    return {'language': language, 'archive_sha256': digest(archive), 'archive_bytes': len(archive),
            'sqlite_sha256': sqlhash, 'actual_lexical_count': counts['lexicon'],
            'target_lexical_count': target_count, 'sqlite_integrity': 'ok', 'foreign_key_check': 'ok',
            'fts5_queries_passed': fts_tests, 'short_query_fallback': 'passed',
            'source_ids': sources, 'fixture_only': fixture, 'schema_version': '2.0.0',
            'contract_version': '1.0.0', 'package_version': '1.0.0',
            'actual_counts': counts}


def verify_signature(archive, key_path, signature_path):
    """Ed25519 signs SIGN_DOMAIN + binary SHA-256; public-key verify only."""
    msg = SIGN_DOMAIN + hashlib.sha256(archive).digest()
    try:
        keytype = subprocess.run(['openssl', 'pkey', '-pubin', '-in', str(key_path), '-text', '-noout'],
                                 capture_output=True, text=True, timeout=10, check=True)
        if 'ED25519 Public-Key' not in keytype.stdout:
            raise ReleaseError('only Ed25519 public keys accepted')
        with tempfile.TemporaryDirectory(prefix='rc-sign-') as td:
            payload = Path(td) / 'signed-message.bin'
            payload.write_bytes(msg)
            subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(key_path),
                            '-rawin', '-in', str(payload), '-sigfile', str(signature_path)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ReleaseError('public-key signature verification failed') from exc
    return True


def source_gate(root):
    ledger = _json((root / 'legal/ledger/sources.json').read_bytes(), 'licensing ledger')
    if ledger.get('schema_version') != '1.0.0' or not isinstance(ledger.get('sources'), list):
        raise ReleaseError('licensing ledger contract invalid')
    return [s for s in ledger['sources'] if isinstance(s, dict) and s.get('status') == 'APPROVED_FOR_REDISTRIBUTION']


def audit(root):
    root = Path(root).resolve()
    manifest = _json((root / 'manifest.json').read_bytes(), 'Route 13 manifest')
    version = _json((root / 'version.json').read_bytes(), 'Route 13 version')
    registered = [x['code'] for x in manifest.get('languages', [])]
    if len(registered) != 100 or len(set(registered)) != 100:
        raise ReleaseError('100 language identities not preserved')
    approved = source_gate(root)
    if not approved:
        if manifest.get('packs') or version.get('packs'):
            raise ReleaseError('production packs advertised with no approved sources')
        return {'status': 'BLOCKED_SOURCE', 'source_sha': None, 'languages': registered,
                'approved_sources': 0, 'actual_lexical_count': 0, 'release_candidates': 0,
                'license_gate': 'BLOCKED_SOURCE', 'publication_approved': False}
    return {'status': 'PENDING_CANDIDATE_VERIFICATION', 'languages': registered,
            'approved_sources': len(approved), 'publication_approved': False}


def evidence_receipts(root, source_ids):
    """Independently bind every pack source to immutable ledger proof bytes."""
    approved = source_gate(root)
    receipts = []
    for source_id in source_ids:
        matching = [s for s in approved if s.get('source_id') == source_id]
        if len(matching) != 1:
            raise ReleaseError('unapproved or ambiguous candidate source ID')
        entry = matching[0]
        retrieval = entry.get('retrieval')
        license_info = entry.get('license')
        review = entry.get('review')
        if (not isinstance(retrieval, dict) or not isinstance(license_info, dict)
                or not isinstance(review, dict) or not review.get('reviewer')
                or not str(review.get('decision_url', '')).startswith('https://')):
            raise ReleaseError('source rights review evidence incomplete')
        for evidence, label in ((retrieval, 'source'), (license_info, 'license')):
            expected = evidence.get('sha256' if label == 'source' else 'evidence_sha256')
            path = evidence.get('artifact_path' if label == 'source' else 'evidence_path')
            if not isinstance(expected, str) or not HASH.fullmatch(expected):
                raise ReleaseError(label + ' SHA-256 evidence absent')
            if digest_file(safe_file(root, path)) != expected:
                raise ReleaseError(label + ' SHA-256 evidence mismatch')
        receipts.append({
            'source_id': source_id,
            'source_sha256': retrieval['sha256'],
            'license_evidence_sha256': license_info['evidence_sha256'],
            'license_id': license_info.get('id'),
            'dataset_version': entry.get('dataset_version'),
        })
    return receipts


def stage_candidate(output, language, archive, report):
    """Stage immutable candidate + receipt, rolling back new files on failure."""
    if (not isinstance(archive, bytes) or len(archive) > MAX_ARCHIVE
            or report.get('language') != language
            or report.get('archive_sha256') != digest(archive)):
        raise ReleaseError('candidate receipt identity/hash mismatch')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = language + '-' + report['archive_sha256']
    destination = output / (name + '.pack.gz')
    report_file = output / (name + '.report.json')
    receipt_bytes = json_bytes(report)
    # Never accept links to an out-of-band candidate or a modified prior receipt.
    if destination.is_symlink() or report_file.is_symlink():
        raise ReleaseError('candidate/receipt symlink forbidden')
    if destination.exists() and (not destination.is_file()
                                  or digest_file(destination) != report['archive_sha256']):
        raise ReleaseError('existing candidate hash collision/tampering')
    if report_file.exists() and (not report_file.is_file()
                                 or report_file.read_bytes() != receipt_bytes):
        raise ReleaseError('existing candidate receipt mismatch/tampering')
    created_archive = False
    created_report = False
    try:
        if not destination.exists():
            fd, stage = tempfile.mkstemp(prefix='.rc-', dir=output)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(archive)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(stage, destination)  # atomic, no clobber
                created_archive = True
            finally:
                Path(stage).unlink(missing_ok=True)
        if not report_file.exists():
            fd, stage = tempfile.mkstemp(prefix='.report-', dir=output)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(receipt_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(stage, report_file)  # atomic, no clobber
                created_report = True
            finally:
                Path(stage).unlink(missing_ok=True)
        if (destination.is_symlink() or report_file.is_symlink()
                or digest_file(destination) != report['archive_sha256']
                or report_file.read_bytes() != receipt_bytes):
            raise ReleaseError('candidate/receipt changed during staging')
    except (OSError, ReleaseError):
        if created_report:
            report_file.unlink(missing_ok=True)
        if created_archive:
            destination.unlink(missing_ok=True)
        raise
    return report


def build_candidate(root, source_relative, expected_source_sha, language, output, *, fixture_only=False):
    root = Path(root).resolve()
    if language not in audit(root)['languages']:
        raise ReleaseError('unregistered language')
    if not HASH.fullmatch(expected_source_sha or ''):
        raise ReleaseError('expected source SHA-256 is mandatory')
    src = safe_file(root, source_relative)
    if src.stat().st_size > 20 * 1024 * 1024:
        raise ReleaseError('source document exceeds canonical compiler limit')
    if digest(src.read_bytes()) != expected_source_sha:
        raise ReleaseError('source snapshot SHA-256 mismatch')
    if not fixture_only and not source_gate(root):
        raise ReleaseError('BLOCKED_SOURCE: no approved real corpus/license evidence')
    from tools.pack_v2.pipeline import compile_pack
    with tempfile.TemporaryDirectory(prefix='rc-compile-') as td:
        archive, item = compile_pack(src, language, Path(td), root, fixture_only=fixture_only)
    report = inspect_archive(archive, language, allow_fixture=fixture_only)
    if report['archive_sha256'] != item['sha256']:
        raise ReleaseError('canonical compiler SHA mismatch')
    report.update(source_sha256=expected_source_sha,
                  license_gate='FIXTURE_ONLY' if fixture_only else 'APPROVED_LEDGER',
                  status='FIXTURE_QUARANTINED' if fixture_only else 'QUARANTINED_PENDING_SIGNATURE',
                  signature_verified=False, publication_approved=False)
    report['license_receipts'] = [] if fixture_only else evidence_receipts(root, report['source_ids'])
    return stage_candidate(output, language, archive, report)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root', type=Path, default=ROOT)
    ap.add_argument('--source', help='repo-relative approved canonical lexical JSON')
    ap.add_argument('--source-sha256')
    ap.add_argument('--language')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--fixture-only', action='store_true')
    ap.add_argument('--verify-public-key', type=Path)
    ap.add_argument('--verify-signature', type=Path)
    args = ap.parse_args(argv)
    try:
        if args.source:
            if not args.language or not args.output:
                raise ReleaseError('candidate build requires language and output')
            state = build_candidate(args.repo_root, args.source, args.source_sha256,
                                    args.language, args.output, fixture_only=args.fixture_only)
        else:
            state = audit(args.repo_root)
        if args.verify_public_key or args.verify_signature:
            if not (args.verify_public_key and args.verify_signature and args.source):
                raise ReleaseError('signature verification needs both files and an archive')
            candidate = Path(args.output) / (args.language + '-' + state['archive_sha256'] + '.pack.gz')
            state['signature_verified'] = verify_signature(candidate.read_bytes(), args.verify_public_key, args.verify_signature)
        print(json_bytes(state).decode('utf-8').strip())
        return 0 if state['status'] != 'BLOCKED_SOURCE' else 2
    except (OSError, ReleaseError, ValueError, KeyError) as exc:
        print(json_bytes({'status': 'BLOCKED_SOURCE', 'error': str(exc), 'publication_approved': False}).decode().strip())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
