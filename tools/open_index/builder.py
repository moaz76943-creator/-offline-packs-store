import argparse
import os
import shutil
import sqlite3
import tempfile
import sys
import json
from tools.open_index.normalization import normalize_text

def check_fts5_available(conn):
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_check USING fts5(test)")
        conn.execute("DROP TABLE _fts5_check")
        return True
    except sqlite3.OperationalError:
        return False

def check_tokenizer(conn, tokenizer):
    try:
        conn.execute(f"CREATE VIRTUAL TABLE _fts5_check USING fts5(x, tokenize='{tokenizer}')")
        conn.execute("DROP TABLE _fts5_check")
        return True
    except sqlite3.OperationalError:
        return False

def get_cjk_segmenter(conn, lang):
    if lang not in ('zh', 'ja', 'ko'):
        return None

    try:
        from tools.linguistic_extensions.cjk.engine import Segmenter

        cursor = conn.execute("SELECT id, surface, pos, script FROM lexicon WHERE language_code=?", (lang,))
        units = []
        for i, row in enumerate(cursor.fetchall()):
            units.append({
                "unit_id": f"u{i}",
                "record_id": row[0],
                "source_id": "dummy",
                "source_revision": "dummy",
                "sense_id": "dummy",
                "language": lang,
                "script": row[3],
                "surface": row[1],
                "pos": row[2],
                "approved": True
            })

        return Segmenter(lang, units)
    except ImportError:
        return None

def tokenize_cjk(text, segmenter):
    if not text or not segmenter:
        return text
    try:
        matches = segmenter.segment(text)
        return " ".join([m.raw for m in matches])
    except Exception:
        return text

def build_index(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp:
        tmp_path = tmp.name

    try:
        shutil.copy2(db_path, tmp_path)
        with sqlite3.connect(tmp_path) as conn:
            if not check_fts5_available(conn):
                raise RuntimeError("FTS5 extension is not available in sqlite3")

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lexicon'")
            if not cursor.fetchone():
                raise RuntimeError("Database does not contain 'lexicon' table")

            cursor = conn.execute("SELECT DISTINCT language_code FROM lexicon")
            langs = [row[0] for row in cursor.fetchall()]

            segmenters = {}
            for lang in langs:
                if lang in ('zh', 'ja', 'ko'):
                    seg = get_cjk_segmenter(conn, lang)
                    if seg:
                        segmenters[lang] = seg
                    else:
                        if not check_tokenizer(conn, "icu"):
                            raise RuntimeError(f"Unsupported tokenizer combination for {lang}")
                elif lang == 'th':
                    if not check_tokenizer(conn, "icu"):
                        raise RuntimeError(f"Unsupported tokenizer combination for {lang}")

            conn.execute("DROP TABLE IF EXISTS lexicon_fts")
            conn.execute("CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface, lemma, gloss, language_code UNINDEXED, tokenize='unicode61 remove_diacritics 0')")

            cursor = conn.execute("SELECT rowid, id, surface, language_code, fields_json FROM lexicon")
            lexicon_rows = cursor.fetchall()

            for row in lexicon_rows:
                rowid, lexeme_id, surface, lang, fields_json = row

                sc = conn.execute("SELECT definition FROM senses WHERE lexeme_id=?", (lexeme_id,))
                gloss_list = [r[0] for r in sc.fetchall()]
                gloss = " ".join(gloss_list)

                fields = json.loads(fields_json)
                lemma = fields.get('lemma', surface)

                norm_surface = normalize_text(surface, lang)
                norm_lemma = normalize_text(lemma, lang)
                norm_gloss = normalize_text(gloss, lang)

                if lang in segmenters:
                    seg = segmenters[lang]
                    norm_surface = tokenize_cjk(norm_surface, seg)
                    norm_lemma = tokenize_cjk(norm_lemma, seg)
                    norm_gloss = tokenize_cjk(norm_gloss, seg)

                conn.execute("INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code) VALUES (?, ?, ?, ?, ?)",
                             (rowid, norm_surface, norm_lemma, norm_gloss, lang))

            conn.execute("INSERT INTO lexicon_fts(lexicon_fts) VALUES('integrity-check')")

            if lexicon_rows:
                count = conn.execute('SELECT COUNT(*) FROM lexicon_fts').fetchone()[0]
                if count != len(lexicon_rows):
                    raise RuntimeError("Indexed row counts mismatch")

                first_lang = lexicon_rows[0][3]
                first_surface = normalize_text(lexicon_rows[0][2], first_lang)
                if first_lang in segmenters:
                    first_surface = tokenize_cjk(first_surface, segmenters[first_lang])

                if first_surface.strip():
                    query_token = first_surface.split()[0]
                    query = '"' + query_token.replace('"', '""') + '"'
                    if not conn.execute("SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT 1", (query,)).fetchone():
                        raise RuntimeError("FTS5 MATCH smoke test failed")

        shutil.move(tmp_path, db_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e

def main():
    parser = argparse.ArgumentParser(description="Deterministic Open FTS5 Index Builder")
    parser.add_argument("db_path", help="Path to the SQLite v2 database")
    args = parser.parse_args()
    build_index(args.db_path)

if __name__ == "__main__":
    main()
