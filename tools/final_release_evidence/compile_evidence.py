import json
import hashlib
import os
import sys
import tempfile
import gzip
import argparse

def load_manifest(manifest_path):
    with open(manifest_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def sha256sum(filename):
    h  = hashlib.sha256()
    b  = bytearray(128*1024)
    mv = memoryview(b)
    with open(filename, 'rb', buffering=0) as f:
        while n := f.readinto(mv):
            h.update(mv[:n])
    return h.hexdigest()

def verify_pack_contents(pack_path, expected_license):
    try:
        with gzip.open(pack_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return 'invalidPack', f"Failed to read or parse pack: {e}", {}

    header = data.get('header', {})
    if not header:
        return 'metadataOnly', "Missing header in pack", {}

    pack_license = header.get('license', '').lower()

    details = {
        'pack_version': header.get('version', 'unknown'),
        'source_license': pack_license,
        'cefr_levels': header.get('levels', []),
        'lexical_counts': len(data.get('lexicon', [])),
        'media_identities': len(data.get('media', [])),
        'domains_count': len(data.get('domains', []))
    }

    if expected_license.lower() not in pack_license and pack_license not in expected_license.lower():
        if 'public domain' not in pack_license and 'zero copyright' not in pack_license:
            return 'licenseBlocked', f"Incompatible license: {pack_license}", details

    if not details['cefr_levels'] and not details['domains_count'] and not details['lexical_counts']:
        return 'metadataOnly', "Missing content evidence", details

    if details['cefr_levels'] and details['domains_count'] > 0:
        return 'releaseReady', "Valid and release ready", details

    return 'verified', "Valid but incomplete release readiness", details

def compile_evidence(manifest_path, packs_dir, output_path):
    manifest = load_manifest(manifest_path)
    languages = manifest.get('languages', [])
    expected_license_status = manifest.get('intellectual_property_status', 'PUBLIC_DOMAIN_ZERO_COPYRIGHT')

    evidence = {}

    for lang in languages:
        code = lang['code']
        pack_file = lang.get('pack_file')

        evidence[code] = {
            'state': 'unknown',
            'details': {}
        }

        if not pack_file:
            evidence[code]['state'] = 'sourceMissing'
            evidence[code]['details']['reason'] = 'No pack_file specified in manifest'
            continue

        pack_path = os.path.join(packs_dir, pack_file)

        if not os.path.exists(pack_path):
            evidence[code]['state'] = 'sourceMissing'
            evidence[code]['details']['reason'] = 'Pack file not found on disk'
            continue

        expected_sha256 = lang.get('sha256')
        actual_sha256 = sha256sum(pack_path)

        evidence[code]['details']['checksum_actual'] = actual_sha256
        evidence[code]['details']['checksum_expected'] = expected_sha256

        if expected_sha256 != actual_sha256:
            evidence[code]['state'] = 'invalidPack'
            evidence[code]['details']['reason'] = f"SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}"
            continue

        state, reason, extra_details = verify_pack_contents(pack_path, expected_license_status)
        evidence[code]['state'] = state
        evidence[code]['details']['reason'] = reason
        evidence[code]['details'].update(extra_details)

    # Atomic write
    dirname = os.path.dirname(output_path) or '.'
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    fd, temp_path = tempfile.mkstemp(dir=dirname, prefix='final_evidence_tmp_', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, output_path)
    except Exception as e:
        os.unlink(temp_path)
        raise e

    return evidence

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='manifest.json')
    parser.add_argument('--packs-dir', default='packs')
    parser.add_argument('--output', default='tools/final_release_evidence/final_evidence.json')
    args = parser.parse_args()

    compile_evidence(args.manifest, args.packs_dir, args.output)
    print(f"Evidence compiled to {args.output}")
