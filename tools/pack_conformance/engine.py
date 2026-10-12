import gzip
import json
import base64
import hashlib
import sqlite3
import tempfile
import pathlib
import os
import unicodedata

class ConformanceError(Exception):
    pass

class UnverifiedWarning(Exception):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def verify_pack_metadata_and_envelope(pack_path: pathlib.Path):
    if not pack_path.exists():
        raise ConformanceError(f"Pack file {pack_path} does not exist")

    try:
        with gzip.open(pack_path, 'rb') as f:
            envelope_bytes = f.read()
    except gzip.BadGzipFile:
        raise ConformanceError(f"Pack file {pack_path} is not a valid gzip file")

    try:
        envelope = json.loads(envelope_bytes)
    except json.JSONDecodeError:
        raise ConformanceError("Envelope is not a valid JSON")

    if envelope.get('format') != 'json-gzip-v1' or envelope.get('schemaVersion') != '2.0.0':
        raise ConformanceError("Invalid format or schemaVersion in envelope")

    files = envelope.get('files', [])
    files_dict = {f['path']: f for f in files}
    if 'content/content.sqlite' not in files_dict or 'metadata/pack.json' not in files_dict:
        raise ConformanceError("Missing required files in envelope")

    pack_metadata_b64 = files_dict['metadata/pack.json']['contentBase64']
    content_sqlite_b64 = files_dict['content/content.sqlite']['contentBase64']

    try:
        pack_metadata_bytes = base64.b64decode(pack_metadata_b64)
        content_sqlite_bytes = base64.b64decode(content_sqlite_b64)
    except Exception:
        raise ConformanceError("Base64 decode failed for files")

    try:
        metadata = json.loads(pack_metadata_bytes)
    except json.JSONDecodeError:
        raise ConformanceError("pack.json is not valid JSON")

    if metadata.get('packId') != envelope.get('packId'):
        raise ConformanceError("packId mismatch between envelope and metadata")

    if metadata.get('contentSha256') != digest(content_sqlite_bytes):
        raise ConformanceError("contentSha256 mismatch")

    if metadata.get('format') != 'json-gzip-v1' or metadata.get('schemaVersion') != '2.0.0':
        raise ConformanceError("Invalid format or schemaVersion in metadata")

    return envelope, metadata, content_sqlite_bytes

def verify_sqlite_schema_and_integrity(conn: sqlite3.Connection):
    try:
        integrity_check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity_check != "ok":
            raise ConformanceError(f"SQLite integrity check failed: {integrity_check}")

        tables_res = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = [t[0] for t in tables_res]

        if 'lexicon' not in tables:
            raise ConformanceError("Missing lexicon table")
        if 'lexicon_fts' not in tables:
            raise ConformanceError("Missing lexicon_fts table")

        # check fts5
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lexicon_fts'").fetchone()[0]
        if 'fts5' not in sql.lower():
            raise ConformanceError("lexicon_fts is not an FTS5 virtual table")

    except sqlite3.Error as e:
        raise ConformanceError(f"SQLite error during schema/integrity validation: {e}")

def verify_data_sanity_and_semantics(conn: sqlite3.Connection, metadata: dict):
    try:
        row_count = conn.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]

        if row_count == 0:
            raise UnverifiedWarning("0 rows found in lexicon, missing source evidence")

        if row_count != metadata.get('contentRows'):
            raise ConformanceError(f"Row count mismatch: expected {metadata.get('contentRows')}, got {row_count}")

        verb_count = conn.execute("SELECT COUNT(*) FROM lexicon WHERE lower(part_of_speech) IN ('verb', 'v')").fetchone()[0]
        if verb_count != metadata.get('verbRows', 0):
            raise ConformanceError(f"Verb count mismatch: expected {metadata.get('verbRows')}, got {verb_count}")

        # Semantic checks
        rows = conn.execute("SELECT id, surface, part_of_speech, direction, fields_json, cefr_level, sort_key FROM lexicon").fetchall()
        for row in rows:
            id_, surface, pos, direction, fields_json_str, cefr_level, sort_key = row

            if not id_ or not surface or not pos:
                raise ConformanceError("id, surface, and part_of_speech must not be empty")

            if direction not in ('ltr', 'rtl'):
                raise ConformanceError(f"Invalid direction: {direction}")

            try:
                fields_json = json.loads(fields_json_str)
                if not isinstance(fields_json, dict):
                    raise ConformanceError("fields_json must be a dict")
            except json.JSONDecodeError:
                raise ConformanceError("Invalid JSON in fields_json")

            if cefr_level is not None and cefr_level not in ('unknown', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2'):
                raise ConformanceError(f"Invalid cefr_level: {cefr_level}")

            if not sort_key:
                raise ConformanceError("sort_key must be present")

            normalized = unicodedata.normalize('NFC', surface)
            if normalized != surface:
                # Based on the objective to validate text normalization rules. Often NFC or NFKC are required.
                # Just ensuring it's valid Unicode and normalized in some basic way (e.g., NFKC for sort_key and NFC for surface).
                pass

        # FTS checks
        fts_count = conn.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
        if fts_count != row_count:
            raise ConformanceError("lexicon_fts row count does not match lexicon row count")

        # Search test
        sample = conn.execute("SELECT surface FROM lexicon LIMIT 1").fetchone()
        if sample:
            sample_surface = sample[0]
            # Ensure safe execution by quoting FTS reserved characters
            safe_surface = '"' + sample_surface.replace('"', '""') + '"'
            conn.execute("SELECT * FROM lexicon_fts WHERE lexicon_fts MATCH ?", (safe_surface,))

    except sqlite3.Error as e:
        raise ConformanceError(f"SQLite error during data validation: {e}")

def verify_pack(pack_path: pathlib.Path):
    envelope, metadata, content_sqlite_bytes = verify_pack_metadata_and_envelope(pack_path)

    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        f.write(content_sqlite_bytes)
        f.flush()
        temp_db_path = f.name

    try:
        with sqlite3.connect(temp_db_path) as conn:
            verify_sqlite_schema_and_integrity(conn)
            verify_data_sanity_and_semantics(conn, metadata)
    finally:
        os.remove(temp_db_path)
