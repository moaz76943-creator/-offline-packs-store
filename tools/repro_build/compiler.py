import json
import sqlite3
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List

from tools.pack_v2.pipeline import make_database, check_sqlite, validate_document, read_json
from tools.lexicon_sanitizer.engine import SanitizerEngine

class ReproBuilder:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()

    def sha256_file(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def build(self, manifest_path: Path, output_dir: Path, fixture_only: bool = False) -> Path:
        sanitizer = SanitizerEngine()
        manifest = read_json(manifest_path)
        source_path = manifest.get('source_path')
        if not source_path:
            raise ValueError('Manifest missing source_path')

        full_source_path = (self.repo_root / source_path).resolve()
        if not full_source_path.exists():
            raise ValueError(f"Source path {full_source_path} does not exist")

        expected_hash = manifest.get('source_sha256')
        if expected_hash and self.sha256_file(full_source_path) != expected_hash:
            raise ValueError(f"Source hash mismatch for {full_source_path}")

        language = manifest.get('language')
        if not language:
            raise ValueError('Manifest missing language')

        # Load document
        doc = read_json(full_source_path)

        expected_schema_version = manifest.get('schema_version')
        if expected_schema_version and doc.get('contract_version') != expected_schema_version:
            raise ValueError(f"Schema version mismatch: expected {expected_schema_version}, got {doc.get('contract_version')}")

        # Sanitize it
        status, sanitized_doc, reason = sanitizer.validate_and_repair(doc)
        if status not in (SanitizerEngine.STATUS_ACCEPT, SanitizerEngine.STATUS_REPAIRABLE):
            raise ValueError(f"Sanitization failed: {reason}")

        doc = sanitized_doc

        # Validate document with pack_v2 validate_document
        validate_document(doc, language, self.repo_root, fixture_only=fixture_only)

        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tempdir:
            temp_db = Path(tempdir) / "temp.sqlite"

            # make_database
            try:
                counts = make_database(doc, language, [], temp_db)
                # verify sqlite integrity
                check_sqlite(temp_db, language)
            except Exception as e:
                # Retain previous artifacts on failure - do not delete existing
                raise ValueError(f"Database build failed: {e}") from e

            # Compute SHA256 of the new DB
            out_sha256 = self.sha256_file(temp_db)
            final_name = f"{language}-{out_sha256}.sqlite"
            final_path = output_dir / final_name

            # Move atomically
            shutil.move(str(temp_db), str(final_path))

            return final_path
