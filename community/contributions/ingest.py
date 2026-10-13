#!/usr/bin/env python3
import argparse
import gzip
import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

# Add project root to sys.path to allow imports from standards
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from standards.lexical.validate import validate as validate_lexical, LexicalContractError
from legal.ledger.admission import LICENSES

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_UNCOMPRESSED_SIZE = 250 * 1024 * 1024  # 250 MB
ALLOWED_EXTENSIONS = {'.json', '.jsonl', '.gz', '.zip', '.tar.gz', '.tgz'}

# Set up directories
BASE_DIR = Path(__file__).resolve().parent
STAGED_DIR = BASE_DIR / 'staged'
QUARANTINE_DIR = BASE_DIR / 'quarantined'
STAGED_DIR.mkdir(exist_ok=True)
QUARANTINE_DIR.mkdir(exist_ok=True)
MANIFEST_FILE = STAGED_DIR / 'manifest.json'

# Set up logging with specific format
logger = logging.getLogger("ingest")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(handler)

def get_hash(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def check_file_limits(filepath: Path):
    if not filepath.exists() or not filepath.is_file():
        raise ValueError(f"File not found: {filepath}")

    size = filepath.stat().st_size
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File size {size} exceeds maximum {MAX_FILE_SIZE}")

    ext = ''.join(filepath.suffixes)
    if not any(filepath.name.endswith(e) for e in ALLOWED_EXTENSIONS):
        raise ValueError(f"Unsupported file extension: {filepath.name}")

def extract_bundle(filepath: Path, extract_dir: Path):
    name = filepath.name
    total_size = 0
    if name.endswith('.zip'):
        with zipfile.ZipFile(filepath, 'r') as zf:
            for info in zf.infolist():
                if info.file_size > MAX_UNCOMPRESSED_SIZE or (total_size + info.file_size) > MAX_UNCOMPRESSED_SIZE:
                    raise ValueError("Zip bomb detected")
                if ".." in info.filename or info.filename.startswith("/"):
                    raise ValueError("Path traversal detected in zip")
                if info.filename.endswith(('.exe', '.sh', '.bat', '.py')):
                    raise ValueError(f"Unsupported executable payload in zip: {info.filename}")
                total_size += info.file_size
            zf.extractall(extract_dir)
    elif name.endswith('.tar.gz') or name.endswith('.tgz'):
        with tarfile.open(filepath, 'r:gz') as tf:
            for info in tf.getmembers():
                if info.size > MAX_UNCOMPRESSED_SIZE or (total_size + info.size) > MAX_UNCOMPRESSED_SIZE:
                    raise ValueError("Tar bomb detected")
                if ".." in info.name or info.name.startswith("/"):
                    raise ValueError("Path traversal detected in tar")
                if info.name.endswith(('.exe', '.sh', '.bat', '.py')):
                    raise ValueError(f"Unsupported executable payload in tar: {info.name}")
                total_size += info.size
            tf.extractall(extract_dir)
    elif name.endswith('.gz'):
        with gzip.open(filepath, 'rb') as gf:
            out_path = extract_dir / filepath.stem
            with open(out_path, 'wb') as out_f:
                while True:
                    chunk = gf.read(4096)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_UNCOMPRESSED_SIZE:
                        raise ValueError("Gzip bomb detected")
                    out_f.write(chunk)
    else:
        # direct copy
        shutil.copy2(filepath, extract_dir / name)

def get_valid_languages():
    repo_root = Path(__file__).resolve().parent.parent.parent
    registry_path = repo_root / 'catalog' / 'content_readiness.v1.json'
    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
            return set(registry.get('states', {}).keys())
    except Exception as e:
        raise RuntimeError(f"Failed to load language registry: {e}")

def validate_submission_data(data: dict, valid_languages: set):
    # This validates the schema and checks for duplicate IDs using standards/lexical/validate.py
    try:
        validate_lexical(data, publication=False)
    except LexicalContractError as e:
        raise ValueError(f"Lexical validation failed: {e}")

    # Extra validation for languages and licenses
    index = {
        'lexemes': {rec['lexeme_id']: rec for rec in data.get('lexemes', [])},
        'senses': {rec['sense_id']: rec for rec in data.get('senses', [])}
    }

    for lexeme in data.get('lexemes', []):
        if lexeme.get('language') not in valid_languages:
            raise ValueError(f"Unknown language ID: {lexeme.get('language')} for lexeme {lexeme.get('lexeme_id')}")
        src = lexeme.get('source', {})
        lid = src.get('license_id')
        if lid not in LICENSES:
            raise ValueError(f"Unsupported or forged license {lid} for lexeme {lexeme.get('lexeme_id')}")

    for translation in data.get('translations', []):
        lang = translation.get('language')
        if lang not in valid_languages:
            raise ValueError(f"Unknown language ID: {lang} for translation {translation.get('translation_id')}")
        src = translation.get('source', {})
        lid = src.get('license_id')
        if lid not in LICENSES:
            raise ValueError(f"Unsupported or forged license {lid} for translation {translation.get('translation_id')}")

        target = index['lexemes'][index['senses'][translation['to_sense_id']]['lexeme_id']]
        source_lexeme = index['lexemes'][index['senses'][translation['from_sense_id']]['lexeme_id']]

        # Checking for reversed pair
        if source_lexeme['language'] == target['language']:
            raise ValueError(f"Reversed or self translation: {translation.get('translation_id')}")
        if target['language'] != lang:
            raise ValueError(f"Target language mismatch in translation {translation.get('translation_id')}: {target['language']} != {lang}")

    for example in data.get('examples', []):
        lang = example.get('language')
        if lang not in valid_languages:
            raise ValueError(f"Unknown language ID: {lang} for example {example.get('example_id')}")
        src = example.get('source', {})
        lid = src.get('license_id')
        if lid not in LICENSES:
            raise ValueError(f"Unsupported or forged license {lid} for example {example.get('example_id')}")

def parse_and_validate_file(filepath: Path, valid_languages: set):
    try:
        # Check unicode integrity
        content = filepath.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise ValueError("Malformed Unicode in file")

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format")

    validate_submission_data(data, valid_languages)
    return data

def update_manifest(file_hash: str, filename: str):
    manifest = {}
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

    if file_hash in manifest:
        return False

    manifest[file_hash] = {
        'filename': filename,
        'status': 'accepted'
    }

    # Atomic write
    temp_manifest = MANIFEST_FILE.with_suffix('.tmp')
    with open(temp_manifest, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    temp_manifest.replace(MANIFEST_FILE)
    return True

def stage_file(filepath: Path, file_hash: str):
    dest_path = STAGED_DIR / f"{file_hash}_{filepath.name}"
    shutil.copy2(filepath, dest_path)
    return dest_path

def quarantine_file(filepath: Path, file_hash: str, reason: str):
    dest_path = QUARANTINE_DIR / f"{file_hash}_{filepath.name}"
    shutil.copy2(filepath, dest_path)

    reason_file = dest_path.with_suffix(dest_path.suffix + '.reason.txt')
    with open(reason_file, 'w', encoding='utf-8') as f:
        f.write(reason)
    return dest_path

def is_already_processed(file_hash: str):
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
            return file_hash in manifest
    return False

def main():
    parser = argparse.ArgumentParser(description="Ingest community contributions")
    parser.add_argument('file', type=Path, help='Path to the contribution bundle')
    args = parser.parse_args()

    file_hash = ''
    try:
        check_file_limits(args.file)
        file_hash = get_hash(args.file)

        if is_already_processed(file_hash):
            logger.info(f"File {args.file.name} (hash {file_hash}) already processed. Skipping.")
            return 0

        valid_languages = get_valid_languages()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            extract_bundle(args.file, temp_path)

            for file_in_bundle in temp_path.rglob('*'):
                if file_in_bundle.suffix not in ['.json', '.jsonl']:
                    continue
                if file_in_bundle.is_file():
                    parse_and_validate_file(file_in_bundle, valid_languages)

            # If we reach here, it's valid
            stage_file(args.file, file_hash)
            update_manifest(file_hash, args.file.name)
            logger.info("Bundle validated and staged successfully")

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        if file_hash:
            quarantine_file(args.file, file_hash, str(e))
        return 1
    return 0

if __name__ == '__main__':
    exit(main())
