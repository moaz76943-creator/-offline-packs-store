import unittest
from tools.merge_coordinator.engine import Coordinator,MergeIncident
from tools.merge_coordinator.policy import Pull

BASE='a'*40
HEAD='b'*40
AFTER='c'*40
PROTECTION={'enforce':True,'strict':True,'required':True,
 'contexts':['public-pr-merge-gate'],'reviews':1,'no_bypass':True}

def candidate(**kw):
    p=Pull(number=1,head=HEAD,base=BASE,draft=False,
           files=('tools/isolated.py',),mergeable=True,
           mergeable_state='clean',head_message='verified',approvals=1,
           author='owner',checks={'public-pr-merge-gate':'success'})
    for k,v in kw.items():
        setattr(p,k,v)
    return p

class Fake:
    def __init__(self):
        self.main=BASE
        self.next_main=AFTER
        self.put=[]
        self.race_main=False
        self.race_head=False
        self.revoked=False
        self.no_protection=False
        self.fail_api=False
        self.bad_after=False
    def head(self):
        if self.race_main:
            return 'd'*40
        if self.bad_after and self.put:
            return 'e'*40
        return self.main
    def pr(self,n):
        return {'state':'open','head':{'sha':'f'*40 if self.race_head else HEAD},
                'base':{'ref':'main'},'draft':False,
                'mergeable':True,'mergeable_state':'clean'}
    def protection(self):
        return {'enforce':False} if self.no_protection else PROTECTION
    def reviews(self,n):
        return [] if self.revoked else [{'user':{'login':'reviewer'},
                  'state':'APPROVED','commit_id':HEAD}]
    def checks(self,sha):
        return {'public-pr-merge-gate':'success'}
    def pages(self,path,max_pages=3):
        return [{'number':1,'head':{'sha':HEAD}}]
    def call(self,path,method='GET',body=None):
        if self.fail_api:
            raise RuntimeError('temporary API failure')
        self.put.append(body)
        self.main=self.next_main
        return {'merged':True,'sha':self.main}

class Tests(unittest.TestCase):
    def runmerge(self,api=None,**kw):
        api=api or Fake()
        return Coordinator(api).integrate(candidate(),main_sha=BASE,
                    protection=PROTECTION,lease=True,**kw)
    def test_merge_exact_head(self):
        api=Fake()
        result=self.runmerge(api)
        self.assertEqual(result['status'],'MERGED')
        self.assertEqual(api.put[0]['sha'],HEAD)
        self.assertEqual(api.put[0]['merge_method'],'squash')
    def test_no_lease(self):
        api=Fake()
        result=Coordinator(api).integrate(candidate(),main_sha=BASE,
                           protection=PROTECTION,lease=False)
        self.assertEqual(result['status'],'NO_LEASE')
        self.assertEqual(api.put,[])
    def test_main_changed(self):
        api=Fake();api.race_main=True
        self.assertEqual(self.runmerge(api)['status'],'STALE_MAIN')
        self.assertEqual(api.put,[])
    def test_head_changed(self):
        api=Fake();api.race_head=True
        self.assertEqual(self.runmerge(api)['status'],'STALE_PR')
        self.assertEqual(api.put,[])
    def test_review_revoked(self):
        api=Fake();api.revoked=True
        self.assertEqual(self.runmerge(api)['status'],'STALE_REVIEWS')
        self.assertEqual(api.put,[])
    def test_protection_revoked(self):
        api=Fake();api.no_protection=True
        self.assertEqual(self.runmerge(api)['status'],'PROTECTION_CHANGED')
        self.assertEqual(api.put,[])
    def test_wrong_inventory(self):
        api=Fake()
        self.assertEqual(self.runmerge(api,inventory={(2,HEAD)})['status'],'STALE_INVENTORY')
        self.assertEqual(api.put,[])
    def test_idempotency(self):
        api=Fake()
        self.assertEqual(self.runmerge(api)['status'],'MERGED')
        self.assertEqual(self.runmerge(api)['status'],'STALE_MAIN')
        self.assertEqual(len(api.put),1)
    def test_api_fail_closed(self):
        api=Fake();api.fail_api=True
        with self.assertRaises(RuntimeError):
            self.runmerge(api)
        self.assertEqual(api.put,[])
    def test_post_merge_incident(self):
        api=Fake();api.bad_after=True
        with self.assertRaises(MergeIncident):
            self.runmerge(api)
    def test_draft_cannot_merge(self):
        api=Fake()
        result=Coordinator(api).integrate(candidate(draft=True),
                         main_sha=BASE,protection=PROTECTION,lease=True)
        self.assertEqual(result['status'],'NOT_READY')
        self.assertEqual(api.put,[])
if __name__=='__main__':
    unittest.main()
