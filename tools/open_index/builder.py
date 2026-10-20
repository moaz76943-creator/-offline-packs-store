#!/usr/bin/env python3
"""Deterministic Open FTS5 Index Builder

Implement reproducible local FTS5 indexing for approved multilingual SQLite v2 corpora.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

def get_tokenizer_for_language(lang_code):
    """Return the tokenizer strategy based on the language code."""
    cjk_thai = {'zho', 'jpn', 'kor', 'tha'}
    arabic_hebrew = {'ara', 'heb'}

    if lang_code in cjk_thai:
        return 'trigram'
    elif lang_code in arabic_hebrew:
        return 'unicode61 remove_diacritics 2'
    return 'unicode61 remove_diacritics 0'

def verify_tokenizer(conn, tokenizer):
    """Check if the given tokenizer is available in sqlite3."""
    try:
        conn.execute(f"CREATE VIRTUAL TABLE _test_fts USING fts5(x, tokenize='{tokenizer}')")
        conn.execute("DROP TABLE _test_fts")
        return True
    except sqlite3.Error:
        return False

def build_index(input_db):
    """Build FTS5 indexes on a staged database copy."""
    input_path = Path(input_db)
    if not input_path.exists():
        raise FileNotFoundError(f"Input database not found: {input_db}")

    staged_db = input_path.with_suffix('.staged.sqlite')
    shutil.copy2(input_path, staged_db)

    conn = None
    try:
        conn = sqlite3.connect(staged_db)

        # Check if the database has the expected schema
        try:
            conn.execute("SELECT 1 FROM lexicon LIMIT 1")
            conn.execute("SELECT 1 FROM lexicon_fts LIMIT 1")
        except sqlite3.Error:
            raise ValueError("Database missing required 'lexicon' or 'lexicon_fts' tables")

        cursor = conn.execute("SELECT language_code, COUNT(*) FROM lexicon GROUP BY language_code ORDER BY COUNT(*) DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            raise ValueError("No lexicon records found to determine language")

        predominant_lang = row[0]
        tokenizer = get_tokenizer_for_language(predominant_lang)

        if not verify_tokenizer(conn, tokenizer):
            raise ValueError(f"Unsupported tokenizer combination: {tokenizer}")

        conn.execute("CREATE TABLE _temp_fts_data AS SELECT rowid, surface, lemma, gloss, language_code FROM lexicon_fts")
        original_count = conn.execute("SELECT COUNT(*) FROM _temp_fts_data").fetchone()[0]

        conn.execute("DROP TABLE lexicon_fts")

        conn.execute(f'''
            CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                surface, lemma, gloss, language_code UNINDEXED,
                tokenize='{tokenizer}'
            )
        ''')

        conn.execute('''
            INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code)
            SELECT rowid, surface, lemma, gloss, language_code FROM _temp_fts_data
        ''')

        new_count = conn.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
        if original_count != new_count:
            raise ValueError(f"Index count mismatch: expected {original_count}, got {new_count}")

        conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

        # We perform a representative MATCH query just to verify no crash occurs and functionality is intact.
        # We'll just fetch one row that exists and query for it.
        sample_row = conn.execute("SELECT surface FROM _temp_fts_data LIMIT 1").fetchone()
        if sample_row and sample_row[0]:
            # We don't assert length > 0 because trigram match on < 3 chars might yield 0,
            # or remove_diacritics might yield 0.
            # We just execute to ensure no sqlite3.Error is thrown.
            # For CJK, trigram requires length >= 3 for exact matches sometimes, but we just verify it doesn't throw.
            surface = sample_row[0].replace("'", "''")
            conn.execute(f"SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH '{surface}'").fetchall()

        conn.execute("DROP TABLE _temp_fts_data")

        conn.commit()
    except Exception as e:
        if conn:
            conn.close()
            conn = None
        if staged_db.exists():
            staged_db.unlink()
        raise e
    finally:
        if conn:
            conn.close()

    staged_db.replace(input_path)
    return input_path

def main():
    parser = argparse.ArgumentParser(description="Deterministic Open FTS5 Index Builder")
    parser.add_argument("input_db", type=Path, help="Path to the SQLite v2 corpus")

    args = parser.parse_args()

    try:
        build_index(args.input_db)
        print("OK")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
