import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / 'tools' / 'merge_accelerator' / 'inventory.py'
spec = importlib.util.spec_from_file_location('inventory', SRC)
inventory = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(inventory)
except FileNotFoundError:
    pass

class InventoryTests(unittest.TestCase):
    def test_skip_ci_only_final_commit_not_title(self):
        item = {'number': 7, 'title': '[skip ci] old title', 'draft': False,
                'base': {'ref': 'main'}, 'head': {'sha': 'a' * 40}, 'user': {'login': 'owner'},
                'mergeable': True}
        result = inventory.classify(item, final_message='Fix bug', checks=[{'name': 'public-pr-merge-gate','status':'completed', 'conclusion':'success','head_sha':'a'*40,'id':1}], reviews=[{'user':{'login':'reviewer'},'state':'APPROVED','commit_id':'a'*40}], required_checks=('public-pr-merge-gate',), expected_base='main', changed_files=['tests/x.py'])
        self.assertNotIn('SKIP_CI_TIP', result['blockers'])
        self.assertEqual(result['status'], 'REVIEWED_CANDIDATE_NOT_AUTHORIZED')

    def test_rejects_missing_checks_even_if_draft_and_approved(self):
        pr = self.example_pr(draft=True)
        result = inventory.classify(pr, final_message='test', checks=[], reviews=[], required_checks=('public-pr-merge-gate',), expected_base='main', changed_files=['tests/x.py'])
        self.assertIn('DRAFT', result['blockers'])
        self.assertIn('NOT_RUN:public-pr-merge-gate', result['blockers'])

    def test_older_passing_check_cannot_override_newer_failure(self):
        pr = self.example_pr(draft=False)
        checks = [{'name':'public-pr-merge-gate','status':'completed','conclusion':'success','head_sha':'a'*40,'id':2},
                  {'name':'public-pr-merge-gate','status':'completed','conclusion':'failure','head_sha':'a'*40,'id':3}]
        r = inventory.classify(pr, 'ok', checks, [], ('public-pr-merge-gate',), 'main', ['tests/x.py'])
        self.assertIn('CI_FAIL:public-pr-merge-gate',r['blockers'])

    def test_stale_check_ignored(self):
        pr = self.example_pr(draft=False)
        checks = [{'name':'public-pr-merge-gate','status':'completed','conclusion':'success','head_sha':'b'*40,'id':2}]
        r=inventory.classify(pr,'ok', checks, [], ('public-pr-merge-gate',),'main',['tests/x.py'])
        self.assertIn('NOT_RUN:public-pr-merge-gate',r['blockers'])

    def test_detects_unsafe_main_target_and_tip_skip(self):
        pr = self.example_pr(draft=False,base='main')
        r = inventory.classify(pr,'[skip ci]',[],[],(), 'staging/v2-full-platform',['lib/services/file.dart'])
        self.assertIn('BASE_REVIEW_REQUIRED', r['blockers'])
        self.assertIn('SKIP_CI_TIP',r['blockers'])
        self.assertIn('CI_POLICY_UNVERIFIED',r['blockers'])
        self.assertIn('SENSITIVE_SCOPE',r['blockers'])

    def test_author_approval_and_stale_review_are_not_valid(self):
        pr = self.example_pr(draft=False)
        checks=[{'name':'public-pr-merge-gate','status':'completed','conclusion':'success','head_sha':'a'*40,'id':1}]
        reviews=[{'user':{'login':'owner'},'state':'APPROVED','commit_id':'a'*40}, {'user':{'login':'friend'},'state':'APPROVED','commit_id':'b'*40}]
        r=inventory.classify(pr,'ok',checks,reviews,('public-pr-merge-gate',),'main',['tests/x.py'])
        self.assertIn('INDEPENDENT_REVIEW_REQUIRED',r['blockers'])

    def test_file_ownership_map_linear_in_number_of_paths(self):
        files={1:['a.py','b.py'],2:['b.py','c.py'],3:['c.py']}
        self.assertEqual(inventory.overlaps(files),{'b.py':[1,2], 'c.py':[2,3]})

    def test_pagination_failure_closed(self):
        class Fake:
            def __init__(self): self.calls=[]
            def get(self,path):
                self.calls.append(path)
                return [{'number':i} for i in range(100)]
        with self.assertRaises(ValueError): inventory.get_pages(Fake(),'/pulls?state=open',max_pages=2)

    def test_github_check_runs_wrapped_response_is_unwrapped(self):
        class Fake:
            def get(self, path):
                return {'total_count': 1, 'check_runs': [{'name': 'public-pr-merge-gate'}]}
        self.assertEqual(inventory.get_pages(Fake(), '/commits/a/check-runs', array_key='check_runs'),
                         [{'name':'public-pr-merge-gate'}])

    def test_unique_sorted_reasons(self):
        pr=self.example_pr(draft=False)
        r=inventory.classify(pr,'ok',[],[],('public-pr-merge-gate',),'main',['packs/a','packs/b'])
        self.assertEqual(r['blockers'].count('SENSITIVE_SCOPE'),1)

    @staticmethod
    def example_pr(draft=True,base='main'):
        return {'number':7,'title':'Fix tests','draft':draft,
                'base':{'ref':base},'head':{'sha':'a'*40}, 'user':{'login':'owner'},'mergeable':True}

if __name__=='__main__': unittest.main()