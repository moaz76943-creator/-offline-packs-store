import unittest
from coordinator import evaluate, policy_error, order_entries

SHA_A = 'a' * 40
SHA_B = 'b' * 40


def entry(**changes):
    value = {
        'number': 900, 'head_sha': SHA_A, 'main_sha': SHA_B,
        'owner': 'integration-coordinator',
        'paths': ['tools/merge_coordinator/'],
        'checks': ['public-pr-merge-gate', 'scoped-qa'],
        'reviewers': ['trusted-reviewer'],
        'dependencies': [], 'excludes': [],
    }
    value.update(changes)
    return value


def pr(**changes):
    value = {'number': 900, 'state': 'open', 'draft': False, 'mergeable': True,
             'mergeable_state': 'clean', 'head': {'sha': SHA_A},
             'base': {'ref': 'main', 'sha': SHA_B},
             'user': {'login': 'author'}}
    value.update(changes)
    return value


def checks(**changes):
    value = {'check_runs': [
        {'name': 'public-pr-merge-gate', 'head_sha': SHA_A, 'status': 'completed',
         'conclusion': 'success', 'app': {'slug': 'github-actions'}, 'id': 5},
        {'name': 'scoped-qa', 'head_sha': SHA_A, 'status': 'completed',
         'conclusion': 'success', 'app': {'slug': 'github-actions'}, 'id': 6},
    ]}
    value.update(changes)
    return value


class ContractTests(unittest.TestCase):
    def decide(self, e=None, p=None, c=None, rv=None, fs=None, title='feat: ready', deps=None):
        return evaluate(e or entry(), p or pr(), c or checks(),
                        rv if rv is not None else [{'user': {'login': 'trusted-reviewer'},
                            'state': 'APPROVED', 'commit_id': SHA_A}],
                        fs if fs is not None else [{'filename': 'tools/merge_coordinator/a.py'}],
                        SHA_B, title, deps if deps is not None else {})

    def test_accepted_exact_sha_with_real_check_and_review(self):
        self.assertEqual(self.decide(), ('VERIFIED_READY', 'exact-head validated'))

    def test_no_implicit_authorization(self):
        self.assertEqual(evaluate({}, pr(), checks(), [], [], SHA_B, 'no skip', {})[0], 'BLOCKED_POLICY')

    def test_fail_closed_missing_or_skipped_ci(self):
        self.assertEqual(self.decide(c={'check_runs': []})[0], 'NOT_RUN')
        self.assertEqual(self.decide(c={'check_runs': [dict(checks()['check_runs'][0], conclusion='skipped')]})[0], 'NOT_RUN')

    def test_pending_or_wrong_head_ci_blocks(self):
        self.assertEqual(self.decide(c={'check_runs': [dict(checks()['check_runs'][0], head_sha=SHA_B)]})[0], 'NOT_RUN')
        self.assertEqual(self.decide(c={'check_runs': [dict(checks()['check_runs'][0], status='in_progress')]})[0], 'NOT_RUN')

    def test_authorization_commit_is_allowed_once_only(self):
        new_main = 'c' * 40
        record = entry(main_sha=SHA_B)
        current = pr(base={'ref':'main', 'sha':new_main})
        self.assertEqual(evaluate(record, current, checks(),
            [{'user':{'login':'trusted-reviewer'}, 'state':'APPROVED', 'commit_id':SHA_A}],
            [{'filename':'tools/merge_coordinator/a.py'}], new_main, 'safe', {},
            authorization_parent=SHA_B, authorization_only=True)[0], 'VERIFIED_READY')
        self.assertEqual(evaluate(record, current, checks(), [], [], new_main, 'safe', {},
            authorization_parent=SHA_B, authorization_only=False)[0], 'STALE_MAIN')

    def test_skip_ci_and_stale_base_block(self):
        self.assertEqual(self.decide(title='feat: candidate [skip ci]')[0], 'BLOCKED_SKIP_CI')
        self.assertEqual(self.decide(p=pr(base={'ref':'main', 'sha':SHA_A}))[0], 'STALE_MAIN')

    def test_unverified_review_blocks(self):
        self.assertEqual(self.decide(rv=[])[0], 'NEEDS_REVIEW')
        self.assertEqual(self.decide(rv=[{'user':{'login':'trusted-reviewer'},'state':'APPROVED','commit_id':SHA_B}])[0], 'NEEDS_REVIEW')
        self.assertEqual(self.decide(rv=[{'user':{'login':'author'},'state':'APPROVED','commit_id':SHA_A}])[0], 'NEEDS_REVIEW')

    def test_unapproved_file_and_pack_publication_block(self):
        self.assertEqual(self.decide(fs=[{'filename':'tools/other/a.py'}])[0], 'SCOPE_VIOLATION')
        self.assertEqual(self.decide(e=entry(paths=['packs/']),fs=[{'filename':'packs/aa.pack.gz'}])[0], 'BLOCKED_POLICY')

    def test_drafts_only_promotable_after_checks_and_authorization(self):
        self.assertEqual(self.decide(p=pr(draft=True))[0], 'PROMOTE_ONLY')
        self.assertNotEqual(self.decide(p=pr(draft=True), c={'check_runs': []})[0], 'PROMOTE_ONLY')

    def test_dependencies_require_merged(self):
        self.assertEqual(self.decide(e=entry(dependencies=[88]), deps={88: {'merged':False}})[0], 'BLOCKED_DEPENDENCY')
        self.assertEqual(self.decide(e=entry(excludes=[101]), deps={101: {'state':'open', 'merged':False}})[0], 'SEMANTIC_CONFLICT')

    def test_unmergeable_and_unknown_never_pass(self):
        self.assertEqual(self.decide(p=pr(mergeable=False, mergeable_state='dirty'))[0], 'CONFLICT')
        self.assertEqual(self.decide(p=pr(mergeable=None, mergeable_state='unknown'))[0], 'NOT_VERIFIED')

    def test_manifest_validation_fail_closed(self):
        self.assertIsNotNone(policy_error(entry(head_sha='short')))
        self.assertIsNotNone(policy_error(entry(paths=['../packs/'])))
        self.assertIsNotNone(policy_error(entry(checks=['not-scoped'])))
        self.assertIsNone(policy_error(entry()))

    def test_dependency_order(self):
        self.assertEqual([x['number'] for x in order_entries([entry(number=2,dependencies=[1]),entry(number=1)])], [1,2])
        with self.assertRaises(ValueError):
            order_entries([entry(number=1,dependencies=[2]),entry(number=2,dependencies=[1])])


if __name__ == '__main__':
    unittest.main()
