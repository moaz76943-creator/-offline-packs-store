import sqlite3
import json
import unicodedata
from typing import Dict, List, Any

class CorpusDeduplicator:
    def __init__(self, db_path: str = ':memory:'):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS lexemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                language TEXT,
                pos TEXT,
                normalized_lemma TEXT,
                lexeme_id TEXT,
                record_json TEXT
            )
        ''')
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_group ON lexemes (language, pos, normalized_lemma)')

    def _normalize_lemma(self, lemma: str) -> str:
        """Strips diacritics and casefolds to group linguistic variants."""
        nfd = unicodedata.normalize('NFD', lemma)
        stripped = ''.join(c for c in nfd if not unicodedata.combining(c))
        return stripped.casefold()

    def add_record(self, record: Dict[str, Any]):
        language = record.get('language', '')
        pos = record.get('pos', '')
        lemma = record.get('lemma', '')
        normalized = self._normalize_lemma(lemma)
        lexeme_id = record.get('lexeme_id', '')

        self.conn.execute(
            'INSERT INTO lexemes (language, pos, normalized_lemma, lexeme_id, record_json) VALUES (?, ?, ?, ?, ?)',
            (language, pos, normalized, lexeme_id, json.dumps(record))
        )

    def compare(self, r1: Dict[str, Any], r2: Dict[str, Any]) -> str:
        if r1.get('lemma') != r2.get('lemma'):
            return 'DISTINCT'
        if r1.get('language') != r2.get('language'):
            return 'DISTINCT'
        if r1.get('pos') != r2.get('pos'):
            return 'DISTINCT'
        if r1.get('dialect') != r2.get('dialect'):
            return 'DISTINCT'

        def strip_keys(d, keys):
            if isinstance(d, dict):
                return {k: strip_keys(v, keys) for k, v in d.items() if k not in keys}
            elif isinstance(d, list):
                return [strip_keys(i, keys) for i in d]
            else:
                return d

        m1 = strip_keys(r1.get('morphology', {}), {'source'})
        m2 = strip_keys(r2.get('morphology', {}), {'source'})
        if m1 != m2:
            return 'DISTINCT'

        s1 = r1.get('senses', [])
        s2 = r2.get('senses', [])
        def sense_sig(s):
            return (s.get('concept_id'), s.get('definition'))

        sigs1 = {sense_sig(s) for s in s1}
        sigs2 = {sense_sig(s) for s in s2}
        if sigs1 and sigs2 and sigs1.isdisjoint(sigs2):
            return 'DISTINCT'

        def strip_for_exact(r):
            res = strip_keys(r, {'lexeme_id', 'sense_id'})
            if isinstance(res, dict) and 'senses' in res and isinstance(res['senses'], list):
                res['senses'] = sorted(res['senses'], key=lambda x: json.dumps(x, sort_keys=True))
            return res

        if json.dumps(strip_for_exact(r1), sort_keys=True) == json.dumps(strip_for_exact(r2), sort_keys=True):
            return 'EXACT_DUPLICATE'

        return 'REVIEW_REQUIRED'

    def process(self):
        """Processes groups of identical (language, pos, normalized_lemma).
        Yields (canonical_record, duplicate_relationships, review_relationships)
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT language, pos, normalized_lemma FROM lexemes')
        groups = cursor.fetchall()

        for lang, pos, n_lemma in groups:
            cursor.execute('''
                SELECT record_json FROM lexemes
                WHERE language = ? AND pos = ? AND normalized_lemma = ?
                ORDER BY lexeme_id
            ''', (lang, pos, n_lemma))

            records = [json.loads(row[0]) for row in cursor.fetchall()]

            if not records:
                continue

            canonicals = []
            for record in records:
                matched_canonical = None
                status = None
                for c_rec, duplicates, reviews in canonicals:
                    status = self.compare(c_rec, record)
                    if status != 'DISTINCT':
                        matched_canonical = (c_rec, duplicates, reviews)
                        break

                if matched_canonical is None:
                    canonicals.append((record, [], []))
                else:
                    if status == 'EXACT_DUPLICATE':
                        matched_canonical[1].append(record)
                    elif status == 'REVIEW_REQUIRED':
                        matched_canonical[2].append(record)

            for c_rec, duplicates, reviews in canonicals:
                yield c_rec, duplicates, reviews

    def close(self):
        self.conn.close()
