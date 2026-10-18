import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple
import tempfile
import shutil

from tools.pack_v2.pipeline import compile_pack, check_sqlite
from tools.lexicon_sanitizer.engine import SanitizerEngine

logger = logging.getLogger(__name__)

class ReproBuilder:
    def __init__(self, workspace: Path, repo_root: Path):
        self.workspace = workspace
        self.repo_root = repo_root

    def build(self, src: Path, language: str, fixture_only: bool = False) -> Path:
        """
        Builds a deterministic pack from a source file.
        Preserves previous valid artifacts on failure by using an atomic staging file.
        """
        sanitizer = SanitizerEngine() # Instantiate per-build to clear state

        # Read the entire document
        with open(src, 'r', encoding='utf-8') as f:
            doc = json.load(f)

        # Sanitize using the validate_and_repair of SanitizerEngine
        status, repaired_doc, reason = sanitizer.validate_and_repair(doc)

        if status == SanitizerEngine.STATUS_QUARANTINE:
            raise ValueError(f"Document quarantined by sanitizer: {reason}")
        if status == SanitizerEngine.STATUS_REVIEW_REQUIRED:
            raise ValueError(f"Document requires review: {reason}")

        doc_to_compile = repaired_doc if repaired_doc else doc

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            # Write sanitized doc to a temp file for compile_pack
            temp_src = td_path / src.name
            with open(temp_src, 'w', encoding='utf-8') as f:
                json.dump(doc_to_compile, f)

            # Copy grammar sidecar if it exists
            grammar_sidecar = src.with_name(f"{language}.grammar.json")
            if grammar_sidecar.exists():
                shutil.copy(grammar_sidecar, td_path / grammar_sidecar.name)

            # compile_pack from pack_v2/pipeline.py handles:
            # - schema validation (validate_document calls jsonschema)
            # - authorization check (via approve_sources unless fixture_only)
            # - building deterministic SQLite db and metadata
            # - gzip envelope creation
            try:
                archive, item = compile_pack(temp_src, language, td_path, self.repo_root, fixture_only=fixture_only)

                # Step 7. Verify SQLite integrity, FTS5 operation and row counts.
                db_path = td_path / f"{language}.sqlite"
                if db_path.exists():
                    counts = check_sqlite(db_path, language)
                    logger.info(f"SQLite verification passed. Row counts: {counts}")
                else:
                    raise RuntimeError("SQLite database was not produced by compile_pack.")
            except Exception as e:
                # If build fails, just let the exception propagate.
                # No files in the final workspace are modified since we compiled into `td_path`.
                raise RuntimeError(f"Pack compilation failed: {e}") from e

            # Create final output file path using the SHA256 of the uncompressed database
            # Output path is addressed by sha256 to guarantee reproducibility
            sha256 = item['sha256']
            final_output = self.workspace / f"{language}-{sha256}.pack.gz"

            # Use atomic operation to write to final destination to avoid partial files
            temp_output = td_path / "final.pack.gz"
            with open(temp_output, 'wb') as f:
                f.write(archive)

            # If the output file already exists, don't overwrite it
            if not final_output.exists():
                shutil.move(temp_output, final_output)

            return final_output
