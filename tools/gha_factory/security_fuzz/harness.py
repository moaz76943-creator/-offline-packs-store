#!/usr/bin/env python3
"""Read-only, bounded adversarial probes against the public Route 07/GHA-06 API.

All packages are synthetic and constructed in temporary directories. The existing
release fixture and validator are imported, not reimplemented or published.
"""
import argparse
import base64
import gzip
import io
import json
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/gha_factory/release'))
from tools.gha_factory.release import candidate as rc
from test_candidate import CandidateTests

SEED = 20261013
FAMILIES = {
    'envelope': ('baseline', 'wrong_language', 'envelope_version', 'schema_version',
                 'missing_member', 'duplicate_member', 'bad_base64', 'bad_metadata_json',
                 'bad_content_json', 'truncated_gzip', 'trailing_gzip', 'wrong_sha256',
                 'bad_utf8', 'duplicate_json_key', 'noncanonical_json', 'fuzz_truncation'),
    'sqlite': ('bad_header', 'wrong_user_version', 'missing_table', 'missing_index',
               'broken_foreign_key', 'missing_fts', 'invalid_fts_surface', 'duplicate_lexical_id'),
    'provenance': ('missing_sources', 'mismatched_sources', 'fixture_forbidden',
                   'false_production_ready', 'unapproved_source', 'fake_signature_flag'),
    'signature': ('missing_public_key', 'invalid_public_key', 'missing_signature',
                  'corrupt_signature'),
    'staging': ('blocked_source_rollback', 'invalid_source_sha_rollback',
                'unsafe_source_path', 'oversized_archive', 'compression_bomb'),
}
# Diagnostic gaps never confer production approval; track independently of test failures.
PROBES = {'duplicate_json_key', 'noncanonical_json', 'false_production_ready',
          'fake_signature_flag'}


def _zip(raw):
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as gz:
        gz.write(raw)
    return stream.getvalue()


def _member(envelope, name):
    return next(x for x in envelope['files'] if x['path'] == name)


def _json_member(envelope, name):
    return json.loads(base64.b64decode(_member(envelope, name)['contentBase64']))


def _set_member(envelope, name, data):
    _member(envelope, name)['contentBase64'] = base64.b64encode(data).decode('ascii')


def _update_content_info(envelope, info):
    """Mutate one inner JSON record and refresh its outer integrity digest."""
    raw = rc.json_bytes(info)
    _set_member(envelope, 'content/content.json', raw)
    meta = _json_member(envelope, 'metadata/pack.json')
    meta['contentMetadataSha256'] = rc.digest(raw)
    _set_member(envelope, 'metadata/pack.json', rc.json_bytes(meta))


def _replace_sqlite(envelope, *, sql=None, corrupted=None):
    contents = base64.b64decode(_member(envelope, 'content/content.sqlite')['contentBase64'])
    if corrupted is None:
        with tempfile.TemporaryDirectory(prefix='security-fixture-') as folder:
            db_file = Path(folder) / 'fixture.sqlite'
            db_file.write_bytes(contents)
            with sqlite3.connect(db_file) as conn:
                conn.execute('PRAGMA foreign_keys=OFF')
                conn.executescript(sql)
                conn.commit()
            corrupted = db_file.read_bytes()
    _set_member(envelope, 'content/content.sqlite', corrupted)
    info = _json_member(envelope, 'content/content.json')
    info['sqliteSha256'] = rc.digest(corrupted)
    info_bytes = rc.json_bytes(info)
    _set_member(envelope, 'content/content.json', info_bytes)
    meta = _json_member(envelope, 'metadata/pack.json')
    meta['contentSha256'] = rc.digest(corrupted)
    meta['contentMetadataSha256'] = rc.digest(info_bytes)
    _set_member(envelope, 'metadata/pack.json', rc.json_bytes(meta))


