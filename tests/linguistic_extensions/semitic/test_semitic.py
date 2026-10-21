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
                  'components segmentation morphemes script orthographic_variant source_id evidence_version').split()
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

    def optional_claims(self, item):
        claims = item['evidence']['claim_locators']
        for field in ('components', 'segmentation'):
            for index, _ in enumerate(item['record'].get(field, [])):
                claims[f'{field}.{index}'] = 'entry:explicit-claim'
        for index, morpheme in enumerate(item['record'].get('morphemes', [])):
            for field in morpheme:
                claims[f'morphemes.{index}.{field}'] = 'entry:explicit-claim'

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

    def test_exact_homographs_preserve_root_and_pattern_ambiguity(self):
        for field, value in (('root', 'كبت'), ('pattern', 'فَعَل')):
            with self.subTest(field=field):
                other = deepcopy(self.ar)
                other['record'][field] = value
                self.validate(other)
                output = self.root / 'homographs.jsonl'
                output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n'
                                          for x in (self.ar, other)), encoding='utf-8')
                for limit in (1, 100):
                    result = lookup(output, self.root, 'ar', self.ar['record']['form'], limit=limit)
                    self.assertEqual('ambiguous', result['status'])
                    self.assertEqual(2, result['total_analyses'])

    def test_missing_and_explicit_empty_optional_lists_share_analysis(self):
        other = deepcopy(self.ar)
        for name in ('processes', 'components', 'segmentation', 'morphemes'):
            other['record'][name] = []
        # Keep all required locators intact. The two forms are semantically
        # the same even though the optional field representation differs.
        canonical = deepcopy(self.ar)
        canonical['record'].pop('processes', None)
        output = self.root / 'optional-empty.jsonl'
        output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n'
                                  for x in (canonical, other)), encoding='utf-8')
        result = lookup(output, self.root, 'ar', self.ar['record']['form'])
        self.assertEqual('attested', result['status'])
        self.assertEqual(1, result['total_analyses'])

    def test_decomposed_query_selects_its_exact_nfc_analysis(self):
        first = self.record('ar', 'أ', 'أ', 'other', {})
        second = self.record('ar', 'إ', 'إ', 'other', {})
        second['record']['sense_id'] = 'ar:test:other'
        for row in (first, second):
            self.validate(row)
        output = self.root / 'nfc.jsonl'
        output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n'
                                  for x in (first, second)), encoding='utf-8')
        result = lookup(output, self.root, 'ar', '\u0627\u0654')
        self.assertEqual('attested', result['status'])
        self.assertEqual([first], result['forms'])
        self.assertTrue(result['normalization_ambiguous'])

    def test_optional_allomorph_requires_language_script_and_string(self):
        for value in (42, '', 'latin', 'ቤት'):
            item = deepcopy(self.ar)
            item['record']['morphemes'] = [dict(surface='كتب', kind='root', position=0,
                                               allomorph=value)]
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.validate(item)
        for candidate, language, form in ((self.ar, 'ar', 'كتب'), (self.am, 'am', 'ቤት')):
            item = deepcopy(candidate)
            item['record']['morphemes'] = [dict(surface=form, kind='root', position=0,
                                               allomorph=form)]
            self.optional_claims(item)
            self.assertEqual(item, self.validate(item, lang=language))

    def test_optional_decompositions_need_per_claim_locators(self):
        for field, value in (('components', ['كتب']), ('segmentation', ['ك', 'تب']),
                              ('morphemes', [dict(surface='كتب', kind='root', position=0, allomorph='كتب')])):
            item = deepcopy(self.ar)
            item['record'][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.validate(item)
            self.optional_claims(item)
            self.assertEqual(item, self.validate(item))

    def test_attested_process_and_decomposition_differences_are_distinct(self):
        for field, values in (('processes', (['broken_plural'], ['reduplication'])),
                               ('components', (['كتب'], ['كبت'])),
                               ('segmentation', (['ك', 'تب'], ['كت', 'ب'])),
                               ('morphemes', ([dict(surface='كتب', kind='root', position=0)],
                                              [dict(surface='كتب', kind='stem', position=0)]))):
            with self.subTest(field=field):
                rows = [deepcopy(self.ar), deepcopy(self.ar)]
                for row, value in zip(rows, values):
                    row['record'][field] = value
                    if field == 'processes':
                        row['evidence']['claim_locators'].pop('processes.broken_plural')
                        row['evidence']['claim_locators']['processes.' + value[0]] = 'entry:process'
                    self.optional_claims(row)
                    self.validate(row)
                output = self.root / 'decomposition.jsonl'
                output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows), encoding='utf-8')
                result = lookup(output, self.root, 'ar', self.ar['record']['form'], limit=1)
                self.assertEqual('ambiguous', result['status'])
                self.assertEqual(2, result['total_analyses'])

    def test_foreign_combining_marks_rejected_in_each_linguistic_field(self):
        for language, template, mark in (('ar', self.ar, '\u05b0'),
                                          ('am', self.am, '\u064e')):
            for field in ('lemma', 'form', 'root', 'pattern', 'morpheme', 'allomorph'):
                with self.subTest(language=language, field=field):
                    item = deepcopy(template)
                    value = item['record']['form']
                    if field in ('morpheme', 'allomorph'):
                        morpheme = dict(surface=value, kind='stem', position=0)
                        morpheme['surface' if field == 'morpheme' else 'allomorph'] = value + mark
                        item['record']['morphemes'] = [morpheme]
                    else:
                        item['record'][field] = value + mark
                        if field in ('root', 'pattern'):
                            item['record'].setdefault('root', value)
                            item['record'].setdefault('pattern', value)
                            item['evidence']['claim_locators'].update(root='entry:root', pattern='entry:pattern')
                    with self.assertRaises(ContractError):
                        self.validate(item, lang=language)
        item = deepcopy(self.am)
        item['record']['form'] += '\u135f'
        self.validate(item, lang='am')  # Ethiopic combining gemination mark.
        self.validate(self.ar)  # Arabic vowel marks remain valid.

    def test_attested_pos_and_verb_stem_remain_distinct_analyses(self):
        for field in ('part_of_speech', 'verb_stem'):
            with self.subTest(field=field):
                first = self.record('ar', 'كتب', 'كتب', 'other', {})
                other = deepcopy(first)
                other['evidence']['part_of_speech'] = 'verb'
                other['evidence']['verb_stem'] = 'كتب'
                other['evidence']['claim_locators']['verb_stem'] = 'entry:stem'
                if field == 'verb_stem':
                    first = deepcopy(other)
                    other['evidence']['verb_stem'] = 'كتَب'
                self.validate(first)
                self.validate(other)
                output = self.root / 'pos-analyses.jsonl'
                output.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n'
                                          for x in (first, other)), encoding='utf-8')
                result = lookup(output, self.root, 'ar', 'كتب', limit=1)
                self.assertEqual('ambiguous', result['status'])
                self.assertEqual(2, result['total_analyses'])

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

    def test_resume_forged_coverage_counts_is_rejected(self):
        self.make_approved([self.ar, self.ar])
        process(self.root, 'ar', 'source-morph', self.root/'count1', max_records=1)
        checkpoint_path = self.root/'count1/checkpoint.json'
        checkpoint = json.loads(checkpoint_path.read_text())
        checkpoint['total_accepted'] = 9999
        write_json(checkpoint_path, checkpoint)
        with self.assertRaisesRegex(ContractError, 'counter'):
            process(self.root, 'ar', 'source-morph', self.root/'count2',
                    resume_dir=self.root/'count1')

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
