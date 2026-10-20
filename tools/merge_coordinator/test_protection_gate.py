import unittest
from protection_gate import allowed


class ProtectionTests(unittest.TestCase):
    def test_unprotected_main_blocks(self):
        self.assertFalse(allowed({'name':'main','protected':False}))

    def test_protected_without_required_check_evidence_blocks(self):
        self.assertFalse(allowed({'name':'main','protected':True}))

    def test_gate_needs_strict_required_checks_and_admin(self):
        branch = {'name':'main', 'protected':True, 'protection':{'required_status_checks':{
            'contexts':['public-pr-merge-gate'], 'strict':True, 'enforcement_level':'non_admins'}}}
        self.assertFalse(allowed(branch))
        branch['protection']['required_status_checks']['enforcement_level']='everyone'
        self.assertTrue(allowed(branch))

    def test_wrong_branch_is_never_approved(self):
        self.assertFalse(allowed({'name':'develop','protected':True,'protection':{'required_status_checks':{
            'contexts':['public-pr-merge-gate'], 'strict':True, 'enforcement_level':'everyone'}}}))


if __name__ == '__main__':
    unittest.main()


class RulesetEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.branch = {'name': 'main', 'protected': True}
        self.rules = [
            {'type':'required_status_checks', 'parameters':{
                'strict_required_status_checks_policy':True,
                'required_status_checks':[{'context':'public-pr-merge-gate'}]}},
            {'type':'pull_request', 'parameters':{'required_approving_review_count':1}},
            {'type':'non_fast_forward'},
            {'type':'deletion'},
        ]

    def test_complete_strict_active_ruleset_permits_merge_gate(self):
        self.assertTrue(allowed(self.branch, self.rules))

    def test_missing_review_and_no_force_guards_fail_closed(self):
        self.assertFalse(allowed(self.branch, self.rules[:1]))
        self.assertFalse(allowed(self.branch, self.rules[:-1]))

    def test_loose_check_and_wrong_check_fail_closed(self):
        bad = [dict(x) for x in self.rules]
        bad[0] = {'type':'required_status_checks', 'parameters':{
            'strict_required_status_checks_policy':False,
            'required_status_checks':[{'context':'public-pr-merge-gate'}]}}
        bad[0]['parameters']['strict_required_status_checks_policy'] = True
        bad[0]['parameters']['required_status_checks'] = [{'context':'unrelated'}]
        self.assertFalse(allowed(self.branch, bad))

    def test_solo_maintainer_ruleset_permits_when_squash_and_thread_resolution_strict(self):
        solo_rules = [
            {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'required_status_checks': [{'context': 'public-pr-merge-gate'}]}},
            {'type': 'pull_request', 'parameters': {
                'required_approving_review_count': 0,
                'dismiss_stale_reviews_on_push': True,
                'required_review_thread_resolution': True,
                'allowed_merge_methods': ['squash']}},
            {'type': 'non_fast_forward'},
            {'type': 'deletion'},
        ]
        self.assertTrue(allowed(self.branch, solo_rules))

    def test_solo_maintainer_ruleset_rejects_loose_conditions(self):
        bad_methods = [
            {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'required_status_checks': [{'context': 'public-pr-merge-gate'}]}},
            {'type': 'pull_request', 'parameters': {
                'required_approving_review_count': 0,
                'dismiss_stale_reviews_on_push': True,
                'required_review_thread_resolution': True,
                'allowed_merge_methods': ['squash', 'merge']}},
            {'type': 'non_fast_forward'},
            {'type': 'deletion'},
        ]
        self.assertFalse(allowed(self.branch, bad_methods))

        bad_threads = [
            {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'required_status_checks': [{'context': 'public-pr-merge-gate'}]}},
            {'type': 'pull_request', 'parameters': {
                'required_approving_review_count': 0,
                'dismiss_stale_reviews_on_push': True,
                'required_review_thread_resolution': False,
                'allowed_merge_methods': ['squash']}},
            {'type': 'non_fast_forward'},
            {'type': 'deletion'},
        ]
        self.assertFalse(allowed(self.branch, bad_threads))

        bad_stale = [
            {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'required_status_checks': [{'context': 'public-pr-merge-gate'}]}},
            {'type': 'pull_request', 'parameters': {
                'required_approving_review_count': 0,
                'dismiss_stale_reviews_on_push': False,
                'required_review_thread_resolution': True,
                'allowed_merge_methods': ['squash']}},
            {'type': 'non_fast_forward'},
            {'type': 'deletion'},
        ]
        self.assertFalse(allowed(self.branch, bad_stale))

