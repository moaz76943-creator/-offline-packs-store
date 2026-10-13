"""Independent synthetic fixtures: tests are NOT approved linguistic content."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[3] / 'tools/factory_extensions/grammar_evidence/factory.py'
spec = importlib.util.spec_from_file_location('grammar_factory', MODULE)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class FactoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'public.bin').write_bytes(b'reviewed synthetic source')
        sha = hashlib.sha256(b'reviewed synthetic source').hexdigest()
        self.source = {'source_id': 'synthetic', 'dataset_version': '1',
                       'artifact_sha256': sha, 'record_locator': 'test:1',
                       'publication_approved': True, 'fixture_only': False}
        self.context = {'root': self.root, 'langs': {'de': {}, 'ar': {}, 'sw': {}},
            'features': frozenset(('case', 'root_pattern', 'noun_classes', 'grammatical_gender')),
            'overrides': {'de': {'case': 'supported'}, 'ar': {'root_pattern': 'supported'},
                          'sw': {'noun_classes': 'supported'}},
            'ledger': {'synthetic': {'status': 'APPROVED_FOR_REDISTRIBUTION', 'kind': 'morphology',
                'dataset_version': '1', 'review': {'reviewer': 'fixture'},
                'retrieval': {'artifact_path': 'public.bin', 'sha256': sha}}}}
        self.rule = {'schema_version': f.VERSION, 'rule_id': 'gr1:de:cases:v1', 'language': 'de',
            'kind': 'descriptive', 'capability': 'case', 'feature_value': 'dative',
            'domain': 'case-marking', 'explanation': 'Illustrative test case.',
            'pattern': 'placeholder pattern', 'register': 'neutral',
            'exceptions': [], 'prerequisites': [], 'sources': [self.source],
            'lexeme_refs': [{'lexeme_id': 'lex.de.buch', 'sense_id': 'sense.de.buch'}],
            'form_refs': [{'lemma_id': 'de:Buch:1', 'sense_id': 'de:Buch:book',
                           'form': 'Büchern', 'features': {'case': 'dative'},
                           'dataset_version': '1', 'artifact_sha256': sha,
                           'record_locator': 'test:1', 'evidence_version': '1'}],
            'example_refs': [{'example_id': 'ex.de.buch',
                              'annotation': {'span': 'Büchern', 'feature': 'case=dative'}}]}
        self.rule['review'] = {'decision': 'approved', 'reviewer_id': 'editor',
                                'decision_url': 'https://example.org/review',
                                'rule_sha256': f.rule_hash(self.rule)}
        lexical = {'contract_version': f.VERSION,
            'lexemes': [{'lexeme_id': 'lex.de.buch', 'language': 'de', 'source': self.source}],
            'senses': [{'sense_id': 'sense.de.buch', 'lexeme_id': 'lex.de.buch', 'source': self.source}],
            'examples': [{'example_id': 'ex.de.buch', 'language': 'de', 'sense_id': 'sense.de.buch',
                          'text': 'mit Büchern', 'source': self.source,
                          'grammar_annotations': [{'span': 'Büchern', 'feature': 'case=dative',
                                                   'explanation_ref': 'gr1:de:cases:v1'}]}]}
        forms = [{'language_code': 'de', 'lemma_id': 'de:Buch:1', 'sense_id': 'de:Buch:book',
                  'form': 'Büchern', 'features': {'case': 'dative'}, 'source_id': 'synthetic',
                  'evidence_version': '1'}]
        self.corpus = f.collect_evidence(lexical, forms)
        self.reviewers = {'editor': {'status': 'approved', 'languages': ['de']}}

    def check(self, rule=None):
        rule = rule or self.rule
        return f.check_rule(rule, self.context, self.corpus, self.reviewers,
                            {rule['rule_id']: rule})

    def test_approved_synthetic_contract(self):
        self.assertEqual(self.check(), [])

    def test_unregistered_language_fails(self):
        bad = copy.deepcopy(self.rule)
        bad['language'] = 'ar'
        self.assertIn('invalid_or_cross_language_identity', self.check(bad))

    def test_unknown_capability_never_inherits_from_family(self):
        bad = copy.deepcopy(self.rule)
        bad['capability'] = 'grammatical_gender'
        self.assertIn('unsupported_or_unknown_capability', self.check(bad))

    def test_noun_class_not_german_gender(self):
        self.assertEqual(f.capability(self.context, 'sw', 'noun_classes'), 'supported')
        self.assertEqual(f.capability(self.context, 'sw', 'grammatical_gender'), 'unknown')

    def test_unapproved_source_blocks(self):
        self.context['ledger'].clear()
        self.assertIn('source_rights_not_approved', self.check())

    def test_replacement_of_source_artifact_blocks(self):
        (self.root / 'public.bin').write_bytes(b'tampered')
        self.assertIn('source_rights_not_approved', self.check())

    def test_fixture_only_lexeme_blocks(self):
        self.corpus['lexemes']['lex.de.buch']['source']['fixture_only'] = True
        self.assertIn('invalid_or_unapproved_lexeme_link', self.check())

    def test_wrong_form_features_block(self):
        bad = copy.deepcopy(self.rule)
        bad['form_refs'][0]['features']['case'] = 'accusative'
        self.assertIn('invalid_or_unapproved_form_link', self.check(bad))

    def test_wrong_annotation_blocks(self):
        bad = copy.deepcopy(self.rule)
        bad['example_refs'][0]['annotation']['feature'] = 'case=accusative'
        self.assertIn('example_feature_contradiction', self.check(bad))

    def test_conflicting_annotations_block(self):
        self.corpus['examples']['ex.de.buch']['grammar_annotations'].append(
            {'span': 'Büchern', 'feature': 'case=accusative', 'explanation_ref': self.rule['rule_id']})
        self.assertIn('conflicting_example_annotations', self.check())

    def test_changed_rule_needs_fresh_editorial_signature(self):
        bad = copy.deepcopy(self.rule)
        bad['explanation'] = 'Changed.'
        self.assertIn('independent_editorial_review_missing', self.check(bad))

    def test_pedagogical_requires_descriptive_parent(self):
        bad = copy.deepcopy(self.rule)
        bad['kind'] = 'pedagogical'
        self.assertIn('pedagogical_rule_requires_descriptive_parent', self.check(bad))

    def test_cycle_and_duplicate_rejected(self):
        a, b = copy.deepcopy(self.rule), copy.deepcopy(self.rule)
        b['rule_id'] = 'gr1:de:other:v1'
        a['prerequisites'] = [b['rule_id']]
        b['prerequisites'] = [a['rule_id']]
        self.assertEqual(f.cycles({a['rule_id']: a, b['rule_id']: b}), {a['rule_id'], b['rule_id']})
        report = f.build_report([a, a], self.context, self.corpus, self.reviewers)
        self.assertIn('duplicate_rule_identity', report['languages']['de']['blocked_reasons'])

    def test_empty_100_registry_report_not_fabricated(self):
        self.context['langs'] = {chr(97+i//26)+chr(97+i%26): {} for i in range(100)}
        report = f.build_report([], self.context, self.corpus, {})
        self.assertEqual(report['language_count'], 100)
        self.assertEqual(report['status'], 'EMPTY_NO_APPROVED_CONTENT')
        self.assertEqual(sum(x['verified_rules'] for x in report['languages'].values()), 0)

    def test_bounded_jsonl_fails_closed(self):
        (self.root/'big.jsonl').write_text(json.dumps({'payload':'x'*f.MAX_ROW})+'\n')
        with self.assertRaises(ValueError):
            f.read_jsonl(self.root/'big.jsonl')

    def test_deterministic_approval_report(self):
        self.assertEqual(f.build_report([self.rule], self.context, self.corpus, self.reviewers),
                         f.build_report([self.rule], self.context, self.corpus, self.reviewers))
        self.assertEqual(f.build_report([self.rule], self.context, self.corpus, self.reviewers)['status'],
                         'APPROVED_RULES')


if __name__ == '__main__':
    unittest.main()
