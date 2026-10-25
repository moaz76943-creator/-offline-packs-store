"""Read-only fail-closed 100-language coverage and SQLite v2 audit."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import sqlite3
import tempfile
from urllib.parse import urlsplit
from pathlib import Path
import re
import sys

MAX_PACK_BYTES = 80 * 1024 * 1024
MAX_ENVELOPE_BYTES = 120 * 1024 * 1024
MAX_JSON_INTEGER_DIGITS = 128
SHA = re.compile(r'^[a-f0-9]{64}$')
CODE = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')


class AuditError(ValueError):
    pass


def _bounded_json_int(token):
    # Metadata integer tokens are evidence, not arbitrary-precision payloads.
    # Bound before int() to avoid interpreter-dependent exceptions and CPU use.
    if len(token.lstrip('-')) > MAX_JSON_INTEGER_DIGITS:
        raise AuditError('oversized JSON integer')
    return int(token)


def _finite_json_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise AuditError('nonfinite JSON number')
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _repository_file(root, relative):
    """Resolve only real files below the checkout; never follow symlink parents."""
    base = Path(root).resolve()
    fragment = Path(relative)
    if fragment.is_absolute() or '..' in fragment.parts or '.git' in fragment.parts:
        raise AuditError(f'unsafe repository path: {relative}')
    path = base
    for part in fragment.parts:
        path = path / part
        if path.is_symlink():
            raise AuditError(f'symlinked repository path: {relative}')
    if not path.is_file() or not path.resolve().is_relative_to(base):
        raise AuditError(f'missing/unsafe repository file: {relative}')
    return path


def _parse_strict_json(content, name):
    """Decode repository or verified pack-member JSON without ambiguous evidence."""
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='strict')
        data = json.loads(content, object_pairs_hook=_unique_pairs,
                          parse_float=_finite_json_float,
                          parse_int=_bounded_json_int,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              AuditError('invalid number')))
        # Escaped lone surrogates survive json.loads; keys and values must
        # remain valid UTF-8 without changing multilingual text.
        pending = [data]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                value.encode('utf-8', errors='strict')
            elif isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        if not isinstance(data, dict):
            raise AuditError(f'JSON object required in {name}')
        return data
    except RecursionError as error:
        raise AuditError(f'JSON nesting exceeds decoder depth in {name}') from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AuditError(f'invalid Unicode/JSON encoding in {name}: {error}') from error


def read_json(root, name):
    path = _repository_file(root, name)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise AuditError(f'oversized metadata: {name}')
    return _parse_strict_json(path.read_bytes(), name)


def _identity_list(items, key, label):
    if not isinstance(items, list) or len(items) != 100:
        raise AuditError(f'{label} must register exactly 100 language identities')
    ids = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            raise AuditError(f'invalid {label} identity')
        value = item[key]
        if not CODE.fullmatch(value):
            raise AuditError(f'invalid {label} language ID: {value}')
        ids.append(value)
    if len(set(ids)) != len(ids):
        raise AuditError(f'duplicate {label} language ID')
    return ids


def _sha_file(path, limit):
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise AuditError('archive exceeds maximum accepted size')
            h.update(chunk)
    return h.hexdigest(), size


def _evidence_matches(root, relative, digest):
    if not isinstance(relative, str) or not relative or not isinstance(digest, str) or not SHA.fullmatch(digest):
        return False
    fragment = Path(relative)
    if fragment.is_absolute() or '..' in fragment.parts or '.git' in fragment.parts:
        return False
    base = root.resolve()
    candidate = base
    for part in fragment.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            return False
    if not candidate.is_file() or not candidate.resolve().is_relative_to(base):
        return False
    try:
        return _sha_file(candidate, 256 * 1024 * 1024)[0] == digest
    except (OSError, AuditError):
        return False


def _approved_sources(root, sources):
    """Admitted IDs only, not raw status claims. Source language mapping is unknown."""
    approved, incomplete, seen = set(), 0, set()
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get('source_id'), str) or not item['source_id'].strip():
            raise AuditError('malformed provenance ledger entry')
        sid = item['source_id']
        if sid in seen:
            raise AuditError('duplicate provenance source ID')
        seen.add(sid)
        if item.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
            continue
        retrieval = item.get('retrieval') if isinstance(item.get('retrieval'), dict) else {}
        license_info = item.get('license') if isinstance(item.get('license'), dict) else {}
        review = item.get('review') if isinstance(item.get('review'), dict) else {}
        def valid_https(value):
            if not isinstance(value, str):
                return False
            try:
                url = urlsplit(value)
                return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
            except ValueError:
                return False
        cleared = all((
            isinstance(item.get('publisher'), str) and bool(item['publisher'].strip()),
            isinstance(item.get('dataset_version'), str) and bool(item['dataset_version'].strip()),
            valid_https(item.get('origin_url')),
            isinstance(item.get('alterations'), list) and bool(item['alterations']),
            isinstance(retrieval.get('identity'), str) and bool(retrieval['identity']),
            valid_https(retrieval.get('url')),
            license_info.get('id') in ('CC0-1.0', 'CC-BY-SA-4.0', 'GFDL-1.3-only', 'PUBLIC-DOMAIN'),
            valid_https(license_info.get('evidence_url')),
            isinstance(review.get('reviewer'), str) and bool(review['reviewer'].strip()),
            valid_https(review.get('decision_url')),
            _evidence_matches(root, retrieval.get('artifact_path'), retrieval.get('sha256')),
            _evidence_matches(root, license_info.get('evidence_path'), license_info.get('evidence_sha256')),
        ))
        if license_info.get('id') == 'PUBLIC-DOMAIN':
            proof = license_info.get('public_domain_proof')
            cleared = cleared and isinstance(proof, dict) and all(proof.get(k) for k in ('jurisdiction', 'legal_basis', 'work_date'))
        if cleared:
            approved.add(sid)
        else:
            incomplete += 1
    return approved, incomplete


def _pack_source_ids(metadata, content_info):
    ids = metadata.get('sourceIds')
    if metadata.get('fixtureOnly') is not False or content_info.get('fixtureOnly') is not False:
        raise AuditError('fixture or unclassified content cannot be a published pack')
    if (not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x.strip()
             and len(x) <= 128 for x in ids) or len(set(ids)) != len(ids)
            or content_info.get('sourceIds') != ids):
        raise AuditError('invalid or mismatched published source IDs')
    return ids


def _directed_pairs(sqlite_bytes, canonical_ids):
    """Count attested A->B records using the verified SQLite, never infer B->A."""
    with tempfile.TemporaryDirectory(prefix='coverage-directions-') as temporary:
        path = Path(temporary) / 'content.sqlite'
        path.write_bytes(sqlite_bytes)
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            db.execute('PRAGMA query_only=ON')
            # Do not trust a SQLite payload merely because its translation
            # joins happen to return rows. Validate the underlying pages and
            # all declared foreign keys, including orphan senses not referenced
            # by a translation. Both checks are read-only and bounded.
            if db.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
                raise AuditError('SQLite integrity check failed')
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise AuditError('SQLite foreign key violation')
            # INNER JOIN coverage queries silently drop broken source/target
            # sense or lexeme links. Reject them before counting directions,
            # even if a synthetic or legacy SQLite file has no FK constraints.
            orphan = db.execute("""
                SELECT 1 FROM translations AS t
                LEFT JOIN senses AS src_sense ON src_sense.sense_id = t.from_sense_id
                LEFT JOIN lexicon AS source ON source.id = src_sense.lexeme_id
                LEFT JOIN senses AS dst_sense ON dst_sense.sense_id = t.to_sense_id
                LEFT JOIN lexicon AS target ON target.id = dst_sense.lexeme_id
                WHERE src_sense.sense_id IS NULL OR source.id IS NULL
                   OR dst_sense.sense_id IS NULL OR target.id IS NULL
                LIMIT 1
            """).fetchone()
            if orphan:
                raise AuditError('orphan translation sense/lexeme reference')
            # A legacy SQLite table may omit FK declarations altogether.
            # Check every sense, not only senses joined from translations:
            # otherwise an unreferenced dangling lexeme_id is invisible to
            # both foreign_key_check and directed-edge JOINs.
            dangling_sense = db.execute("""
                SELECT 1 FROM senses AS sense
                LEFT JOIN lexicon AS lexeme ON lexeme.id = sense.lexeme_id
                WHERE lexeme.id IS NULL
                LIMIT 1
            """).fetchone()
            if dangling_sense:
                raise AuditError('orphan sense/lexeme reference')
            # A valid directed edge does not validate unrelated lexicon rows.
            # Fail closed on missing/unknown language identities throughout the
            # SQLite payload, including words with no sense or translation.
            if not canonical_ids:
                raise AuditError('empty canonical language registry')
            canonical_languages = tuple(sorted(canonical_ids))
            placeholders = ','.join('?' for _ in canonical_languages)
            unknown_lexeme = db.execute(
                f'SELECT 1 FROM lexicon WHERE language_code IS NULL '
                f'OR language_code NOT IN ({placeholders}) LIMIT 1',
                canonical_languages,
            ).fetchone()
            if unknown_lexeme:
                raise AuditError('unregistered language: lexicon language missing or unknown')
            mismatch = db.execute("""
                SELECT 1 FROM translations AS t
                JOIN senses AS src_sense ON src_sense.sense_id = t.from_sense_id
                JOIN lexicon AS source ON source.id = src_sense.lexeme_id
                JOIN senses AS s ON s.sense_id = t.to_sense_id
                JOIN lexicon AS target ON target.id = s.lexeme_id
                WHERE t.language_code IS NULL OR source.language_code IS NULL
                   OR target.language_code IS NULL
                   OR t.language_code <> target.language_code
                LIMIT 1
            """).fetchone()
            if mismatch:
                raise AuditError('translation target language mismatch or missing')
            # Multiple evidence/translation rows can represent one directed
            # sense edge. Count distinct (source sense, target sense) links
            # rather than inflated raw rows; do not infer reverse directions.
            rows = db.execute("""
                SELECT source_language, target_language, COUNT(*)
                FROM (
                    SELECT DISTINCT
                        source.language_code AS source_language,
                        target.language_code AS target_language,
                        t.from_sense_id, t.to_sense_id
                    FROM translations AS t
                    JOIN senses AS src_sense ON src_sense.sense_id = t.from_sense_id
                    JOIN lexicon AS source ON source.id = src_sense.lexeme_id
                    JOIN senses AS dst_sense ON dst_sense.sense_id = t.to_sense_id
                    JOIN lexicon AS target ON target.id = dst_sense.lexeme_id
                )
                GROUP BY source_language, target_language
                ORDER BY source_language, target_language
            """).fetchall()
        except sqlite3.DatabaseError as error:
            raise AuditError(f'invalid SQLite directed coverage database: {error}') from error
        finally:
            db.close()
    if any(a not in canonical_ids or b not in canonical_ids for a, b, _ in rows):
        raise AuditError('translation references unregistered language')
    # Same-language edges are not directed translations, but their language
    # identities must still be checked before they are omitted from coverage.
    return [{'source_language': a, 'target_language': b, 'verified_count': count}
            for a, b, count in rows if a != b]



def _load_pack_checker(root):
    """Load the checked-out public pack verifier regardless of sys.path or CWD."""
    path = _repository_file(root, 'tools/pack_v2/pipeline.py')
    spec = importlib.util.spec_from_file_location('_public_coverage_pack_v2', path)
    if spec is None or spec.loader is None:
        raise AuditError('cannot load canonical v2 verifier')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_envelope


def _verify_pack(root, pack, language):
    if pack.get('id') != language or pack.get('languageCode') != language:
        raise AuditError('v2 published language identity mismatch')
    if pack.get('schemaVersion') != '2.0.0' or pack.get('format') != 'json-gzip-v1':
        raise AuditError('not a canonical verified SQLite v2 package')
    version = pack.get('version')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise AuditError('invalid pack version')
    expected = pack.get('sha256')
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise AuditError('invalid package SHA256')
    path = _repository_file(root, f'packs/{language}-{version}.pack.gz')
    actual, length = _sha_file(path, MAX_PACK_BYTES)
    if actual != expected or length != pack.get('archiveSizeBytes'):
        raise AuditError('package bytes/length do not match manifest')
    try:
        with gzip.open(path, 'rb') as fh:
            blob = fh.read(MAX_ENVELOPE_BYTES + 1)
        if len(blob) > MAX_ENVELOPE_BYTES:
            raise AuditError('inflated package exceeds maximum envelope size')
        contents = _load_pack_checker(root)(blob, language)
    except (OSError, EOFError, ValueError, KeyError) as error:
        raise AuditError(f'invalid SQLite v2 envelope: {error}') from error
    payload = _parse_strict_json(contents['metadata/pack.json'], 'metadata/pack.json')
    info = _parse_strict_json(contents['content/content.json'], 'content/content.json')
    if payload.get('version') != version or info.get('schemaVersion') != '2.0.0':
        raise AuditError('package metadata version mismatch')
    ids = _pack_source_ids(payload, info)
    return {'source_ids': ids, 'directed_pairs': _directed_pairs(
        contents['content/content.sqlite'], set(read_json(root, 'catalog/content_readiness.v1.json')['states'])),
        'content_rows': payload['contentRows']}


def audit(root, *, shard=0, shards=10):
    root = Path(root)
    if shards < 1 or shards > 100 or shard < 0 or shard >= shards:
        raise AuditError('invalid shard index/count')
    manifest = read_json(root, 'manifest.json')
    registry = read_json(root, 'catalog/language_registry.v1.json')
    readiness = read_json(root, 'catalog/content_readiness.v1.json')
    version = read_json(root, 'version.json')
    ledger = read_json(root, 'legal/ledger/sources.json')
    m_ids = _identity_list(manifest.get('languages'), 'code', 'manifest')
    r_ids = _identity_list(registry.get('languages'), 'id', 'registry')
    if set(m_ids) != set(r_ids) or manifest.get('total_languages') != 100:
        raise AuditError('canonical 100-language registry/manifest mismatch')
    state = readiness.get('states')
    if not isinstance(state, dict) or set(state) != set(m_ids):
        raise AuditError('readiness state identities do not match registry')
    if ledger.get('schema_version') != '1.0.0':
        raise AuditError('unsupported source ledger schema')
    sources = ledger.get('sources')
    packs = manifest.get('packs')
    if not isinstance(sources, list) or not isinstance(packs, list):
        raise AuditError('source ledger/packs must be arrays')
    approved, missing_approval_evidence = _approved_sources(root, sources)
    if not sources and (packs or version.get('packs') or version.get('release_status') != 'BLOCKED_DEPENDENCY'):
        raise AuditError('cannot release packages with empty source admission ledger')
    # A pending/rejected source row does not authorize publication metadata.
    # Even with a nonempty ledger, an empty v2 manifest cannot back a release.
    if not packs and (version.get('packs') or version.get('release_status') != 'BLOCKED_DEPENDENCY'):
        raise AuditError('release metadata conflicts with empty published packs')
    # A verified version is a publication claim independent of release_status.
    # With no published v2 packs, metadata must not advertise any verified
    # release even when the status remains BLOCKED_DEPENDENCY.
    if not packs and version.get('latest_verified_version') is not None:
        raise AuditError('unbacked latest verified version without published packs')
    indexed = {}
    for p in packs:
        if not isinstance(p, dict) or not isinstance(p.get('id'), str):
            raise AuditError('malformed published v2 entry')
        if p['id'] in indexed or p['id'] not in m_ids:
            raise AuditError('duplicate or unknown published pack')
        indexed[p['id']] = p
    # Version metadata is a separate public release claim. Validate its
    # shape and identities globally, even when this audit checks only one
    # language shard and the referenced manifest pack is in another shard.
    version_packs = version.get('packs')
    if not isinstance(version_packs, dict):
        raise AuditError('invalid version pack index')
    if not set(version_packs).issubset(indexed):
        raise AuditError('unbacked version pack index entry')
    metadata = {item['code']: item for item in manifest['languages']}
    aliases = {item['id']: item for item in registry['languages']}
    selected = sorted(m_ids)[shard::shards]
    verified = 0
    ready = 0
    rows = []
    all_pairs = []
    manufacturing_candidates = []
    for code in selected:
        item, lang = metadata[code], aliases[code]
        if not item.get('registered') or not isinstance(lang.get('scripts'), list):
            raise AuditError(f'invalid registered metadata: {code}')
        default_script = lang.get('default_script')
        if default_script not in lang['scripts'] or default_script not in registry.get('scripts', {}):
            raise AuditError(f'invalid canonical script: {code}')
        script_metadata = registry['scripts'][default_script]
        if (not isinstance(script_metadata, dict)
                or script_metadata.get('direction') not in ('ltr', 'rtl')
                or item.get('direction') != script_metadata['direction']):
            raise AuditError(f'script direction mismatch: {code}')
        # A verified-pack claim without a published v2 manifest entry is
        # unsupported metadata, not a REGISTERED/PASS result. Do not promote
        # legacy placeholders or report verification from flags alone.
        if item.get('pack_verified') is True and code not in indexed:
            raise AuditError(f'unbacked pack_verified metadata: {code}')
        active = item.get('production_ready') is True or item.get('is_active') is True
        if active and not (item.get('pack_verified') is True and item.get('content_available') is True
                           and code in indexed):
            raise AuditError(f'false production activation: {code}')
        pack_status = 'NOT_PUBLISHED'
        source_status = 'NOT_ATTESTED'
        direction_count = 0
        if code in indexed:
            evidence = _verify_pack(root, indexed[code], code)
            if not set(evidence['source_ids']) <= approved:
                raise AuditError(f'unapproved provenance in pack: {code}')
            verified += 1
            pack_status = 'PACK_VERIFIED'
            source_status = 'SOURCE_APPROVED'
            manufacturing_candidates.append(code)
            for pair in evidence['directed_pairs']:
                if pair['source_language'] not in m_ids or pair['target_language'] not in m_ids:
                    raise AuditError(f'unregistered directed pair: {code}')
                all_pairs.append({**pair, 'verified_in_pack': code})
                direction_count += 1
        if active:
            validation = readiness.get('validation_evidence', {}).get(code)
            if (item.get('production_ready') is not True or state[code] != 'validated'
                    or not isinstance(validation, dict)
                    or validation.get('pack_sha256') != indexed[code].get('sha256')
                    or validation.get('validation_method') != 'automated_quality_gate'
                    or not isinstance(validation.get('acceptance'), dict)
                    or not all(validation['acceptance'].get(k) is True for k in (
                        'source_licensed', 'profile_valid', 'lexicon_coverage',
                        'grammar_goldens', 'examples_quality', 'search_goldens',
                        'script_render', 'offline_pack_integrity', 'safety_policy',
                        'ui_srs_compatibility'))
                    or version.get('release_status') == 'BLOCKED_DEPENDENCY'
                    or code not in version.get('packs', {})):
                raise AuditError(f'false production readiness evidence: {code}')
            ready += 1
        rows.append({'language_id': code, 'status': 'PRODUCTION_READY' if active else
                     'PACK_VERIFIED' if code in indexed else 'REGISTERED',
                     'registry_readiness': state[code], 'source_status': source_status,
                     'pack_status': pack_status, 'pack_available': code in indexed,
                     'pack_verified': code in indexed, 'pack_installed': 'NOT_OBSERVABLE',
                     'production_ready': active, 'verified_directed_pair_count': direction_count,
                     'lexicon_coverage': 'NOT_ASSESSED', 'grammar_coverage': 'NOT_ASSESSED',
                     'qa_coverage': 'NOT_ASSESSED',
                     'blockers': [] if active else
                     ['NO_VERIFIED_V2_PACK', 'SOURCE_TO_LANGUAGE_MAPPING_UNKNOWN'] if code not in indexed
                     else ['MISSING_PRODUCTION_ACCEPTANCE']})
    return {'shard': shard, 'shards': shards, 'language_count': len(selected),
            'registered_total': 100, 'verified_v2_packs': verified,
            'source_ledger_entries': len(sources),
            'source_approved_ids': len(approved), 'status': 'PASS',
            'source_approval_missing_evidence': missing_approval_evidence,
            'language_rows': rows, 'directed_pairs': all_pairs,
            'factory_ready_languages': manufacturing_candidates,
            'production_ready_languages': ready,
            'production_release_claimed': bool(ready)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--shards', type=int, default=10)
    p.add_argument('--shard', type=int, default=0)
    a = p.parse_args(argv)
    try:
        print(json.dumps(audit(a.root, shard=a.shard, shards=a.shards), sort_keys=True))
        return 0
    except (AuditError, OSError, ImportError) as error:
        print(json.dumps({'status': 'FAIL', 'reason': str(error), 'shard': a.shard}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
