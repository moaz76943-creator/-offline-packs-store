import json
import sqlite3
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List

from tools.pack_v2.pipeline import make_database, check_sqlite, validate_document, read_json, MAX_JSON, grammar_records
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
        sanitizer = SanitizerEngine(registry_path=str(self.repo_root / 'catalog/language_registry.v1.json'))
        manifest = read_json(manifest_path)
        source_path = manifest.get('source_path')
        if not source_path:
            raise ValueError('Manifest missing source_path')

        full_source_path = (self.repo_root / source_path).resolve()
        if not full_source_path.exists():
            raise ValueError(f"Source path {full_source_path} does not exist")
        if not os.access(full_source_path, os.R_OK):
            raise PermissionError(f"Cannot read {full_source_path}")

        # Read source exactly once. Parse only the bytes whose digest was checked
        # so a concurrent source replacement cannot change published content.
        with full_source_path.open('rb') as stream:
            source_bytes = stream.read(MAX_JSON + 1)
        if len(source_bytes) > MAX_JSON:
            raise ValueError('Source JSON exceeds limit')
        expected_hash = manifest.get('source_sha256')
        if expected_hash and hashlib.sha256(source_bytes).hexdigest() != expected_hash:
            raise ValueError(f"Source hash mismatch for {full_source_path}")

        language = manifest.get('language')
        if not language:
            raise ValueError('Manifest missing language')

        def distinct(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError('duplicate JSON key: ' + key)
                obj[key] = value
            return obj

        doc = json.loads(
            source_bytes,
            object_pairs_hook=distinct,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError('invalid JSON numeric constant')),
        )

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

        sidecar = full_source_path.with_name(language + '.grammar.json')
        grammar = grammar_records(sidecar if sidecar.is_file() else None, language, fixture_only, self.repo_root)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Stage on the destination filesystem; os.replace stays atomic.
        with tempfile.TemporaryDirectory(dir=output_dir) as tempdir:
            temp_db = Path(tempdir) / "temp.sqlite"

            # make_database
            try:
                counts = make_database(doc, language, grammar, temp_db)
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
            os.replace(temp_db, final_path)

            return final_path
