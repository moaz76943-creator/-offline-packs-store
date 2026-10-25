"""Synthetic structural tests only; no mock source is ever permitted for publication."""
import hashlib
import json
import tempfile
from unittest.mock import patch
import tracemalloc
import unittest
from pathlib import Path

import tools.gha_factory.examples.factory as example_factory

from tools.gha_factory.examples.factory import (MAX_LINE, Rejected, bounded_tsv, digest,
    make_cloze, run, source_approval, source_path, verified_catalog)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'snapshots'
        self.source.mkdir()
        self.out = self.root / 'output'
        self.catalog = self.root / 'manifest.json'
        self.ledger = self.root / 'ledger.json'
        self.config = self.root / 'job.json'
        self.catalog.write_text(json.dumps({'languages': [
            {'code': code} for code in ['ar', 'de', 'en', 'es', 'fr'] +
            [f'zz{i:03d}' for i in range(95)]]}), encoding='utf-8')
        self.ledger.write_text(json.dumps({'schema_version': '1.0.0', 'sources': []}))
        self.write_snapshot('detailed',
            '1\tdeu\tGuten Morgen!\twriterDE\t2026\t2026\n'
            '2\tara\tصباح الخير!\twriterAR\t2026\t2026\n'
            '3\teng\tGood morning!\twriterEN\t2026\t2026\n'
            '4\tspa\t¡Buenos días!\twriterES\t2026\t2026\n'
            '5\tfra\tBonjour !\twriterFR\t2026\t2026\n')
        self.write_snapshot('cc0', '1\tdeu\tGuten Morgen!\t2026\n2\tara\tصباح الخير!\t2026\n')
        self.write_snapshot('links', '1\t2\n2\t1\n1\t3\n3\t1\n4\t5\n5\t4\n')
        self.job = {'source_id': 'tatoeba', 'snapshots': self.snapshots, 'language_map': {}}
        self.save_config()

    def write_snapshot(self, name, content):
        path = self.source / (name + '.tsv')
        path.write_text(content, encoding='utf-8')
        if not hasattr(self, 'snapshots'):
            self.snapshots = {}
        self.snapshots[name] = {'path': name + '.tsv', 'sha256': digest(path)}

    def save_config(self):
        self.config.write_text(json.dumps(self.job), encoding='utf-8')

    def process(self):
        return run(self.source, self.config, self.catalog, self.ledger, self.out,
                   partition_size=2, deadline_seconds=10)

    def test_direct_reciprocal_links_preserve_arabic_and_origins(self):
        report = self.process()
        self.assertEqual(report['counts']['translation_pairs_verified'], 3)
        self.assertEqual(report['counts']['arabic_direct_pairs'], 1)
        self.assertEqual(report['counts']['candidate_sentences'], 5)
        self.assertEqual(report['published'], 0)
        self.assertEqual(report['source_admission'], 'BLOCKED_DEPENDENCY_GHA01')
        records = [json.loads(line) for f in sorted((self.out/'verified_candidates').glob('*.jsonl'))
                   for line in f.read_text(encoding='utf8').splitlines()]
        self.assertEqual({(r['source']['sentence_id'],r['target']['sentence_id']) for r in records},
                         {('1','2'),('1','3'),('4','5')})
        self.assertEqual(records[0]['target']['text'], 'صباح الخير!')
        self.assertEqual(records[0]['source']['license'], 'CC0-1.0')
        self.assertTrue(records[0]['target']['origin_url'].endswith('/2'))
        self.assertEqual(report['audio_license_status'], 'METADATA_ONLY_NO_AUDIO_APPROVED')

    def test_unreciprocated_link_is_not_verified(self):
        self.write_snapshot('links', '1\t2\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        self.assertEqual(self.process()['counts'].get('translation_pairs_verified', 0), 0)

    def test_indirect_translations_are_not_invented(self):
        self.write_snapshot('links','1\t2\n2\t1\n2\t3\n3\t2\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        result = self.process()
        self.assertEqual(result['counts']['translation_pairs_verified'], 2)
        pairs = {(json.loads(line)['source']['sentence_id'],json.loads(line)['target']['sentence_id'])
                 for f in (self.out/'verified_candidates').glob('*.jsonl')
                 for line in f.read_text().splitlines()}
        self.assertNotIn(('1','3'),pairs)

    def test_wrong_script_and_unknown_language_rejected(self):
        self.write_snapshot('detailed', '1\tdeu\tصباح الخير\twriter\t2026\t2026\n'
                           '2\tfoo\tHello!\twriter\t2026\t2026\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        result = self.process()
        self.assertEqual(result['counts']['rejected_wrong_or_unmapped_language'], 2)
        self.assertEqual(result['counts'].get('candidate_sentences',0),0)

    def test_duplicate_sentence_ids_rejected(self):
        self.write_snapshot('detailed','1\tdeu\tHallo!\twriter\t2026\t2026\n'
                            '1\tdeu\tHallo!\twriter\t2026\t2026\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        self.assertEqual(self.process()['counts']['rejected_duplicate_sentence_id'],1)

    def test_audio_licenses_are_independent_of_sentence_text(self):
        self.write_snapshot('audio','1\t100\treader\t\thttps://tatoeba.org/a/100\n'
                            '1\t101\treader\tCC BY-NC 4.0\thttps://tatoeba.org/a/101\n'
                            '1\t102\treader\tCC BY 4.0\thttps://tatoeba.org/a/102\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        report = self.process()
        self.assertEqual(report['counts']['excluded_audio_licensing'],2)
        self.assertEqual(report['counts']['licensed_audio_metadata_only'],1)
        self.assertEqual(report['published'],0)

    def test_modified_snapshot_is_rejected(self):
        (self.source/'links.tsv').write_text('1\t2\n')
        with self.assertRaisesRegex(Rejected,'SHA-256 mismatch'):
            self.process()

    def test_path_escape_is_rejected(self):
        with self.assertRaisesRegex(Rejected, 'unsafe'):
            source_path(self.source, {'path':'../secret.tsv','sha256':'0'*64})

    def test_explicit_mapping_into_100_identities(self):
        mapping = verified_catalog(self.catalog, {'zzz':'zz005'})
        self.assertEqual(mapping['zzz'],'zz005')
        with self.assertRaisesRegex(Rejected,'remapped'):
            verified_catalog(self.catalog, {'deu':'ar'})

    def test_empty_route05_ledger_blocks_approval(self):
        self.assertFalse(source_approval(self.ledger,'tatoeba',self.snapshots['cc0']['sha256']))

    def test_route05_approval_requires_well_formed_evidence_and_rows(self):
        approved = {
            'source_id': 'tatoeba', 'kind': 'examples',
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'license': {'id': 'CC0-1.0', 'evidence_sha256': 'b' * 64,
                        'evidence_url': 'https://example.org/license'},
            'retrieval': {'sha256': self.snapshots['cc0']['sha256'],
                          'identity': 'pinned-cc0-export',
                          'url': 'https://example.org/export'},
            'review': {'reviewer': 'test-reviewer',
                       'decision_url': 'https://example.org/review'},
        }

        def write_sources(rows):
            self.ledger.write_text(json.dumps(
                {'schema_version': '1.0.0', 'sources': rows}), encoding='utf-8')

        write_sources([approved])
        self.assertTrue(source_approval(
            self.ledger, 'tatoeba', self.snapshots['cc0']['sha256']))

        # An arbitrary nonempty string is not an evidence SHA-256.
        bad_digest = dict(approved, license=dict(approved['license'], evidence_sha256='bogus'))
        write_sources([bad_digest])
        self.assertFalse(source_approval(
            self.ledger, 'tatoeba', self.snapshots['cc0']['sha256']))

        # Malformed ledger records and nested evidence must fail closed with
        # a classified error, never an uncaught AttributeError/TypeError.
        malformed = [
            [None],
            [dict(approved, license=['CC0-1.0'])],
            [dict(approved, retrieval=dict(approved['retrieval'],
                                            url=['https://example.org/export']))],
            [dict(approved, review=dict(approved['review'],
                                         decision_url=['https://example.org/review']))],
        ]
        for rows in malformed:
            with self.subTest(rows=rows):
                write_sources(rows)
                with self.assertRaisesRegex(Rejected, 'malformed Route 05 ledger'):
                    source_approval(self.ledger, 'tatoeba',
                                    self.snapshots['cc0']['sha256'])

    def test_malformed_and_oversized_tsv_lines(self):
        p = self.source/'malformed.tsv'
        p.write_bytes(b'1\tx\n'+b'a'*40000+b'\n'+b'\xff\tfoo\n')
        lines=list(bounded_tsv(p,2))
        self.assertIsNone(lines[1][1])
        self.assertIsNotNone(lines[2][2])

    def test_oversized_tsv_line_has_bounded_memory_and_preserves_next_row(self):
        path = self.source / 'giant.tsv'
        path.write_bytes(b'x' * (MAX_LINE * 128) + b'\n2\tvalid\n')
        tracemalloc.start()
        try:
            rows = list(bounded_tsv(path, 2))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(rows, [(1, None, 'oversized_line'), (2, ['2', 'valid'], None)])
        self.assertLess(peak, MAX_LINE * 8)

    def test_tsv_line_byte_limit_and_crlf_are_preserved(self):
        path = self.source / 'limits.tsv'
        accepted = b'1\t' + b'x' * (MAX_LINE - 4) + b'\r\n'
        rejected = b'2\t' + b'x' * (MAX_LINE - 3) + b'\r\n'
        path.write_bytes(accepted + rejected + '3\tصحيح\n'.encode())
        rows = list(bounded_tsv(path, 2))
        self.assertEqual(rows[0], (1, ['1', 'x' * (MAX_LINE - 4)], None))
        self.assertEqual(rows[1], (2, None, 'oversized_line'))
        self.assertEqual(rows[2], (3, ['3', 'صحيح'], None))

    def test_oversized_tsv_line_without_newline_is_rejected_once(self):
        path = self.source / 'unterminated.tsv'
        path.write_bytes(b'x' * (MAX_LINE * 3))
        self.assertEqual(list(bounded_tsv(path, 2)), [(1, None, 'oversized_line')])

    def test_failed_retry_keeps_last_complete_candidate_set(self):
        """An interrupted import must not destroy an earlier verified candidate set."""
        self.process()
        before = {p.relative_to(self.out).as_posix(): digest(p)
                  for p in self.out.rglob('*') if p.is_file()}
        original_reader = bounded_tsv

        def interrupted_links(path, columns):
            for row in original_reader(path, columns):
                yield row
                if columns == 2:
                    raise Rejected('simulated interrupted link import')

        with patch('tools.gha_factory.examples.factory.bounded_tsv',
                   side_effect=interrupted_links):
            with self.assertRaisesRegex(Rejected, 'interrupted link'):
                self.process()
        after = {p.relative_to(self.out).as_posix(): digest(p)
                 for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_failed_jsonl_write_keeps_last_complete_candidate_set(self):
        """A write failure after one pair must not publish a partial JSONL part."""
        self.process()
        before = {p.relative_to(self.out).as_posix(): digest(p)
                  for p in self.out.rglob('*') if p.is_file()}
        original_writer = example_factory.canonical

        def interrupted_writer(obj):
            if (isinstance(obj, dict) and
                    obj.get('link_proof') == 'tatoeba_explicit_reciprocal' and
                    obj['target']['sentence_id'] == '3'):
                raise Rejected('simulated interrupted JSONL write')
            return original_writer(obj)

        with patch('tools.gha_factory.examples.factory.canonical',
                   side_effect=interrupted_writer):
            with self.assertRaisesRegex(Rejected, 'interrupted JSONL'):
                self.process()
        after = {p.relative_to(self.out).as_posix(): digest(p)
                 for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_source_symlink_inside_workspace_is_rejected(self):
        alias = self.source / 'alias.tsv'
        alias.symlink_to('detailed.tsv')
        with self.assertRaisesRegex(Rejected, 'symlink'):
            source_path(self.source, {
                'path': 'alias.tsv', 'sha256': digest(self.source / 'detailed.tsv')})

    def test_multi_thousand_row_tsv_import_with_invalid_tail(self):
        path = self.source / 'detailed.tsv'
        data = ''.join(
            f'{i}\tdeu\tGuten Tag {i}!\twriter\t2026\t2026\n'
            for i in range(1, 4097))
        path.write_bytes(data.encode('utf-8') + b'\xff\tbroken\n')
        self.snapshots['detailed']['sha256'] = digest(path)
        self.job['snapshots'] = self.snapshots
        self.save_config()
        report = run(self.source, self.config, self.catalog, self.ledger, self.out,
                     partition_size=1024, deadline_seconds=10)
        self.assertEqual(report['counts']['candidate_sentences'], 4096)
        self.assertEqual(report['counts']['rejected_sentences'], 1)
        self.assertEqual(report['counts'].get('translation_pairs_verified', 0), 0)
        self.assertEqual(list((self.out / 'verified_candidates').glob('*.jsonl')), [])

    def test_deterministic_partitions_and_checkpoint(self):
        a = self.process()
        before = [(x.name,digest(x)) for x in sorted((self.out/'verified_candidates').glob('*.jsonl'))]
        b = self.process()
        after = [(x.name,digest(x)) for x in sorted((self.out/'verified_candidates').glob('*.jsonl'))]
        self.assertEqual(before,after)
        self.assertEqual(a['checkpoint'],b['checkpoint'])

    def test_cloze_requires_attested_morphology_and_editorial_review(self):
        text = 'I read books.'
        row = {'id':'42','language':'en','text':text,'admitted':True,'attribution':'fixture only'}
        ann={'sentence_id':'42','language':'en','sentence_sha256':sha(text),
             'editorial_unambiguous':True,'editor_review_url':'https://example.org/editor',
             'start':2,'end':6,'sense_id':'sense.read','lexeme_id':'lex.read',
             'features':{'tense':'present','person':'first'},
             'distractors':[{'surface':'write','sense_id':'sense.write'},
                            {'surface':'paint','sense_id':'sense.paint'}]}
        senses={f'sense.{w}':{'language':'en','lexeme_id':'lex.'+w,'approved':True}
                for w in ('read','write','paint')}
        forms={('en','sense.'+w,w,(('person','first'),('tense','present'))) for w in ('read','write','paint')}
        result=make_cloze(row,ann,senses,forms)
        self.assertEqual(result['cloze'],'I ____ books.')
        self.assertEqual(len(result['options']),3)
        self.assertEqual(result['status'],'VERIFIED_CANDIDATE_NOT_PUBLISHED')
        ann['distractors'][0]['surface']='read'
        with self.assertRaisesRegex(Rejected,'unsupported or ambiguous distractor'):
            make_cloze(row,ann,senses,forms)

    def test_cloze_rejects_repeated_answer_or_missing_sense(self):
        sentence={'id':'6','language':'en','text':'go, go!','admitted':True}
        ann={'sentence_id':'6','language':'en','sentence_sha256':sha('go, go!'),
             'editorial_unambiguous':True,'editor_review_url':'https://example.org/r',
             'start':0,'end':2,'sense_id':'s','lexeme_id':'l','features':{'tense':'present'},
             'distractors':[{'surface':'x','sense_id':'x'},{'surface':'y','sense_id':'y'}]}
        with self.assertRaisesRegex(Rejected,'ambiguous answer'):
            make_cloze(sentence,ann,{},set())
        sentence['text']='go!'
        ann['sentence_sha256']=sha('go!')
        with self.assertRaisesRegex(Rejected,'unapproved lexical sense'):
            make_cloze(sentence,ann,{},set())


    def test_cloze_rejects_attested_alternative_of_the_answer_sense(self):
        text = 'I read books.'
        sentence = {'id': '42', 'language': 'en', 'text': text, 'admitted': True}
        ann = {'sentence_id': '42', 'language': 'en', 'sentence_sha256': sha(text),
               'editorial_unambiguous': True, 'editor_review_url': 'https://example.org/review',
               'start': 2, 'end': 6, 'sense_id': 's.read', 'lexeme_id': 'l.read',
               'features': {'tense': 'present'},
               'distractors': [{'surface': 'reading', 'sense_id': 's.read'},
                               {'surface': 'write', 'sense_id': 's.write'}]}
        senses = {'s.read': {'language': 'en', 'lexeme_id': 'l.read', 'approved': True},
                  's.write': {'language': 'en', 'lexeme_id': 'l.write', 'approved': True}}
        forms = {('en', sid, surface, (('tense', 'present'),))
                 for sid, surface in [('s.read', 'read'), ('s.read', 'reading'),
                                      ('s.write', 'write')]}
        # Before the fix, 'reading' was accepted as a distractor even though
        # it is attested as the answer's own sense.
        with self.assertRaisesRegex(Rejected, 'ambiguous distractor'):
            make_cloze(sentence, ann, senses, forms)

    def test_cloze_rejects_nfc_equivalent_distractor_from_other_sense(self):
        text = 'café is open.'
        sentence = {'id': '43', 'language': 'en', 'text': text, 'admitted': True}
        ann = {'sentence_id': '43', 'language': 'en', 'sentence_sha256': sha(text),
               'editorial_unambiguous': True, 'editor_review_url': 'https://example.org/review',
               'start': 0, 'end': 4, 'sense_id': 's.cafe', 'lexeme_id': 'l.cafe',
               'features': {'number': 'singular'},
               'distractors': [{'surface': 'cafe\u0301', 'sense_id': 's.other'},
                               {'surface': 'write', 'sense_id': 's.write'}]}
        senses = {'s.cafe': {'language': 'en', 'lexeme_id': 'l.cafe', 'approved': True},
                  's.other': {'language': 'en', 'lexeme_id': 'l.other', 'approved': True},
                  's.write': {'language': 'en', 'lexeme_id': 'l.write', 'approved': True}}
        forms = {('en', sid, surface, (('number', 'singular'),))
                 for sid, surface in [('s.cafe', 'café'), ('s.other', 'cafe\u0301'),
                                      ('s.write', 'write')]}
        # NFC-equivalent strings are one visible answer even across distinct IDs.
        with self.assertRaisesRegex(Rejected, 'ambiguous distractor'):
            make_cloze(sentence, ann, senses, forms)

    def test_cloze_rejects_unhashable_distractor_sense_id(self):
        text = 'I read books.'
        sentence = {'id': '44', 'language': 'en', 'text': text, 'admitted': True}
        ann = {'sentence_id': '44', 'language': 'en', 'sentence_sha256': sha(text),
               'editorial_unambiguous': True, 'editor_review_url': 'https://example.org/review',
               'start': 2, 'end': 6, 'sense_id': 's.read', 'lexeme_id': 'l.read',
               'features': {'tense': 'present'},
               'distractors': [{'surface': 'write', 'sense_id': ['s.write']},
                               {'surface': 'paint', 'sense_id': 's.paint'}]}
        senses = {'s.read': {'language': 'en', 'lexeme_id': 'l.read', 'approved': True}}
        forms = {('en', 's.read', 'read', (('tense', 'present'),))}
        with self.assertRaisesRegex(Rejected, 'ambiguous distractor'):
            make_cloze(sentence, ann, senses, forms)

    def test_cloze_rejects_canonically_equivalent_distractor(self):
        # Synthetic exact-form evidence: NFC-equivalent alternatives are not
        # distinct answer choices, even if separately attested.
        for answer, alternate, language in [
            ('Äpfel', 'A\u0308pfel', 'de'),
            ('Café', 'Cafe\u0301', 'fr'),
        ]:
            with self.subTest(language=language):
                text = answer + '!'
                features = {'number': 'singular'}
                ann = {
                    'sentence_id': '41', 'language': language,
                    'sentence_sha256': sha(text), 'editorial_unambiguous': True,
                    'editor_review_url': 'https://example.org/review',
                    'start': 0, 'end': len(answer),
                    'sense_id': 'sense.answer', 'lexeme_id': 'lex.answer',
                    'features': features,
                    'distractors': [
                        {'surface': alternate, 'sense_id': 'sense.alternate'},
                        {'surface': 'other', 'sense_id': 'sense.other'},
                    ],
                }
                senses = {
                    'sense.answer': {'language': language, 'lexeme_id': 'lex.answer', 'approved': True},
                    'sense.alternate': {'language': language, 'lexeme_id': 'lex.alternate', 'approved': True},
                    'sense.other': {'language': language, 'lexeme_id': 'lex.other', 'approved': True},
                }
                tags = tuple(sorted(features.items()))
                forms = {
                    (language, 'sense.answer', answer, tags),
                    (language, 'sense.alternate', alternate, tags),
                    (language, 'sense.other', 'other', tags),
                }
                sentence = {'id': '41', 'language': language, 'text': text,
                            'admitted': True}
                with self.assertRaisesRegex(Rejected, 'unsupported or ambiguous distractor'):
                    make_cloze(sentence, ann, senses, forms)

    def test_cloze_rejects_canonically_equivalent_second_span(self):
        # A second visual occurrence can be canonically equivalent even when
        # str.count(answer) sees only one byte-distinct spelling.
        for answer, alternate, language in [
            ('café', 'cafe\u0301', 'fr'),
            ('Äpfel', 'A\u0308pfel', 'de'),
            ('أ', 'ا\u0654', 'ar'),
        ]:
            with self.subTest(language=language):
                text = answer + ' ' + alternate
                tags = (('number', 'singular'),)
                sentence = {'id': 'nfc-span', 'language': language,
                            'text': text, 'admitted': True}
                annotation = {
                    'sentence_id': 'nfc-span', 'language': language,
                    'sentence_sha256': sha(text),
                    'editorial_unambiguous': True,
                    'editor_review_url': 'https://example.org/review',
                    'start': 0, 'end': len(answer),
                    'sense_id': 's.answer', 'lexeme_id': 'l.answer',
                    'features': dict(tags),
                    'distractors': [
                        {'surface': 'other1', 'sense_id': 's.other1'},
                        {'surface': 'other2', 'sense_id': 's.other2'},
                    ],
                }
                senses = {
                    's.answer': {'language': language, 'lexeme_id': 'l.answer', 'approved': True},
                    's.other1': {'language': language, 'lexeme_id': 'l.other1', 'approved': True},
                    's.other2': {'language': language, 'lexeme_id': 'l.other2', 'approved': True},
                }
                forms = {(language, sid, surface, tags)
                         for sid, surface in [
                             ('s.answer', answer), ('s.other1', 'other1'),
                             ('s.other2', 'other2')]}
                with self.assertRaisesRegex(Rejected, 'ambiguous answer span'):
                    make_cloze(sentence, annotation, senses, forms)

    def test_cc0_import_enforces_record_budget_before_detailed_rows(self):
        # Synthetic oversized CC0 fixture: must fail in the CC0 phase, not
        # continue indexing until the unrelated detailed-file budget fires.
        self.write_snapshot('cc0', '1\tdeu\tHallo\t2026\n'
                            '2\tara\tمرحبا\t2026\n'
                            '3\teng\tHello\t2026\n')
        self.job['snapshots'] = self.snapshots
        self.save_config()
        with patch.object(example_factory, 'MAX_RECORDS', 2):
            with self.assertRaisesRegex(Rejected, 'CC0 worker budget exhausted'):
                self.process()
        self.assertFalse(self.out.exists())

    def test_pair_serialization_obeys_deadline_and_keeps_prior_output(self):
        # Time expires immediately after the first reciprocal pair is written.
        # A successful prior generation must survive the aborted retry.
        self.process()
        before = {p.relative_to(self.out).as_posix(): digest(p)
                  for p in self.out.rglob('*') if p.is_file()}
        expired = [False]
        original = example_factory.canonical

        def expire_after_first_pair(obj):
            if isinstance(obj, dict) and obj.get('link_proof') == 'tatoeba_explicit_reciprocal':
                expired[0] = True
            return original(obj)

        def clock():
            return 20 if expired[0] else 0

        with patch.object(example_factory, 'canonical', side_effect=expire_after_first_pair), \
             patch.object(example_factory.time, 'monotonic', side_effect=clock):
            with self.assertRaisesRegex(Rejected, 'pair worker budget exhausted'):
                self.process()
        after = {p.relative_to(self.out).as_posix(): digest(p)
                 for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__=='__main__':
    unittest.main()
