import sqlite3
import json
import argparse
import unicodedata
import sys
from pathlib import Path
from tools.pack_manifest.builder import compute_sha256

class PackConformanceError(Exception):
    pass

class PackConformanceValidator:
    def __init__(self, db_path: Path, manifest_path: Path = None):
        self.db_path = Path(db_path)
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.conn = None
        self.language_code = None
        self.is_verified = True

    def validate(self):
        if not self.db_path.exists():
            raise FileNotFoundError(f"Pack not found: {self.db_path}")

        self._check_manifest_hash()

        try:
            self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            self._check_integrity()
            self._check_metadata()
            self._check_counts()
            self._check_lexicon_data()
            self._check_fts5()
        except sqlite3.Error as e:
            raise PackConformanceError(f"SQLite error: {e}")
        finally:
            if self.conn:
                self.conn.close()
        return self.is_verified

    def _check_manifest_hash(self):
        if not self.manifest_path or not self.manifest_path.exists():
            return

        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception:
            raise PackConformanceError("Invalid manifest file")

        packs = manifest.get('packs', {})
        matched_pack = None

        # Try to find our pack in manifest based on filename
        for pack_id, meta in packs.items():
            if Path(meta.get('path', '')).name == self.db_path.name:
                matched_pack = meta
                break

        if not matched_pack:
            return

        expected_sha256 = matched_pack.get('sha256')
        if expected_sha256:
            actual_sha256 = compute_sha256(self.db_path)
            if actual_sha256 != expected_sha256:
                raise PackConformanceError(f"Hash mismatch. Expected: {expected_sha256}, Actual: {actual_sha256}")

    def _check_integrity(self):
        if self.conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise PackConformanceError("SQLite integrity check failed")
        if self.conn.execute('PRAGMA foreign_key_check').fetchall():
            raise PackConformanceError("SQLite foreign-key check failed")

    def _check_metadata(self):
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if version != 2:
            raise PackConformanceError(f"Expected user_version 2, got {version}")

        metadata_rows = self.conn.execute('SELECT key, value FROM metadata').fetchall()
        metadata = dict(metadata_rows)
        if 'contract_version' not in metadata or 'mapping_version' not in metadata or 'document_id' not in metadata:
            raise PackConformanceError("Missing mandatory metadata fields")

    def _check_counts(self):
        count = self.conn.execute('SELECT COUNT(*) FROM lexicon').fetchone()[0]
        if count == 0:
            raise PackConformanceError("Pack is empty (0 lexicon rows)")

        if self.manifest_path and self.manifest_path.exists():
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            packs = manifest.get('packs', {})
            for pack_id, meta in packs.items():
                if Path(meta.get('path', '')).name == self.db_path.name:
                    declared_count = meta.get('entry_count')
                    if declared_count is not None and declared_count != count:
                        raise PackConformanceError(f"Mismatched declared count in manifest: expected {declared_count}, actual {count}")

    def _check_lexicon_data(self):
        valid_pos = {"noun", "verb", "adjective", "adverb", "pronoun", "particle", "preposition", "conjunction", "interjection", "determiner", "numeral", "classifier", "multiword", "other"}

        cursor = self.conn.cursor()
        cursor.execute('SELECT id, language_code, pos, sort_key, surface, fields_json, source_json FROM lexicon')

        for row in cursor:
            lex_id, lang, pos, sort_key, surface, fields_json, source_json = row

            if self.language_code is None:
                self.language_code = lang
            elif lang != self.language_code:
                raise PackConformanceError(f"Cross-language mislabeled package: expected {self.language_code}, got {lang}")

            if pos not in valid_pos:
                raise PackConformanceError(f"Invalid POS: {pos}")

            expected_sort = unicodedata.normalize('NFKC', surface).casefold()
            if sort_key != expected_sort:
                raise PackConformanceError(f"Invalid sort_key for {surface}: expected {expected_sort}, got {sort_key}")

            try:
                fields = json.loads(fields_json)
                if not isinstance(fields, dict):
                    raise PackConformanceError("fields_json must be a JSON object")
            except ValueError:
                raise PackConformanceError("Corrupt fields_json")

            try:
                source = json.loads(source_json)
                if not source or not source.get('publication_approved') or source.get('fixture_only'):
                    self.is_verified = False
            except ValueError:
                raise PackConformanceError("Corrupt source_json")

        for row in self.conn.execute('SELECT payload_json FROM translations'):
            try:
                payload = json.loads(row[0])
                if not isinstance(payload, dict):
                    raise PackConformanceError("translation payload_json must be a JSON object")
            except ValueError:
                raise PackConformanceError("Corrupt translation payload_json")

    def _check_fts5(self):
        try:
            sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lexicon_fts'").fetchone()
            if not sql or 'fts5' not in sql[0].lower():
                raise PackConformanceError("lexicon_fts is not an FTS5 table")
        except sqlite3.OperationalError as e:
            raise PackConformanceError(f"Incompatible or missing FTS5 index: {e}")

        try:
            self.conn.execute("SELECT * FROM lexicon_fts WHERE lexicon_fts MATCH 'test'").fetchall()
        except sqlite3.OperationalError as e:
            raise PackConformanceError(f"FTS5 query execution failed: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('db_path', type=Path, help='Path to SQLite v2 pack')
    parser.add_argument('--manifest', type=Path, help='Path to optional manifest file for hash and count verification')
    args = parser.parse_args()

    validator = PackConformanceValidator(args.db_path, args.manifest)
    try:
        is_verified = validator.validate()
        status = "VERIFIED" if is_verified else "UNVERIFIED"
        print(f"OK: Conformance validated. Status: {status}")
    except PackConformanceError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
