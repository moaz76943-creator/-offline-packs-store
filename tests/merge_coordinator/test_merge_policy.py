import unittest
from tools.merge_coordinator.policy import Pull,graph
from tools.merge_coordinator.classification import classify

BASE='a'*40
HEAD='b'*40
PROTECTION={'enforce':True,'strict':True,'required':True,
 'reviews':1,'no_bypass':True,
 'contexts':['public-pr-merge-gate','validate']}

def pr(n=1,**override):
    p=Pull(number=n,head=HEAD,base=BASE,draft=False,
           files=(f'tools/isolated_{n}.py',),mergeable=True,
           mergeable_state='clean',head_message='done',
           approvals=1,
           checks={'public-pr-merge-gate':'success','validate':'success'})
    for key,value in override.items():
        setattr(p,key,value)
    return p

def state(*ps,merged=()):
    return [x.state for x in classify(ps,main_sha=BASE,
                        protection=PROTECTION,merged=set(merged))]

class Tests(unittest.TestCase):
    def test_verified(self):
        self.assertEqual(state(pr()),['VERIFIED_READY'])
    def test_draft(self):
        self.assertEqual(state(pr(draft=True)),['DRAFT'])
    def test_skip_head(self):
        self.assertEqual(state(pr(head_message='done [skip ci]')),['BLOCKED_SKIP_CI'])
    def test_failed_ci(self):
        self.assertEqual(state(pr(checks={'public-pr-merge-gate':'failure','validate':'success'})),['UNVERIFIED'])
    def test_skipped_ci(self):
        self.assertEqual(state(pr(checks={'public-pr-merge-gate':'skipped','validate':'success'})),['UNVERIFIED'])
    def test_missing_ci(self):
        self.assertEqual(state(pr(checks={'validate':'success'})),['UNVERIFIED'])
    def test_pending_ci(self):
        self.assertEqual(state(pr(checks={'public-pr-merge-gate':'pending','validate':'success'})),['WAITING_CHECKS'])
    def test_protection_missing(self):
        self.assertEqual(classify([pr()],main_sha=BASE,protection=None)[0].state,'UNVERIFIED')
    def test_main_head_not_current(self):
        self.assertEqual(state(pr(base='c'*40)),['UNVERIFIED'])
    def test_merge_conflict(self):
        self.assertEqual(state(pr(mergeable=False)),['MERGE_CONFLICT'])
    def test_dependency(self):
        self.assertEqual(state(pr(body='Depends-On: #9')),['DEPENDENCY_BLOCKED'])
    def test_resolved_dependency(self):
        self.assertEqual(state(pr(body='Depends-On: #9'),merged={9}),['VERIFIED_READY'])
    def test_review_required(self):
        self.assertEqual(state(pr(approvals=0)),['HUMAN_REVIEW'])
    def test_rights_review(self):
        self.assertEqual(state(pr(files=('legal/source_rights/data.py',))),['RIGHTS_REVIEW'])
    def test_security_review(self):
        self.assertEqual(state(pr(files=('.github/workflows/new.yml',))),['SECURITY_REVIEW'])
    def test_publication_review(self):
        self.assertEqual(state(pr(files=('tools/release_publication/run.py',))),['HUMAN_REVIEW'])
    def test_overlap_blocks(self):
        self.assertEqual(state(pr(1),pr(2,head='c'*40,files=('tools/isolated_1.py',))),
                         ['SEMANTIC_CONFLICT','SEMANTIC_CONFLICT'])
    def test_duplicate_not_merged(self):
        self.assertEqual(state(pr(1),pr(2,files=('tools/isolated_1.py',))),
                         ['SEMANTIC_CONFLICT','DUPLICATE'])
    def test_blocked_independent_does_not_block_ready(self):
        self.assertEqual(state(pr(1,draft=True),pr(2)),['DRAFT','VERIFIED_READY'])
    def test_incomplete_inventory(self):
        self.assertEqual(classify([pr()],main_sha=BASE,protection=PROTECTION,
                                  completeness=False)[0].state,'UNVERIFIED')
if __name__=='__main__':
    unittest.main()
