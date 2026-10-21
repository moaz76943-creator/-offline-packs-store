#!/usr/bin/env python3
import hashlib
import json
import os
import zlib
import gzip
import argparse
from pathlib import Path
import sys
import tempfile
import stat

MAX_FILE_SIZE = 50 * 1024 * 1024 # 50 MB
MAX_MANIFEST_SIZE = 5 * 1024 * 1024 # 5 MB
MAX_UNCOMPRESSED_VCT = 2048 # Usually these are very small, < 2KB
MAX_UNCOMPRESSED_PAYLOAD = 150 * 1024 * 1024 # 150MB

class ManifestError(ValueError):
    pass

def _resolve_path(repo_root: Path, file_path: str) -> Path:
    if '..' in file_path or file_path.startswith('/'):
        raise ManifestError("Untrusted external paths and directory traversal are rejected.")
    resolved = (repo_root / file_path).resolve()
    if not str(resolved).startswith(str(repo_root.resolve())):
        raise ManifestError("Untrusted external paths and directory traversal are rejected.")
    return resolved

def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def _parse_pack_gz(path: Path):
    try:
        # To compute payload hash separate from metadata, we read the gzip file
        # The first line is metadata, the rest is payload
        payload_hash = hashlib.sha256()
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            first_line = f.readline()
            if not first_line:
                raise ManifestError("Empty pack file.")
            try:
                header = json.loads(first_line)
            except json.JSONDecodeError:
                raise ManifestError("Invalid JSON header in pack file.")

            # Count actual entries and hash payload
            entry_count = 0
            for line in f:
                if line.strip():
                    entry_count += 1
                    payload_hash.update(line.encode('utf-8'))

            language = header.get('language') or header.get('lang_code')
            if not language:
                raise ManifestError("Missing language in header.")

            pack_id = header.get('pack_id') or header.get('id', language)
            schema_version = header.get('schema_version') or header.get('version', '1.0')

            expected_count = header.get('lexical_count') or header.get('terms_count', entry_count)
            if entry_count != expected_count:
                raise ManifestError(f"Mismatched entry counts. Expected {expected_count}, got {entry_count}.")

            dependencies = header.get('media_identities') or header.get('dependencies', [])
            source = header.get('source_provenance', header.get('source', []))
            license_id = header.get('license_identifiers', header.get('license', 'UNKNOWN'))

            return {
                'type': 'pack',
                'language': language,
                'pack_id': pack_id,
                'schema_version': schema_version,
                'entry_count': entry_count,
                'source_provenance': source,
                'license_identifiers': license_id,
                'dependencies': dependencies,
                'payload_sha256': payload_hash.hexdigest()
            }
    except Exception as e:
        if isinstance(e, ManifestError):
            raise
        raise ManifestError(f"Error parsing .pack.gz: {e}")

def _parse_vct(path: Path):
    try:
        data = path.read_bytes()
        dec = zlib.decompressobj()
        decompressed = dec.decompress(data, MAX_UNCOMPRESSED_VCT)
        if dec.unconsumed_tail:
            raise ManifestError("Decompression exceeded limit.")

        metadata = json.loads(decompressed.decode('utf-8'))

        pack_id = metadata.get('pack_id') or metadata.get('id')
        if not pack_id:
            raise ManifestError("Missing pack_id in vct.")

        return {
            'type': 'vct',
            'pack_id': pack_id,
            'schema_version': metadata.get('version', '1.0'),
            'source_provenance': metadata.get('source', []),
            'license_identifiers': metadata.get('license', 'UNKNOWN'),
            # For vct, the whole file is metadata + visual info, payload is the file itself
            'payload_sha256': _compute_sha256(path)
        }
    except Exception as e:
        if isinstance(e, ManifestError):
            raise
        raise ManifestError(f"Error parsing .vct: {e}")

def build_manifest(repo_root: Path, file_paths: list[str]) -> dict:
    manifest = {
        'version': '1.0.0',
        'entries': {}
    }

    for file_path in file_paths:
        try:
            resolved = _resolve_path(repo_root, file_path)
            if not resolved.exists() or not resolved.is_file():
                raise ManifestError(f"Missing artifact: {file_path}")

            size = resolved.stat().st_size
            if size > MAX_FILE_SIZE:
                raise ManifestError(f"File {file_path} exceeds maximum allowed size.")

            sha256_hash = _compute_sha256(resolved)

            if file_path.endswith('.pack.gz'):
                meta = _parse_pack_gz(resolved)
            elif file_path.endswith('.vct'):
                meta = _parse_vct(resolved)
            else:
                raise ManifestError(f"Unsupported file type: {file_path}")

            entry = {
                'file_path': file_path,
                'byte_size': size,
                'sha256': sha256_hash,
                **meta
            }
            manifest['entries'][file_path] = entry

        except Exception as e:
            if isinstance(e, ManifestError):
                raise
            raise ManifestError(f"Failed to process {file_path}: {e}")

    for file_path, entry in manifest['entries'].items():
        if entry.get('type') == 'pack':
            for dep in entry.get('dependencies', []):
                dep_found = False
                for e_path, e_data in manifest['entries'].items():
                    if e_data.get('pack_id') == dep or e_path == dep:
                        dep_found = True
                        break
                if not dep_found:
                    raise ManifestError(f"Broken dependency: {dep} required by {file_path} is missing from manifest.")

    # Ensure manifest dict is serializable to string, we enforce max size in persist
    return manifest

def generate_update_plan(old_manifest: dict, new_manifest: dict) -> dict:
    plan = {
        'unchanged': [],
        'added': [],
        'removed': [],
        'changed': []
    }

    old_entries = old_manifest.get('entries', {})
    new_entries = new_manifest.get('entries', {})

    for file_path, new_entry in new_entries.items():
        if file_path not in old_entries:
            plan['added'].append(file_path)
        else:
            old_entry = old_entries[file_path]
            # Compare payload delta instead of full artifact hash to skip metadata-only changes
            if new_entry.get('payload_sha256') == old_entry.get('payload_sha256'):
                plan['unchanged'].append(file_path)
            else:
                plan['changed'].append(file_path)

    for file_path in old_entries.keys():
        if file_path not in new_entries:
            plan['removed'].append(file_path)

    return plan

def main():
    parser = argparse.ArgumentParser(description="Pack Manifest Builder")
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--files', nargs='+', required=True)
    parser.add_argument('--output-manifest', type=Path, required=True)
    parser.add_argument('--old-manifest', type=Path, required=False)
    parser.add_argument('--output-plan', type=Path, required=False)
    args = parser.parse_args()

    try:
        manifest = build_manifest(args.repo_root, args.files)

        manifest_str = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
        if len(manifest_str.encode('utf-8')) > MAX_MANIFEST_SIZE:
            raise ManifestError("Manifest exceeds maximum size.")

        # Write output safely
        # Preserve previous on failure by writing to temp first then moving
        if args.output_manifest.exists():
            backup_path = args.output_manifest.with_suffix('.bak')
            import shutil
            shutil.copy2(args.output_manifest, backup_path)

        fd, temp_path = tempfile.mkstemp(dir=args.output_manifest.parent, prefix='.manifest-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(manifest_str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, args.output_manifest)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        if args.old_manifest and args.old_manifest.exists() and args.output_plan:
            old_manifest = json.loads(args.old_manifest.read_text(encoding='utf-8'))
            plan = generate_update_plan(old_manifest, manifest)
            plan_str = json.dumps(plan, sort_keys=True, indent=2)
            args.output_plan.write_text(plan_str, encoding='utf-8')

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("Success")

if __name__ == '__main__':
    main()
