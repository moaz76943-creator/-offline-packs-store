"""Deterministic Open FTS5 Index Builder."""
import argparse
import json
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
    if language in ('zh', 'ja', 'th', 'ko', 'zho', 'jpn', 'tha', 'kor'):
        return 'trigram'
    # Arabic/Hebrew -> unicode61 remove_diacritics 2
    if language in ('ar', 'he', 'fa', 'ur', 'ara', 'heb', 'fas', 'urd'):
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
    if not os.access(os.getcwd(), os.W_OK):
        raise IndexBuilderError('UNAUTHORIZED_WORKSPACE')
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

            lexicon = db.execute('SELECT rowid, id, surface, fields_json, language_code FROM lexicon')
            for r_rowid, r_id, r_surface, r_fields, r_lang in lexicon:
                try:
                    fields = json.loads(r_fields)
                except (TypeError, ValueError) as exc:
                    raise IndexBuilderError('Invalid lexicon fields_json') from exc
                r_lemma = fields.get('lemma') if isinstance(fields, dict) else None
                if not isinstance(r_lemma, str) or not r_lemma.strip():
                    raise IndexBuilderError('Missing or invalid lemma in fields_json')
                gloss_parts = definitions.get(r_id, []) + outbound.get(r_id, [])
                gloss = ' '.join(sorted(set(gloss_parts)))
                db.execute('INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES(?, ?, ?, ?, ?)',
                           (r_rowid, r_surface, r_lemma, gloss, r_lang))

            # Re-insert integrity check row
            if db.execute("PRAGMA integrity_check(lexicon_fts)").fetchone()[0] != 'ok':
                raise IndexBuilderError('Integrity check failed')

            # Verify indexed row counts and representative MATCH query
            expected_count = db.execute('SELECT COUNT(*) FROM lexicon').fetchone()[0]
            actual_count = db.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0]
            if actual_count != expected_count:
                raise IndexBuilderError('FTS5 row count mismatch')

            # Test MATCH
            # The trigram tokenizer indexes no one- or two-character terms.
            # Do not reject an otherwise valid CJK pack for a short first entry.
            sample_word = db.execute(
                'SELECT rowid, surface FROM lexicon '
                + ('WHERE length(surface) >= 3 ' if tokenizer == 'trigram' else '')
                + 'ORDER BY id LIMIT 1'
            ).fetchone()
            if sample_word is not None:
                query = '"' + sample_word[1].replace('"', '""') + '"'
                if not db.execute(
                    'SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1',
                    (query,)).fetchone():
                    raise IndexBuilderError('FTS5 representative MATCH smoke test failed')
            elif tokenizer == 'trigram' and expected_count > 0:
                # No searchable trigrams exist. Verify that short entries
                # remain readable without allocating a list of all lexemes.
                first_rowid = db.execute(
                    'SELECT rowid FROM lexicon ORDER BY id LIMIT 1'
                ).fetchone()[0]
                if not db.execute(
                    'SELECT 1 FROM lexicon_fts WHERE rowid=?', (first_rowid,)
                ).fetchone():
                    raise IndexBuilderError('FTS5 short-token row missing')

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
