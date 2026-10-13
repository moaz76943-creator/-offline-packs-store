"""Evidence-first cross-language negative regression tests (no remote corpora)."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
from tools.linguistic_extensions.semitic import ContractError, normalize_retrieval, lookup, validate_candidate, load_profile
from tools.linguistic_extensions.semitic.worker import process, coverage, approved_snapshot, resume_checkpoint


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SemiticContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_json(self.root / 'catalog/language_registry.v1.json', {'languages': [
            {'id': 'ar', 'family': 'Semitic', 'scripts': ['Arab']},
            {'id': 'am', 'family': 'Semitic', 'scripts': ['Ethi']},
            {'id': 'mt', 'family': 'Semitic', 'scripts': ['Latn']},
            {'id': 'fa', 'family': 'Iranian', 'scripts': ['Arab']},
            {'id': 'ur', 'family': 'Indo-Aryan', 'scripts': ['Arab']},
            {'id': 'so', 'family': 'Cushitic', 'scripts': ['Latn']},
        ]})
        fields = ('language_code lemma_id sense_id lemma form features root pattern processes '
                  'components morphemes script orthographic_variant source_id evidence_version').split()
        write_json(self.root / 'standards/morphology/form.schema.json', {
            'required': ['language_code', 'lemma_id', 'sense_id', 'lemma', 'form', 'features', 'source_id', 'evidence_version'],
            'properties': {name: {} for name in fields}})
        self.ar = self.record('ar', 'كِتَاب', 'كُتُب', 'noun', {'number': 'plural', 'grammatical_gender': 'masculine'})
        self.ar['record'].update(root='كتب', pattern='فُعُل', processes=['broken_plural'])
        self.ar['evidence']['claim_locators'].update({'root': 'entry:root', 'pattern': 'entry:pattern',
                                                       'processes.broken_plural': 'entry:plural'})
        self.am = self.record('am', 'ቤት', 'ቤቶች', 'noun', {'number': 'plural'})

    def record(self, lang, lemma, form, pos, features, variety=None):
        variety = variety or ('msa' if lang == 'ar' else 'standard')
        return {
            'record': {'language_code': lang, 'lemma_id': lang + ':test:1',
                       'sense_id': lang + ':test:noun', 'lemma': lemma, 'form': form,
                       'features': features, 'source_id': 'source-morph', 'evidence_version': 'snapshot-1',
                       'script': 'Arab' if lang == 'ar' else 'Ethi'},
            'evidence': {'source_locator': 'entry:42', 'dataset_version': 'snapshot-1',
                         'source_sha256': 'a' * 64, 'variety': variety,
                         'part_of_speech': pos, 'attested': True,
                         'claim_locators': {'form': 'entry:42', **{'features.' + k: 'entry:42' for k in features}}}}

    def validate(self, candidate, lang='ar', sha='a' * 64):
        return validate_candidate(candidate, self.root, lang, 'source-morph', 'snapshot-1', sha)

    def make_approved(self, entries):
        # Raw corpus entries deliberately omit their own source SHA: worker binds
        # the verified SHA after hashing the immutable artifact, avoiding a cycle.
        shard_entries = deepcopy(entries)
        for entry in shard_entries:
            entry['evidence'].pop('source_sha256', None)
        shard = (''.join(json.dumps(entry, ensure_ascii=False) + '\n' for entry in shard_entries)).encode()
        path = self.root / 'approved' / 'forms.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(shard)
        source_hash = digest(shard)
        rights = b'copyright notice from test publisher'
        proof = self.root / 'approved' / 'rights.txt'
        proof.write_bytes(rights)
        ledger = {'schema_version': '1.0.0', 'sources': [{
            'source_id': 'source-morph', 'kind': 'morphology', 'origin_url': 'https://example.org/forms',
            'publisher': 'Test publisher', 'dataset_version': 'snapshot-1',
            'retrieval': {'identity': 'snapshot-1', 'date': '2026-10-13',
                          'url': 'https://example.org/forms.jsonl', 'artifact_path': 'approved/forms.jsonl',
                          'sha256': source_hash},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/license',
                        'evidence_path': 'approved/rights.txt', 'evidence_sha256': digest(rights)},
            'status': 'APPROVED_FOR_REDISTRIBUTION', 'alterations': ['none'],
            'review': {'reviewer': 'test reviewer', 'decision_url': 'https://example.org/decision'},
        }]}
        write_json(self.root / 'legal/ledger/sources.json', ledger)
        return path, ledger

    def test_explicit_profiles_and_unregistered_grammar_excluded(self):
        self.assertEqual('Arab', load_profile(self.root, 'ar')['script'])
        self.assertEqual('Ethi', load_profile(self.root, 'am')['script'])
        for code in ('fa','ur','mt','so','ha','he','ps'):
            with self.subTest(code=code), self.assertRaises(ContractError):
                load_profile(self.root, code)

    def test_attested_arabic_broken_plural(self):
        self.assertEqual(self.ar, self.validate(self.ar))

    def test_attested_amharic_is_not_an_arabic_transliteration(self):
        self.assertEqual(self.am, self.validate(self.am, lang='am'))
        fake = deepcopy(self.am)
        fake['record']['form'] = 'كتاب'
        with self.assertRaises(ContractError):
            self.validate(fake, lang='am')
        fake = deepcopy(self.ar)
        fake['record']['language_code'] = 'am'
        with self.assertRaises(ContractError):
            self.validate(fake, lang='am')

    def test_farsi_urdu_use_arabic_script_but_not_semitic(self):
        for code in ('fa', 'ur'):
            item = deepcopy(self.ar)
            item['record']['language_code'] = code
            item['record']['lemma_id'] = code + ':test:1'
            item['record']['sense_id'] = code + ':test:noun'
            with self.assertRaises(ContractError):
                self.validate(item, lang=code)

    def test_missing_root_pattern_or_specific_evidence_blocks(self):
        for mutation in ('pattern','root','claim'):
            item = deepcopy(self.ar)
            if mutation == 'claim':
                item['evidence']['claim_locators'].pop('root')
            else:
                item['record'].pop(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.validate(item)

    def test_distinct_ethiopic_number_inventory(self):
        item = deepcopy(self.am)
        item['record']['features']['number'] = 'dual'
        with self.assertRaises(ContractError):
            self.validate(item, lang='am')

    def test_verb_stems_lexical_evidence_not_generated(self):
        item = self.record('ar','كَتَبَ','يَكْتُبُ','verb', {'aspect': 'imperfective', 'person': 'third', 'mood': 'indicative'})
        with self.assertRaises(ContractError):
            self.validate(item)
        item['evidence']['verb_stem'] = 'يكتب'
        item['evidence']['claim_locators']['verb_stem'] = 'paradigm:stem'
        self.validate(item)
        item['evidence']['verb_stem'] = 'ይጽፋል'
        with self.assertRaises(ContractError):
            self.validate(item)

    def test_arabic_search_folding_preserves_ethiopic(self):
        self.assertEqual(normalize_retrieval('ar','إِكْتَابـ'), 'اكتاب')
        self.assertEqual(normalize_retrieval('am','ቤቶች'), 'ቤቶች')
        self.assertNotEqual(normalize_retrieval('ar','كَتَبَ'), 'كَتَبَ')
        with self.assertRaises(ContractError):
            normalize_retrieval('ur', 'كتاب')

    def test_stripping_harakat_never_hides_ambiguity(self):
        verb_a = self.record('ar','كَتَبَ','كَتَبَ','verb', {'aspect': 'perfective', 'person': 'third'})
        verb_b = self.record('ar','كُتِبَ','كُتِبَ','verb', {'aspect': 'perfective', 'person': 'third', 'voice': 'passive'})
        for row in (verb_a, verb_b):
            row['evidence']['verb_stem'] = row['record']['form']
            row['evidence']['claim_locators']['verb_stem'] = 'entry:stem'
            self.validate(row)
        output = self.root / 'accepted.jsonl'
        output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in (verb_a,verb_b)), encoding='utf-8')
        broad = lookup(output, self.root, 'ar', 'كتب')
        self.assertEqual('ambiguous', broad['status'])
        self.assertEqual(2, broad['total_analyses'])
        exact = lookup(output, self.root, 'ar', 'كَتَبَ')
        self.assertEqual('attested', exact['status'])
        self.assertTrue(exact['normalization_ambiguous'])
        self.assertEqual('كَتَبَ', exact['forms'][0]['record']['form'])
        self.assertEqual('unknown', lookup(output, self.root, 'ar', 'مجهول')['status'])

    def test_arabic_dialect_tag_mandatory_not_inherited(self):
        item = deepcopy(self.ar)
        item['evidence']['variety'] = 'dialect'
        with self.assertRaises(ContractError):
            self.validate(item)
        item['evidence']['dialect_tag'] = 'ar-EG'
        self.validate(item)
        item['evidence']['dialect_tag'] = 'am-ET'
        with self.assertRaises(ContractError):
            self.validate(item)

    def test_empty_ledger_blocks_production(self):
        write_json(self.root / 'legal/ledger/sources.json', {'schema_version': '1.0.0', 'sources': []})
        with self.assertRaisesRegex(ContractError, 'BLOCKED_SOURCE'):
            approved_snapshot(self.root, 'ar', 'source-morph')
        self.assertEqual([], coverage(self.root)['approved_morphology_sources'])
        self.assertEqual({'ar': 0, 'am': 0}, coverage(self.root)['accepted_production_forms'])

    def test_worker_verified_source_and_resume_two_chunks(self):
        path, ledger = self.make_approved([self.ar, self.ar, self.ar])
        first = process(self.root, 'ar', 'source-morph', self.root/'run1',
                        max_records=2, run_id='synthetic-run-1')
        self.assertEqual((2, 2, False), (first['next_line'], first['total_accepted'], first['complete']))
        self.assertEqual(2, first['segment_count'])
        self.assertEqual(ledger['sources'][0]['retrieval']['sha256'],
                         json.loads((self.root/'run1/accepted.jsonl').read_text().splitlines()[0])['evidence']['source_sha256'])
        second = process(self.root, 'ar', 'source-morph', self.root/'run2',
                         max_records=2, resume_dir=self.root/'run1', run_id='synthetic-run-2')
        self.assertEqual((3, 3, True), (second['next_line'], second['total_accepted'], second['complete']))
        self.assertEqual(1, second['segment_count'])
        self.assertEqual('attested', lookup(self.root/'run2/accepted.jsonl', self.root, 'ar', 'كتب')['status'])

    def test_source_tamper_and_status_change_block_without_output(self):
        path, ledger = self.make_approved([self.ar])
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ContractError, 'BLOCKED_SOURCE'):
            process(self.root, 'ar', 'source-morph', self.root/'bad1')
        self.assertFalse((self.root/'bad1/accepted.jsonl').exists())
        path.write_bytes(path.read_bytes()[:-1])
        ledger['sources'][0]['status'] = 'REVIEW_REQUIRED'
        write_json(self.root/'legal/ledger/sources.json', ledger)
        with self.assertRaisesRegex(ContractError, 'BLOCKED_SOURCE'):
            process(self.root, 'ar', 'source-morph', self.root/'bad2')

    def test_resume_mismatched_artifact_is_rejected(self):
        self.make_approved([self.am, self.am])
        first = process(self.root, 'am', 'source-morph', self.root/'am1', max_records=1)
        (self.root/'am1/accepted.jsonl').write_bytes(b'falsified\n')
        with self.assertRaisesRegex(ContractError, 'hash mismatch'):
            process(self.root, 'am', 'source-morph', self.root/'am2', resume_dir=self.root/'am1')

    def test_source_shard_self_asserted_sha_is_rejected(self):
        self.make_approved([self.ar])
        source = self.root/'approved/forms.jsonl'
        raw = json.loads(source.read_text())
        raw['evidence']['source_sha256'] = 'a' * 64
        source.write_text(json.dumps(raw, ensure_ascii=False) + '\n')
        ledger = json.loads((self.root/'legal/ledger/sources.json').read_text())
        ledger['sources'][0]['retrieval']['sha256'] = digest(source.read_bytes())
        write_json(self.root/'legal/ledger/sources.json', ledger)
        with self.assertRaisesRegex(ContractError, 'self-assert'):
            process(self.root, 'ar', 'source-morph', self.root/'bad')

    def test_json_duplicate_fields_and_unsupported_metadata(self):
        from tools.linguistic_extensions.semitic.contract import strict_json
        with self.assertRaises(ContractError):
            strict_json(b'{"a": 1, "a": 2}')
        item = deepcopy(self.ar)
        item['record']['meaning'] = 'made up'
        with self.assertRaises(ContractError):
            self.validate(item)


if __name__ == '__main__':
    unittest.main()
