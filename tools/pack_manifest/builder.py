import gzip
import hashlib
import json
import os
import tempfile
import zlib
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "1.0.0"

def secure_resolve_path(base_dir, target_path_str):
    base_path = Path(base_dir).resolve()
    target_path = (base_path / target_path_str).resolve()
    if not target_path.is_relative_to(base_path):
        raise ValueError(f"Unsafe path detected: {target_path_str} escapes {base_dir}")
    return target_path

def compute_sha256(filepath, chunk_size=65536):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

MAX_JSON_BYTES = 100 * 1024 * 1024
MAX_VCT_BYTES = 2048
MAX_VCT_JSON_BYTES = 65536


def bounded_json_parse(filepath):
    # Bound *decompressed* input before the JSON parser allocates objects.
    size = os.path.getsize(filepath)
    if size > MAX_JSON_BYTES:
        raise ValueError('Compressed artifact exceeds input limit')

    if str(filepath).endswith('.pack.gz'):
        with gzip.open(filepath, 'rb') as stream:
            payload = stream.read(MAX_JSON_BYTES + 1)
        if len(payload) > MAX_JSON_BYTES:
            raise ValueError('Decompressed pack exceeds input limit')
    elif str(filepath).endswith('.vct'):
        if size > MAX_VCT_BYTES:
            raise ValueError('VCT exceeds compressed input limit')
        with open(filepath, 'rb') as stream:
            raw = stream.read(MAX_VCT_BYTES + 1)
        try:
            decompressor = zlib.decompressobj()
            payload = decompressor.decompress(raw, MAX_VCT_JSON_BYTES + 1)
            if (len(payload) > MAX_VCT_JSON_BYTES or
                    not decompressor.eof or decompressor.unused_data or
                    decompressor.unconsumed_tail):
                raise ValueError('Invalid or decompressed-overlimit VCT')
        except zlib.error as exc:
            raise ValueError('Invalid VCT compression') from exc
    else:
        raise ValueError(f'Unsupported file type: {filepath}')

    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Invalid JSON artifact') from exc
    if not isinstance(data, dict):
        raise ValueError('Pack metadata must be a JSON object')
    return data

def extract_metadata(filepath):
    data = bounded_json_parse(filepath)

    if str(filepath).endswith('.pack.gz'):
        pack_id = data.get('lang_code') or data.get('header', {}).get('code')
        if not pack_id:
            raise ValueError(f"Missing pack identity in {filepath}")

        version = data.get('version') or '1.0.0'

        # Compute entry count and validate
        declared_count = data.get('terms_count')
        actual_count = 0
        if 'vocabulary' in data:
            actual_count = len(data['vocabulary'])
        elif 'domains' in data:
            actual_count = len(data['domains'])

        if declared_count is not None and declared_count != actual_count and actual_count > 0:
            # But what if there is no vocabulary/domains? We just trust terms_count.
            pass
        entry_count = declared_count if declared_count is not None else actual_count

        if 'terms_count' in data and 'vocabulary' in data and data['terms_count'] != len(data['vocabulary']):
            raise ValueError(f"Mismatched entry counts in {filepath}")

        license_id = data.get('license') or data.get('header', {}).get('license')
        if not license_id:
            raise ValueError(f"Missing license identifier in {filepath}")

        deps = data.get('dependencies', [])
        provenance = data.get('provenance') or data.get('header', {}).get('provenance') or []

        return {
            'pack_id': pack_id,
            'version': version,
            'entry_count': entry_count,
            'license': license_id,
            'dependencies': deps,
            'provenance': provenance
        }

    elif str(filepath).endswith('.vct'):
        pack_id = data.get('asset_id') or os.path.basename(filepath)
        deps = data.get('dependencies', [])
        provenance = data.get('provenance', [])
        return {
            'pack_id': pack_id,
            'version': data.get('version', '1.0.0'),
            'entry_count': 1,
            'license': data.get('license', 'CC0-1.0'),
            'dependencies': deps,
            'provenance': provenance
        }
    else:
        raise ValueError(f"Unsupported file type: {filepath}")

def build_manifest(base_dir, file_paths, output_manifest_path):
    if not file_paths:
        raise ValueError("Missing artifacts: file_paths is empty")

    manifest = {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'packs': {}
    }

    for rel_path in file_paths:
        target = secure_resolve_path(base_dir, rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Missing artifact: {rel_path}")

        meta = extract_metadata(target)
        size = target.stat().st_size
        sha256 = compute_sha256(target)

        pack_id = meta['pack_id']
        if pack_id in manifest['packs']:
            raise ValueError(f"Duplicate pack identity: {pack_id}")
        manifest['packs'][pack_id] = {
            'path': str(rel_path),
            'version': meta['version'],
            'entry_count': meta['entry_count'],
            'size_bytes': size,
            'sha256': sha256,
            'license': meta['license'],
            'dependencies': meta['dependencies'],
            'provenance': meta['provenance']
        }

    out_dir = os.path.dirname(output_manifest_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=out_dir or '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        os.replace(temp_path, output_manifest_path)
    except Exception as e:
        os.remove(temp_path)
        raise e

def generate_update_plan(old_manifest_path, new_manifest_path):
    if os.path.exists(old_manifest_path):
        with open(old_manifest_path, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
    else:
        old_data = {'packs': {}}

    with open(new_manifest_path, 'r', encoding='utf-8') as f:
        new_data = json.load(f)

    old_packs = old_data.get('packs', {})
    new_packs = new_data.get('packs', {})

    plan = {
        'added': [],
        'updated': [],
        'removed': [],
        'unchanged': []
    }

    for pack_id, new_meta in new_packs.items():
        if pack_id not in old_packs:
            plan['added'].append(pack_id)
        else:
            old_meta = old_packs[pack_id]
            if old_meta['sha256'] == new_meta['sha256'] and old_meta['version'] == new_meta['version'] and old_meta['dependencies'] == new_meta['dependencies'] and old_meta.get('provenance') == new_meta.get('provenance'):
                plan['unchanged'].append(pack_id)
            elif old_meta['sha256'] == new_meta['sha256']:
                # Skip changed metadata with no payload delta
                plan['unchanged'].append(pack_id)
            else:
                plan['updated'].append(pack_id)

    for pack_id in old_packs:
        if pack_id not in new_packs:
            plan['removed'].append(pack_id)

    for key in plan:
        plan[key].sort()

    return plan
