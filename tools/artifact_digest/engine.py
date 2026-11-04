import hashlib
import os
import tempfile
import json
import shutil
from pathlib import Path

def compute_sha256(filepath, chunk_size=65536):
    """
    Perform streaming file-hashing with bounded memory usage over actual artifact bytes.
    """
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def secure_resolve_path(base_dir, relative_path):
    """
    Implement path security to reject symlink escapes and unsafe relative paths.
    """
    base_path = Path(base_dir).resolve()
    # Path().resolve() follows symlinks
    target_path = (base_path / relative_path).resolve()

    try:
        if not target_path.is_relative_to(base_path):
            raise ValueError(f"Unsafe path detected: {relative_path} escapes {base_dir}")
    except AttributeError:
        # Fallback for older python versions if is_relative_to is not available
        if not str(target_path).startswith(str(base_path) + os.sep) and str(target_path) != str(base_path):
            raise ValueError(f"Unsafe path detected: {relative_path} escapes {base_dir}")

    return target_path

def validate_artifact(filepath, metadata):
    """
    Validate declared size vs actual size (via file stat and/or chunk iteration). Reject truncated files.
    Check for valid provenance fields in metadata (source ID, license ID, logical asset ID, version) before approving content.
    Reject missing files (do not silently certify).
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Missing file: {filepath}")

    # Provenance requirements
    required_keys = ['source_id', 'license_id', 'asset_id', 'version']
    for key in required_keys:
        if key not in metadata or not metadata[key]:
            raise ValueError(f"Invalid provenance: missing or empty {key}")

    # Size validation
    declared_size = metadata.get('size_bytes')
    if declared_size is not None:
        actual_size = os.path.getsize(filepath)
        if actual_size != declared_size:
            raise ValueError(f"Size mismatch: declared {declared_size}, actual {actual_size}")

    return True

def build_digest_index(base_dir, artifact_records, index_out_path):
    """
    Build a deterministic artifact digest index (JSON dictionary) from a list of files or manifest definitions.
    artifact_records: list of dicts with 'path' and metadata keys
    """
    index = {}

    for record in artifact_records:
        rel_path = record.get('path')
        if not rel_path:
            continue

        try:
            target_path = secure_resolve_path(base_dir, rel_path)
            # Re-validate artifact
            validate_artifact(target_path, record)
            # Compute hash
            file_hash = compute_sha256(target_path)

            # JSON null means the optional digest was omitted, matching size_bytes.
            declared_sha = record.get('sha256')
            if declared_sha is not None and declared_sha != file_hash:
                raise ValueError(f"Hash mismatch for {rel_path}: declared {declared_sha}, actual {file_hash}")

            index[rel_path] = {
                'sha256': file_hash,
                'size_bytes': os.path.getsize(target_path),
                'source_id': record['source_id'],
                'license_id': record['license_id'],
                'asset_id': record['asset_id'],
                'version': record['version']
            }
        except Exception as e:
            # If invalid, mark as such in the index
            index[rel_path] = {
                'invalid': True,
                'error': str(e),
                'source_id': record.get('source_id'),
                'license_id': record.get('license_id'),
                'asset_id': record.get('asset_id'),
                'version': record.get('version')
            }

    # Sort for deterministic JSON
    sorted_index = dict(sorted(index.items()))

    # Atomic write
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(index_out_path) or '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(sorted_index, f, indent=2, sort_keys=True)
        # atomic rename
        os.replace(temp_path, index_out_path)
    except Exception as e:
        os.remove(temp_path)
        raise e

def compare_indexes(old_index, new_index):
    """
    Provide incremental comparison of an old index and a new index.
    Categorize as unchanged, updated, deleted, and invalid artifacts.
    Produce J087-consumable change events.
    """
    events = {
        'unchanged': [],
        'updated': [],
        'deleted': [],
        'invalid': []
    }

    # We define invalid as missing provenance or size mismatch, but
    # in the context of comparing two built indexes, invalid could mean
    # entries in new_index that somehow are marked invalid, but index only has valid.
    # We will assume new_index could have None or Error strings for sha256 if invalid,
    # but based on build_digest_index we skipped them.
    # Let's adjust to allow returning invalid items if they are passed in.

    for path, new_meta in new_index.items():
        if new_meta.get('invalid'):
            events['invalid'].append(path)
            continue

        if path not in old_index:
            # New items count as updated
            events['updated'].append(path)
        else:
            old_meta = old_index[path]
            # Check if updated or unchanged
            if old_meta.get('sha256') == new_meta.get('sha256'):
                is_changed = False
                for key in ['sha256', 'source_id', 'license_id', 'asset_id', 'version', 'size_bytes', 'invalid']:
                    if old_meta.get(key) != new_meta.get(key):
                        is_changed = True
                        break
                if is_changed:
                    events['updated'].append(path)
                else:
                    events['unchanged'].append(path)
            else:
                events['updated'].append(path)

    for path, old_meta in old_index.items():
        if path not in new_index:
            events['deleted'].append(path)

    for key in events:
        events[key].sort()

    return events
