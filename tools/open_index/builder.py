"""
Deterministic Open FTS5 Index Builder
"""
import sqlite3
import argparse
import shutil
import os
import contextlib

def check_fts5_support(conn):
    try:
        conn.execute("CREATE VIRTUAL TABLE fts5_test USING fts5(test)")
        conn.execute("DROP TABLE fts5_test")
        return True
    except sqlite3.OperationalError:
        return False

def check_tokenizer_support(conn, tokenizer_name):
    try:
        conn.execute(f"CREATE VIRTUAL TABLE fts5_tok_test USING fts5(test, tokenize='{tokenizer_name}')")
        conn.execute("DROP TABLE fts5_tok_test")
        return True
    except sqlite3.OperationalError:
        return False

def get_unicode61_tokenizer():
    # Arabic/Hebrew normalization using approved rules: remove_diacritics 2
    return "unicode61 remove_diacritics 2"

def build_index(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database {db_path} not found.")

    staged_db = db_path + ".staged"
    shutil.copyfile(db_path, staged_db)

    success = False
    try:
        with contextlib.closing(sqlite3.connect(staged_db)) as conn:
            # Verify valid SQLite
            try:
                conn.execute("SELECT 1 FROM sqlite_master").fetchone()
            except sqlite3.DatabaseError:
                raise ValueError(f"Invalid SQLite database: {db_path}")

            if not check_fts5_support(conn):
                raise ValueError("FTS5 is not supported by the SQLite build.")

            if not check_tokenizer_support(conn, 'trigram'):
                raise ValueError("Unsupported tokenizer combination: 'trigram' is required for CJK/Thai but not available.")

            cursor = conn.cursor()

            cursor.execute("DROP TABLE IF EXISTS lexicon_fts")
            cursor.execute("DROP TABLE IF EXISTS lexicon_fts_cjk")

            tokenizer_unicode = get_unicode61_tokenizer()

            # Create FTS table for unicode61 (Arabic, Hebrew, Latin, etc.)
            cursor.execute(f"""
            CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                id UNINDEXED,
                surface,
                language_code UNINDEXED,
                tokenize='{tokenizer_unicode}'
            )
            """)

            # Create FTS table for trigram (CJK, Thai)
            cursor.execute("""
            CREATE VIRTUAL TABLE lexicon_fts_cjk USING fts5(
                id UNINDEXED,
                surface,
                language_code UNINDEXED,
                tokenize='trigram'
            )
            """)

            # Streaming the data to avoid memory issues on large databases
            cursor.execute("SELECT id, surface, language_code FROM lexicon")

            cjk_langs = {'zho', 'jpn', 'kor', 'tha'}

            unicode_count = 0
            cjk_count = 0

            unicode_batch = []
            cjk_batch = []
            batch_size = 10000

            while True:
                row = cursor.fetchone()
                if row is None:
                    break

                if row[2] in cjk_langs:
                    cjk_batch.append(row)
                    cjk_count += 1
                else:
                    unicode_batch.append(row)
                    unicode_count += 1

                if len(unicode_batch) >= batch_size:
                    cursor.executemany("INSERT INTO lexicon_fts(id, surface, language_code) VALUES (?, ?, ?)", unicode_batch)
                    unicode_batch.clear()

                if len(cjk_batch) >= batch_size:
                    cursor.executemany("INSERT INTO lexicon_fts_cjk(id, surface, language_code) VALUES (?, ?, ?)", cjk_batch)
                    cjk_batch.clear()

            if unicode_batch:
                cursor.executemany("INSERT INTO lexicon_fts(id, surface, language_code) VALUES (?, ?, ?)", unicode_batch)
            if cjk_batch:
                cursor.executemany("INSERT INTO lexicon_fts_cjk(id, surface, language_code) VALUES (?, ?, ?)", cjk_batch)

            conn.commit()

            # Verify indexed row counts
            actual_u = cursor.execute("SELECT COUNT(*) FROM lexicon_fts").fetchone()[0]
            actual_c = cursor.execute("SELECT COUNT(*) FROM lexicon_fts_cjk").fetchone()[0]
            if actual_u != unicode_count or actual_c != cjk_count:
                raise ValueError("Row count verification failed")

            # Verify representative MATCH queries using standard SELECT
            if unicode_count > 0:
                cursor.execute("SELECT * FROM lexicon_fts WHERE lexicon_fts MATCH 'test' LIMIT 1").fetchall()
            if cjk_count > 0:
                cursor.execute("SELECT * FROM lexicon_fts_cjk WHERE lexicon_fts_cjk MATCH 'test' LIMIT 1").fetchall()

        success = True
    finally:
        if success:
            os.replace(staged_db, db_path)
        elif os.path.exists(staged_db):
            os.remove(staged_db)

def main():
    parser = argparse.ArgumentParser(description="Deterministic Open FTS5 Index Builder")
    parser.add_argument("db_path", help="Path to SQLite pack")
    args = parser.parse_args()
    build_index(args.db_path)

if __name__ == "__main__":
    main()
