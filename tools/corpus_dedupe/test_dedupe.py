import unittest
from tools.corpus_dedupe.dedupe import CorpusDeduplicator, normalize_strict, normalize_loose

class TestCorpusDeduplicator(unittest.TestCase):
    def setUp(self):
        self.deduplicator = CorpusDeduplicator(admitted_source_licenses={'src.fixture': ('CC-BY', '1')})

    def tearDown(self):
        if hasattr(self, 'deduplicator') and self.deduplicator:
            self.deduplicator.close()

    def test_normalize_strict(self):
        # NFKC casefolding
        self.assertEqual(normalize_strict('Schön'), 'schön')
        self.assertEqual(normalize_strict('eﬃcient'), 'efficient')

    def test_normalize_loose(self):
        # NFKD + diacritic removal + casefold
        self.assertEqual(normalize_loose('Schön'), 'schon')
        self.assertEqual(normalize_loose('كِتَاب'), 'كتاب')

    def test_exact_duplicate(self):
        rec1 = {
            'lexeme_id': 'l1', 'language': 'en', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'concept_id': 'concept.cat', 'definition': 'A small domesticated carnivorous mammal',
                        'source': {'source_id': 'src.fixture', 'license_id': 'CC-BY', 'dataset_version': '1', 'record_locator': 'fixture', 'publication_approved': True, 'fixture_only': False}}],
            'source': {'source_id': 'src.fixture', 'license_id': 'CC-BY', 'dataset_version': '1', 'record_locator': 'fixture', 'publication_approved': True, 'fixture_only': False}
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'en', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'concept_id': 'concept.cat', 'definition': 'A small domesticated carnivorous mammal',
                        'source': {'source_id': 'src.fixture', 'license_id': 'CC-BY', 'dataset_version': '1', 'record_locator': 'fixture', 'publication_approved': True, 'fixture_only': False}}],
            'source': {'source_id': 'src.fixture', 'license_id': 'CC-BY', 'dataset_version': '1', 'record_locator': 'fixture', 'publication_approved': True, 'fixture_only': False}
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 1)
        self.assertEqual(len(self.deduplicator.duplicates), 1)
        self.assertEqual(self.deduplicator.duplicates[0]['status'], 'EXACT_DUPLICATE')

    def test_canonical_record_stays_first_under_reverse_unordered_scans(self):
        # Without explicit ORDER BY, SQLite can return the newest retained
        # row under this planner setting. Selection must remain deterministic.
        self.deduplicator._db.execute('PRAGMA reverse_unordered_selects=ON')
        for ident in ('l1', 'l2', 'l3'):
            self.deduplicator.process_record({
                'lexeme_id': ident, 'language': 'en', 'pos': 'noun',
                'lemma': 'cat', 'senses': [{'definition': 'animal'}],
            })
        self.deduplicator.resolve()
        self.assertEqual([d['duplicate_of'] for d in self.deduplicator.duplicates],
                         ['l1', 'l1'])
        self.assertTrue(all(d['status'] == 'REVIEW_REQUIRED'
                            for d in self.deduplicator.duplicates))
        self.assertEqual(len(self.deduplicator.canonical), 3)

    def test_incompatible_licenses(self):
        rec1 = {
            'lexeme_id': 'l1', 'language': 'en', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'definition': 'A small domesticated carnivorous mammal'}],
            'source': {'license_id': 'CC-BY'}
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'en', 'pos': 'noun', 'lemma': 'cat',
            'senses': [{'definition': 'A small domesticated carnivorous mammal'}],
            'source': {'license_id': 'CC0'}
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 1)
        self.assertEqual(self.deduplicator.duplicates[0]['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.deduplicator.duplicates[0]['reason'], 'incompatible_licenses')

    def test_polysemy(self):
        # Same strict lemma, different senses. Should be preserved.
        rec1 = {
            'lexeme_id': 'l1', 'language': 'en', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'definition': 'Financial institution'}]
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'en', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'definition': 'Side of a river'}]
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 0)

    def test_overlapping_senses(self):
        # Same strict lemma, partially overlapping or identical senses, but maybe different structure?
        # Actually our check is exact match on definition list. What if they share ONE sense?
        # My implementation: if (senses1 & senses2) -> overlapping.
        rec1 = {
            'lexeme_id': 'l1', 'language': 'en', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'definition': 'Financial institution'}]
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'en', 'pos': 'noun', 'lemma': 'bank',
            'senses': [{'definition': 'Financial institution'}, {'definition': 'A place to store things'}]
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 1)
        self.assertEqual(self.deduplicator.duplicates[0]['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.deduplicator.duplicates[0]['reason'], 'overlapping_senses')

    def test_german_umlaut_near_duplicate(self):
        # Different strict lemma, same loose lemma (schon vs schön), same meaning -> near duplicate
        rec1 = {
            'lexeme_id': 'l1', 'language': 'de', 'pos': 'adv', 'lemma': 'schon',
            'senses': [{'definition': 'already'}]
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'de', 'pos': 'adv', 'lemma': 'schön',
            'senses': [{'definition': 'already'}] # Typo in one, so same meaning
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 1)
        self.assertEqual(self.deduplicator.duplicates[0]['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.deduplicator.duplicates[0]['reason'], 'near_duplicate_orthography')

    def test_arabic_diacritics_near_duplicate(self):
        # With and without diacritics
        rec1 = {
            'lexeme_id': 'l1', 'language': 'ar', 'pos': 'noun', 'lemma': 'كِتَاب',
            'senses': [{'definition': 'book'}]
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'ar', 'pos': 'noun', 'lemma': 'كتاب',
            'senses': [{'definition': 'book'}]
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 1)
        self.assertEqual(self.deduplicator.duplicates[0]['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.deduplicator.duplicates[0]['reason'], 'near_duplicate_orthography')

    def test_cjk_homographs(self):
        # Sometimes CJK have homographs or variations. Let's just ensure if lemma is same and senses differ, it's preserved.
        rec1 = {
            'lexeme_id': 'l1', 'language': 'ja', 'pos': 'noun', 'lemma': '空',
            'senses': [{'definition': 'sky'}]
        }
        rec2 = {
            'lexeme_id': 'l2', 'language': 'ja', 'pos': 'noun', 'lemma': '空',
            'senses': [{'definition': 'emptiness'}]
        }
        self.deduplicator.process_record(rec1)
        self.deduplicator.process_record(rec2)
        self.deduplicator.resolve()

        self.assertEqual(len(self.deduplicator.canonical), 2)
        self.assertEqual(len(self.deduplicator.duplicates), 0)

if __name__ == '__main__':
    unittest.main()
