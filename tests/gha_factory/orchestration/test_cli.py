import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.gha_factory.orchestration import cli, engine


class FinalizerCLITests(unittest.TestCase):
    def controller_report(self, jobs):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / 'outputs'
            env = {
                'GITHUB_REPOSITORY': engine.REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '101',
                'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_OUTPUT': str(output_path),
            }
            output = io.StringIO()
            with patch.dict(os.environ, env), patch.object(cli.api, 'GitHub'), \
                    patch.object(cli.legacy, 'context', return_value=({}, 'a' * 64)), \
                    patch.object(engine, 'seed', return_value=[]), \
                    patch.object(engine, 'control', return_value=jobs), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['controller']), 0)
            matrix = dict(line.split('=', 1) for line in output_path.read_text().splitlines())
            self.assertEqual(json.loads(matrix['jobs']), {'include': jobs})
            self.assertEqual(matrix['has_work'], str(bool(jobs)).lower())
            return json.loads(output.getvalue())

    def test_empty_controller_is_success_no_work_without_production_claim(self):
        report = self.controller_report([])
        self.assertEqual(report['work_status'], 'SUCCESS_NO_WORK')
        self.assertEqual(report['claimed'], 0)
        self.assertEqual(report['stage'], 'controller')
        self.assertFalse(report['production_publication'])

    def test_claimed_tasks_are_not_productive_success_before_worker_results(self):
        report = self.controller_report([{'number': 7, 'task_id': 'a' * 64}])
        self.assertEqual(report['work_status'], 'WORK_CLAIMED')
        self.assertEqual(report['claimed'], 1)
        self.assertEqual(report['stage'], 'controller')
        self.assertFalse(report['production_publication'])

    def test_partial_completion_is_reported_with_nonzero_exit(self):
        result = {'issue': 2, 'state': 'SUCCEEDED'}
        error = {'issue': 1, 'error': 'FINALIZATION_REJECTED'}
        env = {
            'GITHUB_REPOSITORY': engine.REPO, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '101',
            'GITHUB_RUN_ATTEMPT': '1', 'JOBS_JSON': '{"include":[]}',
        }
        output = io.StringIO()
        with patch.dict(os.environ, env), patch.object(cli.api, 'GitHub'), \
                patch.object(engine, 'finalize', side_effect=engine.FinalizationError([result], [error])), \
                contextlib.redirect_stdout(output):
            code = cli.main(['finalize', '--artifacts', '/tmp/unused-test-artifacts'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {'results': [result], 'errors': [error]})

    def test_existing_workflow_validates_its_dispatcher_dependencies(self):
        # Contract guard: edits to imported dispatcher/admission code must run
        # the existing integration job, rather than silently bypass it.
        workflow = Path('.github/workflows/gha_dispatcher.yml').read_text()
        paths = workflow.split('  pull_request:', 1)[1].split('  schedule:', 1)[0]
        for folder in ('orchestration', 'dispatcher', 'admission'):
            self.assertIn('tools/gha_factory/' + folder + '/**', paths)
            self.assertIn('tests/gha_factory/' + folder + '/**', paths)
