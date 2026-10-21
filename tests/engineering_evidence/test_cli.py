import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.engineering_evidence import cli


class CliTests(unittest.TestCase):
    def test_writes_immutable_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = {'task_id': 'T-1', 'repository': 'team/repo', 'pr_number': 5,
                      'final_status': 'NOT_RUN', 'base_head_sha': 'a' * 40,
                      'pr_head_sha': 'b' * 40, 'ci_run_id': None,
                      'ci_run_attempt': None, 'pr_url': 'https://github.com/team/repo/pull/5',
                      'reasons': []}
            with patch.object(cli, 'verify', return_value=sample):
                code = cli.main(['--repo','team/repo','--pr','5','--task-id','T-1',
                                 '--owner','agent','--output-dir',tmp])
            self.assertEqual(code, 2)  # NOT_RUN is not success
            files = list(Path(tmp).iterdir())
            self.assertEqual(len(files), 2)
            self.assertEqual({f.suffix for f in files}, {'.json', '.md'})
            self.assertEqual(json.loads(next(f for f in files if f.suffix == '.json').read_text())['final_status'], 'NOT_RUN')
            self.assertIn('NOT_RUN', next(f for f in files if f.suffix == '.md').read_text())

    def test_immutable_reports_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = {'task_id':'x', 'repository':'team/repo', 'pr_number':2, 'final_status':'BLOCKED',
                      'pr_url':'https://github.com/team/repo/pull/2','reasons':['NO_CI'],
                      'base_head_sha':'a'*40,'pr_head_sha':'b'*40,'ci_run_id':None,'ci_run_attempt':None}
            with patch.object(cli, 'verify', return_value=report):
                argv=['--repo','team/repo','--pr','2','--task-id','x','--owner','agent','--output-dir',tmp]
                self.assertEqual(cli.main(argv),2)
                self.assertEqual(cli.main(argv),2)
            self.assertEqual(len(list(Path(tmp).iterdir())),2)

if __name__=='__main__': unittest.main()