def _unapproved_case(name):
    with tempfile.TemporaryDirectory(prefix='security-source-') as folder:
        root = Path(folder)
        ledger = root / 'legal/ledger'
        ledger.mkdir(parents=True)
        (ledger / 'sources.json').write_text('{"schema_version":"1.0.0","sources":[]}', encoding='utf-8')
        (root / 'manifest.json').write_text(json.dumps({
            'languages': [{'code': f'l{i:03}'} for i in range(100)], 'packs': []
        }), encoding='utf-8')
        (root / 'version.json').write_text('{"packs":{}}', encoding='utf-8')
        (root / 'input.json').write_bytes(b'{}')
        dest = root / 'candidates'
        dest.mkdir()
        known_good = dest / 'last-known-good.pack.gz'
        known_good.write_bytes(b'immutable prior release')
        kwargs = {
            'root': root, 'source_relative': 'input.json',
            'expected_source_sha': rc.digest(b'{}'), 'language': 'l000',
            'output': dest,
        }
        if name == 'invalid_source_sha_rollback':
            kwargs['expected_source_sha'] = '0' * 64
        try:
            rc.build_candidate(**kwargs)
        except (rc.ReleaseError, ValueError, OSError):
            if known_good.read_bytes() != b'immutable prior release' or len(list(dest.iterdir())) != 1:
                return 'CRASH'
            return 'REJECTED'
        return 'ACCEPTED'


def _attempt(name, fixture, rng):
    if name in ('blocked_source_rollback', 'invalid_source_sha_rollback', 'unapproved_source'):
        return _unapproved_case('blocked_source_rollback' if name == 'unapproved_source' else name)
    if name == 'unsafe_source_path':
        try:
            with tempfile.TemporaryDirectory(prefix='security-path-') as folder:
                rc.safe_file(Path(folder), '../forbidden')
        except (rc.ReleaseError, ValueError):
            return 'REJECTED'
        return 'ACCEPTED'
    if name in ('missing_public_key', 'invalid_public_key', 'missing_signature', 'corrupt_signature'):
        with tempfile.TemporaryDirectory(prefix='security-sign-') as folder:
            root = Path(folder)
            key = root / 'public.pem'
            sig = root / 'signature.bin'
            if name != 'missing_public_key':
                if name == 'invalid_public_key':
                    key.write_text('not an Ed25519 public key\n', encoding='ascii')
                else:
                    # Public-only RFC 8032 test vector; no private signing material.
                    der = bytes.fromhex('302a300506032b6570032100'
                                        'd75a980182b10ab7d54bfed3c964073a'
                                        '0ee172f3daa62325af021a68f707511a')
                    encoded = base64.b64encode(der).decode('ascii')
                    key.write_text('-----BEGIN PUBLIC KEY-----\n' + encoded +
                                   '\n-----END PUBLIC KEY-----\n', encoding='ascii')
            if name != 'missing_signature':
                sig.write_bytes(b'not a valid Ed25519 signature')
            try:
                rc.verify_signature(b'isolated synthetic archive', key, sig)
            except (rc.ReleaseError, ValueError):
                return 'REJECTED'
        return 'ACCEPTED'
    if name == 'oversized_archive':
        archive = b'X' * (rc.MAX_ARCHIVE + 1)
    elif name == 'compression_bomb':
        # Bounded MAX_ENVELOPE+1 expansion; never persisted on disk.
        archive = gzip.compress(b'X' * (rc.MAX_ENVELOPE + 1), compresslevel=1, mtime=0)
    else:
        env = fixture.sample()
        if name == 'wrong_language':
            env['packId'] = 'es'
        elif name == 'envelope_version':
            env['version'] = '0.9.0'
        elif name == 'schema_version':
            env['schemaVersion'] = '1.0.0'
        elif name == 'missing_member':
            env['files'].pop()
        elif name == 'duplicate_member':
            env['files'][1]['path'] = env['files'][0]['path']
        elif name == 'bad_base64':
            _member(env, 'content/content.sqlite')['contentBase64'] = '@@@'
        elif name in ('bad_metadata_json', 'bad_content_json', 'bad_utf8'):
            member = 'metadata/pack.json' if name == 'bad_metadata_json' else 'content/content.json'
            _set_member(env, member, b'{oops' if name != 'bad_utf8' else b'{"value":"\xff"}')
        elif name == 'wrong_sha256':
            info = _json_member(env, 'content/content.json')
            info['sqliteSha256'] = '0' * 64
            _update_content_info(env, info)
        elif name == 'missing_sources':
            info = _json_member(env, 'content/content.json')
            info['sourceIds'] = []
            _update_content_info(env, info)
        elif name == 'mismatched_sources':
            info = _json_member(env, 'content/content.json')
            info['sourceIds'] = ['fabricated-unapproved']
            raw = rc.json_bytes(info)
            _set_member(env, 'content/content.json', raw)
            meta = _json_member(env, 'metadata/pack.json')
            meta['contentMetadataSha256'] = rc.digest(raw)
            _set_member(env, 'metadata/pack.json', rc.json_bytes(meta))
        elif name == 'false_production_ready':
            info = _json_member(env, 'content/content.json')
            info['fixtureOnly'] = False
            raw = rc.json_bytes(info)
            _set_member(env, 'content/content.json', raw)
            meta = _json_member(env, 'metadata/pack.json')
            meta.update(fixtureOnly=False, contentMetadataSha256=rc.digest(raw))
            _set_member(env, 'metadata/pack.json', rc.json_bytes(meta))
        elif name == 'fake_signature_flag':
            env['signatureVerified'] = True
            env['productionReady'] = True
        elif name == 'wrong_user_version':
            _replace_sqlite(env, sql='PRAGMA user_version=1;')
        elif name == 'missing_table':
            _replace_sqlite(env, sql='DROP TABLE grammar;')
        elif name == 'missing_index':
            _replace_sqlite(env, sql='DROP INDEX idx_lexicon_surface;')
        elif name == 'broken_foreign_key':
            _replace_sqlite(env, sql="UPDATE senses SET lexeme_id='missing';")
        elif name == 'missing_fts':
            _replace_sqlite(env, sql='DELETE FROM lexicon_fts;')
        elif name == 'invalid_fts_surface':
            _replace_sqlite(env, sql="UPDATE lexicon SET surface=char(0)||'test';")
        elif name == 'bad_header':
            _replace_sqlite(env, corrupted=b'not a SQLite database')
        elif name == 'duplicate_lexical_id':
            try:
                _replace_sqlite(env, sql="INSERT INTO lexicon SELECT * FROM lexicon;")
            except sqlite3.IntegrityError:
                return 'REJECTED'
            return 'ACCEPTED'
        raw = rc.json_bytes(env)
        if name == 'duplicate_json_key':
            raw = raw.replace(b'"packId":"de"', b'"packId":"xx","packId":"de"', 1)
        elif name == 'noncanonical_json':
            raw = b'  ' + raw + b' \n'
        archive = _zip(raw)
        if name == 'truncated_gzip':
            archive = archive[:-8]
        elif name == 'trailing_gzip':
            archive += b'evil'
        elif name == 'fuzz_truncation':
            archive = archive[:rng.randint(1, max(1, len(archive) - 1))]
    try:
        rc.inspect_archive(archive, 'de', allow_fixture=name != 'fixture_forbidden' and name != 'false_production_ready')
        return 'ACCEPTED'
    except (rc.ReleaseError, sqlite3.DatabaseError, ValueError, UnicodeError, OSError):
        return 'REJECTED'


