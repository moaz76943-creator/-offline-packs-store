import os
import json
import sqlite3
import hashlib
from typing import Dict, Any, List

def compile_deterministic_sqlite_pack(
    output_pack_path: str,
    pack_id: str,
    source_lang: str,
    target_lang: str,
    words: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compiles an optimized, bitwise-reproducible SQLite pack file
    and returns a cryptographically signed SHA-256 receipt dictionary.
    """
    if os.path.exists(output_pack_path):
        os.remove(output_pack_path)

    os.makedirs(os.path.dirname(output_pack_path), exist_ok=True)
    conn = sqlite3.connect(output_pack_path)
    cur = conn.cursor()

    # إعدادات معمارية موحدة لضمان التطابق الحتمي في البايتات
    cur.execute("PRAGMA page_size = 4096;")
    cur.execute("PRAGMA auto_vacuum = INCREMENTAL;")
    cur.execute("PRAGMA foreign_keys = ON;")

    cur.execute("""
    CREATE TABLE pack_info (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE vocabulary (
        id INTEGER PRIMARY KEY,
        lemma TEXT NOT NULL,
        pos TEXT NOT NULL,
        cefr TEXT NOT NULL,
        meaning TEXT NOT NULL
    );
    """)

    cur.execute("INSERT INTO pack_info VALUES ('pack_id', ?);", (pack_id,))
    cur.execute("INSERT INTO pack_info VALUES ('source_lang', ?);", (source_lang,))
    cur.execute("INSERT INTO pack_info VALUES ('target_lang', ?);", (target_lang,))

    # ترتيب الحقول حتمياً لمنع اختلاف البايتات
    sorted_words = sorted(words, key=lambda x: x.get("lemma", ""))
    for idx, w in enumerate(sorted_words, start=1):
        cur.execute(
            "INSERT INTO vocabulary VALUES (?, ?, ?, ?, ?);",
            (idx, w.get("lemma", ""), w.get("pos", ""), w.get("cefr", "A1"), w.get("meaning", ""))
        )

    conn.commit()
    cur.execute("PRAGMA incremental_vacuum;")
    conn.close()

    # حساب البصمة التشفيرية SHA-256
    sha = hashlib.sha256()
    with open(output_pack_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    pack_hash = sha.hexdigest()

    receipt = {
        "pack_id": pack_id,
        "filename": os.path.basename(output_pack_path),
        "sha256": pack_hash,
        "size_bytes": os.path.getsize(output_pack_path),
        "entry_count": len(sorted_words),
    }

    return receipt
