"""Read-only fail-closed 100-language coverage and SQLite v2 audit."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_PACK_BYTES = 80 * 1024 * 1024
MAX_ENVELOPE_BYTES = 120 * 1024 * 1024
SHA = re.compile(r'^[a-f0-9]{64}$')
CODE = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')


class AuditError(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(root, name):
    path = root / name
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        raise AuditError(f'missing/oversized metadata: {name}')
    try:
        return json.loads(path.read_text(encoding='utf-8'),
                          object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(AuditError('invalid number')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AuditError(f'invalid JSON/encoding in {name}: {error}') from error


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
    path = root / 'packs' / f'{language}-{version}.pack.gz'
    if not path.is_file() or path.is_symlink():
        raise AuditError('published package missing or symlink')
    actual, length = _sha_file(path, MAX_PACK_BYTES)
    if actual != expected or length != pack.get('archiveSizeBytes'):
        raise AuditError('package bytes/length do not match manifest')
    try:
        with gzip.open(path, 'rb') as fh:
            blob = fh.read(MAX_ENVELOPE_BYTES + 1)
        if len(blob) > MAX_ENVELOPE_BYTES:
            raise AuditError('inflated package exceeds maximum envelope size')
        from tools.pack_v2.pipeline import check_envelope
        contents = check_envelope(blob, language)
    except (OSError, EOFError, ValueError, KeyError) as error:
        raise AuditError(f'invalid SQLite v2 envelope: {error}') from error
    payload = json.loads(contents['metadata/pack.json'])
    if not payload.get('sourceIds'):
        raise AuditError('published pack has no verified source IDs')
    return payload['sourceIds']


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
    sources = ledger.get('sources')
    packs = manifest.get('packs')
    if not isinstance(sources, list) or not isinstance(packs, list):
        raise AuditError('source ledger/packs must be arrays')
    approved = {item.get('source_id') for item in sources if isinstance(item, dict)
                and item.get('status') == 'APPROVED_FOR_REDISTRIBUTION'}
    if not sources and (packs or version.get('packs') or version.get('release_status') != 'BLOCKED_DEPENDENCY'):
        raise AuditError('cannot release packages with empty source admission ledger')
    indexed = {}
    for p in packs:
        if not isinstance(p, dict) or not isinstance(p.get('id'), str):
            raise AuditError('malformed published v2 entry')
        if p['id'] in indexed or p['id'] not in m_ids:
            raise AuditError('duplicate or unknown published pack')
        indexed[p['id']] = p
    metadata = {item['code']: item for item in manifest['languages']}
    aliases = {item['id']: item for item in registry['languages']}
    selected = sorted(m_ids)[shard::shards]
    verified = 0
    ready = 0
    for code in selected:
        item, lang = metadata[code], aliases[code]
        if not item.get('registered') or not isinstance(lang.get('scripts'), list):
            raise AuditError(f'invalid registered metadata: {code}')
        default_script = lang.get('default_script')
        if default_script not in lang['scripts'] or default_script not in registry.get('scripts', {}):
            raise AuditError(f'invalid canonical script: {code}')
        if item.get('direction') not in ('ltr', 'rtl'):
            raise AuditError(f'invalid direction: {code}')
        if item.get('production_ready') or item.get('is_active'):
            if not (item.get('pack_verified') and item.get('content_available') and code in indexed):
                raise AuditError(f'false production activation: {code}')
        if code in indexed:
            ids = _verify_pack(root, indexed[code], code)
            if not set(ids) <= approved:
                raise AuditError(f'unapproved provenance in pack: {code}')
            verified += 1
        if state[code] == 'unverified' and item.get('production_ready'):
            raise AuditError(f'unverified language falsely activated: {code}')
        if item.get('production_ready'):
            ready += 1
    return {'shard': shard, 'shards': shards, 'language_count': len(selected),
            'registered_total': 100, 'verified_v2_packs': verified,
            'source_ledger_entries': len(sources),
            'source_approved_ids': len(approved), 'status': 'PASS',
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
