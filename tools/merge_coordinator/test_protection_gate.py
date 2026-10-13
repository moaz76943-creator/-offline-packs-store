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
