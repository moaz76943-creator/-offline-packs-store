"""Only synthetic, quarantined negative tests; never constitute production approval."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.factory_extensions.production_acceptance import audit

def put(root,name,obj):
    p=root/name
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')

class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.codes=[chr(97+i//26)+chr(97+i%26) for i in range(100)]
        put(self.root,'catalog/language_registry.v1.json',
            {'languages':[{'id':c} for c in self.codes]})
        put(self.root,'catalog/content_readiness.v1.json',
            {'states':{c:'unverified' for c in self.codes}})
        put(self.root,'manifest.json',
            {'languages':[{'code':c} for c in self.codes],'packs':[]})
        put(self.root,'version.json',
            {'packs':{},'release_status':'BLOCKED_DEPENDENCY'})
        put(self.root,'legal/ledger/sources.json',{'sources':[]})

    def test_registered_languages_are_not_production_ready(self):
        result=audit.snapshot(self.root)
        self.assertEqual(result['registered'],100)
        self.assertEqual(result['status'],'BLOCKED_SOURCE')
        self.assertFalse(result['production_complete_100_languages'])
        self.assertFalse(result['publication_approved'])
        self.assertTrue(all(x['highest_verified_stage']=='REGISTERED'
                            for x in result['languages']))
        self.assertTrue(all(v is None for v in result['languages'][0]['metrics'].values()))

    def test_rejects_fake_published_pack_when_source_ledger_empty(self):
        put(self.root,'manifest.json',
            {'languages':[{'code':c} for c in self.codes],
             'packs':[{'id':self.codes[0]}]})
        with self.assertRaises(audit.AcceptanceError):
            audit.snapshot(self.root)

    def test_rejects_identity_collision(self):
        ids=self.codes.copy()
        ids[-1]=ids[0]
        put(self.root,'catalog/language_registry.v1.json',
            {'languages':[{'id':c} for c in ids]})
        with self.assertRaises(audit.AcceptanceError):
            audit.snapshot(self.root)

    def test_rejects_duplicate_json_fields(self):
        (self.root/'version.json').write_text('{"packs":{},"packs":{}}')
        with self.assertRaises(audit.AcceptanceError):
            audit.snapshot(self.root)

    def test_rejects_traversal(self):
        with self.assertRaises(audit.AcceptanceError):
            audit.safe_file(self.root,'../evil.pack.gz')

    def test_rejects_untrusted_public_key(self):
        key=self.root/'pub.pem'
        key.write_text('not a public key')
        receipt={'payload':{'kind':'lexical','result':'PASS'},
                 'signature':'A'*88}
        with self.assertRaises(audit.AcceptanceError):
            audit.verify_signed(receipt,key,'0'*64,'lexical')

    def test_cryptographic_ed25519_pass_and_tampering_rejection(self):
        if subprocess.run(['which','openssl'],capture_output=True).returncode:
            self.skipTest('openssl unavailable')
        key=self.root/'priv'; pub=self.root/'pub'
        subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],
                       check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],
                       check=True,capture_output=True)
        payload={'kind':'lexical','language':self.codes[0],'result':'PASS'}
        msg=self.root/'msg'; sig=self.root/'sig'
        msg.write_bytes(audit.DOMAIN+audit.canonical(payload))
        subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),
                        '-rawin','-in',str(msg),'-out',str(sig)],
                       check=True,capture_output=True)
        receipt={'payload':payload,'signature':base64.b64encode(sig.read_bytes()).decode()}
        pin=hashlib.sha256(pub.read_bytes()).hexdigest()
        self.assertEqual(audit.verify_signed(receipt,pub,pin,'lexical'),payload)
        receipt['payload']={**payload,'result':'FAIL'}
        with self.assertRaises(audit.AcceptanceError):
            audit.verify_signed(receipt,pub,pin,'lexical')

    def test_blocks_downgrade_and_changed_archive_bytes(self):
        archive=self.root/'candidate.pack.gz'
        archive.write_bytes(b'not-releasable')
        candidate={'language':self.codes[0],'version':'1.0.0',
                   'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                   'fixture_only':False,
                   'source':{'source_id':'source','dataset_version':'v1','sha256':'a'*64}}
        put(self.root,'bundle.json',{'candidate':candidate})
        kwargs={'qa_key':archive,'qa_pin':'a'*64,
                'publisher_key':archive,'publisher_pin':'a'*64}
        with self.assertRaisesRegex(audit.AcceptanceError,'downgrade'):
            audit.evaluate_candidate(self.root,self.root/'bundle.json','candidate.pack.gz',
                                     previous_version='1.0.0',**kwargs)
        candidate['sha256']='b'*64
        put(self.root,'bundle.json',{'candidate':candidate})
        with self.assertRaisesRegex(audit.AcceptanceError,'hash mismatch'):
            audit.evaluate_candidate(self.root,self.root/'bundle.json','candidate.pack.gz',**kwargs)

if __name__=='__main__':
    unittest.main()
