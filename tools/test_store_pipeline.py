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


    def test_legacy_regular_package_path_remains_valid(self):
        self.packs.mkdir(exist_ok=True)
        raw=b'previously published legacy archive bytes'
        (self.packs/'de.pack.gz').write_bytes(raw)
        meta={'pack_file':'de.pack.gz','size_bytes':len(raw),
              'sha256':hashlib.sha256(raw).hexdigest()}
        compile_store_packs.check_legacy([meta],self.packs)

    def test_legacy_symlink_escape_rejected_even_with_matching_digest(self):
        self.packs.mkdir(exist_ok=True)
        raw=b'outside archive bytes'
        outside=self.root/'outside.pack.gz'
        outside.write_bytes(raw)
        (self.packs/'de.pack.gz').symlink_to(outside)
        meta={'pack_file':'de.pack.gz','size_bytes':len(raw),
              'sha256':hashlib.sha256(raw).hexdigest()}
        with self.assertRaisesRegex(ValueError,'unsafe legacy pack path'):
            compile_store_packs.check_legacy([meta],self.packs)
        self.assertEqual(outside.read_bytes(),raw)

    def test_retained_v2_pack_symlink_escape_fails_before_publication(self):
        self.packs.mkdir(exist_ok=True)
        raw=b'outside retained bytes'
        outside=self.root/'outside.pack.gz'
        outside.write_bytes(raw)
        name='de-1.0.0.pack.gz'
        (self.packs/name).symlink_to(outside)
        previous={'id':'de','version':'1.0.0','archiveSizeBytes':len(raw),
                  'sha256':hashlib.sha256(raw).hexdigest(),
                  'archiveUrl':f'{compile_store_packs.REPO_CDN}/{name}'}
        self.manifest.write_text(json.dumps({'languages':[],'packs':[previous]}),encoding='utf-8')
        before=self.manifest.read_bytes()
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unsafe retained package path',result.stderr)
        self.assertEqual(self.manifest.read_bytes(),before)
        self.assertEqual(outside.read_bytes(),raw)

    def test_existing_new_archive_symlink_escape_fails_closed(self):
        self.packs.mkdir(exist_ok=True)
        raw=b'outside candidate archive bytes'
        outside=self.root/'outside.pack.gz'
        outside.write_bytes(raw)
        (self.packs/'de-1.0.0.pack.gz').symlink_to(outside)
        before=self.manifest.read_bytes()
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unsafe output package path',result.stderr)
        self.assertEqual(self.manifest.read_bytes(),before)
        self.assertEqual(outside.read_bytes(),raw)


    def test_external_source_symlink_fails_closed_without_publication(self):
        original=self.manifest.read_bytes()
        outside=self.root/'external-fixture.json'
        outside.write_text(json.dumps(fixture_doc('de'),ensure_ascii=False),encoding='utf-8')
        (self.sources/'de.json').unlink()
        (self.sources/'de.json').symlink_to(outside)
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unsafe source path',result.stderr)
        self.assertEqual(self.manifest.read_bytes(),original)
        self.assertFalse(self.packs.exists())
        self.assertTrue(outside.is_file())

    def test_internal_source_symlink_is_accepted(self):
        nested=self.sources/'approved-symlink-target'
        nested.mkdir()
        (self.sources/'de.json').rename(nested/'de.json')
        (self.sources/'de.json').symlink_to(nested/'de.json')
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.packs/'de-1.0.0.pack.gz').is_file())

    def test_manifest_symlink_rejected_before_reading_or_publishing(self):
        external=self.root/'external-manifest.json'
        external.write_text('{"languages":[]}',encoding='utf-8')
        saved=external.read_bytes()
        self.manifest.unlink()
        self.manifest.symlink_to(external)
        result=self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('symlinked manifest',result.stderr)
        self.assertEqual(external.read_bytes(),saved)
        self.assertFalse(self.packs.exists())

    def test_atomic_write_rejects_existing_symlink_even_if_bytes_match(self):
        outside=self.root/'outside-content.bin'
        outside.write_bytes(b'unchanged sensitive original')
        link=self.root/'symlinked-manifest.json'
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'symlinked output'):
            compile_store_packs.atomic_write(link,b'unchanged sensitive original')
        self.assertEqual(outside.read_bytes(),b'unchanged sensitive original')
        self.assertTrue(link.is_symlink())

if __name__=='__main__':
    unittest.main()
