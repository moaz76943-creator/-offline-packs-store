import unittest
from auto_policy import auto_eligible, auto_safe_files
SHA = 'a'*40
MAIN = 'b'*40
PR = {'state':'open','draft':False,'head':{'sha':SHA,'repo':{'full_name':'moaz76943-creator/-offline-packs-store'}},'base':{'ref':'main','sha':MAIN},'user':{'login':'moaz76943-creator'},'mergeable':True,'mergeable_state':'clean'}
CHECKS={'check_runs':[{'id':3,'name':n,'head_sha':SHA,'status':'completed','conclusion':'success','app':{'slug':'github-actions'}} for n in ('public-pr-merge-gate',)]}
DOC=[{'filename':'docs/notes.md','status':'added'}]
class PolicyTests(unittest.TestCase):
    def check(self,pr=None,checks=None,reviews=None,files=None,message='feat: docs',main=MAIN):
        return auto_eligible(pr if pr is not None else PR,checks if checks is not None else CHECKS,reviews if reviews is not None else [],files if files is not None else DOC,message,main)
    def test_accept_safe_document(self): self.assertTrue(self.check()[0])
    def test_root_prose_docs_need_no_special_authorization(self):
        for name in ('README.md', 'CHANGELOG.md', 'CONTRIBUTING.md'):
            with self.subTest(name=name):
                self.assertTrue(self.check(files=[{'filename': name, 'status': 'modified'}])[0])
        for name in ('LICENSE', 'CODEOWNERS', 'manifest.json', '.github/workflows/ci.yml'):
            with self.subTest(name=name):
                self.assertFalse(self.check(files=[{'filename': name, 'status': 'modified'}])[0])

    def test_many_low_risk_docs_without_arbitrary_five_file_limit(self):
        files = [{'filename': f'docs/notes_{index}.md', 'status': 'added'}
                 for index in range(24)]
        self.assertTrue(self.check(files=files)[0])
        self.assertFalse(self.check(files=files + [
            {'filename':'legal/ledger/source.json','status':'modified'}])[0])

    def test_large_unproven_file_list_stays_bounded(self):
        files = [{'filename': f'docs/notes_{index}.md', 'status': 'added'}
                 for index in range(301)]
        self.assertFalse(self.check(files=files)[0])
    def test_accept_added_test(self): self.assertTrue(self.check(files=[{'filename':'tests/test_new.py','status':'added'}])[0])
    def test_reject_malformed_and_changed_tests(self):
        for f in ([],[{'filename':'tests/test_existing.py','status':'modified'}],[{'filename':'docs/notes.md','status':'renamed','previous_filename':'docs/old.md'}],[{'filename':'docs/../legal/sources.md','status':'added'}],[{'filename':'docs/governance/decisions.md','status':'added'}]):
            with self.subTest(f=f): self.assertFalse(self.check(files=f)[0])
    def test_reject_sensitive_paths(self):
        for path in ('legal/ledger/sources.json','packs/pack.gz','tools/merge_coordinator/coordinator.py','.github/workflows/public_merge_coordinator.yml'):
            self.assertFalse(auto_safe_files([{'filename':path,'status':'modified'}]))
    def test_reject_draft_or_foreign(self):
        for change in ({'draft':True},{'mergeable':False},{'mergeable_state':'dirty'},{'mergeable_state':'behind'},{'user':{'login':'other'}},{'base':{'ref':'other','sha':MAIN}}):
            self.assertFalse(self.check(pr={**PR,**change})[0])
    def test_stale_base_sha_hint_never_overrides_fresh_clean_state_or_exact_check(self):
        stale = {**PR, 'base': {'ref':'main', 'sha':'c'*40}}
        self.assertTrue(self.check(pr=stale)[0])
        self.assertFalse(self.check(pr=stale, checks={'check_runs': []})[0])
    def test_ci_skip_text_does_not_override_exact_head_evidence(self):
        self.assertTrue(self.check(message='fix: docs [skip ci]')[0])
        self.assertFalse(self.check(message='fix: docs [skip ci]', checks={'check_runs': []})[0])
    def test_reject_review_block(self): self.assertFalse(self.check(reviews=[{'state':'CHANGES_REQUESTED'}])[0])
    def test_reject_missing_or_failed_checks(self):
        for run in ([],[{'id':4,'name':'public-pr-merge-gate','head_sha':SHA,'conclusion':'failure','status':'completed','app':{'slug':'github-actions'}}]):
            with self.subTest(run=run): self.assertFalse(self.check(checks={'check_runs':run})[0])
    def test_latest_check_wins(self):
        x={'check_runs':CHECKS['check_runs']+[{'id':10,'name':'public-pr-merge-gate','head_sha':SHA,'conclusion':'failure','status':'completed','app':{'slug':'github-actions'}}]}
        self.assertFalse(self.check(checks=x)[0])
    def test_extra_unrequired_failed_validate_does_not_block_simple_docs(self):
        optional = {'id':10,'name':'validate','head_sha':SHA,
                    'conclusion':'failure','status':'completed',
                    'app':{'slug':'github-actions'}}
        self.assertTrue(self.check(checks={'check_runs':CHECKS['check_runs']+[optional]})[0])

    def test_sensitive_files_still_rejected(self): self.assertFalse(self.check(files=[{'filename':'docs/guide.md','status':'modified'},{'filename':'tools/release_gate/gate.py','status':'modified'}])[0])

    def test_scoped_search_qa_requires_targeted_hosted_checks(self):
        files = [{'filename':'tools/gha_factory/search_qa/audit.py','status':'modified'},
                 {'filename':'tests/gha_factory/search_qa/test_alignment.py','status':'added'}]
        names = ('public-pr-merge-gate', 'audit (0, 1)',
                 'Validate no fictitious licensed packs', 'admission public regression')
        checks = {'check_runs': [{'id':i+1, 'name':name, 'head_sha':SHA,
                    'status':'completed', 'conclusion':'success',
                    'app':{'slug':'github-actions'}} for i,name in enumerate(names)]}
        self.assertTrue(self.check(files=files,checks=checks)[0])
        checks['check_runs'] = [x for x in checks['check_runs'] if x['name']!='audit (0, 1)']
        self.assertFalse(self.check(files=files,checks=checks)[0])

    def test_scoped_qa_does_not_mix_with_unrelated_files(self):
        fs=[{'filename':'tools/gha_factory/search_qa/audit.py','status':'modified'},
            {'filename':'docs/notes.md','status':'added'}]
        self.assertFalse(auto_safe_files(fs))

    def test_later_approval_resolves_earlier_changes_requested(self):
        older={'user':{'login':'reviewer'},'state':'CHANGES_REQUESTED',
               'submitted_at':'2026-10-15T12:00:00Z'}
        newer={'user':{'login':'reviewer'},'state':'APPROVED',
               'submitted_at':'2026-10-16T12:00:00Z'}
        self.assertTrue(self.check(reviews=[newer,older])[0])
        self.assertFalse(self.check(reviews=[older])[0])
