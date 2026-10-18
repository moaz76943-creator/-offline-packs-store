"""Fail-closed agglutinative extension: no project corpus is shipped as a fixture."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.linguistic_extensions.agglutinative.engine import Extension, EvidenceError

BASE = Path(__file__).resolve().parents[3]
TARGETS = ('tr','az','uz','kk','ky','tk','tt','ba','ug','fi','et','hu','mn','eu')


def fixture_root():
    root = Path(tempfile.mkdtemp())
    (root/'catalog').mkdir()
    (root/'standards/morphology').mkdir(parents=True)
    (root/'legal/ledger/daily').mkdir(parents=True)
    (root/'tools/linguistic_extensions/agglutinative/shards/tr').mkdir(parents=True)
    source = json.loads((BASE/'catalog/language_registry.v1.json').read_text(encoding='utf-8'))
    (root/'catalog/language_registry.v1.json').write_text(json.dumps(source), encoding='utf-8')
    src = json.loads((BASE/'standards/morphology/feature_overrides.json').read_text(encoding='utf-8'))
    (root/'standards/morphology/feature_overrides.json').write_text(json.dumps(src), encoding='utf-8')
    (root/'legal/ledger/sources.json').write_text('{"schema_version":"1.0.0","sources":[]}', encoding='utf-8')
    (root/'legal/ledger/admission.py').write_text(
        (BASE/'legal/ledger/admission.py').read_text(encoding='utf-8'), encoding='utf-8')
    (root/'legal/ledger/license_notice.py').write_text(
        (BASE/'legal/ledger/license_notice.py').read_text(encoding='utf-8'), encoding='utf-8')
    return root


def sample_form():
    # Purely synthetic structural record, not a real language attestation.
    return {'language_code':'tr','lemma_id':'tr:synthetic:1','sense_id':'tr:synthetic:concept',
            'lemma':'örnek','form':'örnek','script':'Latn','features':{'number':'singular'},
            'morphemes':[{'kind':'stem','surface':'örnek','position':0}],
            'evidence':{'status':'verified','generated':False,'source_id':'fixture','dataset_version':'v-test',
                        'artifact_sha256':'a'*64,'attestation_id':'fixture-1'}}


def approved_fixture(root, record):
    """Entirely synthetic, temporary Route 05-shaped evidence; never public data."""
    path='tools/linguistic_extensions/agglutinative/shards/tr/fixture.jsonl'
    raw=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
    (root/path).write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    (root/'test_evidence').mkdir(exist_ok=True)
    snapshot=b'synthetic source file bytes only - not a licensed dictionary'
    (root/'test_evidence/source.bin').write_bytes(snapshot)
    original_sha=hashlib.sha256(snapshot).hexdigest()
    license_bytes=b'fictional source-specific rights evidence for unit testing only'
    (root/'test_evidence/license.txt').write_bytes(license_bytes)
    notice='fixture synthetic-test CC0-1.0 https://example.invalid/source'
    (root/'test_evidence/notice.txt').write_text(notice,encoding='utf-8')
    source={'source_id':'fixture','kind':'morphology',
            'origin_url':'https://example.invalid/source',
            'publisher':'synthetic-test',
            'dataset_version':'v-test','status':'APPROVED_FOR_REDISTRIBUTION',
            'retrieval':{'identity':'synthetic-v1','url':'https://example.invalid/download',
                         'date':'2026-10-13','artifact_path':'test_evidence/source.bin',
                         'sha256':original_sha},
            'license':{'id':'CC0-1.0',
                       'evidence_url':'https://example.invalid/source/rights',
                       'evidence_path':'test_evidence/license.txt',
                       'evidence_sha256':hashlib.sha256(license_bytes).hexdigest()},
            'alterations':['none - synthetic test fixture'],
            'review':{'reviewer':'test-only','decision_url':'https://example.invalid/review'}}
    (root/'legal/ledger/sources.json').write_text(json.dumps({
        'schema_version':'1.0.0','sources':[source]}),encoding='utf-8')
    # Match the artificial per-record fingerprint to this artificial source.
    record['evidence']['artifact_sha256']=original_sha
    raw=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
    (root/path).write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    daily={'schema_version':'1.0.0','date':'2026-10-13',
           'release_candidates':[{'asset_id':'fixture',
               'kind':'morphology','artifact_path':path,'sha256':digest,
               'source_refs':[{'source_id':'fixture','dataset_version':'v-test',
                               'artifact_sha256':original_sha}],
               'output_license_id':'CC0-1.0','compiler_license_id':'test-only',
               'notices':{'fixture':'test_evidence/notice.txt'},
               'compliance':{},'provenance_mode':'source_set',
               'record_provenance_reason':'unit-test synthetic one-source shard only',
               'review':{'reviewer':'test-only',
                         'decision_url':'https://example.invalid/review'}}]}
    (root/'legal/ledger/daily/2026-10-13.json').write_text(
        json.dumps(daily),encoding='utf-8')
    return path,digest

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.root=fixture_root()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.root))

    def test_languages_are_registered_independently(self):
        ext=Extension(self.root)
        self.assertEqual(set(TARGETS),set(ext.languages))
        self.assertEqual('Isolate',ext.profile('eu')['family'])
        self.assertEqual('Mongolic',ext.profile('mn')['family'])
        self.assertEqual(['Arab','Cyrl'],ext.profile('ug')['scripts'])
        self.assertEqual(['Cyrl','Mong'],ext.profile('mn')['scripts'])
        self.assertEqual('canonical_declared',ext.profile('tr')['dimensions']['vowel_harmony'])
        self.assertEqual('unknown',ext.profile('uz')['dimensions']['vowel_harmony'])
        self.assertNotEqual(ext.profile('fi')['model'],ext.profile('et')['model'])
        self.assertNotEqual(ext.profile('et')['model'],ext.profile('hu')['model'])
        self.assertEqual('unknown',ext.profile('eu')['dimensions']['ergativity'])

    def test_no_approved_source_is_not_data(self):
        ext=Extension(self.root)
        path='tools/linguistic_extensions/agglutinative/shards/tr/nope.jsonl'
        (self.root/path).write_text(json.dumps(sample_form())+'\n',encoding='utf-8')
        with self.assertRaises(EvidenceError): ext.audit('tr',path)
        self.assertEqual('unknown',ext.lookup('tr','tr:synthetic:1')['status'])

    def test_verified_shard_coverage_checkpoint_and_query(self):
        path,digest=approved_fixture(self.root,sample_form())
        ext=Extension(self.root)
        result=ext.audit('tr',path)
        self.assertEqual(digest,result['checkpoint_sha256'])
        self.assertEqual(1,result['lemmas'])
        self.assertEqual(1,result['forms'])
        self.assertIn('number',result['covered_dimensions'])
        self.assertIn('case',result['unknown_dimensions'])
        self.assertEqual(['örnek'],[x['form'] for x in ext.lookup('tr','tr:synthetic:1',shard=path)['forms']])
        self.assertEqual('unknown',ext.lookup('tr','tr:synthetic:1',features={'case':'ergative'},shard=path)['status'])
        self.assertEqual('unknown',ext.lookup('tr','tr:another:1',shard=path)['status'])

    def test_generated_rejected_even_if_source_approved(self):
        record=sample_form(); record['evidence']['generated']=True
        path,_=approved_fixture(self.root,record)
        with self.assertRaisesRegex(EvidenceError,'generated'): Extension(self.root).audit('tr',path)

    def test_wrong_script_and_cross_language_rejected(self):
        record=sample_form(); record['script']='Cyrl'
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)
        record=sample_form(); record['lemma_id']='az:synthetic:1'
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)

    def test_evidence_mismatch_and_tamper_rejected(self):
        path,_=approved_fixture(self.root,sample_form())
        (self.root/path).write_text('{}\n',encoding='utf-8')
        with self.assertRaisesRegex(EvidenceError,'checkpoint'): Extension(self.root).audit('tr',path)
        path,_=approved_fixture(self.root,sample_form())
        record=sample_form(); record['evidence']['dataset_version']='wrong'
        # Tampering with the file while fixing the candidate checksum should still fail provenance.
        p=self.root/path; raw=(json.dumps(record,ensure_ascii=False)+'\n').encode(); p.write_bytes(raw)
        daily=self.root/'legal/ledger/daily/2026-10-13.json'; obj=json.loads(daily.read_text());
        obj['release_candidates'][0]['sha256']=hashlib.sha256(raw).hexdigest();daily.write_text(json.dumps(obj))
        with self.assertRaisesRegex(EvidenceError,'provenance'): Extension(self.root).audit('tr',path)

    def test_corrupted_original_source_bytes_fail_closed(self):
        path,_=approved_fixture(self.root,sample_form())
        (self.root/'test_evidence/source.bin').write_bytes(b'source bytes mutated')
        with self.assertRaisesRegex(EvidenceError,'canonical rights admission blocked'):
            Extension(self.root).audit('tr',path)

    def test_corrupted_license_evidence_fails_closed(self):
        path,_=approved_fixture(self.root,sample_form())
        (self.root/'test_evidence/license.txt').write_bytes(b'changed rights proof')
        with self.assertRaisesRegex(EvidenceError,'canonical rights admission blocked'):
            Extension(self.root).audit('tr',path)

    def test_false_approval_strings_cannot_replace_review_evidence(self):
        path,_=approved_fixture(self.root,sample_form())
        ledger=self.root/'legal/ledger/sources.json'
        doc=json.loads(ledger.read_text(encoding='utf-8'))
        doc['sources'][0]['status']='APPROVED_FOR_REDISTRIBUTION'
        doc['sources'][0]['license']['evidence_url']='https://creativecommons.org/publicdomain/zero/1.0/'
        ledger.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(EvidenceError,'canonical rights admission blocked'):
            Extension(self.root).audit('tr',path)

    def test_morpheme_positions_and_unknown_fields_rejected(self):
        record=sample_form();record['morphemes']=[{'kind':'suffix','surface':'x','position':1},{'kind':'stem','surface':'y','position':0}]
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)
        record=sample_form();record['features']={'invented_universal_case':'x'}
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)

    def test_duplicate_json_and_path_traversal_rejected(self):
        ext=Extension(self.root)
        with self.assertRaises(EvidenceError): ext.audit('tr','../legal/ledger/sources.json')
        path,_=approved_fixture(self.root,sample_form())
        raw=(json.dumps(sample_form(),ensure_ascii=False).replace('"script": "Latn"','"script": "Latn", "script":"Latn"')+'\n').encode()
        (self.root/path).write_bytes(raw)
        x=json.loads((self.root/'legal/ledger/daily/2026-10-13.json').read_text());x['release_candidates'][0]['sha256']=hashlib.sha256(raw).hexdigest()
        (self.root/'legal/ledger/daily/2026-10-13.json').write_text(json.dumps(x))
        with self.assertRaises(EvidenceError): ext.audit('tr',path)

    def test_unicode_nfc_and_variant_identity(self):
        record=sample_form();record['form']='o\u0308rnek'
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)
        record=sample_form();record['script']='Latn';record['variant']='az-Latn'
        path,_=approved_fixture(self.root,record)
        with self.assertRaises(EvidenceError): Extension(self.root).audit('tr',path)

if __name__=='__main__': unittest.main()
