"""Deterministic Open FTS5 Index Builder."""
import argparse
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


class IndexBuilderError(ValueError):
    pass


def get_tokenizer_for_language(language):
    # CJK and Thai -> trigram
    if language in ('zho', 'jpn', 'tha', 'kor'):
        return 'trigram'
    # Arabic/Hebrew -> unicode61 remove_diacritics 2
    if language in ('ara', 'heb', 'fas', 'urd'):
        return 'unicode61 remove_diacritics 2'
    # Default -> unicode61 remove_diacritics 0
    return 'unicode61 remove_diacritics 0'


def is_tokenizer_supported(tokenizer_name):
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute(f"CREATE VIRTUAL TABLE test_fts USING fts5(text, tokenize='{tokenizer_name}')")
        return True
    except sqlite3.OperationalError:
        return False


def build_index(db_path):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise IndexBuilderError(f'Input database not found: {path}')

    staged_path = path.with_suffix('.sqlite.staged')

    # Copy the database to a staged file
    shutil.copy2(path, staged_path)

    try:
        with closing(sqlite3.connect(staged_path)) as db:
            # Inspect language from lexicon
            try:
                row = db.execute('SELECT language_code FROM lexicon LIMIT 1').fetchone()
                if not row:
                    raise IndexBuilderError('Lexicon table is empty or missing language_code')
                language = row[0]
            except sqlite3.DatabaseError as e:
                raise IndexBuilderError('Invalid SQLite pack') from e
            except sqlite3.OperationalError as e:
                raise IndexBuilderError('Invalid SQLite pack: missing lexicon table') from e

            tokenizer = get_tokenizer_for_language(language)

            if not is_tokenizer_supported(tokenizer):
                raise IndexBuilderError(f'Unsupported tokenizer combination: {tokenizer}')

            # Drop old FTS table and recreate it
            db.execute('DROP TABLE IF EXISTS lexicon_fts')

            # Use same columns as original schema
            db.execute(f"CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, lemma, gloss, language_code UNINDEXED, tokenize='{tokenizer}')")

            # Repopulate from lexicon, senses, translations
            # We reconstruct the gloss identically to tools.pack_v2.pipeline to ensure deterministic output.

            # Fetch definitions and outbound translations
            definitions = {}
            for lexeme_id, definition in db.execute('SELECT lexeme_id, definition FROM senses'):
                definitions.setdefault(lexeme_id, []).append(definition)

            outbound = {}
            for lexeme_id, text in db.execute('SELECT s.lexeme_id, t.text FROM senses s JOIN translations t ON t.from_sense_id=s.sense_id'):
                outbound.setdefault(lexeme_id, []).append(text)

            lexicon = db.execute('SELECT rowid, id, surface, lemma, language_code FROM lexicon')
            for r_rowid, r_id, r_surface, r_lemma, r_lang in lexicon:
                gloss_parts = definitions.get(r_id, []) + outbound.get(r_id, [])
                gloss = ' '.join(sorted(set(gloss_parts)))
                db.execute('INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES(?, ?, ?, ?, ?)',
                           (r_rowid, r_surface, r_lemma, gloss, r_lang))

            # Re-insert integrity check row
            db.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

            # Verify indexed row counts and representative MATCH query
            expected_count = db.execute('SELECT COUNT(*) FROM lexicon').fetchone()[0]
            actual_count = db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0]
            if actual_count != expected_count:
                raise IndexBuilderError('FTS5 row count mismatch')

            # Test MATCH
            sample_word = db.execute('SELECT surface FROM lexicon ORDER BY id LIMIT 1').fetchone()
            if sample_word:
                query = '"' + sample_word[0].replace('"', '""') + '"'
                if not db.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1', (query,)).fetchone():
                    raise IndexBuilderError('FTS5 representative MATCH smoke test failed')

            db.commit()

        # Atomic replacement
        os.replace(staged_path, path)

    except Exception:
        # Clean up staged file on error
        if staged_path.exists():
            staged_path.unlink()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Deterministic Open FTS5 Index Builder')
    parser.add_argument('db_path', type=Path, help='Path to the input SQLite pack')
    args = parser.parse_args(argv)

    try:
        build_index(args.db_path)
        return 0
    except IndexBuilderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
