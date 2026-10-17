import gzip
import json
import base64
import sqlite3
import pathlib
import os

from .engine import digest

def generate_pack(path: pathlib.Path, envelope_override: dict = None, metadata_override: dict = None, db_setup_override = None, skip_fts: bool = False, raw_envelope_override: bytes = None):
    # Default schema mapping based on tools/compile_store_packs.py

    db_path = path.parent / f"{path.stem}.sqlite"

    conn = sqlite3.connect(db_path)

    if db_setup_override:
        db_setup_override(conn)
    else:
        conn.execute('''CREATE TABLE lexicon (
            id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
            direction TEXT NOT NULL, fields_json TEXT NOT NULL,
            cefr_level TEXT, frequency_rank INTEGER, sort_key TEXT
        )''')

        if not skip_fts:
            conn.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, translation_ar, tokenize='trigram')")

        conn.execute("INSERT INTO lexicon VALUES ('1', 'hello', 'noun', 'ltr', '{}', 'A1', 1, 'hello')")
        conn.execute("INSERT INTO lexicon VALUES ('2', 'run', 'verb', 'ltr', '{}', 'A1', 2, 'run')")

        if not skip_fts:
            conn.execute("INSERT INTO lexicon_fts(rowid, surface, translation_ar) VALUES (1, 'hello', 'marhaba')")
            conn.execute("INSERT INTO lexicon_fts(rowid, surface, translation_ar) VALUES (2, 'run', 'yajri')")
            conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

        conn.execute("PRAGMA user_version=2")
        conn.commit()

    conn.close()

    db_bytes = db_path.read_bytes()
    os.remove(db_path)
    content_hash = digest(db_bytes)

    metadata = {
        'packId': 'en', 'languageCode': 'en', 'displayName': 'English',
        'version': '1.0.0', 'contractVersion': '1.0.0', 'bundleFormat': 'json-gzip-v1',
        'schemaVersion': '2.0.0', 'format': 'json-gzip-v1',
        'contentSha256': content_hash, 'contentRows': 2, 'verbRows': 1
    }
    if metadata_override:
        metadata.update(metadata_override)

    metadata_bytes = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode('utf-8')

    envelope = {
        'packId': 'en', 'version': '1.0.0', 'contractVersion': '1.0.0',
        'schemaVersion': '2.0.0', 'format': 'json-gzip-v1',
        'files': [
            {'path': 'content/content.sqlite', 'contentBase64': base64.b64encode(db_bytes).decode('ascii')},
            {'path': 'metadata/pack.json', 'contentBase64': base64.b64encode(metadata_bytes).decode('ascii')},
        ]
    }
    if envelope_override:
        envelope.update(envelope_override)

    if raw_envelope_override is not None:
        envelope_bytes = raw_envelope_override
    else:
        envelope_bytes = json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')

    with gzip.open(path, 'wb') as f:
        f.write(envelope_bytes)
