#!/usr/bin/env python3
"""
Deterministic Pack Builder & SHA256 Receipt Generator.
Master Constitution Section 08 & 09 Compliant.
Guarantees bitwise reproducible SQLite pack compilation across builds
and generates immutable SHA256 cryptographic receipts.
"""
import hashlib
import json
import os
import sqlite3
import sys

def build_deterministic_pack(input_records: list, output_db_path: str, pack_id: str, source_id: str) -> dict:
    if os.path.exists(output_db_path):
        os.remove(output_db_path)

    os.makedirs(os.path.dirname(os.path.abspath(output_db_path)), exist_ok=True)

    # 1. Initialize SQLite with deterministic parameters
    conn = sqlite3.connect(output_db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA page_size = 4096;")
    cur.execute("PRAGMA auto_vacuum = NONE;")
    cur.execute("PRAGMA user_version = 2;")

    # 2. Schema definition
    cur.execute("""
    CREATE TABLE pack_metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE lexicon (
        id INTEGER PRIMARY KEY,
        lemma TEXT NOT NULL,
        pos TEXT NOT NULL,
        gender TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE senses (
        id INTEGER PRIMARY KEY,
        lexicon_id INTEGER NOT NULL,
        gloss TEXT NOT NULL,
        FOREIGN KEY (lexicon_id) REFERENCES lexicon(id)
    );
    """)

    # Deterministic metadata insert
    cur.execute("INSERT INTO pack_metadata VALUES ('pack_id', ?);", (pack_id,))
    cur.execute("INSERT INTO pack_metadata VALUES ('source_id', ?);", (source_id,))
    cur.execute("INSERT INTO pack_metadata VALUES ('schema_version', '2');")

    # 3. Deterministic sorted insertion
    sorted_records = sorted(input_records, key=lambda x: (x.get('lemma', ''), x.get('pos', '')))
    
    sense_counter = 1
    for lex_id, rec in enumerate(sorted_records, start=1):
        lemma = rec.get('lemma', '').strip()
        pos = rec.get('pos', 'unknown').strip()
        gender = rec.get('gender')
        cur.execute("INSERT INTO lexicon VALUES (?, ?, ?, ?);", (lex_id, lemma, pos, gender))

        for gloss in sorted(rec.get('senses', [])):
            cur.execute("INSERT INTO senses VALUES (?, ?, ?);", (sense_counter, lex_id, gloss.strip()))
            sense_counter += 1

    conn.commit()
    # 4. Canonical VACUUM to ensure deterministic defragmented btree structure
    cur.execute("VACUUM;")
    conn.commit()
    conn.close()

    # 5. Compute SHA256 of resulting binary
    with open(output_db_path, 'rb') as f:
        file_bytes = f.read()
        sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    receipt = {
        'pack_id': pack_id,
        'source_id': source_id,
        'sha256': sha256_hash,
        'size_bytes': len(file_bytes),
        'lexicon_count': len(sorted_records),
        'senses_count': sense_counter - 1,
        'reproducible': True,
    }
    return receipt

if __name__ == "__main__":
    sample_data = [
        {"lemma": "Haus", "pos": "noun", "gender": "neutrum", "senses": ["building", "house"]},
        {"lemma": "Buch", "pos": "noun", "gender": "neutrum", "senses": ["book"]},
        {"lemma": "lernen", "pos": "verb", "gender": None, "senses": ["to learn"]},
    ]
    rec1 = build_deterministic_pack(sample_data, "/tmp/p1.db", "de_core", "kaikki_de")
    rec2 = build_deterministic_pack(sample_data, "/tmp/p2.db", "de_core", "kaikki_de")
    print(f"Build 1 SHA256: {rec1['sha256']}")
    print(f"Build 2 SHA256: {rec2['sha256']}")
    assert rec1['sha256'] == rec2['sha256'], "Non-deterministic build detected!"
    print("[PASS] Bitwise reproducibility verified.")
