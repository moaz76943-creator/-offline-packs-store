import json
import sqlite3
import unicodedata
from typing import Dict, Any, Generator, Tuple

class CorpusDeduplicator:
    def __init__(self, db_path=":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.setup_db()

    def setup_db(self):
        self.conn.executescript("""
            CREATE TABLE records (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL,
                language TEXT NOT NULL,
                pos TEXT NOT NULL,
                normalized_lemma TEXT NOT NULL,
                lemma TEXT NOT NULL,
                senses_json TEXT NOT NULL,
                source_json TEXT NOT NULL,
                full_record_json TEXT NOT NULL
            );
            CREATE INDEX idx_grouping ON records(language, pos, normalized_lemma);
        """)
        self.conn.commit()

    def normalize_lemma(self, lemma: str) -> str:
        # Normalize to NFKD to decompose characters, then casefold, then strip combining diacritics
        # This will group variations like "Mutter" / "Mütter" or Arabic diacritics together
        nfkd = unicodedata.normalize('NFKD', lemma).casefold()
        return ''.join(c for c in nfkd if not unicodedata.combining(c))

    def add_record(self, record: Dict[str, Any]):
        record_id = record.get("document_id")
        if not record_id:
            # Fallback if id is not in standard location
            record_id = record.get("id", "")

        lexemes = record.get("lexemes", [])
        if not lexemes:
            return

        # Assuming one main lexeme per record for deduplication grouping
        lexeme = lexemes[0]
        language = lexeme.get("language", "")
        pos = lexeme.get("pos", "")
        lemma = lexeme.get("lemma", "")
        if not lemma:
             lemma = lexeme.get("surface", "")

        normalized_lemma = self.normalize_lemma(lemma)

        senses = record.get("senses", [])
        # Extract meaningful sense data for comparison
        sense_data = []
        for sense in senses:
            sense_data.append({
                "concept_id": sense.get("concept_id", ""),
                "definition": sense.get("definition", "")
            })

        # Sort senses so order doesn't matter for comparison
        sense_data.sort(key=lambda s: (s["concept_id"], s["definition"]))
        senses_json = json.dumps(sense_data, sort_keys=True)

        source = lexeme.get("source", {})
        source_json = json.dumps(source, sort_keys=True)

        full_record_json = json.dumps(record, sort_keys=True)

        self.conn.execute("""
            INSERT INTO records (id, language, pos, normalized_lemma, lemma, senses_json, source_json, full_record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (record_id, language, pos, normalized_lemma, lemma, senses_json, source_json, full_record_json))

    def process_groups(self) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        # Process groups of potentially matching records
        # Yields tuples of (category, record_dict)
        # category is one of: "canonical", "duplicate", "review_required"

        # Get all distinct grouping keys
        cursor = self.conn.execute("SELECT DISTINCT language, pos, normalized_lemma FROM records ORDER BY language, pos, normalized_lemma")
        groups = cursor.fetchall()

        for group in groups:
            language, pos, normalized_lemma = group

            # Fetch all records in this group, ordered by ID for deterministic output
            group_cursor = self.conn.execute("""
                SELECT id, lemma, senses_json, source_json, full_record_json
                FROM records
                WHERE language = ? AND pos = ? AND normalized_lemma = ?
                ORDER BY id
            """, (language, pos, normalized_lemma))

            records = group_cursor.fetchall()

            if len(records) == 1:
                # Only one record in group, it is canonical
                yield ("canonical", json.loads(records[0]["full_record_json"]))
                continue

            # Multiple records. We must compare them to find canonicals, duplicates, and review required.
            canonical_records = []

            for row in records:
                current_id = row["id"]
                current_lemma = row["lemma"]
                current_senses = row["senses_json"]
                current_source = row["source_json"]
                current_full = json.loads(row["full_record_json"])

                is_duplicate = False
                is_review_required = False

                for canonical in canonical_records:
                    can_lemma = canonical["lemma"]
                    can_senses = canonical["senses_json"]
                    can_source = canonical["source_json"]

                    if current_senses == can_senses:
                        if current_lemma == can_lemma and current_source == can_source:
                            # Exact match on senses, lemma, and source -> exact duplicate
                            is_duplicate = True
                            break
                        else:
                            # Match on senses, but lemma (diacritics) or source (provenance) differ -> review required
                            is_review_required = True
                            # We don't break here, we might find an exact match later in the canonicals
                    # If senses differ, they are distinct, so it's neither duplicate nor review_required against this canonical

                if is_duplicate:
                    yield ("duplicate", current_full)
                elif is_review_required:
                    yield ("review_required", current_full)
                else:
                    # Distinct from all existing canonicals in this group, so it becomes a new canonical
                    canonical_records.append({
                        "id": current_id,
                        "lemma": current_lemma,
                        "senses_json": current_senses,
                        "source_json": current_source
                    })
                    yield ("canonical", current_full)

    def close(self):
        self.conn.close()
