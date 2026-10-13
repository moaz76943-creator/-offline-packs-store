"""Integration regressions for bounded, conservative deduplication (synthetic only)."""
import io
import unittest
from tools.corpus_dedupe.cli import process_stream
from tools.corpus_dedupe.dedupe import CorpusDeduplicator


def record(i, *, lang='ar', lemma='كِتاب', concept='concept.book', lic='CC0-1.0',
           src='src.fixture', script='Arab', sense='book', approved=True):
    return {'lexeme_id': f'lex.{i}', 'language':lang, 'script':script, 'pos':'noun',
            'lemma':lemma, 'senses':[{'concept_id':concept, 'definition':sense}],
            'source':{'source_id':src,'license_id':lic,'dataset_version':'1',
                      'record_locator':str(i),'publication_approved':approved}}


class DiskBackedContractTests(unittest.TestCase):
    def run_rows(self, rows):
        admitted = {'src.fixture': ('CC0-1.0', '1'), 'src.other': ('CC0-1.0', '1')}
        with CorpusDeduplicator(admitted_source_licenses=admitted) as dedup:
            for row in rows: dedup.process_record(row)
            return list(dedup.iter_resolved())

    def test_exact_with_provenance_can_dedupe_and_preserves_sources(self):
        a,b=record('a'),record('b',src='src.other')
        results=self.run_rows([b,a])
        self.assertEqual(['canonical','duplicate'],[kind for kind,_ in results])
        self.assertEqual('src.other',results[1][1]['source']['source_id'])
        self.assertEqual('src.fixture',results[1][1]['canonical_source']['source_id'])
        self.assertEqual('lex.b',results[1][1]['original_record']['lexeme_id'])

    def test_self_asserted_rights_without_admission_never_remove(self):
        with CorpusDeduplicator(admitted_source_licenses={}) as d:
            d.process_record(record('a'))
            d.process_record(record('b'))
            results=list(d.iter_resolved())
        self.assertEqual(2,sum(kind=='canonical' for kind,_ in results))

    def test_missing_license_never_dedupes(self):
        results=self.run_rows([record('a',lic=''),record('b',lic='')])
        self.assertEqual(2,sum(kind=='canonical' for kind,_ in results))
        self.assertTrue(any(x.get('status')=='REVIEW_REQUIRED' for _,x in results))

    def test_conflicting_license_does_not_dedupe(self):
        results=self.run_rows([record('a'),record('b',lic='CC-BY-4.0')])
        self.assertEqual(2,sum(kind=='canonical' for kind,_ in results))

    def test_language_and_script_isolation(self):
        results=self.run_rows([record('a'),record('b',lang='fa'),record('c',script='Latn')])
        self.assertEqual(3,len(results))

    def test_distinct_arabic_diacritics_and_cjk_senses(self):
        a,b=record('a'),record('b',lemma='كتاب')
        c=record('c',lang='ja',script='Jpan',lemma='空',sense='sky')
        d=record('d',lang='ja',script='Jpan',lemma='空',sense='empty',concept='concept.empty')
        results=self.run_rows([a,b,c,d])
        self.assertEqual(4,sum(kind=='canonical' for kind,_ in results))

    def test_duplicate_ids_rejected(self):
        with CorpusDeduplicator(admitted_source_licenses={}) as d:
            d.process_record(record('a'))
            with self.assertRaisesRegex(ValueError,'duplicate lexeme_id'):
                d.process_record(record('a'))

    def test_unknown_concept_no_auto_drop(self):
        a,b=record('a'),record('b')
        a['senses'][0].pop('concept_id')
        b['senses'][0].pop('concept_id')
        results=self.run_rows([a,b])
        self.assertEqual(2,sum(kind=='canonical' for kind,_ in results))

    def test_streaming_many_records_and_guard_legacy_limit(self):
        with CorpusDeduplicator(legacy_result_limit=3,admitted_source_licenses={}) as d:
            for i in range(200):
                d.process_record(record(str(i),lemma='lemma-'+str(i)))
            with self.assertRaisesRegex(ValueError,'legacy in-memory'):
                d.resolve()
            self.assertEqual(200,sum(kind=='canonical' for kind,_ in d.iter_resolved()))

    def test_oversize_fail_closed(self):
        with CorpusDeduplicator(max_record_bytes=32,admitted_source_licenses={}) as d:
            with self.assertRaisesRegex(ValueError,'oversized'):
                d.process_record(record('a'))
        with CorpusDeduplicator(max_record_bytes=10,admitted_source_licenses={}) as d:
            with self.assertRaisesRegex(ValueError,'oversized'):
                process_stream(io.StringIO(' '*50+'\n'),d)


if __name__ == '__main__':
    unittest.main()
