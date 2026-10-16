import json
import sqlite3
import hashlib
from typing import Dict, Any, List, Tuple, Generator, Optional
import os

class CorpusDeduplicator:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                language TEXT,
                pos TEXT,
                normalized_lemma TEXT,
                original_json TEXT,
                provenance_hash TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_grouping ON records(language, pos, normalized_lemma)')
        self.conn.commit()

    def _normalize_lemma(self, lemma: str) -> str:
        """
        Normalize comparison keys without rewriting original spelling.
        Just basic lowercase to group things together, the exact comparison happens later.
        We do NOT strip diacritics or change characters, just case fold for grouping.
        """
        if not lemma:
            return ""
        return lemma.lower().strip()

    def _get_provenance_hash(self, record: Dict[str, Any]) -> str:
        """
        Hash of all source/license IDs to identify provenance exactly.
        """
        sources = set()
        for lexeme in record.get("lexemes", []):
            if "source" in lexeme and "source_id" in lexeme["source"]:
                sources.add(lexeme["source"]["source_id"])
        for sense in record.get("senses", []):
            if "source" in sense and "source_id" in sense["source"]:
                sources.add(sense["source"]["source_id"])

        # Sort to ensure deterministic hash
        sorted_sources = sorted(list(sources))
        return hashlib.sha256(json.dumps(sorted_sources).encode('utf-8')).hexdigest()

    def ingest_record(self, record: Dict[str, Any]):
        """
        Ingest a single record into the SQLite staging table for bounded grouping.
        """
        doc_id = record.get("document_id")
        if not doc_id:
            return

        # Use the first lexeme to determine group.
        # If there are multiple lexemes, we might need a more complex strategy,
        # but typical lexical records have one primary lexeme or they all share
        # language and lemma.
        lexemes = record.get("lexemes", [])
        if not lexemes:
            return

        first_lexeme = lexemes[0]
        language = first_lexeme.get("language", "")
        pos = first_lexeme.get("pos", "")
        lemma = first_lexeme.get("lemma", "")

        normalized_lemma = self._normalize_lemma(lemma)
        provenance_hash = self._get_provenance_hash(record)

        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO records (id, language, pos, normalized_lemma, original_json, provenance_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (doc_id, language, pos, normalized_lemma, json.dumps(record, ensure_ascii=False), provenance_hash))
        self.conn.commit()

    def _calculate_jaccard(self, str1: str, str2: str) -> float:
        set1 = set(str1.lower().split())
        set2 = set(str2.lower().split())
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0

        intersection = set1.intersection(set2)
        union = set1.union(set2)
        return len(intersection) / len(union)

    def _get_definitions(self, record: Dict[str, Any]) -> List[str]:
        defs = []
        for sense in record.get("senses", []):
            if "definition" in sense:
                defs.append(sense["definition"])
        return defs

    def _get_surfaces(self, record: Dict[str, Any]) -> List[str]:
        surfaces = []
        for lexeme in record.get("lexemes", []):
            if "surface" in lexeme:
                surfaces.append(lexeme["surface"])
        return surfaces

    def _get_lemmas(self, record: Dict[str, Any]) -> List[str]:
        lemmas = []
        for lexeme in record.get("lexemes", []):
            if "lemma" in lexeme:
                lemmas.append(lexeme["lemma"])
        return lemmas

    def _get_dialects(self, record: Dict[str, Any]) -> List[str]:
        dialects = []
        for lexeme in record.get("lexemes", []):
            if "dialect" in lexeme and lexeme["dialect"]:
                dialects.append(lexeme["dialect"])
        return dialects

    def _compare_records(self, rec1: Dict[str, Any], rec2: Dict[str, Any], prov_hash1: str, prov_hash2: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Compare two records and determine relationship.
        Returns (status, duplicate_info)
        status: "EXACT_DUPLICATE", "REVIEW_REQUIRED", "DISTINCT"
        """
        # Exact match of content (excluding document_id/contract_version if needed, but simplest is full match of content fields)
        # Check surfaces and lemmas for exactness to prevent merging umlauts/diacritics implicitly
        surf1 = set(self._get_surfaces(rec1))
        surf2 = set(self._get_surfaces(rec2))

        lemma1 = set(self._get_lemmas(rec1))
        lemma2 = set(self._get_lemmas(rec2))

        dialect1 = set(self._get_dialects(rec1))
        dialect2 = set(self._get_dialects(rec2))

        # If surfaces or lemmas or dialects differ, they are distinct (e.g. Müller vs Muller, or different dialects)
        if surf1 != surf2 or lemma1 != lemma2 or dialect1 != dialect2:
            return "DISTINCT", None

        # Compare definitions
        defs1 = self._get_definitions(rec1)
        defs2 = self._get_definitions(rec2)

        # If definitions are completely different, polysemy/homographs -> distinct
        if not defs1 and not defs2:
             pass # no definitions to compare
        elif len(defs1) != len(defs2):
             # Might be near duplicate or distinct. Let's check similarity.
             pass
        else:
             # Check if defs match exactly
             if sorted(defs1) == sorted(defs2):
                 # Definitions match, surfaces match.
                 # Check provenance.
                 if prov_hash1 == prov_hash2:
                     return "EXACT_DUPLICATE", {"duplicate_of": rec1["document_id"], "reason": "exact_match"}
                 else:
                     # Cross-source exact match. Needs review, don't auto-merge due to licenses.
                     return "REVIEW_REQUIRED", {"duplicate_of": rec1["document_id"], "reason": "cross_source_exact"}

        # Near duplicates by definition similarity
        max_sim = 0.0
        for d1 in defs1:
            for d2 in defs2:
                sim = self._calculate_jaccard(d1, d2)
                if sim > max_sim:
                    max_sim = sim

        if max_sim > 0.5: # Threshold for near duplicate
            return "REVIEW_REQUIRED", {"duplicate_of": rec1["document_id"], "reason": f"near_duplicate_sim_{max_sim:.2f}"}

        return "DISTINCT", None


    def process_groups(self) -> Generator[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]], None, None]:
        """
        Stream groups and yield results.
        Yields (status, record, duplicate_metadata)
        status: "CANONICAL", "DUPLICATE", "REVIEW_REQUIRED"
        """
        cursor = self.conn.cursor()
        # Deterministic ordering
        cursor.execute('''
            SELECT language, pos, normalized_lemma
            FROM records
            GROUP BY language, pos, normalized_lemma
            ORDER BY language, pos, normalized_lemma
        ''')

        groups = cursor.fetchall()
        for group in groups:
            lang, pos, norm_lemma = group['language'], group['pos'], group['normalized_lemma']

            group_cursor = self.conn.cursor()
            group_cursor.execute('''
                SELECT id, original_json, provenance_hash
                FROM records
                WHERE language = ? AND pos = ? AND normalized_lemma = ?
                ORDER BY id
            ''', (lang, pos, norm_lemma))

            records_in_group = []
            for row in group_cursor.fetchall():
                records_in_group.append({
                    "id": row['id'],
                    "json": json.loads(row['original_json']),
                    "prov": row['provenance_hash']
                })

            if len(records_in_group) == 1:
                yield "CANONICAL", records_in_group[0]["json"], None
                continue

            # Pairwise comparisons within group
            canonical_recs = []

            for item in records_in_group:
                record = item["json"]
                prov_hash = item["prov"]

                is_duplicate = False
                for can_item in canonical_recs:
                    can_record = can_item["json"]
                    can_prov = can_item["prov"]

                    status, dup_info = self._compare_records(can_record, record, can_prov, prov_hash)

                    if status == "EXACT_DUPLICATE":
                        # Record is a duplicate of can_record
                        yield "DUPLICATE", record, dup_info
                        is_duplicate = True
                        break
                    elif status == "REVIEW_REQUIRED":
                        yield "REVIEW_REQUIRED", record, dup_info
                        is_duplicate = True
                        break

                if not is_duplicate:
                    canonical_recs.append(item)
                    yield "CANONICAL", record, None

    def close(self):
        if self.conn:
            self.conn.close()
