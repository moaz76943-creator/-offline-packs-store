import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import shutil
import tempfile
import base64
import hashlib
import gzip
import io

from tools.pack_v2.pipeline import (
    validate_document, grammar_records, make_database, check_sqlite,
    check_envelope, CONTRACT, MAPPING, FORMAT, VERSION, sha, compact, FILES
)
from tools.lexicon_sanitizer.engine import SanitizerEngine

logger = logging.getLogger(__name__)

class BuildError(Exception):
    pass

class CorpusCompiler:
    def __init__(self, workspace: Path, repo_root: Path):
        self.workspace = workspace
        self.repo_root = repo_root
        self.sanitizer = SanitizerEngine(registry_path=str(repo_root / "catalog" / "language_registry.v1.json"))

    def compile(self, source_path: Path, language: str, fixture_only: bool = False) -> tuple[Path, dict]:
        """
        Compiles a reproducible lexical package from canonical JSON source.
        Returns the path to the output .pack.gz artifact and its metadata.
        """
        try:
            logger.info(f"Starting deterministic build for {language} from {source_path}")

            # Read and parse input
            with open(source_path, 'r', encoding='utf-8') as f:
                doc = json.load(f)

            # 1. Validation and source authorization
            logger.info("Validating document and checking authorization")
            _, sources = validate_document(doc, language, self.repo_root, fixture_only)

            # 2. Grammar records
            sidecar = source_path.with_name(f"{language}.grammar.json")
            grammar = grammar_records(sidecar if sidecar.is_file() else None, language, fixture_only, self.repo_root)
            all_sources = sorted(set(sources) | {r['source']['source_id'] for r in grammar})

            # 3. Sanitization
            logger.info("Running sanitizer against source records")
            status, sanitized_doc, reason = self.sanitizer.validate_and_repair(doc)
            if status in (SanitizerEngine.STATUS_QUARANTINE, SanitizerEngine.STATUS_REVIEW_REQUIRED):
                raise BuildError(f"Sanitization rejected source: {reason}")

            # Compile only validated lexical data
            doc = sanitized_doc

            # 4. Deterministic database compilation
            db_path = self.workspace / f"{language}.sqlite"
            db_path_tmp = self.workspace / f"{language}.sqlite.tmp"

            # Delete tmp if exists
            if db_path_tmp.exists():
                db_path_tmp.unlink()

            try:
                # 7. Verify SQLite integrity, FTS5 operation and row counts.
                counts = make_database(doc, language, grammar, db_path_tmp)
                # make_database already calls check_sqlite internally but let's be explicit and run check_sqlite if we need to
                # however, check_sqlite performs PRAGMA integrity_check, foreign_key_check, user_version, metadata, tables, FTS5 smoke test

                data = db_path_tmp.read_bytes()

                # Setup envelope manifest
                info = {
                   'contractVersion': CONTRACT,
                   'schemaVersion': MAPPING,
                   'documentId': doc['document_id'],
                   'languageCode': language,
                   'languagesPresent': sorted({r['language'] for r in doc['lexemes']}),
                   'tableCounts': counts,
                   'sqliteSha256': sha(data),
                   'sourceIds': all_sources,
                   'fixtureOnly': fixture_only,
                }
                info_bytes = (compact(info) + '\n').encode()

                manifest = {
                    'packId': language,
                    'languageCode': language,
                    'version': VERSION,
                    'contractVersion': CONTRACT,
                    'schemaVersion': MAPPING,
                    'format': FORMAT,
                    'contentRows': counts['lexicon'],
                    'contentSha256': sha(data),
                    'contentMetadataSha256': sha(info_bytes),
                    'sourceIds': all_sources,
                    'fixtureOnly': fixture_only,
                }
                meta_bytes = (compact(manifest) + '\n').encode()

                content = {
                    'content/content.json': info_bytes,
                    'content/content.sqlite': data,
                    'metadata/pack.json': meta_bytes
                }

                envelope = {
                    'packId': language,
                    'version': VERSION,
                    'contractVersion': CONTRACT,
                    'schemaVersion': MAPPING,
                    'format': FORMAT,
                    'files': [{'path': p, 'contentBase64': base64.b64encode(content[p]).decode('ascii')} for p in FILES]
                }

                raw = (compact(envelope) + '\n').encode()
                check_envelope(raw, language)

                sink = io.BytesIO()
                with gzip.GzipFile(fileobj=sink, mode='wb', filename='', mtime=0, compresslevel=9) as zip_file:
                    zip_file.write(raw)

                archive = sink.getvalue()
                archive_hash = sha(archive)

                # Move successful db and create pack
                db_path_tmp.rename(db_path)

                pack_path = self.workspace / f"{language}.{archive_hash}.pack.gz"
                pack_path.write_bytes(archive)

                item = {
                  'id': language,
                  'languageCode': language,
                  'displayName': language,
                  'version': VERSION,
                  'contractVersion': CONTRACT,
                  'schemaVersion': MAPPING,
                  'format': FORMAT,
                  'bundleFormat': FORMAT,
                  'sha256': archive_hash,
                  'contentSha256': sha(data),
                  'archiveSizeBytes': len(archive),
                  'installedSizeBytes': sum(map(len, content.values())),
                  'path': str(pack_path)
                }

                logger.info(f"Successfully built {pack_path}")
                return pack_path, item

            finally:
                if db_path_tmp.exists():
                    db_path_tmp.unlink()

        except Exception as e:
            logger.error(f"Build failed: {e}")
            raise BuildError(str(e)) from e
