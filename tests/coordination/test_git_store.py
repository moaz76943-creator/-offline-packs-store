import base64
import hashlib
import json
import unittest
from tools.coordination.leases import GitRefStore, Denied, Coordinator

Q='moaz76943-creator/deutsch-build'
P='moaz76943-creator/-offline-packs-store'
SHA='a'*40

class FakeGitHub:
    def __init__(self):
        self.head='b'*40
        self.trees={self.head:'c'*40}
        self.blobs={}
        self.tree_by_sha={}
        self.commits={}
        self.links={self.head:{'schema':1,'leases':{},'events':[]}}
        self.i=0
        self.private=True
        self.branches={(P,'main'):SHA,(Q,'staging/v2-full-platform'):SHA}
    def _sha(self):
        self.i+=1
        return f'{self.i:040x}'
    def branch_head(self,repo,branch):return self.branches[(repo,branch)]
    def request(self,path,method='GET',body=None):
        if path==f'repos/{Q}' and method=='GET':return {'private':self.private}
        if path.endswith('/git/ref/heads/coordination/leases') and method=='GET':
            return {'object':{'sha':self.head}}
        if f'/contents/tools/coordination/leases.json?' in path:
            return {'content':base64.b64encode(json.dumps(self.links[self.head]).encode()).decode()}
        if '/git/commits/' in path and method=='GET':
            sha=path.rsplit('/',1)[-1]
            return {'tree':{'sha':self.trees[sha]}}
        if path.endswith('/git/blobs') and method=='POST':
            sha=self._sha();self.blobs[sha]=body['content'];return {'sha':sha}
        if path.endswith('/git/trees') and method=='POST':
            sha=self._sha();self.tree_by_sha[sha]=body['tree'][0]['sha'];return {'sha':sha}
        if path.endswith('/git/commits') and method=='POST':
            sha=self._sha();self.commits[sha]=body;self.trees[sha]=body['tree'];return {'sha':sha}
        if path.endswith('/git/refs/heads/coordination/leases') and method=='PATCH':
            commit=self.commits[body['sha']]
            if commit['parents']!=[self.head] or body['force'] is not False:
                raise Denied('NON_FAST_FORWARD')
            self.links[body['sha']]=json.loads(self.blobs[self.tree_by_sha[commit['tree']]])
            self.head=body['sha']
            return {'object':{'sha':self.head}}
        raise RuntimeError(path)

class GitStoreTests(unittest.TestCase):
    def test_unsafe_public_ledger_is_refused(self):
        api=FakeGitHub();api.private=False
        with self.assertRaises(Denied):GitRefStore(api,Q)
    def test_non_force_cas_rejects_stale_writer(self):
        api=FakeGitHub();store=GitRefStore(api,Q)
        old,a=store.snapshot();new1=json.loads(json.dumps(a));new2=json.loads(json.dumps(a))
        new1['events']=[{'marker':1}];new2['events']=[{'marker':2}]
        self.assertTrue(store.commit(old,new1))
        self.assertFalse(store.commit(old,new2))
        self.assertEqual(store.snapshot()[1]['events'],[{'marker':1}])
    def test_real_store_lease_claim_retries_optimistically(self):
        api=FakeGitHub();store=GitRefStore(api,Q)
        coord=Coordinator(store,api,clock=lambda:100,actor='tester')
        first=coord.claim('t1',P,'main',SHA,['tools/a/**'],'alice',120)
        second=coord.claim('t2',P,'main',SHA,['tools/a/x.py'],'bob',120)
        self.assertEqual(first['status'],'CLAIMED')
        self.assertEqual(second['status'],'READ_ONLY')
        self.assertEqual(len(store.snapshot()[1]['leases']),1)

if __name__=='__main__':unittest.main()
