import sqlite3
from typing import Dict, Any, List, Tuple

def create_dual_projection_fts_table(conn: sqlite3.Connection):
    """
    Creates an FTS5 table with dual projections.
    Omits content='' so display_term and target_gloss are stored and readable directly.
    """
    cur = conn.cursor()
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
        display_term,
        normalized_key,
        target_gloss
    );
    """)
    conn.commit()

def index_search_term(conn: sqlite3.Connection, rowid: int, display_term: str, normalized_key: str, target_gloss: str):
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO search_fts(rowid, display_term, normalized_key, target_gloss)
    VALUES (?, ?, ?, ?);
    """, (rowid, display_term, normalized_key, target_gloss))
    conn.commit()

def execute_tolerant_search(conn: sqlite3.Connection, query_term: str, limit: int = 10) -> List[Tuple[int, str, str]]:
    clean_query = query_term.replace('"', '').replace("'", "''").strip()
    cur = conn.cursor()
    cur.execute("""
    SELECT rowid, display_term, target_gloss
    FROM search_fts
    WHERE search_fts MATCH ?
    LIMIT ?;
    """, (f'"{clean_query}"*', limit))
    return cur.fetchall()
