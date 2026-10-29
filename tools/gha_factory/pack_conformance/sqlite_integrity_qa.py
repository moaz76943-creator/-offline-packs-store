import os
import sqlite3
from typing import Tuple, List

SQLITE_HEADER_MAGIC = b"SQLite format 3\x00"

def audit_sqlite_pack(file_path: str) -> Tuple[bool, List[str]]:
    errors = []
    if not os.path.exists(file_path):
        return False, [f"File does not exist: {file_path}"]

    if os.path.getsize(file_path) < 16:
        return False, [f"File is too small to contain a valid SQLite header: {file_path}"]

    # 1. فحص هيدر SQLite السحري (أول 16 بايت)
    with open(file_path, "rb") as f:
        header = f.read(16)
        if header != SQLITE_HEADER_MAGIC:
            errors.append(f"Invalid SQLite header magic in {file_path}")

    # 2. فحص سلامة الجداول والعلاقات الخارجية
    try:
        conn = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
        cur = conn.cursor()

        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchone()
        if not res or res[0] != "ok":
            errors.append(f"Integrity check failed: {res[0] if res else 'None'}")

        cur.execute("PRAGMA foreign_key_check;")
        fk_violations = cur.fetchall()
        if fk_violations:
            errors.append(f"Foreign key violations detected: {len(fk_violations)} violation(s)")

        conn.close()
    except Exception as e:
        errors.append(f"Failed to inspect SQLite database: {str(e)}")

    return len(errors) == 0, errors
