import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator

class TestCorpusDeduplicator(unittest.TestCase):
    def setUp(self):
        self.deduper = CorpusDeduplicator(":memory:")

    def tearDown(self):
        self.deduper.close()

    def _process_and_get_results(self):
        canonical = []
        duplicates = []
        review = []
        for status, rec, info in self.deduper.process_groups():
            if status == "CANONICAL":
                canonical.append(rec)
            elif status == "DUPLICATE":
                duplicates.append(rec)
            elif status == "REVIEW_REQUIRED":
                review.append(rec)
        return canonical, duplicates, review

    def test_exact_duplicate_detection(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "A trial", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "A trial", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 1)
        self.assertEqual(len(rev), 0)

    def test_near_duplicate_detection(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "A procedure intended to establish the quality, performance, or reliability of something, especially before it is taken into widespread use.", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "A procedure intended to establish the quality, performance, or reliability of something.", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 1)

    def test_german_umlaut_variants(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Müller", "surface": "Müller", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Miller", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "de", "pos": "noun", "lemma": "Muller", "surface": "Muller", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Miller", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_arabic_diacritics(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "ar", "pos": "noun", "lemma": "كِتَاب", "surface": "كِتَاب", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Book", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "ar", "pos": "noun", "lemma": "كتاب", "surface": "كتاب", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Book", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_cjk_homographs(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "zh", "pos": "noun", "lemma": "长", "surface": "长", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Length", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "zh", "pos": "noun", "lemma": "长", "surface": "长", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Chief", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_polysemy(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "bank", "surface": "bank", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Financial institution", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "bank", "surface": "bank", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "Side of a river", "source": {"source_id": "src1"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 2)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 0)

    def test_cross_source_duplicates(self):
        rec1 = {
            "document_id": "doc1",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src1"}}],
            "senses": [{"definition": "A trial", "source": {"source_id": "src1"}}]
        }
        rec2 = {
            "document_id": "doc2",
            "lexemes": [{"language": "en", "pos": "noun", "lemma": "test", "surface": "test", "source": {"source_id": "src2"}}],
            "senses": [{"definition": "A trial", "source": {"source_id": "src2"}}]
        }
        self.deduper.ingest_record(rec1)
        self.deduper.ingest_record(rec2)

        can, dup, rev = self._process_and_get_results()
        self.assertEqual(len(can), 1)
        self.assertEqual(len(dup), 0)
        self.assertEqual(len(rev), 1)

if __name__ == '__main__':
    unittest.main()
