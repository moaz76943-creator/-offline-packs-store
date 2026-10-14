"""Admission invariants: synthetic fixtures ONLY; never production corpus."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))
from tools.gha_factory.admission.pipeline import (admit, AdmissionError, SOURCE_SCHEMA,
                                                  load_reviews,registered_languages)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'legal/ledger').mkdir(parents=True)
        (self.root / 'input').mkdir()
        (self.root/'catalog').mkdir()
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({'schema_version':'1.0.0','languages':[{'id':x,'default_script':'Arab' if x=='ar' else 'Latn'} for x in ('de','ar','en','es','fr')]}))
        self.raw = b'{"lang_code":"de","word":"Haus","pos":"noun","senses":[{"glosses":["home"]}]}\n'
        (self.root/'input/raw.jsonl').write_bytes(self.raw)
        self.evidence = b'Publisher states original dataset is CC0 1.0; synthetic fixture only.\n'
        (self.root/'input/license.txt').write_bytes(self.evidence)
        self.source = {
            'source_id':'test-owner-fixture','kind':'dictionary',
            'origin_url':'https://example.org/dataset', 'publisher':'Fixture Author',
            'dataset_version':'fixture-v1',
            'retrieval':{'identity':'fixture-immutable','url':'https://example.org/raw.jsonl',
                         'date':'2026-10-13','artifact_path':'input/raw.jsonl','sha256':sha(self.raw)},
            'license':{'id':'CC0-1.0','evidence_url':'https://example.org/dataset/LICENSE',
                       'evidence_path':'input/license.txt','evidence_sha256':sha(self.evidence)},
            'status':'APPROVED_FOR_REDISTRIBUTION','alterations':['none'],
            'review':{'reviewer':'fixture-reviewer','decision_url':'https://example.org/decision/1'}
        }
        self._ledger()

    def _ledger(self):
        (self.root/'legal/ledger/sources.json').write_text(
            json.dumps({'schema_version':'1.0.0','sources':[self.source]}),encoding='utf-8')

    def run_admit(self, **kwargs):
        ver=kwargs.pop('dataset_version_override','fixture-v1')
        return admit(repo_root=self.root, source_id='test-owner-fixture',
                     input_path=self.root/'input/raw.jsonl',out_dir=self.root/'out',
                     language='de',dataset_version=ver,
                     format_name='wiktextract-jsonl',part_size=1,**kwargs)

    def test_accepted_fixture_is_partitioned_and_queue_is_discoverable(self):
        report=self.run_admit()
        self.assertEqual(report['actual_accepted_records'],1)
        self.assertEqual(report['status'],'ACCEPTED_FOR_QUEUE')
        job=report['jobs'][0]
        self.assertEqual(job['source_id'],'test-owner-fixture')
        self.assertEqual(job['record_count'],1)
        self.assertTrue((self.root/'out'/job['path']).is_file())
        self.assertEqual(job['sha256'],sha((self.root/'out'/job['path']).read_bytes()))
        self.assertEqual((self.root/'out/queue.json').exists(),True)
        self.assertEqual(json.loads((self.root/'out/queue.json').read_text())['jobs'][0]['resume_id'],job['resume_id'])

    def test_source_not_approved_is_blocked_without_output(self):
        self.source['status']='REVIEW_REQUIRED';self._ledger()
        with self.assertRaisesRegex(AdmissionError,'BLOCKED_SOURCE'):
            self.run_admit()
        self.assertFalse((self.root/'out').exists())

    def test_missing_license_evidence_rejected(self):
        (self.root/'input/license.txt').unlink()
        with self.assertRaisesRegex(AdmissionError,'license evidence'):
            self.run_admit()

    def test_mismatched_source_hash_rejected(self):
        (self.root/'input/raw.jsonl').write_bytes(self.raw + b'\n')
        with self.assertRaisesRegex(AdmissionError,'source hash'):
            self.run_admit()

    def test_unapproved_version_rejected(self):
        with self.assertRaisesRegex(AdmissionError,'version'):
            self.run_admit(dataset_version_override='fixture-v2')

    def test_invalid_utf8_and_malformed_jsonl_rejected_atomically(self):
        for raw in (b'\xff\n',b'{not json}\n',b'\xef\xbb\xbf{}\n',b'[]\n'):
            with self.subTest(raw=raw):
                (self.root/'input/raw.jsonl').write_bytes(raw)
                self.source['retrieval']['sha256']=sha(raw);self._ledger()
                with self.assertRaises(AdmissionError):self.run_admit()
                self.assertFalse((self.root/'out').exists())

    def test_wrong_language_and_missing_language_rejected(self):
        for row in ({'lang_code':'fr','word':'Maison','pos':'noun','senses':[{'glosses':['house']}]},
                    {'word':'Haus','pos':'noun','senses':[{'glosses':['house']}]}) :
            with self.subTest(row=row):
                raw=(json.dumps(row)+'\n').encode();(self.root/'input/raw.jsonl').write_bytes(raw)
                self.source['retrieval']['sha256']=sha(raw);self._ledger()
                with self.assertRaisesRegex(AdmissionError,'language'):self.run_admit()

    def test_license_change_on_record_rejected(self):
        raw=b'{"lang_code":"de","word":"Haus","pos":"noun","license_id":"CC-BY-NC-4.0","senses":[{"glosses":["home"]}]}\n'
        (self.root/'input/raw.jsonl').write_bytes(raw)
        self.source['retrieval']['sha256']=sha(raw);self._ledger()
        with self.assertRaisesRegex(AdmissionError,'record license'):self.run_admit()

    def test_raw_audio_and_sentence_fields_not_admitted_as_licensed_media(self):
        row={'lang_code':'de','word':'Haus','pos':'noun','sounds':[{'audio':'file.ogg'}],
             'senses':[{'glosses':['home'],'examples':[{'text':"Some other author's sentence"}]}]}
        raw=(json.dumps(row)+'\n').encode();(self.root/'input/raw.jsonl').write_bytes(raw)
        self.source['retrieval']['sha256']=sha(raw);self._ledger()
        report=self.run_admit()
        accepted=json.loads((self.root/'out'/report['jobs'][0]['path']).read_text())
        self.assertNotIn('sounds',accepted['content'])
        self.assertNotIn('examples',accepted['content'])
        self.assertEqual(accepted['excluded_categories'],['examples','human_audio'])

    def test_repeat_fresh_run_has_identical_resume_ids(self):
        first=self.run_admit()['jobs'][0]['resume_id']
        (self.root/'out').rename(self.root/'old')
        second=self.run_admit()['jobs'][0]['resume_id']
        self.assertEqual(first,second)

    def test_no_overwrite_existing_queue(self):
        self.run_admit()
        with self.assertRaisesRegex(AdmissionError,'already exists'):self.run_admit()

    def test_route05_unsupported_family_fails_closed(self):
        self.source['license']['id']='CC-BY-SA-3.0';self._ledger()
        with self.assertRaisesRegex(AdmissionError,'Route 05'):
            self.run_admit()

    def test_wrong_script_is_not_silently_accepted(self):
        raw='{"lang_code":"de","word":"بيت","pos":"noun","senses":[{"glosses":["home"]}]}\n'.encode()
        (self.root/'input/raw.jsonl').write_bytes(raw)
        self.source['retrieval']['sha256']=sha(raw);self._ledger()
        with self.assertRaisesRegex(AdmissionError,'script'):self.run_admit()

    def test_record_source_id_must_match_approved_identity(self):
        raw=b'{"source_id":"another-dataset","lang_code":"de","word":"Haus","pos":"noun","senses":[{"glosses":["home"]}]}\n'
        (self.root/'input/raw.jsonl').write_bytes(raw)
        self.source['retrieval']['sha256']=sha(raw);self._ledger()
        with self.assertRaisesRegex(AdmissionError,'source identity'):self.run_admit()

    def test_all_100_catalog_identifiers_supported_when_registered(self):
        ids=['de','ar','en','es','fr']+['test-lang-'+str(i) for i in range(95)]
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({
            'schema_version':'1.0.0',
            'languages':[{'id':x,'default_script':'Arab' if x=='ar' else 'Latn'} for x in ids]}))
        self.assertEqual(registered_languages(self.root),frozenset(ids))
        self.assertEqual(len(registered_languages(self.root)),100)

    def test_reviews_never_mark_sources_approved(self):
        reviewed=load_reviews(HERE/'docs/gha_factory/provenance/reviewed_sources.json')
        self.assertGreaterEqual(len(reviewed['sources']),6)
        self.assertFalse(any(s['status']=='APPROVED_FOR_REDISTRIBUTION' for s in reviewed['sources']))
        self.assertFalse(any(s.get('artifact_sha256') for s in reviewed['sources']))


    def test_symlinked_legal_proof_rejected_even_with_matching_hash(self):
        (self.root / 'input/license-link.txt').symlink_to('license.txt')
        self.source['license']['evidence_path'] = 'input/license-link.txt'
        self._ledger()
        with self.assertRaisesRegex(AdmissionError, 'symlink'):
            self.run_admit()
        self.assertFalse((self.root / 'out').exists())

    def test_cc0_metadata_with_noncommercial_notice_rejected_without_queue(self):
        self.evidence = b'Official license: Attribution-NonCommercial-ShareAlike 4.0\n'
        (self.root / 'input/license.txt').write_bytes(self.evidence)
        self.source['license']['evidence_sha256'] = sha(self.evidence)
        self._ledger()
        with self.assertRaisesRegex(AdmissionError, 'license notice conflicts'):
            self.run_admit()
        self.assertFalse((self.root / 'out').exists())

if __name__=='__main__': unittest.main()
