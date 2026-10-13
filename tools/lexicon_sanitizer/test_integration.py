"""Conservative sanitizer integration regressions: synthetic records only."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.lexicon_sanitizer.cli import process_file, stream_json_collections, MAX_JSON_BYTES
from tools.lexicon_sanitizer.engine import (
    LexiconSanitizer, STATUS_ACCEPT, STATUS_QUARANTINE, STATUS_REVIEW_REQUIRED
)


class IdentityIsolationTests(unittest.TestCase):
    def setUp(self):
        self.s = LexiconSanitizer()
        for lid, lang, lemma in (('lex.en','en','book'), ('lex.es','es','libro'),
                                 ('lex.alt','es','tomo'), ('lex.ja','ja','空')):
            self.assertIn(self.s.sanitize_lexeme(
                {'lexeme_id':lid,'language':lang,'lemma':lemma,'pos':'noun'})[0],
                (STATUS_ACCEPT, STATUS_REVIEW_REQUIRED))
        for sid,lid in (('sense.en','lex.en'), ('sense.es','lex.es'),
                        ('sense.alt','lex.alt'), ('sense.ja','lex.ja')):
            self.assertEqual(STATUS_ACCEPT,self.s.sanitize_sense(
                {'sense_id':sid,'lexeme_id':lid,'concept_id':'concept.'+sid})[0])

    def tearDown(self):
        self.s.close()

    def tr(self,tid, from_id='sense.en', to_id='sense.es', lang='es', text='libro', source=True):
        rec={'translation_id':tid,'from_sense_id':from_id,'to_sense_id':to_id,
             'language':lang,'text':text}
        if source:
            rec['source']={'source_id':'src.fixture','license_id':'CC0-1.0',
                           'dataset_version':'1.0','record_locator':'row-1'}
        return rec

    def test_forward_and_reverse_need_independent_target_identity(self):
        self.assertEqual(STATUS_ACCEPT,self.s.sanitize_translation(self.tr('t.1'))[0])
        self.assertEqual(STATUS_ACCEPT,self.s.sanitize_translation(
            self.tr('t.2',from_id='sense.es',to_id='sense.en',lang='en',text='book'))[0])

    def test_reverse_conflicting_target_is_quarantined(self):
        status,_,reason=self.s.sanitize_translation(self.tr('wrong',from_id='sense.es',
                                                           to_id='sense.en',lang='es'))
        self.assertEqual(STATUS_QUARANTINE,status)
        self.assertIn('directed pair',reason)

    def test_translation_different_target_sense_stays_independent(self):
        self.assertEqual(STATUS_ACCEPT,self.s.sanitize_translation(self.tr('t.one'))[0])
        self.assertEqual(STATUS_ACCEPT,self.s.sanitize_translation(
            self.tr('t.two',to_id='sense.alt'))[0])

    def test_duplicate_translation_identity_review_not_deleted(self):
        self.s.sanitize_translation(self.tr('t.one'))
        self.assertEqual(STATUS_REVIEW_REQUIRED,self.s.sanitize_translation(self.tr('t.two'))[0])

    def test_missing_source_and_unresolved_senses_never_admitted(self):
        self.assertEqual(STATUS_REVIEW_REQUIRED,self.s.sanitize_translation(
            self.tr('t.a',source=False))[0])
        self.assertEqual(STATUS_REVIEW_REQUIRED,self.s.sanitize_translation(
            self.tr('t.b',from_id='unknown.sense'))[0])

    def test_cross_language_stable_id_collision_rejected(self):
        self.assertEqual(STATUS_ACCEPT,self.s.sanitize_translation(self.tr('t.dup'))[0])
        self.assertEqual(STATUS_QUARANTINE,self.s.sanitize_translation(
            self.tr('t.dup',to_id='sense.alt'))[0])

    def test_surrogate_quarantine_hash_is_reversible(self):
        record={'lexeme_id':'bad','language':'en','lemma':chr(0xD800),'pos':'noun'}
        self.assertEqual(STATUS_QUARANTINE,self.s.sanitize_lexeme(record)[0])
        self.assertRegex(self.s.compute_hash(record),r'^[a-f0-9]{64}$')

    def test_diacritics_and_cjk_lexical_forms_are_not_collapsed(self):
        a=self.s.sanitize_lexeme({'lexeme_id':'ar.1','language':'ar','lemma':'كِتاب','pos':'noun'})
        b=self.s.sanitize_lexeme({'lexeme_id':'ar.2','language':'ar','lemma':'كتاب','pos':'noun'})
        self.assertEqual((STATUS_ACCEPT,STATUS_ACCEPT),(a[0],b[0]))
        self.assertEqual(STATUS_REVIEW_REQUIRED,self.s.sanitize_lexeme(
            {'lexeme_id':'lex.ja.other','language':'ja','lemma':'空','pos':'noun'})[0])


class JsonlAndDiskTests(unittest.TestCase):
    def test_large_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'large.json'
            with f.open('wb') as out:
                out.truncate(MAX_JSON_BYTES+1)
            with self.assertRaisesRegex(ValueError,'Oversized JSON'):
                list(stream_json_collections(f))

    def test_jsonl_correctly_routes_sense_foreign_key(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'rows.jsonl'
            rows=[{'lexeme_id':'lex.en','language':'en','lemma':'book','pos':'noun'},
                  {'sense_id':'sense.en','lexeme_id':'lex.en','concept_id':'concept.book'}]
            src.write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8')
            out=Path(d)/'out'; quarantine=Path(d)/'quarantine'
            self.assertTrue(process_file(src,out,quarantine,Path(__file__).resolve().parents[2]))
            result=(out/src.name).read_text(encoding='utf-8').splitlines()
            self.assertEqual(2,len(result))
            self.assertEqual('sense.en',json.loads(result[1])['sense_id'])
            self.assertEqual('',(quarantine/'rows_quarantined.jsonl').read_text(encoding='utf-8'))

    def test_jsonl_quarantine_preserves_original_reviewable_record(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'rows.jsonl'
            src.write_text(json.dumps({'lexeme_id':'lex.a','language':'en',
                                       'lemma':'word','pos':'noun'})+'\n'
                           +json.dumps({'lexeme_id':'lex.b','language':'en',
                                        'lemma':'word','pos':'noun'})+'\n',encoding='utf-8')
            out=Path(d)/'out'; quarantine=Path(d)/'quarantine'
            self.assertTrue(process_file(src,out,quarantine,Path(__file__).resolve().parents[2]))
            rows=(out/src.name).read_text(encoding='utf-8').splitlines()
            quarantined=(quarantine/'rows_quarantined.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(2,len(rows))
            self.assertEqual(1,len(quarantined))
            self.assertEqual('lex.b',json.loads(quarantined[0])['original']['lexeme_id'])

    def test_input_never_overwritten_as_output(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'rows.jsonl';src.write_text('{}\n',encoding='utf-8')
            orig=src.read_bytes()
            self.assertFalse(process_file(src,Path(d),Path(d)/'quarantine',Path(__file__).resolve().parents[2]))
            self.assertEqual(orig,src.read_bytes())


if __name__ == '__main__':
    unittest.main()
