import importlib.util,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'tools/language_coverage/report.py'
s=importlib.util.spec_from_file_location('lang',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def sample():
    ids=[f'{c}{d}' for c in 'abcdefghij' for d in 'abcdefghij']
    manifest={'languages':[{'code':i,'name':i,'registered':True,'production_ready':False} for i in ids], 'packs':[]}
    registry={'languages':[{'id':i} for i in ids]}
    readiness={'states':{i:'unverified' for i in ids}}
    return ids,manifest,registry,readiness,{'sources':[]}
class Coverage(unittest.TestCase):
    def test_canonical_100_registered_unknown_not_zero(self):
        _,a,b,c,d=sample();r=m.coverage(a,b,c,d)
        self.assertEqual(r['registered'],100)
        self.assertEqual(r['language_rows'][0]['verbs'],'UNKNOWN')
        self.assertEqual(r['approved_source_ids'],0)
    def test_missing_language_disallowed(self):
        _,a,b,c,d=sample();a['languages'].pop()
        with self.assertRaises(ValueError):m.coverage(a,b,c,d)
    def test_duplicate_identity_disallowed(self):
        _,a,b,c,d=sample();a['languages'][0]['code']=a['languages'][1]['code']
        with self.assertRaises(ValueError):m.coverage(a,b,c,d)
    def test_false_published_ready_fails(self):
        _,a,b,c,d=sample();a['languages'][0]['production_ready']=True
        with self.assertRaises(ValueError):m.coverage(a,b,c,d)
    def test_unknown_pair_is_not_zero(self):
        ids,a,b,c,d=sample();pairs=[{'source_language':ids[0],'target_language':ids[1],'translation_count':22,'reviewed':False}]
        r=m.coverage(a,b,c,d,pairs=pairs)
        self.assertEqual(r['directed_pairs'][0]['verified_count'],'UNKNOWN')
    def test_sparse_pair_avoids_reverse_direction_assumption(self):
        ids,a,b,c,d=sample();pairs=[{'source_language':ids[0],'target_language':ids[1],'translation_count':2,'reviewed':True,'license_status':'APPROVED_FOR_REDISTRIBUTION','source_sha256':'a'*64}]
        r=m.coverage(a,b,c,d,pairs=pairs)
        self.assertEqual(len(r['directed_pairs']),1)
        self.assertEqual(r['directed_pairs'][0]['verified_count'],'UNKNOWN')
        self.assertEqual(r['directed_pairs'][0]['claimed_count'],2)
        self.assertEqual(r['language_rows'][0]['sentences'],'UNKNOWN')
    def test_pair_duplicate_disallowed(self):
        ids,a,b,c,d=sample();p={'source_language':ids[0],'target_language':ids[1]}
        with self.assertRaises(ValueError):m.coverage(a,b,c,d,pairs=[p,p])
    def test_reverse_pair_separate(self):
        ids,a,b,c,d=sample();r=m.coverage(a,b,c,d,pairs=[{'source_language':ids[0],'target_language':ids[1]},{'source_language':ids[1],'target_language':ids[0]}]);self.assertEqual(len(r['directed_pairs']),2)
    def test_stale_production_version_cannot_claim_release_without_packs(self):
        _,a,b,c,d=sample()
        v={'release_status':'PRODUCTION_READY','packs':[]}
        with self.assertRaises(ValueError):m.coverage(a,b,c,d,version=v)

    def test_non_mapping_pair_rejected(self):
        ids,a,b,c,d=sample()
        with self.assertRaises(ValueError):m.coverage(a,b,c,d,pairs=[42])

    def test_unapproved_source_must_not_publish(self):
        ids,a,b,c,d=sample();a['packs']=[{'id':ids[0]}]
        with self.assertRaises(ValueError):m.coverage(a,b,c,d)
if __name__=='__main__':unittest.main()
