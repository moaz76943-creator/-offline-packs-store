"""Fixture-only isolated E2E checks; never modify live packages/manifest."""
import argparse
import base64
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import compile_store_packs

SCRIPT=Path(__file__).with_name('compile_store_packs.py')
LANGUAGES={'de':('Haus','Latn','ltr'),'ar':('بيت','Arab','rtl'),
           'en':('house','Latn','ltr'),'es':('casa','Latn','ltr'),
           'fr':('maison','Latn','ltr')}


def fixture_doc(language):
    word,script,direction=LANGUAGES[language]
    origin='https://example.org/fixtures-only'
    source={'source_id':'fixture.demo','origin_url':origin,'publisher':'Self-authored synthetic test',
            'dataset_version':'1','retrieval_id':'synthetic:1','license_id':'LicenseRef-SyntheticTestFixture',
            'record_locator':'illustration','publication_approved':False,'fixture_only':True,
            'artifact_sha256':None}
    lex='lex.'+language+'.one'
    sense='sense.'+language+'.one'
    return {'contract_version':'1.0.0','document_id':'fixture.'+language+'.only',
       'lexemes':[{'lexeme_id':lex,'language':language,'script':script,'lemma':word,
                   'surface':word,'pos':'noun','direction':direction,'source':source}],
       'senses':[{'sense_id':sense,'lexeme_id':lex,'concept_id':'concept.'+language+'.house',
                  'definition':word,'source':source}],
       'examples':[{'example_id':'example.'+language+'.one','sense_id':sense,
                    'language':language,'script':script,'text':word+'.','source':source}],
       'relations':[],'translations':[]}


class StorePipelineTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.sources=self.root/'sources'
        self.sources.mkdir()
        self.packs=self.root/'packs'
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text('{"languages":[]}',encoding='utf-8')
        self.write('de',fixture_doc('de'))

    def write(self,language,doc):
        (self.sources/(language+'.json')).write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')

    def invoke(self,*opts,fixture=True):
        cmd=[sys.executable,str(SCRIPT),'--source-dir',str(self.sources),
             '--output-dir',str(self.packs),'--manifest',str(self.manifest)]
        if fixture:cmd.append('--fixture-only')
        return subprocess.run([*cmd,*opts],capture_output=True,text=True,timeout=35)

    def unpack(self,lang):
        raw=(self.packs/(lang+'-1.0.0.pack.gz')).read_bytes()
        envelope=json.loads(gzip.decompress(raw))
        members={r['path']:base64.b64decode(r['contentBase64'],validate=True) for r in envelope['files']}
        return raw,envelope,members

    def test_five_pilot_languages_real_fts_and_metadata(self):
        for lang in LANGUAGES:self.write(lang,fixture_doc(lang))
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        for lang,(word,_,_) in LANGUAGES.items():
            raw,envelope,files=self.unpack(lang)
            self.assertEqual(envelope['packId'],lang)
            self.assertEqual(set(files),{'content/content.json','content/content.sqlite','metadata/pack.json'})
            desc=json.loads(files['content/content.json'])
            meta=json.loads(files['metadata/pack.json'])
            self.assertEqual(desc['tableCounts']['lexicon'],1)
            self.assertEqual(desc['tableCounts']['examples'],1)
            self.assertTrue(desc['fixtureOnly'])
            self.assertEqual(meta['contentSha256'],hashlib.sha256(files['content/content.sqlite']).hexdigest())
            self.assertEqual(meta['contentMetadataSha256'],hashlib.sha256(files['content/content.json']).hexdigest())
            dbpath=self.root/(lang+'.sqlite')
            dbpath.write_bytes(files['content/content.sqlite'])
            with sqlite3.connect(dbpath) as conn:
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)
                self.assertTrue(conn.execute('SELECT 1 FROM lexicon_fts WHERE lexicon_fts MATCH ?',('"'+word+'"',)).fetchone())
                self.assertEqual(conn.execute('SELECT count(*) FROM lexemes').fetchone()[0],1)
            record={i['id']:i for i in json.loads(self.manifest.read_text())['packs']}[lang]
            self.assertEqual(record['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(record['installedSizeBytes'],sum(map(len,files.values())))

    def test_repeat_build_deterministic_and_preserves_old_valid_pack(self):
        self.assertEqual(self.invoke().returncode,0)
        old=self.unpack('de')[0]
        before=self.manifest.read_bytes()
        again=self.invoke()
        self.assertEqual(again.returncode,0,again.stderr)
        self.assertEqual(self.manifest.read_bytes(),before)
        self.assertEqual(self.unpack('de')[0],old)
        self.write('ar',fixture_doc('ar'))
        self.assertEqual(self.invoke('--language','ar').returncode,0)
        self.assertEqual(self.unpack('de')[0],old)

    def test_damaged_json_and_mismatched_language_do_not_publish(self):
        self.write('de',fixture_doc('de'))
        self.assertEqual(self.invoke().returncode,0)
        original=self.unpack('de')[0]
        existing=self.manifest.read_bytes()
        (self.sources/'de.json').write_text('{bad JSON',encoding='utf-8')
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(self.unpack('de')[0],original)
        self.assertEqual(self.manifest.read_bytes(),existing)
        self.write('de',fixture_doc('ar'))
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(self.manifest.read_bytes(),existing)

    def test_requires_approved_ledger_by_default(self):
        r=self.invoke(fixture=False)
        self.assertNotEqual(r.returncode,0)
        self.assertFalse(self.packs.exists())

    def test_missing_source_and_no_changes_on_dry_run(self):
        before=self.manifest.read_bytes()
        self.assertEqual(self.invoke('--dry-run').returncode,0)
        self.assertFalse(self.packs.exists())
        self.assertEqual(self.manifest.read_bytes(),before)
        (self.sources/'de.json').unlink()
        self.assertNotEqual(self.invoke().returncode,0)

    def test_bad_existing_hash_fails_closed(self):
        self.assertEqual(self.invoke().returncode,0)
        data=json.loads(self.manifest.read_text())
        data['packs'][0]['sha256']='0'*64
        self.manifest.write_text(json.dumps(data))
        self.write('ar',fixture_doc('ar'))
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.packs/'ar-1.0.0.pack.gz').exists())

    def test_collision_keeps_prior_archive(self):
        self.assertEqual(self.invoke().returncode,0)
        original=self.unpack('de')[0]
        self.write('de',fixture_doc('de'))
        source=fixture_doc('de')
        source['lexemes'][0]['surface']='Haus geändert'
        self.write('de',source)
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('refusing to overwrite',result.stderr)
        self.assertEqual(self.unpack('de')[0],original)

    def test_interrupted_manifest_write_rolls_back_new_package(self):
        self.assertEqual(self.invoke().returncode,0)
        original=self.unpack('de')[0]
        before=self.manifest.read_bytes()
        self.write('ar',fixture_doc('ar'))
        options=argparse.Namespace(fixture_only=True,source_dir=self.sources,
                  output_dir=self.packs,manifest=self.manifest,language=['ar'],dry_run=False)
        real_write=compile_store_packs.atomic_write
        def interrupted(path,data):
            if path==self.manifest:
                raise OSError('simulated interrupted manifest publication')
            return real_write(path,data)
        with patch.object(compile_store_packs,'atomic_write',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'interrupted'):
                compile_store_packs.run(options)
        self.assertFalse((self.packs/'ar-1.0.0.pack.gz').exists())
        self.assertEqual(self.unpack('de')[0],original)
        self.assertEqual(self.manifest.read_bytes(),before)

    def test_grammar_sidecar_content_is_real(self):
        src=fixture_doc('de')['lexemes'][0]['source']
        grammar={'contract_version':'1.0.0','languageCode':'de','rules':[
            {'grammar_id':'grammar.de.test','category':'case','title':'Dative example','source':src,
             'body':'This is a test rule, not production content.'}]}
        (self.sources/'de.grammar.json').write_text(json.dumps(grammar))
        r=self.invoke()
        self.assertEqual(r.returncode,0,r.stderr)
        _,_,inner=self.unpack('de')
        desc=json.loads(inner['content/content.json'])
        self.assertEqual(desc['tableCounts']['grammar'],1)
        path=self.root/'grammar.sqlite'
        path.write_bytes(inner['content/content.sqlite'])
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT title FROM grammar').fetchone()[0],'Dative example')

if __name__=='__main__':
    unittest.main()
