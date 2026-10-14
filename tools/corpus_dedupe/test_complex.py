import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator

class TestComplex(unittest.TestCase):
    def test_mixed_exact_and_near_duplicates(self):
        records = [
            {
                "lexeme_id": "1", "language": "en", "pos": "noun", "lemma": "cat",
                "source": {"publisher": "pub1"}
            },
            {
                "lexeme_id": "2", "language": "en", "pos": "noun", "lemma": "cat",
                "source": {"publisher": "pub1"}
            },
            {
                "lexeme_id": "3", "language": "en", "pos": "noun", "lemma": "cat",
                "source": {"publisher": "pub2"}
            }
        ]
        deduper = CorpusDeduplicator()
        results = list(deduper.process_stream(iter(records)))

        # We expect 2 canonical records out:
        # One from pub1 (representing 1 and 2, which are exact duplicates)
        # One from pub2
        # Both marked REVIEW_REQUIRED since they are near duplicates of each other
        self.assertEqual(len(results), 2)

        pub1_record = next(r for r in results if r["source"]["publisher"] == "pub1")
        pub2_record = next(r for r in results if r["source"]["publisher"] == "pub2")

        self.assertEqual(pub1_record["status"], "REVIEW_REQUIRED")
        self.assertEqual(pub2_record["status"], "REVIEW_REQUIRED")

        self.assertEqual(deduper.get_duplicate_map(), {"1": ["2"]})

if __name__ == '__main__':
    unittest.main()
