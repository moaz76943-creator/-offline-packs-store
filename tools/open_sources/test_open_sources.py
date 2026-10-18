"""Open-source adapters. Fixtures only; no network and no ledger edits."""

import hashlib
import unittest
from pathlib import Path

from tools.language_production.catalog import ROOT
from tools.open_sources.adapters import adapt_records, load_sources
from tools.open_sources.assess import positive_match

EVIDENCE = ROOT / 'legal' / 'source_evidence'


class LicenseAssessmentTests(unittest.TestCase):
    def test_evidence_hashes_match_the_catalog(self):
        sources = load_sources()
        for source in sources.values():
            path = source.get('evidence_path')
            if not path:
                self.assertFalse(source['compatible'])
                continue
            digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            self.assertEqual(digest, source['evidence_sha256'], source['id'])

    def test_wiktionary_co_offer_passes_and_gpl_does_not(self):
        wiki = (EVIDENCE / 'wiktionary-copyrights.txt').read_text(encoding='utf-8')
        ok, reasons = positive_match(wiki, 'CC-BY-SA-4.0', ('GFDL-1.3-only',))
        self.assertTrue(ok, reasons)
        gpl = (EVIDENCE / 'apertium-eng-copying.txt').read_text(encoding='utf-8')
        self.assertFalse(positive_match(gpl, 'CC-BY-SA-4.0')[0])
        self.assertFalse(positive_match(gpl, 'GPL-3.0-only')[0])

    def test_adapters_filter_policy_and_do_not_invent_anchors(self):
        sources = load_sources()
        blocked = ({'Q154'}, {'wine'})
        kaikki = adapt_records('kaikki.wiktextract', [
            {'word': 'apple', 'lang_code': 'en', 'senses': [{'glosses': ['a fruit'], 'wikidata': ['Q89']}]},
            {'word': 'mystery', 'lang_code': 'en', 'senses': [{'glosses': ['unknown']}]},
            {'word': 'wine', 'lang_code': 'en', 'senses': [{'glosses': ['a drink'], 'wikidata': ['Q154']}]},
        ], sources=sources, blocklist=blocked)
        self.assertEqual(kaikki['kept'], 1)
        self.assertEqual(kaikki['rows'][0]['concept_id'], 'concept.q89')
        self.assertFalse(kaikki['rows'][0]['publication_approved'])
        self.assertEqual(kaikki['rows'][1]['status'], 'unplaced')
        self.assertEqual(kaikki['rows'][2]['status'], 'exclude')
        self.assertIn('Wiktionary contributors', kaikki['attribution'])
        self.assertIn('publication_approved: false', kaikki['attribution'])

        tatoeba = adapt_records('tatoeba.sentences', [
            {'language': 'en', 'text': 'The apple is red', 'author': 'Ada'},
            {'language': 'en', 'text': 'A house', 'author': ''},
        ], sources=sources, blocklist=blocked)
        self.assertEqual(tatoeba['kept'], 1)
        self.assertFalse(tatoeba['rows'][0]['ledger_compatible'])
        self.assertIn('estimated:heuristic-v1', tatoeba['rows'][0]['level']['evidence'])
        self.assertEqual(tatoeba['rows'][1]['reason'], 'missing_attribution')
        self.assertIn('Ada', tatoeba['attribution'])

        ud = adapt_records('universal-dependencies', [
            {'language': 'en', 'lemma': 'apple', 'features': 'Number=Sing',
             'license_notice': (EVIDENCE / 'ud-english-ewt-license.txt').read_text(encoding='utf-8')},
            {'language': 'en', 'lemma': 'apple', 'features': 'Number=Sing',
             'license_notice': (EVIDENCE / 'apertium-eng-copying.txt').read_text(encoding='utf-8')},
        ], sources=sources, blocklist=blocked)
        self.assertEqual(ud['rows'][0]['status'], 'keep')
        self.assertEqual(ud['rows'][1]['status'], 'reject')

        for source_id in ('unimorph', 'apertium', 'omegawiki'):
            result = adapt_records(source_id, [{'lemma': 'apple', 'language': 'en'}], sources=sources, blocklist=blocked)
            self.assertEqual(result['kept'], 0, source_id)
            self.assertEqual(result['rows'][0]['status'], 'reject')

    def test_package_does_not_read_the_ledger_or_packs(self):
        text = '\n'.join(
            path.read_text(encoding='utf-8')
            for path in (ROOT / 'tools' / 'open_sources').glob('*.py')
            if path.name != 'test_open_sources.py'
        )
        self.assertNotIn('sources.json', text)
        self.assertNotIn('packs/', text)


class OrganizationIndependenceTests(unittest.TestCase):
    def test_profiles_cover_every_registry_language_without_packs(self):
        from tools.language_production.catalog import load_json, REGISTRY_PATH
        from tools.language_production.organization import (
            FRAMEWORKS_PATH, PROFILES_PATH, build_profiles, validate_organization,
        )
        registry = load_json(REGISTRY_PATH)
        profiles = load_json(PROFILES_PATH)
        frameworks = load_json(FRAMEWORKS_PATH)
        graph = {'sections': [{
            'id': 'food',
            'subsections': [{
                'id': 'food.q2095',
                'concepts': [{'id': 'concept.q2095', 'wikidata': 'Q2095', 'anchor_label': 'food'}],
            }],
        }]}
        problems = validate_organization(graph, frameworks, profiles, registry, blocked_concepts={'Q154'})
        self.assertEqual(problems, [])
        self.assertEqual(len(profiles['languages']), len(registry['languages']))
        arabic = next(row for row in profiles['languages'] if row['id'] == 'ar')
        self.assertTrue(arabic['rtl'])
        self.assertEqual(arabic['script'], 'Arab')
        self.assertTrue(arabic['transliteration_needed'])
        self.assertEqual(build_profiles(registry)['languages'], profiles['languages'])
        german = next(row for row in profiles['languages'] if row['id'] == 'de')
        self.assertEqual(german['verb_classes']['applicability'], 'unknown')

    def test_concept_graph_is_blocked_item_free_when_present(self):
        path = ROOT / 'catalog' / 'organization' / 'concept_graph.v1.json'
        if not path.is_file():
            return
        from tools.language_production.organization import iter_concepts, load_graph
        from tools.language_production.catalog import load_sections
        graph = load_graph(path)
        blocked = {'Q154', 'Q11416', 'Q154136', 'Q11639'}
        expected = [section['id'] for section in load_sections()['sections']]
        present = [section['id'] for section in graph['sections']]
        if present != expected:
            return
        for section, _subsection, concept in iter_concepts(graph):
            self.assertNotIn(concept['wikidata'], blocked)
            self.assertEqual(concept['id'], f"concept.{concept['wikidata'].lower()}")
        for section in graph['sections']:
            count = sum(len(item['concepts']) for item in section['subsections'])
            self.assertGreaterEqual(count, 200, section['id'])
