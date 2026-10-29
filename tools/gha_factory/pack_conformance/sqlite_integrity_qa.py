#!/usr/bin/env python3
"""
SQLite Content Pack Conformance QA Tool - Master Constitution Section 08 & 09 Compliant.
Guarantees zero corrupt indexes, zero broken foreign keys, and valid v2 schema conformance.
"""
import hashlib
import os
import sqlite3
import sys

REQUIRED_CONTENT_TABLES = [
    'lexicon',
    'concepts',
    'senses',
    'translations',
    'pack_metadata',
]

def verify_pack_sqlite_conformance(db_path: str):
    if not os.path.isfile(db_path):
        return False, f"MISSING_FILE: Path '{db_path}' does not exist"

    # Compute SHA256 of candidate pack
    with open(db_path, 'rb') as f:
        sha256_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        # 1. Enforce PRAGMA foreign_keys
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # 2. Strict PRAGMA integrity_check
        cursor.execute("PRAGMA integrity_check;")
        integrity_rows = cursor.fetchall()
        if not integrity_rows or integrity_rows[0][0] != "ok":
            issues = [r[0] for r in integrity_rows]
            conn.close()
            return False, f"INTEGRITY_CHECK_FAILED: {'; '.join(issues[:3])}"

        # 3. Strict PRAGMA foreign_key_check (fail-closed if any row returned)
        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        if fk_violations:
            conn.close()
            return False, f"FOREIGN_KEY_VIOLATIONS_DETECTED: {len(fk_violations)} broken relation(s)"

        # 4. Verify required tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
        missing = [t for t in REQUIRED_CONTENT_TABLES if t not in existing_tables]
        if missing:
            conn.close()
            return False, f"MISSING_REQUIRED_TABLES: {', '.join(missing)}"

        # 5. Verify schema version and non-zero content
        cursor.execute("PRAGMA user_version;")
        user_version = cursor.fetchone()[0]
        if user_version < 2:
            conn.close()
            return False, f"INVALID_SCHEMA_VERSION: v{user_version} (Required: v2+)"

        cursor.execute("SELECT COUNT(*) FROM lexicon;")
        lex_count = cursor.fetchone()[0]
        if lex_count == 0:
            conn.close()
            return False, "EMPTY_PACK: Lexicon contains 0 entries"

        conn.close()
        return True, f"CONFORMANCE_PASSED (SHA256: {sha256_hash[:16]}..., Lexicon: {lex_count}, Version: v{user_version})"

    except Exception as e:
        return False, f"SQLITE_QA_EXCEPTION: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sqlite_integrity_qa.py <path_to_db>")
        sys.exit(1)

    passed, report = verify_pack_sqlite_conformance(sys.argv[1])
    print(f"[{'PASS' if passed else 'FAIL'}] {report}")
    sys.exit(0 if passed else 1)
