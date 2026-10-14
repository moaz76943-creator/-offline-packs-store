import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from tools.coordination.leases import Coordinator, Denied, overlaps, normalize_path, GitRefStore

P='moaz76943-creator/-offline-packs-store'
Q='moaz76943-creator/deutsch-build'
SHA='a'*40

class FakeAPI:
    def __init__(self):
        self.branches={(P,'main'):SHA,(Q,'staging/v2-full-platform'):SHA}
        self.runs={}
        self.pull={}
        self.files={}
    def branch_head(self, repo, branch):
        return self.branches[(repo,branch)]
    def terminated_run(self, repo, run_id, attempt):
        return self.runs.get((repo,run_id,attempt),False)
    def pr_files(self, repo, pr):
        return self.pull[(repo,pr)], self.files[(repo,pr)]

class FakeStore:
    def __init__(self):
        self.guard=threading.Lock()
        self.version=0
        self.data={'schema':1,'leases':{},'events':[]}
    def snapshot(self):
        with self.guard:return self.version,copy.deepcopy(self.data)
    def commit(self,prev,new):
        with self.guard:
            if prev!=self.version:return False
            self.version+=1
            self.data=copy.deepcopy(new)
            return True

class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeAPI();self.store=FakeStore();self.co=Coordinator(self.store,self.api,clock=lambda:1000,actor='github-user')
    def claim(self,task='first',paths=None,repo=P,branch='main',owner='agent1',ttl=300,pr=None):
        return self.co.claim(task,repo,branch,SHA,paths or ['tools/coordination/**'],owner,ttl,pr)
    def test_parallel_same_scope_exactly_one_winner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda i:self.claim(task=f'task{i}',owner=f'a{i}'),range(8)))
        self.assertEqual(sum(x['status']=='CLAIMED' for x in results),1)
        self.assertEqual(sum(x['status']=='READ_ONLY' for x in results),7)
    def test_parallel_read_only_does_not_modify(self):
        before=self.store.version
        self.assertEqual(self.co.inspect(P,'main',['tools/coordination/a.py'])['status'],'READY')
        self.assertEqual(self.store.version,before)
    def test_ancestor_descendant_overlap(self):
        self.assertTrue(overlaps('tools/a/**','tools/a'))
        self.assertTrue(overlaps('tools/a','tools/a/**'))
        self.assertTrue(overlaps('tools/a/**','tools/a/nested/x.py'))
        self.assertFalse(overlaps('tools/a/**','tools/abc/x.py'))
    def test_path_traversal_and_untrusted_globs_rejected(self):
        for x in ('../abc','/etc/passwd','a/../b','a\\b','a/**/b','a//b','a/./b','', 'a/*'):
            with self.subTest(x=x), self.assertRaises(Denied):normalize_path(x)
    def test_repository_separation(self):
        first=self.claim()
        second=self.claim('other',repo=Q,branch='staging/v2-full-platform')
        self.assertEqual(first['status'],'CLAIMED')
        self.assertEqual(second['status'],'CLAIMED')
    def test_branch_movement_blocks_new_claim(self):
        self.api.branches[(P,'main')]='b'*40
        self.assertEqual(self.claim()['status'],'BLOCKED')
    def test_branch_movement_blocks_renewal(self):
        token=self.claim()['lease_id'];self.api.branches[(P,'main')]='b'*40
        self.assertEqual(self.co.renew('first',token,'agent1',300)['status'],'BLOCKED')
    def test_live_lease_cannot_be_recovered(self):
        token=self.claim()['lease_id']
        self.assertEqual(self.co.recover('first',token)['status'],'BLOCKED')
    def test_expiry_alone_is_not_recovery_authority(self):
        token=self.claim()['lease_id']
        self.co.clock=lambda:1400
        self.assertEqual(self.co.recover('first',token)['status'],'BLOCKED')
        self.assertEqual(self.claim('second')['status'],'READ_ONLY')
    def test_expired_finished_worker_recovers(self):
        token=self.co.claim('first',P,'main',SHA,['tools/x/**'],'agent1',300,None,run_id=33,run_attempt=2)['lease_id']
        self.api.runs[(P,33,2)]=True
        self.co.clock=lambda:1301
        self.assertEqual(self.co.recover('first',token)['status'],'RECOVERED')
        self.assertEqual(self.co.claim('next',P,'main',SHA,['tools/x/y.py'],'a2',300)['status'],'CLAIMED')
    def test_aba_old_owner_cannot_renew_or_release(self):
        token=self.co.claim('first',P,'main',SHA,['tools/x/**'],'agent1',300,None,run_id=34,run_attempt=1)['lease_id']
        self.co.clock=lambda:1301;self.api.runs[(P,34,1)]=True
        self.co.recover('first',token)
        newer=self.co.claim('first',P,'main',SHA,['tools/x/**'],'agent1',300)
        self.assertNotEqual(token,newer['lease_id'])
        self.assertEqual(self.co.renew('first',token,'agent1',300)['status'],'BLOCKED')
        self.assertEqual(self.co.release('first',token,'agent1')['status'],'BLOCKED')
    def test_renew_and_release_owner_identity(self):
        token=self.claim()['lease_id']
        self.assertEqual(self.co.renew('first',token,'wrong',300)['status'],'BLOCKED')
        self.assertEqual(self.co.renew('first',token,'agent1',300)['status'],'RENEWED')
        self.assertEqual(self.co.release('first',token,'agent1')['status'],'RELEASED')
        self.assertEqual(self.claim('second')['status'],'CLAIMED')
    def test_preflight_rename_checks_both_names(self):
        token=self.co.claim('first',P,'main',SHA,['tools/new/**'],'agent1',300,pr=20)['lease_id']
        self.api.pull[(P,20)]={'number':20,'base_ref':'main','head_sha':'b'*40,'changed_files':1}
        self.api.files[(P,20)]=[{'filename':'tools/new/a.py','previous_filename':'outside/old.py','status':'renamed'}]
        self.assertEqual(self.co.verify_pr('first',token,'agent1',20,'b'*40)['status'],'BLOCKED')
    def test_preflight_changed_pr_head_blocks(self):
        token=self.co.claim('first',P,'main',SHA,['tools/new/**'],'agent1',300,pr=20)['lease_id']
        self.api.pull[(P,20)]={'number':20,'base_ref':'main','head_sha':'d'*40,'changed_files':1}
        self.api.files[(P,20)]=[{'filename':'tools/new/a.py','status':'added'}]
        self.assertEqual(self.co.verify_pr('first',token,'agent1',20,'b'*40)['status'],'BLOCKED')
    def test_nonconflicting_pr_preflight(self):
        token=self.co.claim('first',P,'main',SHA,['tools/new/**'],'agent1',300,pr=20)['lease_id']
        self.api.pull[(P,20)]={'number':20,'base_ref':'main','head_sha':'b'*40,'changed_files':1}
        self.api.files[(P,20)]=[{'filename':'tools/new/a.py','status':'added'}]
        self.assertEqual(self.co.verify_pr('first',token,'agent1',20,'b'*40)['status'],'AUTHORIZED_SCOPE_ONLY')
    def test_recovery_run_attempt_must_match(self):
        token=self.co.claim('first',P,'main',SHA,['tools/x/**'],'agent1',300,None,run_id=33,run_attempt=2)['lease_id']
        self.api.runs[(P,33,1)]=True
        self.co.clock=lambda:1301
        self.assertEqual(self.co.recover('first',token)['status'],'BLOCKED')

if __name__=='__main__':unittest.main()
