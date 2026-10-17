import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator

class TestCorpusDeduplicator(unittest.TestCase):
    def setUp(self):
        self.engine = CorpusDeduplicator(":memory:")

    def tearDown(self):
        self.engine.close()

    def _process(self):
        canonical = []
        duplicate = []
        review = []
        for cat, rec in self.engine.process_groups():
            if cat == "canonical":
                canonical.append(rec)
            elif cat == "duplicate":
                duplicate.append(rec)
            elif cat == "review_required":
                review.append(rec)
        return canonical, duplicate, review

    def test_exact_duplicate(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "A trial"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "A trial"}]
        }
        self.engine.add_record(rec1)
        self.engine.add_record(rec2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 1)
        self.assertEqual(len(rev), 0)
        self.assertEqual(can[0]["document_id"], "doc1")
        self.assertEqual(dup[0]["document_id"], "doc2")

    def test_polysemy(self):
        # Same word, different meanings -> both canonical
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "bank", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "River edge"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "bank", "source": {"provenance": "B"}}],
            "senses": [{"concept_id": "c2", "definition": "Financial institution"}]
        }
        self.engine.add_record(rec1)
        self.engine.add_record(rec2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_cross_source_duplicate(self):
        # Same word, same meaning, different source -> review required
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "A trial"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "source": {"provenance": "B"}}],
            "senses": [{"concept_id": "c1", "definition": "A trial"}]
        }
        self.engine.add_record(rec1)
        self.engine.add_record(rec2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 1)

    def test_german_umlauts(self):
        # Mutter vs Mütter - same normalized key, but distinct senses so they are distinct
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Mutter", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "mother (singular)"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Mütter", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c2", "definition": "mothers (plural)"}]
        }
        self.engine.add_record(rec1)
        self.engine.add_record(rec2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_german_umlauts_review(self):
        # Same senses, different diacritics -> review required
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Mutter", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "mother (singular)"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Muetter", "source": {"provenance": "A"}}], # Just illustrative, might not NFKD to same depending on mapping, but let's assume Arabic diacritics. Let's use actual diacritics.
            "senses": [{"concept_id": "c1", "definition": "mother (singular)"}]
        }

        # Let's use a clear Arabic example for diacritics where NFKD strips it
        rec_ar1 = {
            "document_id": "doc3",
            "lexemes": [{"language": "ar", "pos": "noun", "lemma": "كِتَاب", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c3", "definition": "book"}]
        }
        rec_ar2 = {
            "document_id": "doc4",
            "lexemes": [{"language": "ar", "pos": "noun", "lemma": "كتاب", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c3", "definition": "book"}]
        }
        self.engine.add_record(rec_ar1)
        self.engine.add_record(rec_ar2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 1)
        self.assertEqual(rev[0]["document_id"], "doc4")

    def test_cjk_homographs(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "zh", "pos": "noun", "lemma": "银行", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c1", "definition": "bank (financial)"}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "zh", "pos": "noun", "lemma": "银行", "source": {"provenance": "A"}}],
            "senses": [{"concept_id": "c2", "definition": "galaxy (less common meaning)"}]
        }
        self.engine.add_record(rec1)
        self.engine.add_record(rec2)

        can, dup, rev = self._process()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

if __name__ == "__main__":
    unittest.main()
