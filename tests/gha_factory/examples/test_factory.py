"""Synthetic structural tests only; no mock source is ever permitted for publication."""
import hashlib
import json
import tempfile
from unittest.mock import patch
import tracemalloc
import unittest
from pathlib import Path

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


if __name__=='__main__':
    unittest.main()
