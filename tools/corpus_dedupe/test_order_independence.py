import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator, get_content_hash

class TestOrderIndependence(unittest.TestCase):
    def test_senses_order_independence(self):
        rec1 = {
            "lexeme_id": "1",
            "language": "en",
            "lemma": "test",
            "pos": "noun",
            "senses": [
                {"definition": "A"},
                {"definition": "B"}
            ]
        }

        rec2 = {
            "lexeme_id": "2",
            "language": "en",
            "lemma": "test",
            "pos": "noun",
            "senses": [
                {"definition": "B"},
                {"definition": "A"}
            ]
        }

        # Their content hash must match
        h1 = get_content_hash(rec1)
        h2 = get_content_hash(rec2)
        self.assertEqual(h1, h2)

if __name__ == '__main__':
    unittest.main()
