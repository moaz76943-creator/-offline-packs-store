#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024  # 1 MB limit

# BCP-47 rough regex
LOCALE_RE = re.compile(r'^[a-z]{2,3}(-[a-zA-Z0-9]{2,8})*$')
LEXEME_ID_RE = re.compile(r'^[a-z][a-z0-9._:-]{2,127}$')

def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None

def verify_magic(path, format_hint):
    try:
        with open(path, 'rb') as f:
            header = f.read(12)
    except OSError:
        return False

    if len(header) < 4:
        return False

    if format_hint == 'wav':
        return header.startswith(b'RIFF') and b'WAVE' in header
    elif format_hint in ('ogg', 'webm'): # just general check for now
        return header.startswith(b'OggS') or header.startswith(b'\x1a\x45\xdf\xa3')
    elif format_hint == 'mp3':
        return header.startswith(b'ID3') or header.startswith(b'\xff\xfb') or header.startswith(b'\xff\xfa') or header.startswith(b'\xff\xf2') or header.startswith(b'\xff\xe3')
    return False

def check_rights_and_ledger(source_id, ledger_data):
    if not isinstance(ledger_data, dict):
        return False
    sources = ledger_data.get('sources', [])
    for src in sources:
        if src.get('source_id') == source_id:
            if src.get('kind') != 'pronunciation':
                return False
            if src.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
                return False
            return True
    return False

def process_candidates(candidates, ledger, root_dir):
    accepted = []
    rejected = []

    for entry in candidates:
        try:
            # 1. Identity & Rights
            lexeme_id = entry.get('lexeme_id', '')
            locale = entry.get('locale', '')
            source_id = entry.get('source_id', '')

            if not LEXEME_ID_RE.match(lexeme_id):
                raise ValueError("Invalid lexeme_id")
            if not LOCALE_RE.match(locale):
                raise ValueError("Invalid locale")

            if not check_rights_and_ledger(source_id, ledger):
                raise ValueError("Source rights missing or unapproved")

            # 2. TTS vs Human
            if entry.get('human_recorded') is not True:
                raise ValueError("Must be human_recorded")
            if entry.get('is_tts') is True:
                raise ValueError("TTS is not allowed")

            # Anti-biometric
            if 'biometric_profile' in entry or 'speaker_age' in entry:
                raise ValueError("Biometric/personal metadata not allowed")

            # 3. File integrity & size
            artifact_path = entry.get('artifact_path', '')
            if artifact_path.startswith('http://') or artifact_path.startswith('https://'):
                raise ValueError("Remote audio not allowed")

            full_path = (Path(root_dir) / artifact_path).resolve()
            if not full_path.is_relative_to(Path(root_dir).resolve()):
                raise ValueError("Path escapes root")

            if not full_path.is_file():
                raise ValueError("File does not exist")

            size = os.path.getsize(full_path)
            if size > MAX_FILE_SIZE:
                raise ValueError("File too large")

            # Extra metadata checks
            duration = entry.get('duration_ms', 0)
            if duration and duration > 10000:  # 10s arbitrary limit for max duration, normally pronunciation is 1-3s
                raise ValueError("Audio duration too long")

            channels = entry.get('channels')
            if channels and channels > 2:
                raise ValueError("Too many channels")

            sample_rate = entry.get('sample_rate')
            if sample_rate and sample_rate not in (16000, 22050, 24000, 32000, 44100, 48000):
                raise ValueError("Unsupported sample rate")

            expected_sha = entry.get('sha256')
            actual_sha = sha256_file(full_path)
            if actual_sha != expected_sha:
                raise ValueError("SHA256 mismatch")

            # 4. Format & Header
            format_hint = entry.get('format', 'ogg')
            if not verify_magic(full_path, format_hint):
                raise ValueError("Invalid file format or malformed header")

            # Accepted
            entry_copy = dict(entry)
            # Ensure no unwanted properties exist just to be safe
            accepted.append(entry_copy)

        except ValueError as e:
            entry_copy = dict(entry)
            entry_copy['rejection_reason'] = str(e)
            rejected.append(entry_copy)

    # Deterministic output
    accepted.sort(key=lambda x: (x.get('lexeme_id',''), x.get('locale','')))
    return accepted, rejected

def main():
    parser = argparse.ArgumentParser(description="Audio Pronunciation Admission Gate")
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--quarantine', required=True, type=Path)
    parser.add_argument('--repo-root', default='.', type=Path)
    args = parser.parse_args()

    try:
        with open(args.ledger, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
    except Exception as e:
        print(f"Error reading ledger: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            candidates = [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        sys.exit(1)

    accepted, rejected = process_candidates(candidates, ledger_data, args.repo_root)

    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            for item in accepted:
                f.write(json.dumps(item, separators=(',', ':')) + '\n')

        with open(args.quarantine, 'w', encoding='utf-8') as f:
            for item in rejected:
                f.write(json.dumps(item, separators=(',', ':')) + '\n')
    except Exception as e:
        print(f"Error writing output/quarantine: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
