"""Regression tests for legacy agent candidates: never claim v2 or erase old bytes.

These test fixtures are synthetic, not reviewed sources or publishable packs.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agents.work import build_pack


class LegacyAgentPackSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'de.sqlite'
        self.row = {
            'language': 'de', 'concept_id': 'concept.q1',
            'lemma': 'Essen', 'source_id': 'wikidata.lexemes',
            'record_id': 'L1', 'license_id': 'CC0-1.0',
            'retrieval_date': '2026-10-18',
        }

    def test_output_is_explicitly_nonproduction_legacy_candidate(self):
        result = build_pack([self.row], self.target)
        self.assertTrue(result['wrote'])
        self.assertFalse(result.get('production_ready', True))
        receipt = json.loads(self.target.with_suffix('.sha256.json').read_text())
        self.assertEqual(receipt['format'], 'legacy-entry-candidate')
        self.assertFalse(receipt['production_ready'])
        with sqlite3.connect(self.target) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM entries').fetchone()[0], 1)

    def test_database_write_failure_keeps_exact_previous_pack_and_receipt(self):
        build_pack([self.row], self.target)
        original = self.target.read_bytes()
        receipt = self.target.with_suffix('.sha256.json').read_bytes()
        with patch('tools.agents.work.sqlite3.connect', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                build_pack([dict(self.row, lemma='Gehen')], self.target)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(self.target.with_suffix('.sha256.json').read_bytes(), receipt)
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),
                         ['de.sha256.json', 'de.sqlite'])

    def test_receipt_replace_failure_rolls_back_database(self):
        build_pack([self.row], self.target)
        original = self.target.read_bytes()
        receipt = self.target.with_suffix('.sha256.json').read_bytes()
        real_replace = os.replace

        def fail_receipt(source, dest):
            if Path(dest) == self.target.with_suffix('.sha256.json'):
                raise OSError('receipt write interrupted')
            return real_replace(source, dest)

        with patch('tools.agents.work.os.replace', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                build_pack([dict(self.row, lemma='Gehen')], self.target)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(self.target.with_suffix('.sha256.json').read_bytes(), receipt)
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),
                         ['de.sha256.json', 'de.sqlite'])

    def test_same_candidate_does_not_rewrite_database_or_receipt(self):
        build_pack([self.row], self.target)
        original = self.target.read_bytes()
        sidecar = self.target.with_suffix('.sha256.json').read_bytes()
        result = build_pack([self.row], self.target)
        self.assertFalse(result['wrote'])
        self.assertEqual(result['reason'], 'unchanged candidate')
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(self.target.with_suffix('.sha256.json').read_bytes(), sidecar)
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),
                         ['de.sha256.json', 'de.sqlite'])

    def test_untraceable_new_rows_do_not_destroy_previous_candidate(self):
        build_pack([self.row], self.target)
        original = self.target.read_bytes()
        result = build_pack([{'language': 'de', 'lemma': 'TODO'}], self.target)
        self.assertFalse(result['wrote'])
        self.assertEqual(self.target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
