import gzip
import json
import os
import hashlib
import tempfile
from pathlib import Path

def secure_resolve_path(base_dir, relative_path):
    """
    Resolve a path relative to base_dir, rejecting any traversal outside base_dir.
    """
    base_path = Path(base_dir).resolve()
    target_path = (base_path / relative_path).resolve()

    try:
        if not target_path.is_relative_to(base_path):
            raise ValueError(f"Unsafe path detected: {relative_path} escapes {base_dir}")
    except AttributeError:
        # Fallback for older Python versions
        if not str(target_path).startswith(str(base_path) + os.sep) and str(target_path) != str(base_path):
            raise ValueError(f"Unsafe path detected: {relative_path} escapes {base_dir}")

    return target_path

def compute_sha256(filepath, chunk_size=65536):
    """
    Perform streaming file-hashing with bounded memory usage.
    """
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def count_entries(filepath):
    """
    Parse a .pack.gz or JSON file with bounded parsing memory to get the actual entry count.
    Since files can be large, we read the JSON incrementally if possible, or just parse carefully.
    For standard .pack.gz files, we look for 'terms_count', or 'vocabulary' length.
    We'll do a standard json.load for now but in a production environment with huge files,
    we would use ijson. The requirements say 'Bound parsing memory', so we check file size first
    to avoid blowing up memory. If it's too large for standard json.loads, we'd need streaming.
    Given standard Python, we can do a quick load if it's small, or parse line by line if jsonl.
    """
    size = os.path.getsize(filepath)
    if size > 100 * 1024 * 1024:
        raise ValueError("File too large to parse completely into memory.")

    try:
        if str(filepath).endswith('.gz'):
            with gzip.open(filepath, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        else:
            with open(filepath, 'rt', encoding='utf-8') as f:
                data = json.load(f)

        if isinstance(data, dict):
            if 'vocabulary' in data and isinstance(data['vocabulary'], list):
                return len(data['vocabulary'])
            elif 'terms_count' in data:
                return data['terms_count']
            elif 'senses' in data and isinstance(data['senses'], list):
                return len(data['senses'])
            elif 'concepts' in data and isinstance(data['concepts'], list):
                return len(data['concepts'])
            else:
                return 0
        elif isinstance(data, list):
            return len(data)
        else:
            return 0
    except Exception as e:
        raise ValueError(f"Failed to parse or count entries for {filepath}: {str(e)}")


def build_manifest(base_dir, records, out_path):
    """
    Builds a deterministic versioned manifest from the given records.
    records is a list of dicts with:
      path: relative path to the artifact
      language: language code
      pack_id: unique pack identifier
      schema_version: e.g. "2.0.0"
      source_id: provenance
      license_id: license
      dependencies: list of dependent paths
      entry_count: expected entry count (optional, but if provided, must match actual)
    """
    manifest = {
        "version": "1.0.0",
        "packs": []
    }

    for record in records:
        rel_path = record.get('path')
        if not rel_path:
            raise ValueError("Record missing path")

        target_path = secure_resolve_path(base_dir, rel_path)
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Missing artifact: {target_path}")

        # Provenance requirements
        for key in ['source_id', 'license_id', 'pack_id', 'schema_version', 'language']:
            if not record.get(key):
                raise ValueError(f"Invalid record for {rel_path}: missing {key}")

        actual_size = os.path.getsize(target_path)
        actual_sha256 = compute_sha256(target_path)
        actual_count = count_entries(target_path)

        expected_count = record.get('entry_count')
        if expected_count is not None and expected_count != actual_count:
            raise ValueError(f"Mismatched entry count for {rel_path}: expected {expected_count}, got {actual_count}")

        # Check dependencies
        deps = record.get('dependencies', [])
        for dep in deps:
            dep_path = secure_resolve_path(base_dir, dep)
            if not os.path.exists(dep_path):
                raise FileNotFoundError(f"Broken dependency for {rel_path}: {dep} not found")

        pack_entry = {
            "path": rel_path,
            "language": record['language'],
            "pack_id": record['pack_id'],
            "schema_version": record['schema_version'],
            "entry_count": actual_count,
            "size_bytes": actual_size,
            "sha256": actual_sha256,
            "source_id": record['source_id'],
            "license_id": record['license_id'],
            "dependencies": record.get('dependencies', [])
        }

        manifest["packs"].append(pack_entry)

    # Sort for deterministic JSON
    manifest["packs"] = sorted(manifest["packs"], key=lambda x: x["path"])

    # Atomic write to preserve previous on failure
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(out_path) or '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        os.replace(temp_path, out_path)
    except Exception as e:
        os.remove(temp_path)
        raise e

def generate_update_plan(old_manifest, new_manifest):
    """
    Compare two manifests and identify safe daily content changes.
    Skip unchanged packs and changed metadata with no payload delta.
    Return an update plan dict of `unchanged`, `updated`, `added`, `removed` lists (of paths).
    """
    plan = {
        'unchanged': [],
        'updated': [],
        'added': [],
        'removed': []
    }

    old_packs = {p['path']: p for p in old_manifest.get('packs', [])}
    new_packs = {p['path']: p for p in new_manifest.get('packs', [])}

    for path, new_meta in new_packs.items():
        if path not in old_packs:
            plan['added'].append(path)
        else:
            old_meta = old_packs[path]
            # Check payload delta
            payload_changed = (old_meta.get('sha256') != new_meta.get('sha256') or
                               old_meta.get('size_bytes') != new_meta.get('size_bytes'))

            if not payload_changed:
                # If payload is unchanged, we skip, even if other metadata changed
                plan['unchanged'].append(path)
            else:
                plan['updated'].append(path)

    for path in old_packs:
        if path not in new_packs:
            plan['removed'].append(path)

    # Sort for deterministic output
    for key in plan:
        plan[key].sort()

    return plan

# We should add a check for broken dependencies.
# Although the prompt didn't specify exactly what "broken dependency" means,
# it usually means a dependency file doesn't exist locally.