def run_family(family, *, seed=SEED, max_cases=48):
    if family not in FAMILIES or not isinstance(seed, int) or not 1 <= max_cases <= 48:
        raise ValueError('unknown family, seed, or unsafe case bound')
    rng = random.Random(seed)
    fixture = CandidateTests()
    fixture.setUp()
    evidence = []
    try:
        for name in FAMILIES[family][:max_cases]:
            try:
                actual = _attempt(name, fixture, rng)
            except Exception:
                actual = 'CRASH'  # Never emit sensitive traceback, paths, or corpus bytes.
            expected = 'ACCEPTED' if name == 'baseline' else 'REJECTED'
            if name in PROBES:
                if actual == 'ACCEPTED':
                    status = 'SECURITY_FINDING'
                elif actual == 'REJECTED':
                    status = 'CLOSED'
                else:
                    # A crashed probe is not proof that the validator rejected it.
                    status = 'FAIL'
            else:
                status = 'PASS' if actual == expected else 'FAIL'
            evidence.append({'case': name, 'actual': actual, 'status': status})
    finally:
        fixture.doCleanups()
    return {'schema': 'security-fuzz-evidence-v1', 'family': family, 'seed': seed,
            'cases_executed': len(evidence), 'failures': sum(x['status'] == 'FAIL' for x in evidence),
            'security_findings': [x['case'] for x in evidence if x['status'] == 'SECURITY_FINDING'],
            'publication_approved': False, 'cases': evidence}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', choices=sorted(FAMILIES), required=True)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--max-cases', type=int, default=48)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_family(args.family, seed=args.seed, max_cases=args.max_cases)
    except (ValueError, ImportError):
        return 2
    output = (json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n')
    if args.out:
        destination = args.out.resolve()
        if destination.is_relative_to(ROOT) or not destination.parent.is_dir():
            return 2  # Never overwrite any tracked pack, manifest, or repository path.
        destination.write_text(output, encoding='utf-8')
    print(output, end='')
    return int(result['failures'] != 0)


if __name__ == '__main__':
    raise SystemExit(main())
