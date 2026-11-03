import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.compiler.deterministic_pack_builder import build_deterministic_pack

class TestDeterministicPackBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reproducible_sha256_across_multiple_compilations(self):
        dataset = [
            {"lemma": "Wasser", "pos": "noun", "gender": "neutrum", "senses": ["water"]},
            {"lemma": "Brot", "pos": "noun", "gender": "neutrum", "senses": ["bread"]},
            {"lemma": "essen", "pos": "verb", "gender": None, "senses": ["to eat"]},
        ]

        path_a = os.path.join(self.temp_dir.name, "pack_a.db")
        path_b = os.path.join(self.temp_dir.name, "pack_b.db")

        # Compile twice independently
        receipt_a = build_deterministic_pack(dataset, path_a, "de_a1", "kaikki_de")
        receipt_b = build_deterministic_pack(dataset, path_b, "de_a1", "kaikki_de")

        # Assert 100% identical SHA256
        self.assertEqual(receipt_a['sha256'], receipt_b['sha256'])
        self.assertEqual(receipt_a['size_bytes'], receipt_b['size_bytes'])
        self.assertEqual(receipt_a['lexicon_count'], 3)
        self.assertTrue(receipt_a['reproducible'])

    def test_shuffled_colliding_lemma_pos_records_have_same_sha(self):
        rows = [
            {"lemma": "Bank", "pos": "noun", "gender": "feminine", "senses": ["financial institution", "bank"]},
            {"lemma": "Bank", "pos": "noun", "gender": "feminine", "senses": ["bench"]},
            {"lemma": "Bank", "pos": "noun", "gender": None, "senses": ["shore"]},
            {"lemma": "Bank", "pos": "noun", "gender": "", "senses": ["savings"]},
        ]
        path_a = os.path.join(self.temp_dir.name, "colliding_a.db")
        path_b = os.path.join(self.temp_dir.name, "colliding_b.db")
        receipt_a = build_deterministic_pack(rows, path_a, "de_core", "src")
        receipt_b = build_deterministic_pack(list(reversed(rows)), path_b, "de_core", "src")
        self.assertEqual(receipt_a["sha256"], receipt_b["sha256"])

    def test_sense_order_is_canonical_across_shuffles(self):
        rows = [
            {"lemma": "Bank", "pos": "noun", "gender": "feminine", "senses": ["bench", "seat"]},
            {"lemma": "Bank", "pos": "noun", "gender": "feminine", "senses": ["finance", "institution"]},
        ]
        path_a = os.path.join(self.temp_dir.name, "senses_a.db")
        path_b = os.path.join(self.temp_dir.name, "senses_b.db")
        receipt_a = build_deterministic_pack(rows, path_a, "de_core", "src")
        shuffled = [{**item, "senses": list(reversed(item["senses"]))} for item in reversed(rows)]
        receipt_b = build_deterministic_pack(shuffled, path_b, "de_core", "src")
        self.assertEqual(receipt_a["sha256"], receipt_b["sha256"])

if __name__ == "__main__":
    unittest.main()
