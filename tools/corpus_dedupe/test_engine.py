import unittest
from tools.corpus_dedupe.engine import CorpusDeduplicator

class TestLinguisticVariants(unittest.TestCase):
    def setUp(self):
        self.deduper = CorpusDeduplicator()

    def tearDown(self):
        self.deduper.close()

    def test_german_umlaut_variants(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'deu', 'pos': 'adj', 'lemma': 'schön',
            'senses': [{'concept_id': 'c1', 'definition': 'beautiful'}]
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'deu', 'pos': 'adj', 'lemma': 'schon',
            'senses': [{'concept_id': 'c2', 'definition': 'already'}]
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 2, "schön and schon should be distinct")

    def test_arabic_diacritics(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'ara', 'pos': 'noun', 'lemma': 'كَتَبَ',
            'senses': [{'concept_id': 'c1', 'definition': 'to write'}]
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'ara', 'pos': 'noun', 'lemma': 'كُتُب',
            'senses': [{'concept_id': 'c2', 'definition': 'books'}]
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 2, "Different diacritics with different meanings should be distinct")

    def test_cjk_homographs(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'zho', 'pos': 'noun', 'lemma': '行',
            'senses': [{'concept_id': 'c1', 'definition': 'row'}]
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'zho', 'pos': 'noun', 'lemma': '行',
            'senses': [{'concept_id': 'c2', 'definition': 'to walk'}]
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 2, "CJK homographs with disjoint senses should be distinct")

    def test_polysemy_preservation(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'eng', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'concept_id': 'c1', 'definition': 'financial institution'}]
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'eng', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'concept_id': 'c2', 'definition': 'river side'}]
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 2, "Polysemous words with disjoint senses should be distinct")

class TestLicensingAndDuplicates(unittest.TestCase):
    def setUp(self):
        self.deduper = CorpusDeduplicator()

    def tearDown(self):
        self.deduper.close()

    def test_exact_duplicate(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'eng', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'sense_id': 's1', 'concept_id': 'c1', 'definition': 'feline'}],
            'source': {'publisher': 'A', 'license_id': 'CC-BY'}
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'eng', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'sense_id': 's2', 'concept_id': 'c1', 'definition': 'feline'}],
            'source': {'publisher': 'A', 'license_id': 'CC-BY'}
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 1)
        c_rec, dups, revs = results[0]
        self.assertEqual(len(dups), 1)
        self.assertEqual(len(revs), 0)
        self.assertEqual(dups[0]['lexeme_id'], 'l2')

    def test_near_duplicate_incompatible_licenses(self):
        r1 = {
            'lexeme_id': 'l1', 'language': 'eng', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'sense_id': 's1', 'concept_id': 'c1', 'definition': 'feline'}],
            'source': {'publisher': 'A', 'license_id': 'CC-BY'}
        }
        r2 = {
            'lexeme_id': 'l2', 'language': 'eng', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'sense_id': 's2', 'concept_id': 'c1', 'definition': 'feline'}],
            'source': {'publisher': 'B', 'license_id': 'GFDL'}
        }
        self.deduper.add_record(r1)
        self.deduper.add_record(r2)

        results = list(self.deduper.process())
        self.assertEqual(len(results), 1)
        c_rec, dups, revs = results[0]
        self.assertEqual(len(dups), 0)
        self.assertEqual(len(revs), 1, "Incompatible licenses should mark as REVIEW_REQUIRED, not EXACT_DUPLICATE")
        self.assertEqual(revs[0]['lexeme_id'], 'l2')

if __name__ == '__main__':
    unittest.main()
