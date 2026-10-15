import sqlite3
import sys
import os
import argparse
import tempfile
import shutil
import json

class BuilderError(ValueError):
    pass

def check_tokenizer(db, tokenize_str):
    try:
        db.execute(f"CREATE VIRTUAL TABLE temp_test_fts USING fts5(x, tokenize='{tokenize_str}');")
        db.execute("DROP TABLE temp_test_fts;")
        return True
    except sqlite3.OperationalError:
        return False

def build_index(db_path):
    if not os.path.exists(db_path):
        raise BuilderError("Database file not found")

    db_dir = os.path.dirname(os.path.abspath(db_path))
    if not os.access(db_dir, os.R_OK | os.W_OK):
        raise BuilderError("Workspace is inaccessible")

    # Check if FTS5 is supported in the first place
    try:
        test_db = sqlite3.connect(':memory:')
        test_db.execute("CREATE VIRTUAL TABLE temp_test_fts USING fts5(x);")
    except sqlite3.OperationalError:
        raise BuilderError("FTS5 not supported by this SQLite build")

    # Connect to the original db to check language
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as src_db:
        src_db.row_factory = sqlite3.Row
        try:
            lang_row = src_db.execute("SELECT value FROM metadata WHERE key='language_code'").fetchone()
            if not lang_row:
                raise BuilderError("Empty database metadata")
            language = lang_row['value']
        except sqlite3.OperationalError:
            raise BuilderError("Invalid database schema")

    # Select tokenizer
    # Using pipeline.py standard unicode61 remove_diacritics 0 for all cases unless specified
    # but since arabic/hebrew normalizations use standard tokenization for exact lookup, we use unicode61 remove_diacritics 0
    tokenizer = "unicode61 remove_diacritics 0"
    if language in ('zh', 'ja'):
        if check_tokenizer(test_db, "trigram"):
            tokenizer = "trigram"
        else:
            raise BuilderError(f"Unsupported language {language} without trigram tokenizer")
    elif language == 'th':
        raise BuilderError("Thai dictionary tokenization not supported natively")

    # Staging - MUST BE IN SAME DIR FOR ATOMIC REPLACE
    fd, temp_path = tempfile.mkstemp(prefix="open_index_", suffix=".sqlite", dir=db_dir)
    os.close(fd)
    shutil.copy2(db_path, temp_path)

    try:
        with sqlite3.connect(temp_path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DROP TABLE IF EXISTS lexicon_fts")

            ddl = f"CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED, tokenize='{tokenizer}');"
            db.execute(ddl)

            # Rebuild index
            query = """
            SELECT l.rowid, l.id, l.surface, l.fields_json, l.language_code,
                   IFNULL((SELECT GROUP_CONCAT(definition, ' ') FROM senses WHERE lexeme_id = l.id), '') AS defs,
                   IFNULL((SELECT GROUP_CONCAT(text, ' ') FROM translations t JOIN senses s ON t.from_sense_id = s.sense_id WHERE s.lexeme_id = l.id), '') AS trans
            FROM lexicon l
            """
            rows = []
            for row in db.execute(query):
                fields = json.loads(row[3]) if row[3] else {}
                lemma = fields.get('lemma', '')
                gloss_parts = []
                if row[5]:
                    gloss_parts.extend(row[5].split(' '))
                if row[6]:
                    gloss_parts.extend(row[6].split(' '))
                gloss = ' '.join(sorted(set(gloss_parts)))
                rows.append((row[0], row[2], lemma, gloss, row[4]))

            db.executemany("INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES (?, ?, ?, ?, ?)", rows)

            db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

            # Check counts
            lexicon_count = db.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
            fts_count = db.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
            if lexicon_count != fts_count:
                raise BuilderError("FTS5 row count mismatch")

            # representative match
            surface = db.execute("SELECT surface FROM lexicon LIMIT 1").fetchone()[0]
            # Replace single quotes or unneeded quotes for trigram compatibility
            # For CJK, trigram matching on exact strings might fail if we wrap in quotes and it is not space-separated.
            # But FTS MATCH "..." works if the exact trigrams match.
            query_str = '"' + surface.replace('"', '""') + '"'

            # Use LIKE for fallback in testing or exact syntax for MATCH
            match = db.execute("SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1", (query_str,)).fetchone()
            if not match:
                raise BuilderError("FTS5 match smoke test failed")

            db.execute("PRAGMA foreign_keys=ON")

            # verify overall schema integrity
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BuilderError("SQLite integrity_check failed")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise BuilderError("SQLite foreign_key_check failed")

        os.replace(temp_path, db_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e

def main():
    parser = argparse.ArgumentParser(description="Deterministic Open FTS5 Index Builder")
    parser.add_argument("database", help="Path to SQLite v2 pack database")
    args = parser.parse_args()

    try:
        build_index(args.database)
        print("Success")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
