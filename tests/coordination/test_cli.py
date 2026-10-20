import unittest
from unittest.mock import patch
from tools.coordination import cli

class CliTests(unittest.TestCase):
    def test_read_only_conflict_exit_without_mutation(self):
        with patch.object(cli,'GitRefStore') as store, patch.object(cli,'GhApi') as api:
            with patch.object(cli,'Coordinator') as co:
                co.return_value.inspect.return_value={'status':'READ_ONLY','reason':'SCOPE_CONFLICT'}
                result=cli.main(['--ledger-repo','org/private','inspect','--repo','org/public',
                    '--branch','main','--path','tools/x/**'])
                self.assertEqual(result,2)
                co.return_value.inspect.assert_called_once()
    def test_claim_requires_explicit_scope_and_sha(self):
        with self.assertRaises(SystemExit) as failure:
            cli.main(['--ledger-repo','org/private','claim','--repo','org/public','--branch','main',
                '--task','T','--owner','agent'])
        self.assertEqual(failure.exception.code,2)
    def test_bootstrap_not_implicit(self):
        with patch.object(cli,'GitRefStore') as store,patch.object(cli,'GhApi') as api,patch.object(cli,'bootstrap_private_store') as bootstrap:
            with patch.object(cli,'Coordinator') as co:
                co.return_value.inspect.return_value={'status':'READY'}
                cli.main(['--ledger-repo','org/private','inspect','--repo','org/public','--branch','main',
                    '--path','tools/x/**'])
                bootstrap.assert_not_called()

if __name__=='__main__':unittest.main()
