import unittest
from auto_policy import auto_eligible, auto_safe_files
SHA = 'a'*40
MAIN = 'b'*40
PR = {'state':'open','draft':False,'head':{'sha':SHA,'repo':{'full_name':'moaz76943-creator/-offline-packs-store'}},'base':{'ref':'main','sha':MAIN},'user':{'login':'moaz76943-creator'},'mergeable':True,'mergeable_state':'clean'}
CHECKS={'check_runs':[{'id':3,'name':n,'head_sha':SHA,'status':'completed','conclusion':'success','app':{'slug':'github-actions'}} for n in ('public-pr-merge-gate','validate')]}
DOC=[{'filename':'docs/notes.md','status':'added'}]
class PolicyTests(unittest.TestCase):
    def check(self,pr=None,checks=None,reviews=None,files=None,message='feat: docs',main=MAIN):
        return auto_eligible(pr if pr is not None else PR,checks if checks is not None else CHECKS,reviews if reviews is not None else [],files if files is not None else DOC,message,main)
    def test_accept_safe_document(self): self.assertTrue(self.check()[0])
    def test_accept_added_test(self): self.assertTrue(self.check(files=[{'filename':'tests/test_new.py','status':'added'}])[0])
    def test_reject_malformed_and_changed_tests(self):
        for f in ([],[{'filename':'tests/test_existing.py','status':'modified'}],[{'filename':'docs/notes.md','status':'renamed','previous_filename':'docs/old.md'}],[{'filename':'docs/../legal/sources.md','status':'added'}],[{'filename':'docs/governance/decisions.md','status':'added'}]):
            with self.subTest(f=f): self.assertFalse(self.check(files=f)[0])
    def test_reject_sensitive_paths(self):
        for path in ('legal/ledger/sources.json','packs/pack.gz','tools/merge_coordinator/coordinator.py','.github/workflows/public_merge_coordinator.yml'):
            self.assertFalse(auto_safe_files([{'filename':path,'status':'modified'}]))
    def test_reject_draft_or_foreign(self):
        for change in ({'draft':True},{'mergeable':False},{'mergeable_state':'dirty'},{'user':{'login':'other'}},{'base':{'ref':'main','sha':'c'*40}}):
            self.assertFalse(self.check(pr={**PR,**change})[0])
    def test_reject_ci_skip(self): self.assertFalse(self.check(message='fix: docs [skip ci]')[0])
    def test_reject_review_block(self): self.assertFalse(self.check(reviews=[{'state':'CHANGES_REQUESTED'}])[0])
    def test_reject_missing_or_failed_checks(self):
        for run in ([],[{'id':4,'name':'public-pr-merge-gate','head_sha':SHA,'conclusion':'failure','status':'completed','app':{'slug':'github-actions'}}]):
            with self.subTest(run=run): self.assertFalse(self.check(checks={'check_runs':run})[0])
    def test_latest_check_wins(self):
        x={'check_runs':CHECKS['check_runs']+[{'id':10,'name':'validate','head_sha':SHA,'conclusion':'failure','status':'completed','app':{'slug':'github-actions'}}]}
        self.assertFalse(self.check(checks=x)[0])
    def test_no_skip_or_sensitive_automerge(self): self.assertFalse(self.check(files=[{'filename':'docs/guide.md','status':'modified'},{'filename':'tools/release_gate/gate.py','status':'modified'}])[0])
