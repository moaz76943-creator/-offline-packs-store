import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator, get_content_hash, get_provenance_hash

class TestCorpusDeduplicator(unittest.TestCase):
    def test_exact_duplicates(self):
        records = [
            {
                "lexeme_id": "id1",
                "language": "en",
                "pos": "noun",
                "lemma": "cat",
                "senses": [{"definition": "a small feline"}],
                "source": {"publisher": "pub1", "license_id": "CC0"}
            },
            {
                "lexeme_id": "id2",
                "language": "en",
                "pos": "noun",
                "lemma": "cat",
                "senses": [{"definition": "a small feline"}],
                "source": {"publisher": "pub1", "license_id": "CC0"}
            }
        ]

        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["lexeme_id"], "id1")
        self.assertEqual(deduper.get_duplicate_map(), {"id1": ["id2"]})

    def test_near_duplicates_different_provenance(self):
        records = [
            {
                "lexeme_id": "id1",
                "language": "en",
                "pos": "noun",
                "lemma": "dog",
                "senses": [{"definition": "a canine"}],
                "source": {"publisher": "pub1", "license_id": "CC0"}
            },
            {
                "lexeme_id": "id2",
                "language": "en",
                "pos": "noun",
                "lemma": "dog",
                "senses": [{"definition": "a canine"}],
                "source": {"publisher": "pub2", "license_id": "CC-BY"}
            }
        ]

        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["status"], "REVIEW_REQUIRED")
        self.assertEqual(results[1]["status"], "REVIEW_REQUIRED")

    def test_distinct_senses(self):
        records = [
            {
                "lexeme_id": "id1",
                "language": "en",
                "pos": "noun",
                "lemma": "bank",
                "senses": [{"definition": "financial institution"}],
                "source": {"publisher": "pub1", "license_id": "CC0"}
            },
            {
                "lexeme_id": "id2",
                "language": "en",
                "pos": "noun",
                "lemma": "bank",
                "senses": [{"definition": "side of a river"}],
                "source": {"publisher": "pub1", "license_id": "CC0"}
            }
        ]

        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))

        self.assertEqual(len(results), 2)
        self.assertNotIn("status", results[0])
        self.assertNotIn("status", results[1])

    def test_german_umlauts(self):
        records = [
            {"lexeme_id": "1", "language": "de", "pos": "noun", "lemma": "Apfel"},
            {"lexeme_id": "2", "language": "de", "pos": "noun", "lemma": "Äpfel"}
        ]
        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))
        self.assertEqual(len(results), 2)

    def test_arabic_diacritics(self):
        records = [
            {"lexeme_id": "1", "language": "ar", "pos": "verb", "lemma": "كَتَبَ", "source": {"p": 1}},
            {"lexeme_id": "2", "language": "ar", "pos": "verb", "lemma": "كُتِبَ", "source": {"p": 1}}
        ]
        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))
        self.assertEqual(len(results), 2)

    def test_cjk_homographs(self):
        records = [
            {"lexeme_id": "1", "language": "zh", "pos": "noun", "lemma": "花", "senses": [{"definition": "flower"}]},
            {"lexeme_id": "2", "language": "zh", "pos": "noun", "lemma": "花", "senses": [{"definition": "to spend"}]}
        ]
        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))
        self.assertEqual(len(results), 2)

if __name__ == '__main__':
    unittest.main()
