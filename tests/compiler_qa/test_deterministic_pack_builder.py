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

if __name__ == "__main__":
    unittest.main()
