#!/usr/bin/env python3
"""Audio source-admission engine for human-recorded pronunciations."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB max for pronunciation
MAX_DURATION_MS = 15000  # 15 seconds

# Very basic BCP-47 tag matching for the locale check
BCP47_RE = re.compile(r'^[a-z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$')
HASH_RE = re.compile(r'^[a-f0-9]{64}$')

def url_ok(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        u = urlsplit(value)
        return u.scheme in ('http', 'https')
    except Exception:
        return False

def check_magic_bytes(filepath, expected_format):
    """Verify file headers match the expected audio format."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(12)
    except OSError:
        return False

    if expected_format == 'wav':
        return header.startswith(b'RIFF') and header[8:12] == b'WAVE'
    elif expected_format == 'ogg':
        return header.startswith(b'OggS')
    elif expected_format == 'mp3':
        # ID3 tag or MPEG ADTS sync word
        return header.startswith(b'ID3') or header.startswith(b'\xff\xfb') or header.startswith(b'\xff\xfa') or header.startswith(b'\xff\xf3') or header.startswith(b'\xff\xf2')
    return False

def process_audio_file(entry, ledger_sources, root_dir):
    """Process a single audio entry, returning an error message if invalid, else None."""
    # Validate basic metadata presence
    for k in ('lexical_id', 'locale', 'variant', 'source_id', 'format', 'file_path', 'sha256', 'size_bytes', 'is_human'):
        if k not in entry:
            return f"missing required field: {k}"

    if not entry.get('is_human'):
        return "rejected: not human-recorded audio (TTS is not allowed)"

    locale = entry.get('locale')
    if not isinstance(locale, str) or not BCP47_RE.match(locale):
        return "invalid locale format"

    source_id = entry.get('source_id')
    if source_id not in ledger_sources:
        return f"source_id '{source_id}' not found in legal ledger"

    source_info = ledger_sources[source_id]
    if source_info.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
        return f"source '{source_id}' not APPROVED_FOR_REDISTRIBUTION"
    if source_info.get('kind') != 'pronunciation':
        return f"source '{source_id}' kind must be 'pronunciation'"

    # Path validation
    file_path = entry.get('file_path')
    if url_ok(file_path):
        return "remote audio references are not allowed"

    path = Path(file_path)
    if path.is_absolute() or '..' in path.parts or '.git' in path.parts:
        return "file path must be relative and within the repository"

    resolved = (Path(root_dir).resolve() / path).resolve()
    if not resolved.is_relative_to(Path(root_dir).resolve()):
        return "file escapes repository"

    if not resolved.is_file():
        return "audio file does not exist"

    # Size check
    actual_size = resolved.stat().st_size
    if actual_size != entry.get('size_bytes'):
        return f"file size mismatch: expected {entry.get('size_bytes')}, got {actual_size}"
    if actual_size > MAX_FILE_SIZE:
        return f"file too large: {actual_size} bytes (max {MAX_FILE_SIZE})"

    # Duration check (metadata based)
    duration = entry.get('duration_ms')
    if duration is not None:
        if not isinstance(duration, int) or duration < 0:
            return "invalid duration_ms"
        if duration > MAX_DURATION_MS:
            return f"duration too long: {duration}ms (max {MAX_DURATION_MS})"

    # Sample rate and channel validation
    sample_rate = entry.get('sample_rate')
    if sample_rate is not None and (not isinstance(sample_rate, int) or sample_rate <= 0):
        return "invalid sample_rate"

    channels = entry.get('channels')
    if channels is not None and (not isinstance(channels, int) or channels <= 0):
        return "invalid channels"

    # SHA-256 validation
    expected_hash = entry.get('sha256')
    if not isinstance(expected_hash, str) or not HASH_RE.match(expected_hash):
        return "invalid sha256 format"

    digest = hashlib.sha256()
    with open(resolved, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            digest.update(chunk)

    if digest.hexdigest() != expected_hash:
        return "SHA-256 hash mismatch (possibly truncated or corrupted file)"

    # Format header validation
    fmt = entry.get('format')
    if fmt not in ('wav', 'ogg', 'mp3'):
        return f"unsupported format: {fmt}"

    if not check_magic_bytes(resolved, fmt):
        return "magic bytes mismatch: declared format does not match file header"

    return None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True, help="Input JSONL manifest")
    parser.add_argument('--ledger', type=Path, required=True, help="Path to sources.json ledger")
    parser.add_argument('--output', type=Path, required=True, help="Output JSONL of approved assets")
    parser.add_argument('--quarantine-dir', type=Path, required=True, help="Directory to move invalid manifest entries")
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    args = parser.parse_args()

    root = args.repo_root.resolve()

    try:
        with open(args.ledger, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
    except Exception as e:
        print(f"Error loading ledger: {e}", file=sys.stderr)
        sys.exit(1)

    ledger_sources = {src.get('source_id'): src for src in ledger.get('sources', [])}

    args.quarantine_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    approved = []
    quarantined = []

    try:
        with open(args.manifest, 'r', encoding='utf-8') as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    quarantined.append({"raw_line": line, "error": "invalid json"})
                    continue

                error = process_audio_file(entry, ledger_sources, root)
                if error:
                    entry['_quarantine_reason'] = error
                    quarantined.append(entry)
                else:
                    approved.append(entry)
    except Exception as e:
        print(f"Error reading manifest: {e}", file=sys.stderr)
        sys.exit(1)

    # Write approved manifest deterministically (sorted by lexical_id and locale for consistency)
    approved.sort(key=lambda x: (x.get('lexical_id', ''), x.get('locale', ''), x.get('variant', '')))

    with open(args.output, 'w', encoding='utf-8') as f:
        for entry in approved:
            f.write(json.dumps(entry, sort_keys=True) + '\n')

    # Write quarantined manifest
    if quarantined:
        quarantine_file = args.quarantine_dir / "rejected.jsonl"
        with open(quarantine_file, 'w', encoding='utf-8') as f:
            for entry in quarantined:
                f.write(json.dumps(entry, sort_keys=True) + '\n')
        print(f"NO-GO: {len(quarantined)} assets quarantined.", file=sys.stderr)
        sys.exit(1)

    print("All assets approved successfully.")
    sys.exit(0)

if __name__ == '__main__':
    main()
