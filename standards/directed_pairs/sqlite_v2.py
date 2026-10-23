#!/usr/bin/env python3
"""Deterministic mapping of directed pair definitions to SQLite v2 format.
"""
import argparse
import json
import sqlite3
import sys

if __package__:
    from .validate import DirectedPairContractError, validate
else:
    from validate import DirectedPairContractError, validate

SQLITE_USER_VERSION = 2
MAPPING_VERSION = '1.0.0'
DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE directed_pairs(
  pair_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  source_language TEXT NOT NULL,
  target_language TEXT NOT NULL,
  source_sense_id TEXT NOT NULL,
  target_sense_id TEXT NOT NULL,
  source_lexeme_id TEXT NOT NULL,
  target_lexeme_id TEXT NOT NULL,
  target_text TEXT NOT NULL,
  equivalence TEXT NOT NULL,
  confidence REAL NOT NULL,
  fields_json TEXT NOT NULL
);
'''

def create_db(conn):
    conn.executescript(DDL)
    conn.execute(f'PRAGMA user_version = {SQLITE_USER_VERSION}')
    conn.execute("INSERT INTO metadata(key, value) VALUES ('directed_pairs_mapping_version', ?)", (MAPPING_VERSION,))


def map_document(doc: dict, conn: sqlite3.Connection):
    validate(doc)
    doc_id = doc["document_id"]
    source_lang = doc["source_language"]
    target_lang = doc["target_language"]

    with conn:
        for pair in doc.get("pairs", []):
            fields_json = json.dumps({
                "context": pair.get("context"),
                "domain": pair.get("domain"),
                "examples": pair.get("examples"),
                "source": pair.get("source")
            }, separators=(',', ':'))

            conn.execute('''
                INSERT INTO directed_pairs (
                  pair_id, document_id, source_language, target_language,
                  source_sense_id, target_sense_id, source_lexeme_id, target_lexeme_id,
                  target_text, equivalence, confidence, fields_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pair["pair_id"],
                doc_id,
                source_lang,
                target_lang,
                pair["source_sense_id"],
                pair["target_sense_id"],
                pair["source_lexeme_id"],
                pair["target_lexeme_id"],
                pair["target_text"],
                pair["equivalence"],
                pair["confidence"],
                fields_json
            ))


def main():
    parser = argparse.ArgumentParser(description="Map directed pairs JSON to SQLite V2.")
    parser.add_argument("input_json", help="Validated input JSON file")
    parser.add_argument("output_sqlite", help="Output SQLite database file")
    args = parser.parse_args()

    try:
        with open(args.input_json, 'r', encoding='utf-8') as f:
            data = json.load(f)

        conn = sqlite3.connect(args.output_sqlite)
        create_db(conn)
        map_document(data, conn)
        conn.close()

    except Exception as e:
        print(f"Error mapping document: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
