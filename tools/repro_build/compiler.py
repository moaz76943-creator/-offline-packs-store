import os
import shutil
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from tools.lexicon_sanitizer.engine import SanitizerEngine
from tools.pack_v2.pipeline import make_database, validate_document

class ReproBuilder:
    def __init__(self, engine: Optional[SanitizerEngine] = None):
        if engine is None:
            self.engine = SanitizerEngine()
        else:
            self.engine = engine

    def _hash_file(self, path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, 'rb') as f:
            while chunk := f.read(8192):
                sha.update(chunk)
        return sha.hexdigest()

    def compile(self, doc: Dict[str, Any], language: str, grammar: List[Dict[str, Any]], workspace: Path, repo_root: Path, fixture_only: bool = False) -> Tuple[Path, Dict[str, int]]:
        # 1. Verify access and source-data authorization.
        # 2. Define an exact-input build manifest.
        # 3. Pin source identity, content hashes and schema version.
        validate_document(doc, language, repo_root, fixture_only)

        # 4. Run approved sanitization against staged source records.
        status, repaired_doc, reason = self.engine.validate_and_repair(doc)

        if status in (SanitizerEngine.STATUS_QUARANTINE, SanitizerEngine.STATUS_REVIEW_REQUIRED):
            raise ValueError(f"Document sanitization failed: {reason}")

        doc_to_compile = repaired_doc if repaired_doc else doc

        # Check if empty sources (after sanitization, perhaps?)
        if not doc_to_compile.get('lexemes'):
            raise ValueError('Empty sources are not allowed')

        output_name = f"{language}.sqlite"
        temp_output = workspace / f"temp_{output_name}"
        final_output = workspace / output_name

        backup_path = None
        if final_output.exists():
            backup_path = workspace / f"{output_name}.bak"
            shutil.copy2(final_output, backup_path)

        try:
            # 5. Compile only validated lexical data.
            # 6. Preserve grammatical and directed-pair metadata.
            # 7. Verify SQLite integrity, FTS5 operation and row counts.
            counts = make_database(doc_to_compile, language, grammar, temp_output)

            # 8. Generate content-addressed output artifact names.
            # 9. Ensure output is reproducible from the same input.
            content_hash = self._hash_file(temp_output)
            content_addressed_name = f"{language}_{content_hash[:8]}.sqlite"
            content_addressed_path = workspace / content_addressed_name

            shutil.copy2(temp_output, content_addressed_path)
            shutil.move(temp_output, final_output)

            # Remove backup on success
            if backup_path and backup_path.exists():
                backup_path.unlink()

            return content_addressed_path, counts
        except Exception as e:
            # 10. Preserve previous valid artifacts if the build fails.
            if temp_output.exists():
                temp_output.unlink()
            if backup_path and backup_path.exists():
                shutil.move(backup_path, final_output)
            raise e
