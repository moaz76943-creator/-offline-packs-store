import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.directed_pairs.translation_provenance_manager import (
    DirectedTranslationEdge,
    DirectedTranslationStore,
    PROVENANCE_DIRECT,
    PROVENANCE_PIVOT
)

class TestDirectedTranslationProvenance(unittest.TestCase):
    def edge(self, reverse=False, provenance=PROVENANCE_DIRECT):
        return DirectedTranslationEdge(
            'ar' if reverse else 'de', 'de' if reverse else 'ar',
            'بيت' if reverse else 'Haus', 'Haus' if reverse else 'بيت',
            'fixture_source', 'CC0-1.0', provenance,
            0.7 if provenance == PROVENANCE_PIVOT else 1.0)

    def test_reverse_requires_independent_direct_attestation(self):
        store = DirectedTranslationStore()
        forward = self.edge()
        store.add_edge(self.edge(reverse=True, provenance=PROVENANCE_PIVOT))
        self.assertFalse(store.has_reverse_edge(forward))
        store.add_edge(self.edge(reverse=True))
        self.assertTrue(store.has_reverse_edge(forward))

    def test_caller_and_query_mutations_cannot_change_stored_provenance(self):
        store = DirectedTranslationStore()
        edge = self.edge()
        store.add_edge(edge)
        edge.source_id = ''
        edge.target_lang = 'fr'
        stored = store.get_translations('de', 'ar', 'Haus')[0]
        self.assertEqual(stored.source_id, 'fixture_source')
        self.assertEqual(stored.target_lang, 'ar')
        stored.source_id = ''
        self.assertEqual(store.get_translations('de', 'ar', 'Haus')[0].source_id, 'fixture_source')

    def test_asymmetric_direction_enforced(self):
        store = DirectedTranslationStore()
        edge = DirectedTranslationEdge(
            source_lang="de",
            target_lang="ar",
            source_lemma="Schloss",
            target_lemma="قصر",
            source_id="kaikki_de_deu_core",
            license_id="CC-BY-SA-4.0",
            provenance_type=PROVENANCE_DIRECT,
            confidence=1.0
        )
        store.add_edge(edge)

        # Assert forward edge exists
        de_ar = store.get_translations("de", "ar", "Schloss")
        self.assertEqual(len(de_ar), 1)
        self.assertEqual(de_ar[0].target_lemma, "قصر")

        # Assert reverse direction is NOT automatically inferred (A->B != B->A)
        ar_de = store.get_translations("ar", "de", "قصر")
        self.assertEqual(len(ar_de), 0)
        self.assertFalse(store.has_reverse_edge(edge))

    def test_missing_provenance_rejected(self):
        store = DirectedTranslationStore()
        with self.assertRaises(ValueError):
            # Attempt to add translation without legal source_id
            bad_edge = DirectedTranslationEdge(
                source_lang="de",
                target_lang="ar",
                source_lemma="Hund",
                target_lemma="كلب",
                source_id="",  # Missing provenance!
                license_id="CC-BY-SA-4.0"
            )
            store.add_edge(bad_edge)

    def test_pivot_provenance_tagged_with_lower_confidence(self):
        pivot_edge = DirectedTranslationEdge(
            source_lang="de",
            target_lang="ar",
            source_lemma="Haus",
            target_lemma="بيت",
            source_id="kaikki_de_deu_core",
            license_id="CC-BY-SA-4.0",
            provenance_type=PROVENANCE_PIVOT,
            confidence=0.7
        )
        self.assertEqual(pivot_edge.provenance_type, PROVENANCE_PIVOT)
        self.assertLess(pivot_edge.confidence, 1.0)

if __name__ == "__main__":
    unittest.main()
