import argparse
import base64
import json
import sqlite3
import sys
import tempfile
import unicodedata
import re
from pathlib import Path
from contextlib import closing

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from tools.gha_factory.pack_conformance import check
from tools.pack_v2 import pipeline
from tools.gha_factory.release import candidate

VALID_POS = {"noun", "verb", "adjective", "adverb", "pronoun", "particle", "preposition",
             "conjunction", "interjection", "determiner", "numeral", "classifier", "multiword", "other"}

def run_conformance(pack_path: Path, expected_sha256: str = None):
    if not pack_path.is_file():
        raise FileNotFoundError(f"Pack not found: {pack_path}")

    blob = pack_path.read_bytes()
    try:
        raw = candidate.bounded_gzip(blob)
    except Exception as e:
        raise check.ConformanceError('ARCHIVE_CORRUPT', 'corrupted gzip')

    env = check.object_json(raw, pipeline.MAX_ENVELOPE)
    language = env.get('packId')
    if not language:
        raise check.ConformanceError('INVALID_RECEIPT', 'envelope packId missing')

    members = candidate._members(env)
    db_bytes = members.get('content/content.sqlite')
    if not db_bytes:
        raise check.ConformanceError('INVALID_RECEIPT', 'content.sqlite missing')

    info = check.object_json(members['content/content.json'])

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / 'db.sqlite'
        db_path.write_bytes(db_bytes)

        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            # 3. Validate SQLite integrity and mandatory metadata fields.
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise check.ConformanceError('SQLITE_CORRUPT', 'SQLite integrity check failed')
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise check.ConformanceError('SQLITE_CORRUPT', 'SQLite foreign key check failed')

            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            required = {'metadata', 'concepts', 'lexicon', 'senses', 'examples', 'lexicon_fts'}
            if not required.issubset(tables):
                raise check.ConformanceError('SQLITE_CORRUPT', 'SQLite v2 tables/FTS5 missing')

            # 4. Check language identity and content version consistency.
            lang_db = conn.execute("SELECT value FROM metadata WHERE key='language_code'").fetchone()
            if not lang_db or lang_db[0] != language:
                raise check.ConformanceError('LANGUAGE_ID_MISMATCH', 'Metadata language mismatch')

            # 5. Compare declared counts with real lexicon rows.
            counts = {k: conn.execute(f'SELECT count(*) FROM {k}').fetchone()[0] for k in ('concepts', 'lexicon', 'senses', 'examples')}
            if 'tableCounts' in info:
                decl = info['tableCounts']
                for k in ('concepts', 'lexicon', 'senses', 'examples'):
                    if decl.get(k) != counts[k]:
                        raise check.ConformanceError('COUNT_MISMATCH', f'Declared {k} mismatch')
            if counts['lexicon'] < 1:
                raise check.ConformanceError('INVALID_RECEIPT', 'Empty lexicon')

            # 6. Verify fields_json and translation structures.
            # 7. Validate POS and optional grammatical field semantics.
            for row in conn.execute("SELECT id, pos, part_of_speech, fields_json, language_code, surface, sort_key FROM lexicon"):
                if row[1] not in VALID_POS or row[2] not in VALID_POS:
                    raise check.ConformanceError('INVALID_POS', f"Invalid POS {row[1]} or {row[2]}")
                try:
                    fields = json.loads(row[3])
                except json.JSONDecodeError:
                    raise check.ConformanceError('INVALID_JSON', 'fields_json is invalid JSON')
                if row[4] != language:
                    raise check.ConformanceError('LANGUAGE_ID_MISMATCH', 'Cross-language lexicon contamination')

                # 10. Validate supported Unicode and text normalization rules.
                surface = row[5]
                sort_key = row[6]
                norm_surface = unicodedata.normalize('NFKC', surface).casefold()
                if norm_surface != sort_key:
                    raise check.ConformanceError('TEXT_NORMALIZATION_MISMATCH', 'Sort key does not match normalized NFKC casefold surface')

            # 8. Detect incompatible or missing FTS5 indexes.
            # 9. Run actual representative lexical search queries.
            # Use lexicon directly
            sample = conn.execute("SELECT surface FROM lexicon WHERE length(trim(surface)) > 0 LIMIT 10").fetchall()
            if sample:
                for row in sample:
                    surface = row[0]
                    # Tokenize as FTS does (unicode61)
                    tokens = re.findall(r'[^\W_]+', surface, re.UNICODE)
                    if not tokens:
                        continue
                    # Search using the FTS MATCH syntax to verify index works functionally
                    query = '"' + tokens[0].replace('"', '""') + '"'
                    res = conn.execute("SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1", (query,)).fetchone()
                    if not res:
                        raise check.ConformanceError('FTS5_CORRUPT', f'FTS5 MATCH returned no entry for {query}')

            # Translation structures
            if 'translations' in tables:
                for row in conn.execute("SELECT from_sense_id, to_sense_id, language_code, payload_json FROM translations"):
                    try:
                        payload = json.loads(row[3])
                    except json.JSONDecodeError:
                        raise check.ConformanceError('INVALID_JSON', 'translations payload is invalid JSON')

    # Finally run check.inspect to get the report and execute additional checks there
    report = check.inspect(blob, language, root=repo_root, allow_fixture=True, expected_sha256=expected_sha256)

    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pack', type=Path, required=True, help="Path to the SQLite v2 pack")
    parser.add_argument('--sha256', type=str, help="Expected SHA256 of the pack archive")
    args = parser.parse_args()

    try:
        report = run_conformance(args.pack, args.sha256)
        print(pipeline.compact(report))
        sys.exit(0)
    except check.ConformanceError as e:
        if e.code == 'PROVENANCE_MISSING':
            print(pipeline.compact({'status': 'UNVERIFIED', 'error_code': e.code, 'reason': str(e), 'publication_approved': False}))
        else:
            print(pipeline.compact({'status': 'FAIL', 'error_code': e.code, 'reason': str(e), 'publication_approved': False}))
        sys.exit(1)
    except Exception as e:
        print(pipeline.compact({'status': 'FAIL', 'error_code': 'UNKNOWN_FAILURE', 'reason': str(e), 'publication_approved': False}))
        sys.exit(1)
