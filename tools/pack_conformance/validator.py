import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

class ConformanceError(Exception):
    pass

class PackConformanceValidator:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Pack not found: {self.db_path}")

    def _connect(self):
        uri = f"file:{self.db_path.absolute()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def validate(self):
        conn = self._connect()
        try:
            self._check_integrity(conn)
            self._check_metadata(conn)
            self._check_language_identity(conn)
            self._check_fields_json(conn)
            self._check_fts5(conn)
            self._check_sort_key_normalization(conn)
        finally:
            conn.close()

    def _check_integrity(self, conn):
        try:
            # First check if it's a valid SQLite DB at all
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ConformanceError('SQLite integrity check failed')

            foreign_keys = conn.execute('PRAGMA foreign_key_check').fetchall()
            if foreign_keys:
                raise ConformanceError('SQLite foreign key check failed')
        except sqlite3.DatabaseError as e:
            raise ConformanceError(f'Database error during integrity check: {e}')

    def _check_metadata(self, conn):
        try:
            metadata = dict(conn.execute('SELECT key, value FROM metadata'))
        except sqlite3.OperationalError:
            raise ConformanceError('metadata table missing')

        if 'contract_version' not in metadata:
            raise ConformanceError('contract_version missing in metadata')
        if 'mapping_version' not in metadata:
            raise ConformanceError('mapping_version missing in metadata')
        if 'document_id' not in metadata:
            raise ConformanceError('document_id missing in metadata')

        # Check actual row count with metadata terms_count if it exists
        if 'terms_count' in metadata:
            declared_count = int(metadata['terms_count'])
            actual_count = conn.execute('SELECT count(*) FROM lexicon').fetchone()[0]
            if declared_count != actual_count:
                raise ConformanceError(f'Mismatched entry counts: declared {declared_count}, actual {actual_count}')

    def _check_language_identity(self, conn):
        try:
            langs = conn.execute('SELECT DISTINCT language_code FROM lexicon').fetchall()
        except sqlite3.OperationalError:
            raise ConformanceError('lexicon table missing')
        if len(langs) > 1:
            raise ConformanceError('Cross-language mislabeled package detected: multiple language codes in lexicon')

    def _check_fields_json(self, conn):
        try:
            rows = conn.execute('SELECT id, fields_json, source_json FROM lexicon').fetchall()
        except sqlite3.OperationalError:
            raise ConformanceError('lexicon table missing or missing required columns')

        has_source = False
        for row in rows:
            try:
                fields = json.loads(row['fields_json'])
                source = json.loads(row['source_json'])
                if source:
                    has_source = True
            except json.JSONDecodeError:
                raise ConformanceError(f"Invalid JSON in lexicon for id {row['id']}")

            # validate grammatical fields semantics / pos
            if 'pos' not in fields:
                raise ConformanceError(f"Missing pos in fields_json for id {row['id']}")

        if not has_source and len(rows) > 0:
            print("WARNING: Unverified status - absent source evidence", file=sys.stderr)

    def _check_fts5(self, conn):
        try:
            # check if lexicon_fts exists and is an fts table
            conn.execute('SELECT count(*) FROM lexicon_fts').fetchone()
        except sqlite3.OperationalError:
            raise ConformanceError("FTS5 index 'lexicon_fts' missing or corrupted")

        # Run actual representative lexical search queries to verify FTS5 works
        try:
            conn.execute("SELECT surface FROM lexicon_fts WHERE lexicon_fts MATCH 'test'").fetchall()
        except sqlite3.OperationalError as e:
             raise ConformanceError(f"FTS5 MATCH query failed: {e}")

    def _check_sort_key_normalization(self, conn):
        try:
            rows = conn.execute('SELECT id, surface, sort_key FROM lexicon').fetchall()
        except sqlite3.OperationalError:
            raise ConformanceError('lexicon table missing or missing required columns')

        for row in rows:
            expected_sort_key = unicodedata.normalize('NFKC', row['surface']).casefold()
            if row['sort_key'] != expected_sort_key:
                raise ConformanceError(f"Invalid sort_key for id {row['id']}: expected {expected_sort_key}, got {row['sort_key']}")


def main():
    parser = argparse.ArgumentParser(description="Strict conformance test suite for SQLite v2 content packs.")
    parser.add_argument("pack_path", type=Path, help="Path to the SQLite pack to validate")
    args = parser.parse_args()

    validator = PackConformanceValidator(args.pack_path)
    try:
        validator.validate()
        print("OK: SQLite pack conformance checks passed")
        sys.exit(0)
    except ConformanceError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
