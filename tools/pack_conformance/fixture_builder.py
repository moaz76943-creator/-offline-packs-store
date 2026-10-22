import json
import sqlite3
import os
import shutil
from pathlib import Path
from standards.lexical.sqlite_v2 import build

FIXTURES_DIR = Path("tools/pack_conformance/fixtures")

def get_base_document():
    return {
        "contract_version": "1.0.0",
        "document_id": "fixture_doc",
        "lexemes": [
            {
                "lexeme_id": "lex1",
                "surface": "hello",
                "lemma": "hello",
                "pos": "noun",
                "direction": "ltr",
                "language": "eng",
                "script": "Latn",
                "source": {
                    "source_id": "test", "retrieval_id": "test",
                    "publication_approved": True, "origin_url": "https://test",
                    "publisher": "test", "dataset_version": "1.0",
                    "license_id": "CC0", "record_locator": "123",
                    "fixture_only": False
                }
            }
        ],
        "senses": [
            {
                "sense_id": "sense1",
                "lexeme_id": "lex1",
                "concept_id": "concept1",
                "definition": "a greeting",
                "source": {
                    "source_id": "test", "retrieval_id": "test",
                    "publication_approved": True, "origin_url": "https://test",
                    "publisher": "test", "dataset_version": "1.0",
                    "license_id": "CC0", "record_locator": "123",
                    "fixture_only": False
                }
            }
        ],
        "translations": [],
        "examples": [],
        "relations": []
    }

def create_valid_pack():
    doc = get_base_document()
    build(doc, FIXTURES_DIR / "valid.db")

def create_unverified_pack():
    doc = get_base_document()
    doc["lexemes"][0]["source"]["fixture_only"] = True
    doc["senses"][0]["source"]["fixture_only"] = True
    build(doc, FIXTURES_DIR / "unverified.db")

def create_empty_pack():
    doc = get_base_document()
    doc["lexemes"] = []
    doc["senses"] = []
    build(doc, FIXTURES_DIR / "empty.db")

def create_corrupt_schema_pack():
    doc = get_base_document()
    db_path = FIXTURES_DIR / "corrupt_schema.db"
    build(doc, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE lexicon SET pos = 'invalidpos'")
    conn.commit()
    conn.close()

def create_corrupt_json_pack():
    doc = get_base_document()
    db_path = FIXTURES_DIR / "corrupt_json.db"
    build(doc, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE lexicon SET fields_json = '{bad_json'")
    conn.commit()
    conn.close()

def create_mismatched_lang_pack():
    doc = get_base_document()
    doc["lexemes"].append({
        "lexeme_id": "lex2",
        "surface": "hola",
        "lemma": "hola",
        "pos": "noun",
        "direction": "ltr",
        "language": "spa",
        "script": "Latn",
        "source": doc["lexemes"][0]["source"]
    })
    doc["senses"].append({
        "sense_id": "sense2",
        "lexeme_id": "lex2",
        "concept_id": "concept1",
        "definition": "un saludo",
        "source": doc["senses"][0]["source"]
    })
    build(doc, FIXTURES_DIR / "mismatched_lang.db")

def create_missing_fts_pack():
    doc = get_base_document()
    db_path = FIXTURES_DIR / "missing_fts.db"
    build(doc, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE lexicon_fts")
    conn.commit()
    conn.close()

def create_missing_metadata_pack():
    doc = get_base_document()
    db_path = FIXTURES_DIR / "missing_metadata.db"
    build(doc, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM metadata WHERE key = 'contract_version'")
    conn.commit()
    conn.close()

def build_all():
    if FIXTURES_DIR.exists():
        shutil.rmtree(FIXTURES_DIR)
    FIXTURES_DIR.mkdir(parents=True)

    create_valid_pack()
    create_unverified_pack()
    create_empty_pack()
    create_corrupt_schema_pack()
    create_corrupt_json_pack()
    create_mismatched_lang_pack()
    create_missing_fts_pack()
    create_missing_metadata_pack()

if __name__ == "__main__":
    build_all()
