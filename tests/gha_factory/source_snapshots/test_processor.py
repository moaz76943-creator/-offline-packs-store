"""Synthetic-only source snapshot contract tests: never fetch real corpora."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.gha_factory.source_snapshots import processor as p

def h(b):return hashlib.sha256(b).hexdigest()

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'catalog').mkdir()
        (self.root/'legal/ledger').mkdir(parents=True)
        (self.root/'proof.txt').write_bytes(b'rights fixture')
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({
            'schema_version':'1.0.0','languages':[{'id':'de','default_script':'Latn'}]}))
        self.data=(b'{"lang_code":"de","word":"Baum","pos":"noun","senses":[{"glosses":["tree"]}]}\n'
                   b'{"lang_code":"de","word":"Brot","pos":"noun","senses":[{"glosses":["bread"]}]}\n'
                   b'{malformed\n'
                   b'{"lang_code":"de","word":"Apfel","pos":"noun","senses":[{"glosses":["apple"]}]}\n')
        self.zip=gzip.compress(self.data,mtime=0)
        (self.root/'not-committed').mkdir()
        (self.root/'not-committed/snapshot.gz').write_bytes(self.zip)
        self.src={'source_id':'synthetic-only','kind':'dictionary','status':'APPROVED_FOR_REDISTRIBUTION',
            'dataset_version':'test','publisher':'synthetic','origin_url':'https://fixtures.example.test/origin',
            'retrieval':{'identity':'test','url':'https://fixtures.example.test/snapshot.gz',
                'date':'2026-01-01','sha256':h(self.zip),'artifact_path':'not-committed/snapshot.gz'},
            'license':{'id':'CC0-1.0','evidence_url':'https://fixtures.example.test/rights',
                'evidence_path':'proof.txt','evidence_sha256':h(b'rights fixture')},
            'review':{'reviewer':'test-only','decision_url':'https://fixtures.example.test/decision'},
            'alterations':['none']}
        self.save()
    def save(self):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps({'schema_version':'1.0.0','sources':[self.src]}))
    def job(self):return p.approved(self.root,'synthetic-only','de','test')
    def test_rights_fail_closed(self):
        self.src['status']='REVIEW_REQUIRED';self.save()
        with self.assertRaises(p.Blocked):self.job()
        self.src['status']='APPROVED_FOR_REDISTRIBUTION'
        self.src['license']['evidence_sha256']='0'*64;self.save()
        with self.assertRaises(p.Blocked):self.job()
    def test_https_and_redirect_preconditions(self):
        for url in ['http://fixtures.example.test/x','https://127.0.0.1/x',
                    'https://fixtures.example.test.evil.org/x','https://user@fixtures.example.test/x',
                    'https://fixtures.example.test:8080/x']:
            with self.assertRaises(p.Blocked):p.reviewed_url(url,'fixtures.example.test')
    def test_complete_hash_and_deterministic_partition(self):
        source=self.job()
        f=self.root/'data.gz';f.write_bytes(self.zip)
        out=self.root/'output'
        report=p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2)
        self.assertEqual((report['real_input_rows'],report['accepted_rows'],report['rejected_rows']),(4,3,1))
        self.assertEqual(len(report['partitions']),2)
        self.assertEqual(p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2),report)
        (out/'part-00000000.jsonl').write_text('corruption')
        with self.assertRaises(p.Blocked):p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz',shard_rows=2)
    def test_incomplete_or_corrupt_source_and_abandoned_stage(self):
        source=self.job()
        f=self.root/'data.gz';f.write_bytes(b'partial')
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',len(self.zip),fmt='jsonl.gz')
        f.write_bytes(self.zip)
        (self.root/'out').mkdir()
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',len(self.zip),fmt='jsonl.gz')
    def test_missing_reviewed_artifact_blocks_even_with_approved_ledger(self):
        (self.root/'not-committed/snapshot.gz').unlink()
        with self.assertRaises(p.Blocked):self.job()
    def test_wrong_language_and_empty_lexical_senses_rejected(self):
        lines=(b'{"lang_code":"de","word":"Apfel","pos":"noun","senses":[{"glosses":["apple"]}]}\n'
               b'{"lang_code":"fr","word":"pomme","pos":"noun","senses":[{"glosses":["apple"]}]}\n'
               b'{"lang_code":"de","word":"Apfel","pos":"noun","senses":[]}\n')
        self.zip=gzip.compress(lines,mtime=0)
        (self.root/'not-committed/snapshot.gz').write_bytes(self.zip)
        self.src['retrieval']['sha256']=h(self.zip);self.save()
        source=self.job()
        result=p.partitions(self.root/'not-committed/snapshot.gz',source,self.root/'shards',len(self.zip),fmt='jsonl.gz')
        self.assertEqual((result['real_input_rows'],result['accepted_rows'],result['rejected_rows']),(3,1,2))
    def test_tampered_receipt_and_reject_symlink(self):
        src=self.job()
        f=self.root/'file';f.write_bytes(self.zip)
        out=self.root/'verified'
        result=p.partitions(f,src,out,len(self.zip),fmt='jsonl.gz')
        receipt=out/'receipt.json'
        tampered=dict(result,source_id='unreviewed')
        receipt.write_text(json.dumps(tampered))
        with self.assertRaises(p.Blocked):p.partitions(f,src,out,len(self.zip),fmt='jsonl.gz')
        receipt.write_text(json.dumps(result))
        (out/'rejects.jsonl').unlink()
        (out/'rejects.jsonl').symlink_to(self.root/'proof.txt')
        with self.assertRaises(p.Blocked):p.partitions(f,src,out,len(self.zip),fmt='jsonl.gz')
    def test_download_closed_without_queue_lease(self):
        with self.assertRaisesRegex(p.Blocked,'BLOCKED_DEPENDENCY_GHA02'):
            p.download({'host':'fixtures.example.test','url':'https://fixtures.example.test/a'},self.root/'down',100)
    def test_source_hash_tampering_blocks(self):
        source=self.job()
        f=self.root/'file';f.write_bytes(self.zip+b'extra')
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'shards',len(self.zip),fmt='jsonl.gz')

    def test_malformed_existing_receipt_counters_fail_closed(self):
        source=self.job()
        f=self.root/'file';f.write_bytes(self.zip)
        out=self.root/'shards'
        original=p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz')
        tampered=dict(original,accepted_rows='3')
        (out/'receipt.json').write_text(json.dumps(tampered))
        with self.assertRaises(p.Blocked):
            p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz')
    def test_bad_checkpoint_receipt_fails_closed(self):
        source=self.job()
        f=self.root/'file';f.write_bytes(self.zip)
        out=self.root/'shards'
        original=p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz')
        tampered=dict(original,checkpoint=dict(original['checkpoint'],last_row=99999999))
        (out/'receipt.json').write_text(json.dumps(tampered))
        with self.assertRaises(p.Blocked):
            p.partitions(f,source,out,len(self.zip),fmt='jsonl.gz')
    def test_corrupt_compressed_input_fails_closed(self):
        corrupt=self.zip[:-4]+b'XXXX'
        self.src['retrieval']['sha256']=h(corrupt);self.save()
        (self.root/'not-committed/snapshot.gz').write_bytes(corrupt)
        source=self.job()
        with self.assertRaises(p.Blocked):
            p.partitions(self.root/'not-committed/snapshot.gz',source,self.root/'shards',len(corrupt),fmt='jsonl.gz')

    def test_streamed_25001_rows_have_deterministic_shard_counts(self):
        one=b'{"lang_code":"de","word":"Baum","pos":"noun","senses":[{"glosses":["tree"]}]}\n'
        payload=gzip.compress(one*25001,mtime=0)
        (self.root/'not-committed/snapshot.gz').write_bytes(payload)
        self.src['retrieval']['sha256']=h(payload);self.save()
        source=self.job()
        report=p.partitions(self.root/'not-committed/snapshot.gz',source,self.root/'out',len(payload),fmt='jsonl.gz')
        self.assertEqual((report['real_input_rows'],report['accepted_rows'],report['rejected_rows']),(25001,25001,0))
        self.assertEqual([x['rows'] for x in report['partitions']],[10000,10000,5001])
    def test_arabic_utf8_is_preserved_byte_for_byte(self):
        (self.root/'catalog/language_registry.v1.json').write_text(json.dumps({
            'schema_version':'1.0.0','languages':[{'id':'ar','default_script':'Arab'}]}))
        line=(json.dumps({'lang_code':'ar','word':'كتاب','pos':'noun','senses':[{'glosses':['مؤلَّف مكتوب']}]},
                         ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        payload=gzip.compress(line,mtime=0)
        (self.root/'not-committed/snapshot.gz').write_bytes(payload)
        self.src['retrieval']['sha256']=h(payload);self.save()
        source=p.approved(self.root,'synthetic-only','ar','test')
        report=p.partitions(self.root/'not-committed/snapshot.gz',source,self.root/'out',len(payload),fmt='jsonl.gz')
        self.assertEqual(report['accepted_rows'],1)
        self.assertEqual((self.root/'out/part-00000000.jsonl').read_bytes(),line)
    def test_bounded_decompression_halts_before_expansion(self):
        source=self.job()
        f=self.root/'data.gz';f.write_bytes(self.zip)
        with self.assertRaises(p.Blocked):
            p.partitions(f,source,self.root/'out',len(self.zip),fmt='jsonl.gz',max_expand=24)

    def test_empty_corpus_not_ready(self):
        source=self.job();source['source_sha256']=h(b'')
        f=self.root/'empty';f.write_bytes(b'')
        with self.assertRaises(p.Blocked):p.partitions(f,source,self.root/'out',0)


    def test_reject_symlinked_parent_of_input_or_output(self):
        source=self.job()
        alias=self.root/'alias'
        alias.symlink_to(self.root/'not-committed',target_is_directory=True)
        with self.assertRaisesRegex(p.Blocked,'symlink'):
            p.partitions(alias/'snapshot.gz',source,self.root/'out',len(self.zip),fmt='jsonl.gz')
        (self.root/'destination').mkdir()
        output_link=self.root/'output-link'
        output_link.symlink_to(self.root/'destination',target_is_directory=True)
        with self.assertRaisesRegex(p.Blocked,'symlink'):
            p.partitions(self.root/'not-committed/snapshot.gz',source,
                         output_link/'out',len(self.zip),fmt='jsonl.gz')
        self.assertFalse((self.root/'destination/out').exists())

    def test_reject_symlinked_license_evidence_parent(self):
        link=self.root/'proof-link'
        link.symlink_to(self.root,target_is_directory=True)
        self.src['license']['evidence_path']='proof-link/proof.txt'
        self.save()
        with self.assertRaises(p.Blocked):
            self.job()

    def test_replay_rejects_unlisted_or_missing_files(self):
        source=self.job()
        file=self.root/'not-committed/snapshot.gz'
        out=self.root/'out'
        p.partitions(file,source,out,len(self.zip),fmt='jsonl.gz')
        (out/'unlisted-copy.jsonl').write_bytes((out/'part-00000000.jsonl').read_bytes())
        with self.assertRaisesRegex(p.Blocked,'unexpected/duplicate'):
            p.partitions(file,source,out,len(self.zip),fmt='jsonl.gz')
        (out/'unlisted-copy.jsonl').unlink()
        (out/'part-00000000.jsonl').unlink()
        with self.assertRaises(p.Blocked):
            p.partitions(file,source,out,len(self.zip),fmt='jsonl.gz')

    def test_replay_rejects_forged_publication_and_counts(self):
        source=self.job()
        file=self.root/'not-committed/snapshot.gz'
        out=self.root/'out'
        original=p.partitions(file,source,out,len(self.zip),fmt='jsonl.gz')
        receipt=out/'receipt.json'
        for change in ({'publication_approved':True},
                       {'schema_version':'unreviewed'},
                       {'expanded_bytes':-1},
                       {'rejected_rows':0,'accepted_rows':4}):
            receipt.write_text(json.dumps(dict(original,**change)))
            with self.assertRaises(p.Blocked):
                p.partitions(file,source,out,len(self.zip),fmt='jsonl.gz')

    def test_independent_stage_reproduces_exact_receipt_and_bytes(self):
        source=self.job()
        file=self.root/'not-committed/snapshot.gz'
        first=self.root/'replay-first'
        second=self.root/'replay-second'
        a=p.partitions(file,source,first,len(self.zip),fmt='jsonl.gz',shard_rows=2)
        b=p.partitions(file,source,second,len(self.zip),fmt='jsonl.gz',shard_rows=2)
        self.assertEqual(a,b)
        self.assertEqual({x.name:x.read_bytes() for x in first.iterdir()},
                         {x.name:x.read_bytes() for x in second.iterdir()})
        self.assertEqual(a['status'],'STAGED_ONLY')
        self.assertFalse(a['publication_approved'])

if __name__=='__main__':unittest.main()
