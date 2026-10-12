"""Executed with unittest discover; includes negative cross-language cases."""
import unittest

from engine import ContractError, MorphologyEngine


class PublicMorphologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MorphologyEngine(cache_size=4)

    def test_registry_coverage_and_family_identity(self):
        profiles = list(self.engine.iter_profiles())
        self.assertEqual(100, len(profiles))
        self.assertEqual(100, len({p['identity']['code'] for p in profiles}))
        self.assertEqual('Semitic', self.engine.profile('ar')['identity']['family'])
        self.assertEqual('Bantu', self.engine.profile('sw')['identity']['family'])
        self.assertEqual('Sinitic', self.engine.profile('zh')['identity']['family'])
        self.assertEqual('Turkic', self.engine.profile('tr')['identity']['family'])
        self.assertTrue(all(not p['form_inventory_complete'] for p in profiles))

    def test_untested_language_never_claims_attested(self):
        self.assertEqual('capability_only', self.engine.profile('mg')['analysis_status'])
        self.assertEqual('unknown', self.engine.profile('mg')['capabilities']['case'])
        self.assertEqual('unknown', self.engine.analyze('mg', 'mg:unknown:1')['status'])

    def test_german_irregular_nouns_and_verbs(self):
        x = self.engine.analyze('de', 'de:Buch:1', {'case':'nominative', 'number':'plural'})
        self.assertEqual(['Bücher'], [r['form'] for r in x['forms']])
        self.assertEqual('Büchern', self.engine.analyze('de', 'de:Buch:1', {'case':'dative','number':'plural'})['forms'][0]['form'])
        self.assertEqual('ging', self.engine.analyze('de', 'de:gehen:1', {'tense':'preterite'})['forms'][0]['form'])
        self.assertEqual('gegangen', self.engine.analyze('de', 'de:gehen:1', {'verb_form':'past_participle'})['forms'][0]['form'])

    def test_arabic_broken_plural_and_root(self):
        record = self.engine.analyze('ar', 'ar:kitab:1', {'number':'plural'})['forms'][0]
        self.assertEqual(('كُتُب', 'ك-ت-ب'), (record['form'], record['root']))
        self.assertIn('broken_plural', record['processes'])
        self.assertEqual('رِجَال', self.engine.analyze('ar', 'ar:rajul:1', {'number':'plural'}, 'ar:rajul:man')['forms'][0]['form'])
        self.assertEqual('unknown', self.engine.analyze('ar', 'ar:rajul:1', {'number':'plural'}, 'ar:rajul:foot')['status'])

    def test_english_irregular_and_phrasal(self):
        self.assertEqual('mice', self.engine.analyze('en', 'en:mouse:1', {'number':'plural'})['forms'][0]['form'])
        self.assertEqual('went', self.engine.analyze('en', 'en:go:1', {'tense':'past'})['forms'][0]['form'])
        self.assertEqual('took off', self.engine.analyze('en', 'en:take_off:1', {'tense':'past'})['forms'][0]['form'])

    def test_spanish_inflection_agreement(self):
        self.assertEqual('hablamos', self.engine.analyze('es','es:hablar:1', {'person':'first','number':'plural','tense':'present'})['forms'][0]['form'])
        self.assertEqual('bonita', self.engine.analyze('es','es:bonito:1', {'grammatical_gender':'feminine'})['forms'][0]['form'])
        self.assertEqual('he hablado', self.engine.analyze('es','es:hablar:1', {'tense':'present_perfect'})['forms'][0]['form'])

    def test_french_compound_and_inflection(self):
        self.assertEqual('mangeons', self.engine.analyze('fr','fr:manger:1', {'tense':'present','number':'plural'})['forms'][0]['form'])
        record = self.engine.analyze('fr','fr:manger:1', {'tense':'passe_compose'})['forms'][0]
        self.assertEqual("j'ai mangé", record['form'])
        self.assertIn('compound_verb', record['processes'])
        self.assertEqual('ai', self.engine.analyze('fr','fr:avoir:1', {'tense':'present'})['forms'][0]['form'])

    def test_language_specific_family_contracts(self):
        self.assertIn('slavic_aspect', self.engine.contracts('ru'))
        self.assertIn('turkic_harmony', self.engine.contracts('tr'))
        self.assertIn('bantu_noun_class', self.engine.contracts('sw'))
        self.assertIn('cjk_classifiers', self.engine.contracts('zh'))
        self.assertIn('segmentation', self.engine.contracts('th'))
        self.assertNotIn('tone_and_analytic', self.engine.contracts('ja'))
        self.assertEqual(['Cyrl','Latn'], self.engine.profile('sr')['scripts'])
        self.assertEqual(['Hans','Hant'], self.engine.profile('zh')['scripts'])

    def test_cross_language_mixing_rejected(self):
        with self.assertRaises(ContractError):
            self.engine.analyze('en', 'de:Buch:1')
        with self.assertRaises(ContractError):
            self.engine.analyze('ar', 'de:gehen:1')
        self.assertEqual('unknown', self.engine.analyze('en', 'en:go:1', {'grammatical_gender':'masculine'})['status'])
        self.assertEqual('unknown', self.engine.analyze('ar', 'ar:kitab:1', {'number':'dual'})['status'])
        self.assertEqual('unknown', self.engine.analyze('de', 'de:gehen:1', {'tense':'present','person':'third'})['status'])
        self.assertEqual('unknown', self.engine.analyze('fr', 'fr:manger:1', {'noun_classes':'m-wa'})['status'])

    def test_lru_memory_bound(self):
        for code in self.engine.language_codes:
            self.engine.profile(code)
        for code, lemma in [('de','de:Buch:1'),('de','de:gehen:1'),('ar','ar:kitab:1'),('en','en:mouse:1'),('fr','fr:manger:1')]:
            self.engine.analyze(code, lemma)
        self.assertLessEqual(self.engine.cache_usage['profiles'], 4)
        self.assertLessEqual(self.engine.cache_usage['lemmas'], 4)
        self.assertEqual('unknown', self.engine.analyze('de','de:UNKNOWN:1')['status'])


if __name__ == '__main__':
    unittest.main()
