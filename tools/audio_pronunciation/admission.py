import argparse
import json
import sys
import hashlib
from pathlib import Path
import wave
import struct
import re
import shutil

MAX_SIZE_BYTES = 512 * 1024 # 512 KB
MAX_DURATION_SECONDS = 5.0
SUPPORTED_FORMATS = {'mp3', 'ogg', 'wav'}
LICENSES = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'}

# Standard locale matcher
LOCALE_REGEX = re.compile(r'^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$')

def valid_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def check_audio_file(path):
    if not path.exists() or not path.is_file():
        return "not_found"

    if path.stat().st_size > MAX_SIZE_BYTES:
        return "too_large"

    ext = path.suffix.lower()[1:]
    if ext not in SUPPORTED_FORMATS:
        return "unsupported_format"

    with open(path, 'rb') as f:
        header = f.read(4)
        if ext == 'wav' and not header.startswith(b'RIFF'):
            return "malformed"
        elif ext == 'ogg' and not header.startswith(b'OggS'):
            return "malformed"
        elif ext == 'mp3' and not (header.startswith(b'\xff') or header.startswith(b'ID3')):
            return "malformed"

    if ext == 'wav':
        try:
            with wave.open(str(path), 'rb') as w:
                frames = w.getnframes()
                rate = w.getframerate()
                duration = frames / float(rate)
                if duration > MAX_DURATION_SECONDS:
                    return "too_long"
        except wave.Error:
            return "malformed"

    return "ok"


def evaluate(manifest, ledger):
    out = []
    approved = []

    sources = {}
    if isinstance(ledger, dict) and 'sources' in ledger:
        for s in ledger['sources']:
            if 'source_id' in s:
                sources[s['source_id']] = s

    for item in manifest.get('assets', []):
        if not isinstance(item, dict):
            continue

        record_id = item.get('record_id')
        if not record_id:
            out.append("MISSING_RECORD_ID")
            continue

        locale = item.get('locale')
        if not locale or not LOCALE_REGEX.match(locale):
            out.append(f"{record_id}: INVALID_LOCALE")
            continue

        lexical_id = item.get('lexical_id')
        if not lexical_id:
            out.append(f"{record_id}: MISSING_LEXICAL_ID")
            continue

        source = item.get('source', {})
        if source.get('synthesized') or source.get('tts'):
            out.append(f"{record_id}: SYNTHESIZED_AUDIO_REJECTED")
            continue

        source_id = source.get('source_id')
        if source_id not in sources:
            out.append(f"{record_id}: UNVERIFIED_SOURCE")
            continue

        ledger_src = sources[source_id]
        if ledger_src.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
            out.append(f"{record_id}: NOT_APPROVED_FOR_REDISTRIBUTION")
            continue

        lid = ledger_src.get('license', {}).get('id')
        if lid not in LICENSES:
            out.append(f"{record_id}: BLOCKED_LICENSE")
            continue

        audio_path = item.get('audio_path')
        if not audio_path:
             out.append(f"{record_id}: MISSING_AUDIO_PATH")
             continue

        if audio_path.startswith("http://") or audio_path.startswith("https://"):
            out.append(f"{record_id}: REMOTE_AUDIO_REJECTED")
            continue

        declared_sha256 = item.get('sha256')
        if not declared_sha256:
            out.append(f"{record_id}: MISSING_SHA256")
            continue

        p = Path(audio_path)
        status = check_audio_file(p)
        if status == "not_found":
            out.append(f"{record_id}: FILE_NOT_FOUND")
            continue
        elif status == "too_large":
            out.append(f"{record_id}: FILE_TOO_LARGE")
            continue
        elif status == "too_long":
            out.append(f"{record_id}: FILE_TOO_LONG")
            continue
        elif status == "unsupported_format":
             out.append(f"{record_id}: UNSUPPORTED_FORMAT")
             continue
        elif status == "malformed":
             out.append(f"{record_id}: MALFORMED_FILE")
             continue

        if status == "ok":
            actual_sha256 = valid_hash(p)
            if actual_sha256 != declared_sha256:
                out.append(f"{record_id}: HASH_MISMATCH")
                continue

        # If all checks pass
        approved.append(item)

    return out, approved


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audio Admission Gate")
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('approved_audio.json'))
    parser.add_argument('--quarantine', type=Path, default=Path('quarantine'))
    args = parser.parse_args(argv)

    try:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        ledger = json.loads(args.ledger.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"Error reading inputs: {e}", file=sys.stderr)
        return 2

    errors, approved = evaluate(manifest, ledger)

    if errors:
        args.quarantine.mkdir(parents=True, exist_ok=True)
        # Identify bad records
        bad_ids = [e.split(":")[0].strip() for e in errors if ":" in e]
        for item in manifest.get('assets', []):
            if item.get('record_id') in bad_ids:
                if 'audio_path' in item:
                    try:
                        p = Path(item['audio_path'])
                        if p.exists() and p.is_file():
                            # Quarantine the asset by moving it
                            target = args.quarantine / p.name
                            shutil.move(str(p), str(target))
                    except Exception as e:
                        pass # Ignore errors moving

    for e in errors:
        print('BLOCK ' + e)

    # Write deterministic approved manifest
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Sort for determinism
    approved = sorted(approved, key=lambda x: x.get('record_id', ''))
    approved_manifest = {"assets": approved}
    args.output.write_text(json.dumps(approved_manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    if errors:
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
