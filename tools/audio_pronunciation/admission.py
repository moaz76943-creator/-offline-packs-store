import argparse
import hashlib
import json
import sys
import wave
import struct
from pathlib import Path

# Maximum constraints
MAX_FILE_SIZE = 512 * 1024 # 512 KB
MAX_DURATION_SECONDS = 5.0
SUPPORTED_FORMATS = {'wav': b'RIFF'}
ALLOWED_SAMPLE_RATES = {16000, 22050, 44100, 48000}
ALLOWED_CHANNELS = {1, 2}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def validate_audio_file(path: Path) -> list[str]:
    issues = []

    if not path.exists():
        return ["FILE_MISSING"]

    if path.stat().st_size > MAX_FILE_SIZE:
        issues.append("FILE_TOO_LARGE")

    try:
        with path.open('rb') as f:
            header = f.read(4)
            if header != SUPPORTED_FORMATS['wav']:
                issues.append("UNSUPPORTED_FORMAT")
                return issues # Stop here if not WAV, wave module will crash

        with wave.open(str(path), 'rb') as w:
            channels = w.getnchannels()
            sample_width = w.getsampwidth()
            framerate = w.getframerate()
            nframes = w.getnframes()

            if channels not in ALLOWED_CHANNELS:
                issues.append("UNSUPPORTED_CHANNELS")

            if framerate not in ALLOWED_SAMPLE_RATES:
                issues.append("UNSUPPORTED_SAMPLE_RATE")

            duration = nframes / float(framerate)
            if duration > MAX_DURATION_SECONDS:
                issues.append("DURATION_TOO_LONG")

    except wave.Error:
        issues.append("MALFORMED_AUDIO")
    except Exception as e:
        issues.append(f"AUDIO_ERROR: {str(e)}")

    return issues

def validate_metadata(metadata: dict, ledger: dict) -> list[str]:
    issues = []

    # 1. Require verified source identity and redistribution rights.
    source_id = metadata.get('source_id')
    if not source_id:
        issues.append("MISSING_SOURCE_ID")
    else:
        # Check against ledger
        ledger_sources = {s['source_id']: s for s in ledger.get('sources', [])}
        source_info = ledger_sources.get(source_id)
        if not source_info:
            issues.append("UNVERIFIED_SOURCE")
        else:
            if source_info.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
                 issues.append("UNAPPROVED_SOURCE")
            # 10. Reject missing rights evidence
            if not source_info.get('license', {}).get('evidence_path'):
                 issues.append("MISSING_RIGHTS_EVIDENCE")

            # 11. Reject hidden remote audio references in supposedly offline-ready packages.
            # (Ensured by checking local file existence, handled elsewhere)

    # 8. Preserve lexical entry ID, locale and pronunciation variant.
    if not metadata.get('lexical_id'):
        issues.append("MISSING_LEXICAL_ID")
    if not metadata.get('locale'):
        issues.append("MISSING_LOCALE")

    # 9. Distinguish human-recorded audio from TTS voice capability.
    if metadata.get('is_tts', False):
        issues.append("TTS_REJECTED") # 18. Never synthesize audio merely to meet language coverage.

    # 17. Avoid incorporating biometric speaker profiles or unnecessary personal voice metadata.
    if 'speaker_profile' in metadata or 'biometrics' in metadata:
        issues.append("BIOMETRICS_REJECTED")

    # 14. Preserve source attribution and license obligations.
    if not metadata.get('attribution'):
        issues.append("MISSING_ATTRIBUTION")

    return issues

def evaluate(metadata_path: Path, audio_dir: Path, ledger_path: Path, output_path: Path) -> int:
    try:
        with ledger_path.open('r', encoding='utf-8') as f:
            ledger = json.load(f)
    except Exception as e:
        print(f"Error loading ledger: {e}", file=sys.stderr)
        return 1

    try:
        with metadata_path.open('r', encoding='utf-8') as f:
            metadata_list = json.load(f)
    except Exception as e:
        print(f"Error loading metadata: {e}", file=sys.stderr)
        return 1

    approved = []
    quarantined = []

    for item in metadata_list:
        issues = validate_metadata(item, ledger)

        audio_file = audio_dir / item.get('file_path', '')
        # 11. Reject hidden remote audio references
        if 'http' in item.get('file_path', ''):
             issues.append("REMOTE_AUDIO_REJECTED")

        if not issues and not audio_file.exists():
            issues.append("FILE_MISSING")

        if not issues:
             audio_issues = validate_audio_file(audio_file)
             issues.extend(audio_issues)

        if not issues:
             # 3. Validate actual file existence and content SHA-256.
             actual_sha256 = sha256_file(audio_file)
             if item.get('sha256') and item['sha256'] != actual_sha256:
                  issues.append("SHA256_MISMATCH")
             else:
                  item['sha256'] = actual_sha256 # set if not provided, or verified

        if issues:
            item['quarantine_reasons'] = issues
            quarantined.append(item)
        else:
            approved.append(item)

    # 12. Generate deterministic approved audio manifests.
    # Sort for determinism
    approved.sort(key=lambda x: (x.get('locale', ''), x.get('lexical_id', ''), x.get('file_path', '')))

    manifest = {
        'schema_version': '1.0.0',
        'approved_assets': approved,
        'quarantined_assets': quarantined
    }

    with output_path.open('w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    if quarantined:
        for item in quarantined:
            print(f"QUARANTINED {item.get('file_path')}: {', '.join(item['quarantine_reasons'])}")
        return 1

    return 0

def main(argv=None):
    parser = argparse.ArgumentParser(description="Audio Source-Admission Engine")
    parser.add_argument('--metadata', type=Path, required=True, help="Input metadata JSON")
    parser.add_argument('--audio-dir', type=Path, required=True, help="Directory containing audio files")
    parser.add_argument('--ledger', type=Path, required=True, help="Path to legal ledger JSON")
    parser.add_argument('--output', type=Path, required=True, help="Path to output manifest JSON")

    args = parser.parse_args(argv)

    return evaluate(args.metadata, args.audio_dir, args.ledger, args.output)

if __name__ == '__main__':
    sys.exit(main())
